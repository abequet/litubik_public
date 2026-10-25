# SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Shared-folder transport (sync phase 4, option C).

The project is linked to a locally synced folder (Nextcloud/OneDrive/Drive…):
the OS sync client moves the bytes, LitUbik only reads/writes files — no
network code. Layout inside the folder:

    litubik-manifest.json          # project identity + latest snapshot version
    snapshots/v<N>.zip             # published by the coordinator
    contributions/<email>/<seq>.json

Files are immutable once written (append-only seq) and written atomically
(tmp + os.replace) so a partial cloud sync can never corrupt an exchange.
A scan (periodic background loop, or the "Synchroniser maintenant" button):
- imports co-reviewers' new contribution packages, in seq order, resuming
  from the journal (max imported seq per author);
- writes the local reviewers' contributions when their content changed since
  the last push (sha-256 over the serialized rows + shared-keys set);
- coordinator: keeps the folder's snapshot up to date (auto_publish) —
  satellites only get an "update available" signal, applying stays a click.
"""
import hashlib
import json
import logging
import os
import shutil
from pathlib import Path

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import Project, ProjectMember, SyncEvent, User
from app.services.sync.common import SnapshotError, log_event
from app.services.sync.contributions import (
    build_contributions, collect_contributions_data, import_contributions,
    parse_package,
)
from app.services.sync.credentials_sync import collect_shared
from app.services.sync import signing

logger = logging.getLogger(__name__)

MANIFEST_NAME = "litubik-manifest.json"


def _atomic_write(path: Path, content: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    os.replace(tmp, path)


def _read_manifest(folder: Path) -> dict | None:
    path = folder / MANIFEST_NAME
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _write_manifest(folder: Path, project: Project):
    _atomic_write(folder / MANIFEST_NAME, json.dumps({
        "format": "litubik-folder", "format_version": 1,
        "project_uuid": project.uuid, "project_name": project.name,
        "coordinator_email": project.coordinator_email,
        "latest_snapshot_version": project.snapshot_version,
    }, ensure_ascii=False, indent=1))


def _latest_folder_snapshot(folder: Path) -> tuple[int, Path | None]:
    best, best_path = 0, None
    snapshots = folder / "snapshots"
    if snapshots.is_dir():
        for f in snapshots.glob("v*.zip"):
            try:
                version = int(f.stem[1:])
            except ValueError:
                continue
            if version > best:
                best, best_path = version, f
    return best, best_path


def _content_hash(db: Session, project: Project, author: User) -> str:
    payload = {"core": collect_contributions_data(db, project, author),
               "credentials": collect_shared(db, project, owner=author)}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str)
                          .encode()).hexdigest()


def _last_pushed_hash(db: Session, project_id: int, email: str) -> str | None:
    event = (db.query(SyncEvent)
             .filter_by(project_id=project_id, direction="export",
                        kind="contributions", author_email=email)
             .order_by(SyncEvent.id.desc()).first())
    return (event.counts or {}).get("content_hash") if event else None


def _last_imported_seq(db: Session, project_id: int, email: str) -> int:
    return (db.query(func.max(SyncEvent.seq))
            .filter_by(project_id=project_id, direction="import",
                       kind="contributions", author_email=email)
            .scalar()) or 0


def _local_real_members(db: Session, project: Project) -> list[User]:
    return [u for m, u in db.query(ProjectMember, User)
            .join(User, User.id == ProjectMember.user_id)
            .filter(ProjectMember.project_id == project.id).all()
            if u.password_hash != ""]


def _import_actor(db: Session, project: Project,
                  actor: User | None) -> User | None:
    """Who inbound imports run as: the caller if they may import, else the
    project's first local admin (background scans have no caller)."""
    if actor is not None and actor.is_admin:
        return actor
    if actor is not None:
        member = (db.query(ProjectMember)
                  .filter_by(project_id=project.id, user_id=actor.id).first())
        if member is not None and member.role == "admin":
            return actor
    for m, u in (db.query(ProjectMember, User)
                 .join(User, User.id == ProjectMember.user_id)
                 .filter(ProjectMember.project_id == project.id,
                         ProjectMember.role == "admin")):
        if u.password_hash != "":
            return u
    return None


