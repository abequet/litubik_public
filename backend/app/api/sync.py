# SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Sync phase 1: project snapshot export/import.

Export runs as a job producing a zip under data/exports/ (download endpoint
below); import uploads the archive to a temp file and hands it to a job. The
import mode (create satellite / update satellite) is decided by the project
uuid inside the archive — see services/sync/snapshot.py.
"""
import json
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from fastapi import (
    APIRouter, Depends, Form, HTTPException, Response, UploadFile,
)
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.services.connectors.keys import PROVIDER_PATTERN
from app.api.deps import (
    CurrentUser, DbDep, NoSandboxWrites, ProjectMemberDep, get_project,
    require_project_admin,
)
from app.core.config import get_settings
from app.core.crypto import encrypt_secret
from app.models import DatabaseCredential, Job, LLMCredential, SyncEvent, User
from app.services.connectors.keys import KEYED_PROVIDERS
from app.services.sync import jobs as sync_jobs  # noqa: F401 — registers handlers
from app.services.sync.common import SnapshotError
from app.services.sync.contributions import (
    build_contributions, import_contributions, parse_package,
)
from app.services.sync.snapshot import MAX_DATA_JSON_BYTES
from app.workers.runner import runner

# demo visitors: no sync at all (server folders, snapshots, shared keys)
router = APIRouter(prefix="/api", tags=["sync"],
                   dependencies=[NoSandboxWrites])

# M5: cap the uploaded snapshot archive on disk (a project snapshot with PDFs
# can be large, but not unbounded — a zip bomb would otherwise fill the disk /
# OOM the mono-process server).
MAX_SNAPSHOT_UPLOAD_BYTES = 1024 * 1024 * 1024  # 1 GiB


def _save_upload_capped(upload: UploadFile, dest: Path, cap: int) -> None:
    written = 0
    try:
        with open(dest, "wb") as out:
            while True:
                chunk = upload.file.read(1024 * 1024)
                if not chunk:
                    break
                written += len(chunk)
                if written > cap:
                    raise HTTPException(
                        status_code=413,
                        detail="Archive trop volumineuse "
                               f"(max {cap // (1024 * 1024)} Mo)")
                out.write(chunk)
    except Exception:
        dest.unlink(missing_ok=True)
        raise


class SyncInfo(BaseModel):
    project_id: int
    uuid: str
    sync_role: str
    snapshot_version: int
    coordinator_email: str
    has_passphrase: bool = False
    n_shared_keys: int = 0


class ExportIn(BaseModel):
    include_pdfs: bool = True
    # public replication archive (services/sync/public): no PDFs, abstracts,
    # raw database exports or shared keys; reviewers optionally pseudonymised
    public: bool = False
    pseudonymize: bool = False


@router.get("/projects/{project_id}/sync", response_model=SyncInfo)
def sync_info(project_id: int, member: ProjectMemberDep, db: DbDep):
    project = get_project(project_id, db)
    n_shared = (
        db.query(LLMCredential)
        .filter_by(project_id=project_id, shared=True).count()
        + db.query(DatabaseCredential)
        .filter_by(project_id=project_id, shared=True).count())
    return SyncInfo(project_id=project.id, uuid=project.uuid,
                    sync_role=project.sync_role,
                    snapshot_version=project.snapshot_version,
                    coordinator_email=project.coordinator_email,
                    has_passphrase=bool(project.sync_passphrase_encrypted),
                    n_shared_keys=n_shared)


class FolderIn(BaseModel):
    path: str = Field(max_length=1000)  # empty = unlink the folder
    auto_publish: bool = False


@router.post("/projects/{project_id}/sync/folder",
             dependencies=[Depends(require_project_admin)])
def set_folder(project_id: int, payload: FolderIn, db: DbDep):
    """Link the project to a locally synced shared folder (Nextcloud/Drive…).
    The background loop then scans it every few minutes."""
    project = get_project(project_id, db)
    path = payload.path.strip()
    if path:
        folder = Path(path)
        # L8: constrain the directory-creation primitive — require an absolute
        # path and, when a base is configured (hosted instances), keep it inside
        # that base so an admin can't have the server mkdir anywhere it can write.
        if not folder.is_absolute():
            raise HTTPException(status_code=400,
                                detail="Le chemin du dossier doit être absolu")
        base = get_settings().sync_folder_base.strip()
        if base:
            try:
                resolved = folder.resolve()
                resolved.relative_to(Path(base).resolve())
            except (ValueError, OSError):
                raise HTTPException(
                    status_code=403,
                    detail="Le dossier doit se trouver sous le répertoire de "
                           f"synchronisation autorisé ({base})")
        try:
            folder.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            raise HTTPException(status_code=400,
                                detail=f"Dossier inaccessible : {e}")
        from app.services.sync.folder import _read_manifest
        manifest = _read_manifest(folder)
        if manifest and manifest.get("project_uuid") not in ("", project.uuid):
            raise HTTPException(
                status_code=409,
                detail="Ce dossier est déjà utilisé par un autre projet "
                       "LitUbik")
    project.sync_dir = path
    project.sync_auto_publish = payload.auto_publish
    db.commit()
    return {"ok": True, "path": path, "auto_publish": payload.auto_publish}


@router.get("/projects/{project_id}/sync/folder")
def get_folder_state(project_id: int, member: ProjectMemberDep, db: DbDep):
    from app.services.sync.folder import folder_state
    project = get_project(project_id, db)
    return folder_state(db, project)


@router.post("/projects/{project_id}/sync/folder/scan")
def scan_folder(project_id: int, user: CurrentUser, member: ProjectMemberDep,
                db: DbDep):
    """'Synchroniser maintenant': one pass, returns what happened."""
    from app.services.sync.folder import scan_project
    project = get_project(project_id, db)
    if not project.sync_dir:
        raise HTTPException(status_code=400,
                            detail="Aucun dossier partagé configuré")
    return scan_project(db, project, actor=user)


@router.post("/projects/{project_id}/sync/folder/publish",
             dependencies=[Depends(require_project_admin)])
def publish_folder(project_id: int, payload: ExportIn, user: CurrentUser,
                   db: DbDep):
    """Coordinator: build a fresh snapshot and place it in the folder (job)."""
    project = get_project(project_id, db)
    if project.sync_role != "coordinator":
        raise HTTPException(status_code=400,
                            detail="Seul le coordinateur publie l'instantané")
    if not project.sync_dir:
        raise HTTPException(status_code=400,
                            detail="Aucun dossier partagé configuré")
    job = runner.submit("sync_publish_folder",
                        {"project_id": project_id,
                         "include_pdfs": payload.include_pdfs,
                         "user_id": user.id},
                        project_id=project_id, user_id=user.id)
    return {"job_id": job.id}


@router.post("/projects/{project_id}/sync/folder/apply-snapshot",
             dependencies=[Depends(require_project_admin)])
def apply_folder_snapshot(project_id: int, user: CurrentUser, db: DbDep):
    """Satellite: apply the newest snapshot found in the folder (job)."""
    from app.services.sync.folder import latest_folder_snapshot_path
    project = get_project(project_id, db)
    path = latest_folder_snapshot_path(project)
    if path is None:
        raise HTTPException(status_code=404,
                            detail="Aucun instantané dans le dossier")
    job = runner.submit("sync_import_snapshot",
                        {"path": str(path), "user_id": user.id,
                         "keep_file": True},
                        project_id=project_id, user_id=user.id)
    return {"job_id": job.id}


class PassphraseIn(BaseModel):
    passphrase: str = Field(max_length=200)  # empty = clear


@router.post("/projects/{project_id}/sync/passphrase",
             dependencies=[Depends(require_project_admin)])
def set_passphrase(project_id: int, payload: PassphraseIn, db: DbDep):
    """The project passphrase protecting shared API keys in transit. Every
    instance of the project enters the same one (communicated out-of-band);
    stored encrypted with the instance secret, never returned."""
    project = get_project(project_id, db)
    phrase = payload.passphrase.strip()
    # M7: the encrypted key blob (with its salt + iteration count) travels in
    # every snapshot placed in the shared folder, so anyone with READ access can
    # mount an offline dictionary attack — a short passphrase would surrender
    # all shared API keys. Enforce a floor of 12 characters.
    if phrase and len(phrase) < 12:
        raise HTTPException(status_code=400,
                            detail="12 caractères minimum pour la phrase "
                                   "secrète (elle protège les clés API "
                                   "partagées contre une attaque hors-ligne)")
    project.sync_passphrase_encrypted = encrypt_secret(phrase) if phrase \
        else None
    db.commit()
    return {"ok": True, "has_passphrase": bool(phrase)}


class SharedKeyOut(BaseModel):
    kind: str  # llm | database
    id: int
    provider: str
    default_model: str = ""
    owner_email: str | None
    shared: bool
    is_mine: bool


@router.get("/projects/{project_id}/sync/shared-keys",
            response_model=list[SharedKeyOut])
def list_project_keys(project_id: int, user: CurrentUser,
                      member: ProjectMemberDep, db: DbDep):
    """The project-scoped API keys (the only ones that can travel)."""
    get_project(project_id, db)
    emails = {u.id: u.email for u in db.query(User).all()}
    out = [
        SharedKeyOut(kind="llm", id=c.id, provider=c.provider,
                     default_model=c.default_model,
                     owner_email=emails.get(c.owner_user_id),
                     shared=c.shared, is_mine=c.owner_user_id == user.id)
        for c in db.query(LLMCredential).filter_by(project_id=project_id)
    ] + [
        SharedKeyOut(kind="database", id=c.id, provider=c.provider,
                     owner_email=emails.get(c.owner_user_id),
                     shared=c.shared, is_mine=c.owner_user_id == user.id)
        for c in db.query(DatabaseCredential).filter_by(project_id=project_id)
    ]
    return out


class ShareIn(BaseModel):
    shared: bool


@router.post("/projects/{project_id}/sync/shared-keys/{kind}/{key_id}/share")
def toggle_share(project_id: int, kind: str, key_id: int, payload: ShareIn,
                 user: CurrentUser, member: ProjectMemberDep, db: DbDep):
    """Opt a project key in/out of sync transport — its owner's decision
    (an app admin can also intervene)."""
    model = {"llm": LLMCredential, "database": DatabaseCredential}.get(kind)
    if model is None:
        raise HTTPException(status_code=404, detail="Unknown key kind")
    row = db.get(model, key_id)
    if row is None or row.project_id != project_id:
        raise HTTPException(status_code=404, detail="Key not found")
    if row.owner_user_id not in (None, user.id) and not user.is_admin:
        raise HTTPException(status_code=403,
                            detail="Seul le propriétaire de la clé décide de "
                                   "son partage")
    if row.owner_user_id is None:  # legacy row: claiming it by toggling
        row.owner_user_id = user.id
    row.shared = payload.shared
    db.commit()
    return {"ok": True, "shared": row.shared}


class AdoptGlobalIn(BaseModel):
    provider: str = Field(max_length=20)


@router.post("/projects/{project_id}/sync/shared-keys/adopt-global",
             response_model=SharedKeyOut,
             dependencies=[Depends(require_project_admin)])
def adopt_global_llm_key(project_id: int, payload: AdoptGlobalIn,
                         user: CurrentUser, db: DbDep):
    """Copy one of the instance's GLOBAL LLM keys into this project as a
    shared key — the one-click path for a coordinator whose key was stored
    app-wide and who wants their co-reviewers' instances to use it (only
    project-scoped keys travel in snapshots/packages).

    H2: restricted to project admins and forbidden to demo sandbox accounts —
    otherwise a visitor could drain the superadmin's paid global LLM key by
    laundering it through a project-scoped credential (which is not filtered by
    the demo global-key guard).

    Only the superadmin, whose keys the global ones are: a shared key travels
    wrapped under the project passphrase, which its admin chooses, so any other
    project admin could adopt the operator's key and read it in clear from
    their own export."""
    from app.core.demo import is_demo_user
    if is_demo_user(user):
        raise HTTPException(
            status_code=403,
            detail="Les comptes de démonstration ne peuvent pas adopter la "
                   "clé globale de l'instance")
    if not user.is_admin:
        raise HTTPException(
            status_code=403,
            detail="Seul l'administrateur de l'instance peut partager ses "
                   "clés globales")
    get_project(project_id, db)
    source = (db.query(LLMCredential)
              .filter_by(project_id=None, provider=payload.provider).first())
    if source is None:
        raise HTTPException(status_code=404,
                            detail="Aucune clé globale pour ce fournisseur")
    row = (db.query(LLMCredential)
           .filter_by(project_id=project_id, provider=payload.provider)
           .first())
    if row is not None and row.owner_user_id not in (None, user.id) \
            and not user.is_admin:
        raise HTTPException(
            status_code=409,
            detail="Une clé de ce fournisseur existe déjà sur ce projet "
                   "(elle appartient à un autre membre)")
    if row is None:
        row = LLMCredential(project_id=project_id, provider=payload.provider)
        db.add(row)
    # same instance, same Fernet: the encrypted blob copies as-is
    row.api_key_encrypted = source.api_key_encrypted
    row.default_model = source.default_model
    row.base_url = source.base_url
    row.owner_user_id = user.id
    row.shared = True
    db.commit()
    db.refresh(row)
    return SharedKeyOut(kind="llm", id=row.id, provider=row.provider,
                        default_model=row.default_model,
                        owner_email=user.email, shared=True, is_mine=True)


@router.get("/projects/{project_id}/sync/global-llm-providers")
def global_llm_providers(project_id: int, user: CurrentUser,
                         member: ProjectMemberDep, db: DbDep):
    """Providers having a global key not yet attached to this project (feeds
    the adopt-global buttons) — none for anyone but the superadmin, the only
    one allowed to adopt them."""
    get_project(project_id, db)
    if not user.is_admin:
        return []
    have = {c.provider for c in db.query(LLMCredential)
            .filter_by(project_id=project_id)}
    return [c.provider for c in db.query(LLMCredential)
            .filter_by(project_id=None) if c.provider not in have]


class ProjectDbKeyIn(BaseModel):
    provider: str = Field(pattern=PROVIDER_PATTERN)
    api_key: str = Field(min_length=6, max_length=200)
    shared: bool = True


@router.put("/projects/{project_id}/sync/database-keys",
            response_model=SharedKeyOut)
def upsert_project_db_key(project_id: int, payload: ProjectDbKeyIn,
                          user: CurrentUser, member: ProjectMemberDep,
                          db: DbDep):
    """A member adds THEIR institutional Scopus/IEEE key to the project
    (project-scoped keys override the instance-global one for searches and
    counts). One key per provider and per project — first owner wins."""
    get_project(project_id, db)
    if payload.provider not in KEYED_PROVIDERS:
        raise HTTPException(status_code=400, detail="Unknown provider")
    row = (db.query(DatabaseCredential)
           .filter_by(project_id=project_id, provider=payload.provider)
           .first())
    if row is not None and row.owner_user_id not in (None, user.id) \
            and not user.is_admin:
        raise HTTPException(
            status_code=409,
            detail="Une clé de ce fournisseur existe déjà sur ce projet "
                   "(elle appartient à un autre membre)")
    if row is None:
        row = DatabaseCredential(project_id=project_id,
                                 provider=payload.provider)
        db.add(row)
    row.api_key_encrypted = encrypt_secret(payload.api_key.strip())
    row.owner_user_id = user.id
    row.shared = payload.shared
    db.commit()
    db.refresh(row)
    return SharedKeyOut(kind="database", id=row.id, provider=row.provider,
                        owner_email=user.email, shared=row.shared,
                        is_mine=True)


@router.delete("/projects/{project_id}/sync/shared-keys/{kind}/{key_id}")
def delete_project_key(project_id: int, kind: str, key_id: int,
                       user: CurrentUser, member: ProjectMemberDep,
                       db: DbDep):
    model = {"llm": LLMCredential, "database": DatabaseCredential}.get(kind)
    if model is None:
        raise HTTPException(status_code=404, detail="Unknown key kind")
    row = db.get(model, key_id)
    if row is None or row.project_id != project_id:
        raise HTTPException(status_code=404, detail="Key not found")
    if row.owner_user_id not in (None, user.id) and not user.is_admin \
            and member.role != "admin":
        raise HTTPException(status_code=403,
                            detail="Seul le propriétaire (ou un admin) "
                                   "supprime cette clé")
    db.delete(row)
    db.commit()
    return {"ok": True}


@router.post("/projects/{project_id}/sync/export-snapshot",
             dependencies=[Depends(require_project_admin)])
def export_snapshot(project_id: int, payload: ExportIn, user: CurrentUser,
                    db: DbDep):
    get_project(project_id, db)
    if payload.pseudonymize and not payload.public:
        raise HTTPException(status_code=400,
                            detail="Pseudonymisation applies to the public "
                                   "archive only")
    job = runner.submit("sync_export_snapshot",
                        {"project_id": project_id,
                         "include_pdfs": payload.include_pdfs,
                         "public": payload.public,
                         "pseudonymize": payload.pseudonymize,
                         "user_id": user.id},
                        project_id=project_id, user_id=user.id)
    return {"job_id": job.id}


@router.get("/projects/{project_id}/sync/snapshot-download")
def download_snapshot(project_id: int, job_id: int, member: ProjectMemberDep,
                      db: DbDep):
    job = db.get(Job, job_id)
    if (job is None or job.type != "sync_export_snapshot"
            or job.project_id != project_id):
        raise HTTPException(status_code=404, detail="Export not found")
    if job.status != "done":
        raise HTTPException(status_code=409, detail="Export not finished")
    path = job.result.get("path", "")
    if not path or not Path(path).exists():
        raise HTTPException(status_code=410,
                            detail="Archive no longer on disk — re-export")
    return FileResponse(path, filename=job.result.get("filename",
                                                      "snapshot.zip"),
                        media_type="application/zip")


@router.post("/projects/{project_id}/sync/export-contributions")
def export_contributions(project_id: int, user: CurrentUser,
                         member: ProjectMemberDep, db: DbDep):
    """Download MY complete contribution set (votes incl. AI generated on this
    instance, JBI, extraction values, annotations, skips) as one JSON file to
    send to the coordinator. Full export — importing it twice is harmless."""
    project = get_project(project_id, db)
    data, filename = build_contributions(db, project, user)
    return Response(
        json.dumps(data, ensure_ascii=False),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@router.post("/projects/{project_id}/sync/import-contributions",
             dependencies=[Depends(require_project_admin)])
def import_contributions_endpoint(project_id: int, file: UploadFile,
                                  user: CurrentUser, db: DbDep):
    """Merge a co-reviewer's contribution package into this project. Conflict
    detection re-runs for every screening round the package touched."""
    project = get_project(project_id, db)
    # a package is a project's votes and notes, never more than a snapshot's
    # data.json: refuse to load anything larger into memory
    raw = file.file.read(MAX_DATA_JSON_BYTES + 1)
    if len(raw) > MAX_DATA_JSON_BYTES:
        raise HTTPException(
            status_code=413,
            detail="Paquet trop volumineux "
                   f"(max {MAX_DATA_JSON_BYTES // (1024 * 1024)} Mo)")
    try:
        payload = parse_package(raw)
        if payload.get("project_uuid") != project.uuid:
            raise SnapshotError("Ce paquet appartient à un autre projet")
        return import_contributions(db, payload, user)
    except SnapshotError as e:
        raise HTTPException(status_code=400, detail=str(e))


class SyncEventOut(BaseModel):
    id: int
    direction: str
    kind: str
    author_email: str
    seq: int
    based_on_version: int
    filename: str
    counts: dict
    warnings: list
    created_at: datetime

    model_config = {"from_attributes": True}


@router.get("/projects/{project_id}/sync/events",
            response_model=list[SyncEventOut])
def sync_events(project_id: int, member: ProjectMemberDep, db: DbDep,
                limit: int = 50):
    """The exchange journal (newest first)."""
    get_project(project_id, db)
    return (db.query(SyncEvent).filter_by(project_id=project_id)
            .order_by(SyncEvent.id.desc())
            .limit(min(max(limit, 1), 200)).all())


class JoinFolderIn(BaseModel):
    path: str = Field(min_length=1, max_length=1000)


@router.post("/sync/join-folder")
def join_folder(payload: JoinFolderIn, user: CurrentUser, db: DbDep):
    """One-step bootstrap for a co-reviewer: point at the shared folder the
    coordinator publishes into — the latest snapshot found there is imported
    (creating/updating the satellite copy) and the project gets linked to the
    folder, so every later exchange is automatic."""
    from app.services.sync.folder import _latest_folder_snapshot, _read_manifest
    folder = Path(payload.path.strip())
    # L8, as in set_folder: on an instance that confines shared folders to a
    # base directory, joining one outside it is refused too
    base = get_settings().sync_folder_base.strip()
    if base:
        try:
            folder.resolve().relative_to(Path(base).resolve())
        except (ValueError, OSError):
            raise HTTPException(
                status_code=403,
                detail="Le dossier doit se trouver sous le répertoire de "
                       f"synchronisation autorisé ({base})")
    if not folder.is_dir():
        raise HTTPException(status_code=400,
                            detail=f"Dossier introuvable : {payload.path}")
    manifest = _read_manifest(folder)
    version, snapshot_path = _latest_folder_snapshot(folder)
    if snapshot_path is None:
        raise HTTPException(
            status_code=400,
            detail="Aucun instantané dans ce dossier — le coordinateur doit "
                   "d'abord « Publier l'instantané dans le dossier »"
                   + ("" if manifest else " (litubik-manifest.json absent : "
                      "est-ce le bon dossier ?)"))
    job = runner.submit("sync_import_snapshot",
                        {"path": str(snapshot_path), "user_id": user.id,
                         "keep_file": True, "link_folder": str(folder)},
                        project_id=None, user_id=user.id)
    return {"job_id": job.id, "snapshot_version": version}


@router.post("/sync/import-snapshot")
def import_snapshot(file: UploadFile, user: CurrentUser, db: DbDep,
                    restore: bool = Form(False)):
    """Upload an archive and import it (create or update, by project uuid).
    Authorization for the update mode is enforced inside the job (local
    project admin required); creation is open to any logged-in user.
    restore=true marks the archive as one of the user's OWN backups: a
    coordinator project may then be overwritten (kept coordinator, local
    contributions NOT merged back — the archive is the reference), and a
    create yields a coordinator project instead of a satellite copy."""
    tmp_dir = get_settings().data_dir / "tmp_sync"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    tmp_path = tmp_dir / f"{uuid4()}.zip"
    _save_upload_capped(file, tmp_path, MAX_SNAPSHOT_UPLOAD_BYTES)
    job = runner.submit("sync_import_snapshot",
                        {"path": str(tmp_path), "user_id": user.id,
                         "restore_own": restore},
                        project_id=None, user_id=user.id)
    return {"job_id": job.id}