def folder_state(db: Session, project: Project) -> dict:
    """Cheap folder inspection for the UI (no imports, no writes)."""
    if not project.sync_dir:
        return {"configured": False}
    folder = Path(project.sync_dir)
    if not folder.is_dir():
        return {"configured": True, "path": project.sync_dir, "ok": False,
                "error": "Dossier introuvable (lecteur non monté ?)"}
    latest, _ = _latest_folder_snapshot(folder)
    pending = []
    contributions = folder / "contributions"
    if contributions.is_dir():
        local_emails = {u.email for u in _local_real_members(db, project)}
        for author_dir in contributions.iterdir():
            email = author_dir.name.lower()
            if not author_dir.is_dir() or email in local_emails:
                continue
            last = _last_imported_seq(db, project.id, email)
            n_new = sum(1 for f in author_dir.glob("*.json")
                        if _seq_of(f) > last)
            if n_new:
                pending.append({"author": email, "n_new": n_new})
    return {
        "configured": True, "path": project.sync_dir, "ok": True,
        "auto_publish": project.sync_auto_publish,
        "latest_snapshot_version": latest,
        "update_available": (project.sync_role == "satellite"
                             and latest > project.snapshot_version),
        "snapshot_behind": (project.sync_role == "coordinator"
                            and latest < project.snapshot_version),
        "pending_contributions": pending,
    }


def _seq_of(path: Path) -> int:
    try:
        return int(path.stem)
    except ValueError:
        return -1


def scan_project(db: Session, project: Project,
                 actor: User | None = None) -> dict:
    """One synchronization pass over the project's shared folder."""
    summary = {"imported": [], "pushed": [], "published": None,
               "update_available": False, "warnings": []}
    if not project.sync_dir:
        return summary
    folder = Path(project.sync_dir)
    if not folder.is_dir():
        summary["warnings"].append(
            f"Dossier partagé introuvable : {project.sync_dir}")
        return summary

    manifest = _read_manifest(folder)
    if manifest and manifest.get("project_uuid") not in ("", project.uuid):
        summary["warnings"].append(
            "Ce dossier appartient à un autre projet LitUbik — scan annulé")
        return summary
    if manifest is None and project.sync_role == "coordinator":
        _write_manifest(folder, project)

    # -- inbound: co-reviewers' contribution packages -----------------------
    contributions = folder / "contributions"
    importer = _import_actor(db, project, actor)
    local_emails = {u.email for u in _local_real_members(db, project)}
    if contributions.is_dir():
        for author_dir in sorted(contributions.iterdir()):
            email = author_dir.name.lower()
            if not author_dir.is_dir() or email in local_emails:
                continue
            last = _last_imported_seq(db, project.id, email)
            new_files = sorted((f for f in author_dir.glob("*.json")
                                if _seq_of(f) > last), key=_seq_of)
            if new_files and importer is None:
                summary["warnings"].append(
                    f"{len(new_files)} paquet(s) de {email} en attente — "
                    "aucun admin local pour les importer")
                continue
            for f in new_files:
                try:
                    # read whole before its signature can be checked: bounded
                    from app.services.sync.snapshot import MAX_DATA_JSON_BYTES
                    if f.stat().st_size > MAX_DATA_JSON_BYTES:
                        raise SnapshotError("paquet trop volumineux")
                    payload = parse_package(f.read_bytes())
                    if payload.get("project_uuid") != project.uuid:
                        raise SnapshotError("paquet d'un autre projet")
                    # H3: the shared folder is untrusted (anyone with write
                    # access can drop a file) — only import packages proven to
                    # come from a passphrase holder. Unsigned/forged packages
                    # are never auto-attributed to their claimed author.
                    if signing.verify_dict(project, payload) is not True:
                        raise SnapshotError(
                            "paquet non authentifié — définissez une phrase "
                            "secrète de projet identique sur chaque instance "
                            "pour activer la synchronisation du dossier")
                    report = import_contributions(db, payload, importer)
                    summary["imported"].append(
                        {"author": email, "seq": _seq_of(f),
                         "conflicts_created": report["conflicts_created"]})
                except SnapshotError as e:
                    summary["warnings"].append(f"{f.name} : {e}")
                    log_event(db, project.id, "import", "contributions",
                              author_email=email, seq=_seq_of(f),
                              filename=f.name,
                              warnings=[f"échec du scan : {e}"])
                    db.commit()

    # -- outbound: local reviewers' contributions when they changed ---------
    for user in _local_real_members(db, project):
        current = _content_hash(db, project, user)
        if current == _last_pushed_hash(db, project.id, user.email):
            continue
        data, _filename = build_contributions(
            db, project, user, extra_counts={"content_hash": current})
        target = contributions / user.email / f"{data['seq']}.json"
        _atomic_write(target, json.dumps(data, ensure_ascii=False))
        summary["pushed"].append({"author": user.email, "seq": data["seq"]})

    # -- snapshots ----------------------------------------------------------
    latest, _path = _latest_folder_snapshot(folder)
    if project.sync_role == "coordinator":
        if latest < project.snapshot_version and project.sync_auto_publish:
            published = _copy_last_export(db, project, folder)
            if published:
                summary["published"] = project.snapshot_version
                _write_manifest(folder, project)
    else:
        summary["update_available"] = latest > project.snapshot_version
    return summary


def _copy_last_export(db: Session, project: Project, folder: Path) -> bool:
    """auto_publish: mirror the coordinator's last exported archive into the
    folder (publication itself — building the zip — stays an explicit act,
    via export or the Publier button)."""
    from app.core.config import get_settings
    source = (get_settings().data_dir / "exports"
              / f"litubik_{project.uuid[:8]}_v{project.snapshot_version}.zip")
    if not source.exists():
        return False
    target = folder / "snapshots" / f"v{project.snapshot_version}.zip"
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".zip.tmp")
    shutil.copyfile(source, tmp)
    os.replace(tmp, target)
    return True


def publish_snapshot_to_folder(db: Session, project: Project, exporter: User,
                               include_pdfs: bool, progress=None) -> dict:
    """Build a fresh snapshot and place it into the shared folder."""
    from app.services.sync.snapshot import build_snapshot
    if not project.sync_dir:
        raise SnapshotError("Aucun dossier partagé configuré")
    folder = Path(project.sync_dir)
    if not folder.is_dir():
        raise SnapshotError(f"Dossier introuvable : {project.sync_dir}")
    path = build_snapshot(db, project, include_pdfs=include_pdfs,
                          exporter=exporter, progress=progress)
    target = folder / "snapshots" / f"v{project.snapshot_version}.zip"
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".zip.tmp")
    shutil.copyfile(path, tmp)
    os.replace(tmp, target)
    _write_manifest(folder, project)
    return {"version": project.snapshot_version, "file": str(target),
            "size_kb": round(target.stat().st_size / 1024)}


def latest_folder_snapshot_path(project: Project) -> Path | None:
    if not project.sync_dir:
        return None
    _, path = _latest_folder_snapshot(Path(project.sync_dir))
    return path


def scan_all_projects():
    """Background pass over every folder-linked project (5-min loop)."""
    from app.core.db import SessionLocal
    with SessionLocal() as db:
        projects = (db.query(Project)
                    .filter(Project.sync_dir != "",
                            Project.archived_at.is_(None)).all())
        for project in projects:
            try:
                scan_project(db, project, actor=None)
            except Exception:
                logger.exception("Folder sync scan failed for project %s",
                                 project.id)
                db.rollback()
