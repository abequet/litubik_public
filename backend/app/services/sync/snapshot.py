# SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Project snapshot archive: export to / import from a `.litubik.zip`.

Layout: manifest.json + data.json (see serialize.py) + files/{ris_raw,protocol,
pdfs}. PDFs are named by record uuid inside the archive so they survive the
id remapping on import.

Import modes (decided by the project uuid):
- create: the project does not exist locally -> created as a satellite.
- update: it does -> the structural state and other people's contributions are
  replaced by the archive; contributions authored by *real local accounts*
  (password set) are preserved: newest `updated_at` wins for votes / JBI /
  extraction values, the local set wins wholesale for a local author's PDF
  annotations, local skip state is re-applied. Rows pointing at a uuid that
  disappeared from the archive are quarantined into the import report.
"""
import json
import re
import shutil
import zipfile
from pathlib import Path
from uuid import uuid4

from sqlalchemy import text as sa_text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.instance import get_instance_id
from app.core.zipguard import ZipTooLarge, check_unpacked_size
from app.models import (
    AiReveal,
    AiUsage, AppraisalConfig, AppraisalConsensus, AppraisalInstrument,
    Assignment, CertaintyAssessment, ChecklistAnswer, CitationEdge,
    Concept, Conflict,
    CustomDatabase,
    DedupPair,
    Equation, EquationCount, EquationRecall, ExtractionAssignment, ExtractionColumn,
    ExtractionConfig,
    ExtractionValue, FullText, GoldenRef, Import, JbiAppraisal, PdfAnnotation,
    Project, ProjectInvitation, ProjectMember, Protocol, ProtocolDeviation,
    Record, RecordTag,
    ReportSection, ResultsSynthesis, ScreeningConfig, ScreeningLot, SnowballRun, Source,
    SynthesisOutcome, SynthesisPlan, Tag,
    SearchUpdatePlan, SearchUpdateRun,
    User, Vote, WorkSession,
)
from app.services import framing
from app.services.sync.common import SnapshotError, log_event
from app.services.sync.credentials_sync import (
    apply_credentials_blob, build_credentials_blob,
)
from app.services.sync.serialize import (
    as_utc, collect_emails, iso, parse_dt, serialize_project,
)

FORMAT = "litubik-snapshot"
FORMAT_VERSION = 2  # 2: studies within articles (chantier 9)

# M5: reject a zip whose data.json decompresses to an absurd size before we
# ever load it into memory (json.loads of a multi-GB compressible member would
# OOM the mono-process server).
MAX_DATA_JSON_BYTES = 512 * 1024 * 1024
MAX_MANIFEST_BYTES = 1024 * 1024
# The other members (raw search exports, protocol files, PDFs) are inflated to
# disk on import. PDFs barely compress, so a real archive unpacks to about its
# own size (1 GiB upload cap) plus data.json; four times that is never reached
# by one, and stops a zip bomb from filling the disk.
MAX_SNAPSHOT_UNPACKED_BYTES = 4 * 1024 ** 3

__all__ = ["SnapshotError", "build_snapshot", "import_snapshot",
           "read_manifest"]


def _utcnow_iso() -> str:
    from app.models.accounts import utcnow
    return utcnow().isoformat()


def _storage(project_id: int) -> Path:
    return get_settings().storage_dir / str(project_id)


def _file_name(value) -> str:
    """A stored file's name, as the uploads and connectors record it: a bare
    name. An archive is not trusted to hold one, and a path there ("../..",
    an absolute path) would make the next export read any file on the server
    into the zip."""
    name = Path(str(value or "").replace("\\", "/")).name
    return "" if name in (".", "..") else name


def _local_schema_revision(db: Session) -> str | None:
    try:
        row = db.execute(
            sa_text("SELECT version_num FROM alembic_version")).fetchone()
        return row[0] if row else None
    except Exception:  # test DBs are created via metadata, not alembic
        return None


def _known_revisions() -> set[str]:
    from app.core.paths import alembic_dir
    versions_dir = alembic_dir() / "versions"
    ids: set[str] = set()
    for f in versions_dir.glob("*.py"):
        m = re.search(r"^revision(?:\s*:\s*\w+)?\s*=\s*['\"]([0-9a-f]+)['\"]",
                      f.read_text(encoding="utf-8"), re.M)
        if m:
            ids.add(m.group(1))
    return ids


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

def build_snapshot(db: Session, project: Project, include_pdfs: bool,
                   exporter: User, progress=None, public: bool = False,
                   pseudonymize: bool = False) -> Path:
    """Write the archive under data/exports/ and return its path.

    A coordinator export bumps `snapshot_version` (it defines a new reference
    state); a satellite re-export keeps the version it imported.

    public: the replication archive a team may publish (services/sync/public):
    no PDFs, abstracts, raw database exports or shared keys. It does not bump
    the version: it publishes the current state, it does not define a new one.
    pseudonymize (public only): reviewers become "Reviewer N".
    """
    from app.services.sync import public as public_archive

    def report(done, total, message):
        if progress:
            progress(done, total, message)

    if pseudonymize and not public:
        raise SnapshotError("Pseudonymisation applies to the public archive only")
    if public:
        include_pdfs = False
    elif project.sync_role == "coordinator":
        project.snapshot_version += 1
        db.commit()

    report(0, 3, "Sérialisation du projet…")
    data = serialize_project(db, project)
    exporter_email = exporter.email
    if public:
        public_archive.strip_for_publication(data)
        if pseudonymize:
            mapping = public_archive.pseudonym_map(data, (exporter.email,))
            public_archive.pseudonymize(data, mapping)
            exporter_email = mapping[exporter.email.lower()]
    manifest = {
        "format": FORMAT,
        "format_version": FORMAT_VERSION,
        "app": "LitUbik",
        "schema_revision": _local_schema_revision(db),
        "project_uuid": project.uuid,
        "project_name": project.name,
        "snapshot_version": project.snapshot_version,
        "exported_at": _utcnow_iso(),
        "exporter": {"email": exporter_email,
                     "instance_id": get_instance_id(db)},
        "includes_pdfs": include_pdfs,
    }
    if public:
        manifest["public_replication"] = {
            "removed": list(public_archive.REMOVED),
            "pseudonymized": pseudonymize,
        }

    exports_dir = get_settings().data_dir / "exports"
    exports_dir.mkdir(parents=True, exist_ok=True)
    out = exports_dir / (f"litubik_{project.uuid[:8]}"
                         f"_v{project.snapshot_version}"
                         f"{'_public' if public else ''}.zip")

    storage = _storage(project.id)
    record_uuids = {r.id: r.uuid for r in
                    db.query(Record.id, Record.uuid)
                    .filter(Record.project_id == project.id)}

    # shared project API keys travel encrypted under the project passphrase —
    # never in a public archive
    if public:
        credentials_enc, n_shared_keys, keys_note = None, 0, ""
    else:
        credentials_enc, n_shared_keys, keys_note = build_credentials_blob(
            db, project)

    # M6: authenticate provenance + content with the project passphrase (no-op
    # when none is set). The signature covers the manifest and the exact
    # data.json bytes written below. A public archive is not signed: its
    # readers do not hold the passphrase.
    from app.services.sync import signing
    data_bytes = json.dumps(data, ensure_ascii=False).encode()
    sig = (None if public else
           signing.sign_bytes(project, signing.snapshot_blob(manifest,
                                                             data_bytes)))
    if sig is not None:
        manifest["signature"] = sig

    report(1, 3, "Écriture de l'archive…")
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False,
                                                indent=1))
        zf.writestr("data.json", data_bytes)
        if credentials_enc is not None:
            zf.writestr("credentials.enc", json.dumps(credentials_enc))
        if public:
            zf.writestr("README.txt", public_archive.readme(manifest))

        for imp in data["imports"]:
            filename = _file_name(imp["filename"])
            if filename and not public:  # vendors' raw exports
                src = storage / "ris_raw" / filename
                if src.exists():
                    zf.write(src, f"files/ris_raw/{filename}")
        for proto in data["protocols"]:
            source = _file_name(proto["source_filename"])
            if source:
                name = f"v{proto['version']}_{source}"
                src = storage / "protocol" / name
                if src.exists():
                    zf.write(src, f"files/protocol/{name}")

        if include_pdfs:
            fulltexts = (db.query(FullText)
                         .join(Record, Record.id == FullText.record_id)
                         .filter(Record.project_id == project.id).all())
            with_file = [f for f in fulltexts
                         if f.file_path and Path(f.file_path).exists()]
            for i, ft in enumerate(with_file):
                uuid = record_uuids.get(ft.record_id)
                if uuid:
                    zf.write(ft.file_path, f"files/pdfs/{uuid}.pdf")
                if i % 25 == 0:
                    report(1, 3, f"PDF {i + 1}/{len(with_file)}…")

    log_event(db, project.id, "export", "snapshot",
              author_email=exporter.email, instance_id=get_instance_id(db),
              seq=project.snapshot_version, filename=out.name,
              counts={"size_kb": round(out.stat().st_size / 1024),
                      "records": len(record_uuids),
                      "includes_pdfs": include_pdfs,
                      "shared_keys": n_shared_keys,
                      "public": public, "pseudonymized": pseudonymize},
              warnings=[keys_note] if keys_note else [],
              user_id=exporter.id)
    db.commit()
    report(3, 3, "Archive prête")
    return out


# ---------------------------------------------------------------------------
# Import
# ---------------------------------------------------------------------------

def read_manifest(zip_path: Path) -> dict:
    try:
        with zipfile.ZipFile(zip_path) as zf:
            check_unpacked_size(zf, MAX_SNAPSHOT_UNPACKED_BYTES, {
                "manifest.json": MAX_MANIFEST_BYTES,
                "data.json": MAX_DATA_JSON_BYTES})
            manifest = json.loads(zf.read("manifest.json"))
    except ZipTooLarge as e:
        raise SnapshotError(f"Archive rejetée : {e}")
    except (zipfile.BadZipFile, KeyError, json.JSONDecodeError) as e:
        raise SnapshotError(f"Archive invalide : {e}")
    if manifest.get("format") != FORMAT:
        raise SnapshotError("Ce fichier n'est pas un instantané LitUbik")
    if manifest.get("format_version", 0) > FORMAT_VERSION:
        raise SnapshotError(
            "Instantané produit par une version plus récente de LitUbik — "
            "mettez cette instance à jour")
    revision = manifest.get("schema_revision")
    if revision and revision not in _known_revisions():
        raise SnapshotError(
            "Schéma de base plus récent que cette instance "
            f"(révision {revision}) — mettez LitUbik à jour")
    return manifest


def import_snapshot(db: Session, zip_path: Path, importer: User,
                    progress=None, restore_own: bool = False) -> dict:
    """Create or update the local copy of the archived project.

    restore_own = "restaurer son propre instantané" : the archive is one of
    OUR OWN backups, not a coordinator's snapshot received for a satellite
    copy. It changes two things: a coordinator project may be overwritten
    (normally refused), and the archive is taken as the reference state — no
    merge-back of local contributions (restoring a backup means discarding
    what happened since). On a create it makes the project coordinator, not
    satellite: restoring a backup on a fresh instance must yield a project
    the owner can still administer."""
    def report(done, total, message):
        if progress:
            progress(done, total, message)

    manifest = read_manifest(zip_path)
    with zipfile.ZipFile(zip_path) as zf:
        try:
            data_info = zf.getinfo("data.json")
        except KeyError:
            raise SnapshotError("Archive invalide : data.json manquant")
        if data_info.file_size > MAX_DATA_JSON_BYTES:
            raise SnapshotError(
                "data.json de l'archive trop volumineux "
                f"({data_info.file_size // (1024 * 1024)} Mo) — archive rejetée")
        data_raw = zf.read("data.json")
        data = json.loads(data_raw)

        project = (db.query(Project)
                   .filter_by(uuid=manifest["project_uuid"]).first())
        mode = "update" if project else "create"
        warnings: list[str] = []

        if mode == "create":
            # M6: a create-mode import cannot be authenticated — the project is
            # unknown here, so there is no passphrase to verify the archive
            # against. It then mints a pending account for every member email
            # the archive names, which a stranger's archive could use to squat
            # addresses on this instance.
            #
            # We do not block it: bootstrapping a satellite from a snapshot is
            # the normal way a co-reviewer joins, and the same "invite an
            # arbitrary address" primitive already exists for any user through
            # projects.add_member. So the proportionate answer is visibility —
            # the importer is told, by name, which accounts the archive is about
            # to create. A hosted deployment that wants this closed should
            # restrict project creation, not snapshot import.
            incoming = [u.get("email", "") for u in (data.get("users") or [])]
            unknown = sorted(
                e for e in incoming
                if e and db.query(User).filter_by(email=e.lower()).first() is None)
            if unknown:
                warnings.append(
                    f"Cet instantané crée {len(unknown)} compte(s) en attente : "
                    + ", ".join(unknown[:10])
                    + ("…" if len(unknown) > 10 else "")
                    + ". Ils pourront s'inscrire avec ces adresses.")

        if mode == "update":
            # M6: authenticate the archive against the local project passphrase.
            # Hard-reject ONLY a genuine mismatch (we hold the key and it fails)
            # — a tampered/forged archive. "Signed but no local passphrase" is
            # left as unverified (a satellite may not have entered it yet).
            from app.services.sync import signing
            signature = manifest.get("signature")
            key = signing.project_key(project)
            if signature and key is not None:
                if signing.verify_bytes(project,
                                        signing.snapshot_blob(manifest, data_raw),
                                        signature) is not True:
                    raise SnapshotError(
                        "Signature de l'instantané invalide (archive altérée "
                        "ou phrase secrète de projet incorrecte)")
            elif signature and key is None:
                warnings.append(
                    "Instantané signé mais aucune phrase secrète locale — "
                    "provenance non vérifiée")
            elif not signature and project.sync_passphrase_encrypted:
                warnings.append(
                    "Instantané non signé alors qu'une phrase secrète est "
                    "définie — provenance non vérifiée")
            if project.sync_role == "coordinator" and not restore_own:
                raise SnapshotError(
                    "Ce projet est coordinateur sur cette instance — un "
                    "instantané ne peut pas écraser l'état du coordinateur. "
                    "Pour restaurer volontairement une sauvegarde de ce "
                    "projet, utilisez « Restaurer depuis un instantané » "
                    "(page Synchronisation)")
            member = (db.query(ProjectMember)
                      .filter_by(project_id=project.id, user_id=importer.id)
                      .first())
            if not importer.is_admin and (member is None
                                          or member.role != "admin"):
                raise SnapshotError(
                    "Seul un admin du projet peut appliquer une mise à jour "
                    "d'instantané")

        report(0, 10, "Comptes des membres…")
        users = _ensure_users(db, data, warnings)
        shadow_users = users.pop("__shadows__")

        stash = {}
        old_pdf_dir = None
        if mode == "update":
            if restore_own:
                # backup restore: the archive IS the reference state — merging
                # newer local contributions back in would defeat the point
                report(1, 10, "Restauration : l'archive fait foi…")
            else:
                report(1, 10, "Sauvegarde des contributions locales…")
                stash = _stash_local_contributions(db, project)
            old_pdf_dir = _set_aside_pdfs(db, project)
            report(2, 10, "Remplacement de l'état du projet…")
            local_pid = project.id
            was_coordinator = project.sync_role == "coordinator"
            kept_version = project.snapshot_version
            _delete_project_children(db, project)  # ends with expunge_all
            project = db.get(Project, local_pid)
            _apply_project_fields(project, data, manifest)
            if restore_own and was_coordinator:
                # this instance stays the reference: keep its coordinator
                # identity, never roll the published version counter back
                project.coordinator_email = ""
                project.coordinator_instance_id = None
                project.snapshot_version = max(
                    kept_version, manifest.get("snapshot_version", 0))
        else:
            project = Project(
                uuid=manifest["project_uuid"],
                sync_role="coordinator" if restore_own else "satellite",
                created_by=importer.id)
            _apply_project_fields(project, data, manifest)
            if restore_own:
                project.coordinator_email = ""
                project.coordinator_instance_id = None
            created_at = parse_dt(data["project"].get("created_at"))
            if created_at:
                project.created_at = created_at
            db.add(project)
            db.flush()

        report(3, 10, "Membres…")
        _import_members(db, project, data, users, importer, warnings)

        report(4, 10, "Données structurelles…")
        maps = _insert_tables(db, project, data, users, report)

        report(7, 10, "Fichiers…")
        pdfs_missing = _import_files(zf, db, project, data, maps,
                                     old_pdf_dir)

        kept, quarantined = {}, []
        if stash:
            report(8, 10, "Fusion des contributions locales…")
            kept, quarantined = _merge_stash(db, project, stash, maps, users)

        credentials_blob = (json.loads(zf.read("credentials.enc"))
                            if "credentials.enc" in zf.namelist() else None)
        credentials_counts = apply_credentials_blob(
            db, project, credentials_blob, replace_owner_emails=None,
            warnings=warnings)

    log_event(db, project.id, "import", "snapshot",
              author_email=manifest["exporter"].get("email", ""),
              instance_id=manifest["exporter"].get("instance_id") or "",
              seq=manifest.get("snapshot_version", 0),
              filename=zip_path.name,
              counts={"mode": mode, "restore": restore_own,
                      "records": len(maps["records"]),
                      "votes": len(data.get("votes", []))},
              warnings=warnings, user_id=importer.id)
    db.commit()
    report(10, 10, "Import terminé")
    return {
        "mode": mode,
        "restored": restore_own,
        "project_id": project.id,
        "project_uuid": project.uuid,
        "project_name": project.name,
        "snapshot_version": project.snapshot_version,
        "counts": {k: len(v) for k, v in maps.items()},
        "n_votes": len(data.get("votes", [])),
        "kept_local": kept,
        "quarantined_count": len(quarantined),
        "quarantined_sample": quarantined[:20],
        "shadow_users": shadow_users,
        "pdfs_missing": pdfs_missing,
        "credentials": credentials_counts,
        "warnings": warnings,
    }


def _apply_project_fields(project: Project, data: dict, manifest: dict):
    p = data["project"]
    project.name = p["name"]
    project.description = p.get("description", "")
    project.research_question = p.get("research_question", "")
    # Snapshots written before the framing settings existed carry neither key;
    # the defaults are the historical behaviour, so an older coordinator never
    # silently re-frames a satellite.
    project.review_type = p.get("review_type") or framing.DEFAULT_REVIEW_TYPE
    project.question_framework = (p.get("question_framework")
                                  or framing.DEFAULT_FRAMEWORK)
    project.llm_no_fallback = bool(p.get("llm_no_fallback", False))
    project.databases = p.get("databases") or None
    # Registration is structural: the coordinator registered the review, and a
    # satellite must report the same identifier. An older snapshot carries none
    # of these keys, which reads as "undeclared" — the historical state.
    project.registry = p.get("registry") or ""
    project.registration_id = p.get("registration_id") or ""
    project.registration_url = p.get("registration_url") or ""
    project.registered_at = parse_dt(p.get("registered_at"))
    project.protocol_url = p.get("protocol_url") or ""
    project.highlights = p.get("highlights") or {}
    project.coordinator_email = manifest["exporter"]["email"]
    project.coordinator_instance_id = manifest["exporter"].get("instance_id")
    project.snapshot_version = manifest.get("snapshot_version", 0)


def _ensure_users(db: Session, data: dict, warnings: list[str]) -> dict:
    """email -> local User for every email in the archive; people without a
    local account get a shadow account (empty password hash: cannot log in,
    claimed at registration — see api/auth.register)."""
    display_names = {m["email"].lower(): m.get("display_name") or ""
                     for m in data.get("members", [])}
    existing = {u.email: u for u in db.query(User).all()}
    users: dict = {}
    shadows: list[str] = []
    for email in sorted(collect_emails(data)):
        user = existing.get(email)
        if user is None:
            user = User(email=email, password_hash="",
                        display_name=display_names.get(email)
                        or email.split("@")[0])
            db.add(user)
            db.flush()
            shadows.append(email)
        users[email] = user
    users["__shadows__"] = shadows
    return users


def _import_members(db: Session, project: Project, data: dict, users: dict,
                    importer: User, warnings: list[str]):
    importer_listed = False
    for m in data.get("members", []):
        email = m["email"].lower()
        if m.get("status") == "invited":
            db.add(ProjectInvitation(project_id=project.id, email=email,
                                     role=m.get("role", "reviewer")))
            continue
        user = users[email]
        db.add(ProjectMember(project_id=project.id, user_id=user.id,
                             role=m.get("role", "reviewer")))
        if user.id == importer.id:
            importer_listed = True
    if not importer_listed:
        db.add(ProjectMember(project_id=project.id, user_id=importer.id,
                             role="admin"))
        warnings.append(
            "Vous ne figurez pas parmi les membres de l'instantané : ajouté "
            "comme admin local — vos contributions ne seront synchronisées "
            "que si le coordinateur vous ajoute au projet")
    db.flush()


# -- update mode: stash / delete ------------------------------------------

def _real_local_user_ids(db: Session) -> dict[int, str]:
    """Accounts a human can actually log into on this instance (not shadows)."""
    return {u.id: u.email for u in db.query(User)
            .filter(User.password_hash != "")}


def _stash_local_contributions(db: Session, project: Project) -> dict:
    locals_ = _real_local_user_ids(db)
    record_uuids = {r.id: r.uuid for r in
                    db.query(Record.id, Record.uuid)
                    .filter(Record.project_id == project.id)}
    column_uuids = {c.id: c.uuid for c in
                    db.query(ExtractionColumn)
                    .filter_by(project_id=project.id)}
    config_uuids = {c.id: c.uuid for c in
                    db.query(ScreeningConfig)
                    .filter_by(project_id=project.id)}

    votes = []
    for v in db.query(Vote).filter_by(project_id=project.id):
        if v.is_ai:
            if v.generated_by not in locals_.values():
                continue
        elif v.voter_user_id not in locals_:
            continue
        votes.append({
            "record": record_uuids.get(v.record_id), "stage": v.stage,
            "round": v.round,
            "email": locals_.get(v.voter_user_id), "is_ai": v.is_ai,
            "decision": v.decision, "reasons": v.reasons,
            "justification": v.justification,
            "criteria_eval": v.criteria_eval, "confidence": v.confidence,
            "generated_by": v.generated_by,
            "imported_from": v.imported_from,
            "created_at": iso(v.created_at), "updated_at": iso(v.updated_at)})

    # every study of the project: the archive brings the coordinator's, but a
    # study declared here (position > 0) must survive the import, and local
    # values are addressed through them
    from app.models import ExtractionStudy
    study_rows = (db.query(ExtractionStudy)
                  .join(Record, Record.id == ExtractionStudy.record_id)
                  .filter(Record.project_id == project.id).all())
    studies = [
        {"uuid": s.uuid, "record": record_uuids.get(s.record_id),
         "position": s.position, "label": s.label,
         "study_design": s.study_design, "design_origin": s.design_origin,
         "email": locals_.get(s.created_by)}
        for s in study_rows if record_uuids.get(s.record_id)
    ]
    study_ref = {s.id: (s.uuid, s.position) for s in study_rows}

    def study_fields(study_id):
        uuid, position = study_ref.get(study_id, (None, 0))
        return {"study": uuid, "study_position": position}

    jbi = [
        {"record": record_uuids.get(j.record_id), "email": locals_[j.user_id],
         "design": j.design, "answers": j.answers, "overall": j.overall,
         "comment": j.comment, "imported_from": j.imported_from,
         "updated_at": iso(j.updated_at), **study_fields(j.study_id)}
        for j in db.query(JbiAppraisal)
        .join(Record, Record.id == JbiAppraisal.record_id)
        .filter(Record.project_id == project.id)
        if j.user_id in locals_
    ]

    values = [
        {"record": record_uuids.get(v.record_id),
         "column": column_uuids.get(v.column_id),
         "email": locals_[v.user_id], "value": v.value, "origin": v.origin,
         "validated": v.validated, "imported_from": v.imported_from,
         "updated_at": iso(v.updated_at), **study_fields(v.study_id)}
        for v in db.query(ExtractionValue)
        .join(Record, Record.id == ExtractionValue.record_id)
        .filter(Record.project_id == project.id)
        if v.user_id in locals_
    ]

    annotations = [
        {"record": record_uuids.get(a.record_id), "email": locals_[a.user_id],
         "page": a.page, "rects": a.rects, "quote": a.quote, "note": a.note,
         "color": a.color, "imported_from": a.imported_from,
         "created_at": iso(a.created_at),
         "updated_at": iso(a.updated_at)}
        for a in db.query(PdfAnnotation).filter_by(project_id=project.id)
        if a.user_id in locals_
    ]

    skips = [
        {"config": config_uuids.get(a.config_id),
         "record": record_uuids.get(a.record_id),
         "email": locals_[a.user_id], "skipped_at": iso(a.skipped_at)}
        for a in db.query(Assignment)
        .join(ScreeningConfig, ScreeningConfig.id == Assignment.config_id)
        .filter(ScreeningConfig.project_id == project.id)
        if a.user_id in locals_ and a.skipped_at is not None
    ]

    tag_names = {t.id: t.name for t in
                 db.query(Tag).filter_by(project_id=project.id)}
    tags = [
        {"tag": tag_names.get(rt.tag_id),
         "record": record_uuids.get(rt.record_id),
         "email": locals_[rt.created_by], "created_at": iso(rt.created_at)}
        for rt in db.query(RecordTag)
        .join(Tag, Tag.id == RecordTag.tag_id)
        .filter(Tag.project_id == project.id)
        if rt.created_by in locals_ and tag_names.get(rt.tag_id)
    ]

    work_sessions = [
        {"uuid": s.uuid, "email": locals_[s.user_id], "stage": s.stage,
         "started_at": iso(s.started_at), "last_seen_at": iso(s.last_seen_at),
         "n_heartbeats": s.n_heartbeats, "instance_id": s.instance_id,
         "imported_from": s.imported_from}
        for s in db.query(WorkSession).filter_by(project_id=project.id)
        if s.user_id in locals_
    ]

    return {"votes": votes, "jbi": jbi, "values": values,
            "annotations": annotations, "skips": skips, "tags": tags,
            "work_sessions": work_sessions, "studies": studies}


def _set_aside_pdfs(db: Session, project: Project) -> Path | None:
    """Move the pdfs dir aside so stored files survive the record-id remap;
    an index.json sidecar maps record uuid -> file name for re-linking."""
    rows = (db.query(FullText, Record.uuid)
            .join(Record, Record.id == FullText.record_id)
            .filter(Record.project_id == project.id,
                    FullText.file_path != ""))
    index = {uuid: Path(ft.file_path).name for ft, uuid in rows
             if Path(ft.file_path).exists()}
    pdfs = _storage(project.id) / "pdfs"
    if not index or not pdfs.exists():
        return None
    old = _storage(project.id) / "pdfs_old"
    if old.exists():
        shutil.rmtree(old, ignore_errors=True)
    pdfs.rename(old)
    (old / "index.json").write_text(json.dumps(index), encoding="utf-8")
    return old


def _delete_project_children(db: Session, project: Project):
    """Children without a project_id column (equation_counts, assignments,
    fulltexts, extraction values/assignments, jbi, record_tags) go through
    DB-level ON DELETE CASCADE (PRAGMA foreign_keys=ON)."""
    pid = project.id
    for model in (ReportSection, AiUsage, ResultsSynthesis, PdfAnnotation,
                  SearchUpdateRun, SearchUpdatePlan,
                  Conflict, Vote, AiReveal, WorkSession,
                  CitationEdge, SnowballRun, DedupPair, Tag, ScreeningConfig,
                  # AppraisalConfig is unique per project: a stale row would
                  # collide with the one the archive brings back
                  AppraisalConsensus, AppraisalConfig, AppraisalInstrument,
                  SynthesisOutcome, SynthesisPlan, ProtocolDeviation,
                  ChecklistAnswer,
                  ExtractionConfig, ExtractionColumn, Record, Import, Source,
                  GoldenRef, Equation, CustomDatabase, Concept, Protocol,
                  ProjectMember,
                  ProjectInvitation):
        db.query(model).filter_by(project_id=pid).delete(
            synchronize_session=False)
    db.flush()
    # fully clear the identity map: re-inserted rows reuse autoincrement ids
    # of the deleted ones, which would collide with the stale instances
    db.expunge_all()


# -- insertion --------------------------------------------------------------

def _insert_tables(db: Session, project: Project, data: dict, users: dict,
                   report) -> dict:
    """Insert every serialized table in dependency order; returns the
    portable-key -> local-id maps ("counts" in the report)."""
    pid = project.id

    def uid(email):
        user = users.get(email.lower()) if email else None
        return user.id if user else None

    protocols = {}
    for p in data.get("protocols", []):
        row = Protocol(
            project_id=pid, uuid=p["uuid"], version=p["version"],
            source_filename=_file_name(p.get("source_filename")),
            source_text=p.get("source_text", ""),
            generated_with=p.get("generated_with", ""),
            protocol_md=p.get("protocol_md", ""),
            criteria=p.get("criteria") or [],
            validated_at=parse_dt(p.get("validated_at")),
            created_at=parse_dt(p.get("created_at")))
        db.add(row)
        protocols[p["uuid"]] = row
    db.flush()

    concepts = {}
    for c in data.get("concepts", []):
        row = Concept(project_id=pid, uuid=c["uuid"], name=c["name"],
                      description=c.get("description", ""),
                      keywords=c.get("keywords") or [],
                      position=c.get("position", 0))
        db.add(row)
        concepts[c["uuid"]] = row
    db.flush()

    for c in data.get("custom_databases", []):
        db.add(CustomDatabase(
            project_id=pid, uuid=c["uuid"], db_id=c["db_id"], label=c["label"],
            syntax=c.get("syntax", "generic"),
            instructions=c.get("instructions", ""), url=c.get("url", ""),
            created_at=parse_dt(c.get("created_at"))))
    db.flush()

    equations = {}
    for e in data.get("equations", []):
        row = Equation(
            project_id=pid, uuid=e["uuid"], label=e["label"],
            mode=e.get("mode") or "concepts",
            structure=e.get("structure") or {},
            translations=e.get("translations") or {},
            params=e.get("params") or {}, status=e.get("status", "draft"),
            frozen_at=parse_dt(e.get("frozen_at")),
            golden_results=e.get("golden_results"),
            created_at=parse_dt(e.get("created_at")))
        db.add(row)
        db.flush()
        equations[e["uuid"]] = row
        for c in e.get("counts", []):
            db.add(EquationCount(
                equation_id=row.id, database_name=c["database_name"],
                count=c["count"], method=c.get("method", "api"),
                noted_at=parse_dt(c.get("noted_at"))))
        for r in e.get("recalls", []):
            db.add(EquationRecall(
                equation_id=row.id, database_name=r["database_name"],
                method=r.get("method", "api"), total=r.get("total", 0),
                found=r.get("found", 0), missing=r.get("missing") or [],
                checked_at=parse_dt(r.get("checked_at"))))

    golden = {}
    for g in data.get("golden_refs", []):
        row = GoldenRef(project_id=pid, uuid=g["uuid"], doi=g.get("doi"),
                        pmid=g.get("pmid"),
                        title=g.get("title", ""), year=g.get("year"),
                        apa=g.get("apa", ""),
                        added_at=parse_dt(g.get("added_at")))
        db.add(row)
        golden[g["uuid"]] = row

    sources = {}
    for s in data.get("sources", []):
        row = Source(project_id=pid, uuid=s["uuid"], type=s["type"],
                     name=s["name"], round=s.get("round", 1))
        db.add(row)
        sources[s["uuid"]] = row
    db.flush()

    imports = {}
    for i in data.get("imports", []):
        source = sources.get(i.get("source"))
        if source is None:
            continue
        equation = equations.get(i.get("equation"))
        row = Import(project_id=pid, uuid=i["uuid"], source_id=source.id,
                     equation_id=equation.id if equation else None,
                     filename=_file_name(i.get("filename")),
                     n_records=i.get("n_records", 0),
                     imported_by=uid(i.get("imported_by")),
                     imported_at=parse_dt(i.get("imported_at")),
                     searched_at=parse_dt(i.get("searched_at")),
                     declared_hits=i.get("declared_hits"),
                     date_restricted=i.get("date_restricted"),
                     discipline_restricted=i.get("discipline_restricted"),
                     disciplines=i.get("disciplines"),
                     doc_type_restricted=i.get("doc_type_restricted"),
                     doc_types=i.get("doc_types"),
                     search_fields=i.get("search_fields"))
        db.add(row)
        imports[i["uuid"]] = row
    db.flush()

    report(5, 10, f"Records ({len(data.get('records', []))})…")
    records = {}
    for r in data.get("records", []):
        imp = imports.get(r.get("import"))
        if imp is None:
            continue
        row = Record(
            project_id=pid, uuid=r["uuid"], import_id=imp.id,
            doi=r.get("doi"), pmid=r.get("pmid"), title=r.get("title", ""),
            authors=r.get("authors") or [], year=r.get("year"),
            journal=r.get("journal", ""), abstract=r.get("abstract", ""),
            raw_ris=r.get("raw_ris", ""),
            dedup_status=r.get("dedup_status", "pending"),
            study_design=r.get("study_design"),
            design_origin=r.get("design_origin"),
            abstract_original=r.get("abstract_original"),
            abstract_edited_by=uid(r.get("abstract_edited_by")),
            abstract_edited_at=parse_dt(r.get("abstract_edited_at")),
            translations=r.get("translations"))
        db.add(row)
        records[r["uuid"]] = row
    db.flush()
    for r in data.get("records", []):  # canonical links, second pass
        if r.get("canonical") and r["uuid"] in records:
            canonical = records.get(r["canonical"])
            if canonical:
                records[r["uuid"]].canonical_id = canonical.id
    db.flush()

    def rid(uuid):
        row = records.get(uuid)
        return row.id if row else None

    for d in data.get("dedup_pairs", []):
        record_id, canonical_id = rid(d.get("record")), rid(d.get("canonical"))
        if record_id and canonical_id:
            db.add(DedupPair(
                project_id=pid, record_id=record_id,
                canonical_id=canonical_id, score=d.get("score", 0.0),
                reason=d.get("reason", ""), status=d.get("status", "pending"),
                created_at=parse_dt(d.get("created_at")),
                resolved_by=uid(d.get("resolved_by")),
                resolved_at=parse_dt(d.get("resolved_at"))))

    for c in data.get("citation_edges", []):
        citing, cited = rid(c.get("citing")), rid(c.get("cited"))
        if citing and cited:
            db.add(CitationEdge(
                project_id=pid, citing_record_id=citing,
                cited_record_id=cited, direction=c["direction"],
                round=c.get("round", 2),
                created_at=parse_dt(c.get("created_at"))))

    snowballs = {}
    for s in data.get("snowball_runs", []):
        row = SnowballRun(
            project_id=pid, uuid=s["uuid"], round=s["round"],
            seed_record_ids=[rid(u) for u in s.get("seed_record_uuids", [])
                             if rid(u)],
            n_seeds=s.get("n_seeds", 0), n_backward=s.get("n_backward", 0),
            n_forward=s.get("n_forward", 0),
            n_new_records=s.get("n_new_records", 0),
            n_new_unique=s.get("n_new_unique", 0),
            created_at=parse_dt(s.get("created_at")))
        db.add(row)
        snowballs[s["uuid"]] = row

    for r in data.get("search_update_runs", []):
        db.add(SearchUpdateRun(
            project_id=pid, uuid=r["uuid"], round=r["round"],
            databases=r.get("databases") or [],
            since_at=parse_dt(r.get("since_at")),
            n_fetched=r.get("n_fetched", 0), n_new_unique=r.get("n_new_unique", 0),
            triggered_by=r.get("triggered_by", "manual"),
            errors=r.get("errors") or {}, created_by=uid(r.get("created_by")),
            started_at=parse_dt(r.get("started_at")),
            finished_at=parse_dt(r.get("finished_at"))))
    plan = data.get("search_update_plan")
    if plan:
        eq_row = equations.get(plan.get("equation")) if plan.get("equation") else None
        db.add(SearchUpdatePlan(
            project_id=pid, uuid=plan["uuid"], enabled=plan.get("enabled", False),
            interval_days=plan.get("interval_days", 30),
            databases=plan.get("databases") or [],
            equation_id=eq_row.id if eq_row is not None else None,
            last_run_at=parse_dt(plan.get("last_run_at")),
            next_run_at=parse_dt(plan.get("next_run_at")),
            created_by=uid(plan.get("created_by"))))

    configs = {}
    for c in data.get("screening_configs", []):
        row = ScreeningConfig(
            project_id=pid, uuid=c["uuid"], stage=c["stage"],
            round=c.get("round", 1), n_reviewers=c.get("n_reviewers", 2),
            decision_rule=c.get("decision_rule", "all"),
            maybe_policy=c.get("maybe_policy", "conflict"),
            ai_enabled=c.get("ai_enabled", False),
            ai_mode=c.get("ai_mode", "suggestion"),
            ai_triage=c.get("ai_triage", "off"),
            ai_batch=c.get("ai_batch", False),
            ai_reveal=c.get("ai_reveal", "always"),
            allocation=c.get("allocation", "all"),
            overlap_pct=c.get("overlap_pct", 20),
            conflict_resolution=c.get("conflict_resolution", "consensus"),
            reviewer_ids=[x for x in (uid(e) for e in
                                      c.get("reviewer_emails", [])) if x],
            weights={str(uid(e)): pct for e, pct in
                     (c.get("weights") or {}).items() if uid(e)} or None,
            lot_size=c.get("lot_size") or 100,
            arbiter_ids=[x for x in (uid(e) for e in
                                     c.get("arbiter_emails", [])) if x],
            lead_user_id=(uid(c["lead_email"]) if c.get("lead_email")
                          else None),
            triage_control_pct=c.get("triage_control_pct") or 0,
            anonymous=bool(c.get("anonymous", False)),
            status=c.get("status", "draft"),
            started_at=parse_dt(c.get("started_at")),
            created_at=parse_dt(c.get("created_at")))
        db.add(row)
        configs[c["uuid"]] = row
    db.flush()

    lots = {}
    for lot in data.get("screening_lots", []):
        config = configs.get(lot.get("config"))
        if config is None:
            continue
        row = ScreeningLot(
            config_id=config.id, uuid=lot["uuid"], index=lot.get("index", 0),
            user_ids=[x for x in (uid(e) for e in lot.get("emails", [])) if x],
            due_at=parse_dt(lot.get("due_at")),
            status=lot.get("status", "open"),
            created_at=parse_dt(lot.get("created_at")))
        db.add(row)
        lots[lot["uuid"]] = row
    db.flush()

    report(6, 10, f"Votes ({len(data.get('votes', []))})…")
    for a in data.get("assignments", []):
        config, record_id = configs.get(a.get("config")), rid(a.get("record"))
        user_id = uid(a.get("email"))
        lot = lots.get(a.get("lot")) if a.get("lot") else None
        if config and record_id and user_id:
            db.add(Assignment(config_id=config.id, record_id=record_id,
                              user_id=user_id,
                              lot_id=lot.id if lot else None,
                              skipped_at=parse_dt(a.get("skipped_at"))))

    for v in data.get("votes", []):
        record_id = rid(v.get("record"))
        if record_id is None:
            continue
        db.add(Vote(
            project_id=pid, record_id=record_id, stage=v["stage"],
            round=v.get("round", 1), voter_user_id=uid(v.get("email")),
            is_ai=v.get("is_ai", False), decision=v["decision"],
            reasons=v.get("reasons") or [],
            justification=v.get("justification", ""),
            criteria_eval=v.get("criteria_eval") or {},
            confidence=v.get("confidence"),
            generated_by=v.get("generated_by"),
            imported_from=v.get("imported_from"),
            created_at=parse_dt(v.get("created_at")),
            updated_at=parse_dt(v.get("updated_at"))))

    for r in data.get("ai_reveals", []):
        record_id, user_id = rid(r.get("record")), uid(r.get("email"))
        if record_id is None or user_id is None:
            continue
        db.add(AiReveal(
            project_id=pid, record_id=record_id, stage=r["stage"],
            round=r.get("round", 1), user_id=user_id,
            revealed_at=parse_dt(r.get("revealed_at")),
            imported_from=r.get("imported_from")))

    for s in data.get("work_sessions", []):
        user_id = uid(s.get("email"))
        if user_id is None or not s.get("uuid"):
            continue
        db.add(WorkSession(
            project_id=pid, uuid=s["uuid"], user_id=user_id,
            stage=s.get("stage", "ta"),
            started_at=parse_dt(s.get("started_at")),
            last_seen_at=parse_dt(s.get("last_seen_at")),
            n_heartbeats=s.get("n_heartbeats", 0),
            instance_id=s.get("instance_id") or "",
            imported_from=s.get("imported_from")))

    for c in data.get("conflicts", []):
        record_id = rid(c.get("record"))
        if record_id is None:
            continue
        db.add(Conflict(
            project_id=pid, record_id=record_id, stage=c["stage"],
            round=c.get("round", 1), status=c.get("status", "open"),
            resolution=c.get("resolution", ""),
            resolution_note=c.get("resolution_note", ""),
            origin=c.get("origin", "votes"), reasons=c.get("reasons") or [],
            resolved_by=uid(c.get("resolved_by")),
            resolved_at=parse_dt(c.get("resolved_at"))))

    fulltexts = {}
    for f in data.get("fulltexts", []):
        record_id = rid(f.get("record"))
        if record_id is None:
            continue
        row = FullText(
            record_id=record_id, status=f.get("status", "pending"),
            file_path="", filename=f.get("filename", ""),
            via=f.get("via", ""), oa_url=f.get("oa_url", ""),
            error=f.get("error", ""), size_kb=f.get("size_kb"),
            updated_at=parse_dt(f.get("updated_at")))
        db.add(row)
        fulltexts[f["record"]] = row

    columns = {}
    for c in data.get("extraction_columns", []):
        row = ExtractionColumn(
            project_id=pid, uuid=c["uuid"], name=c["name"],
            col_type=c.get("col_type", "text"),
            description=c.get("description", ""),
            options=c.get("options") or [], is_jbi=c.get("is_jbi", False),
            position=c.get("position", 0))
        db.add(row)
        columns[c["uuid"]] = row
    db.flush()

    xc = data.get("extraction_config")
    if xc:
        xconfig = ExtractionConfig(
            project_id=pid, n_extractors=xc.get("n_extractors", 1),
            extractor_ids=[x for x in (uid(e) for e in
                                       xc.get("extractor_emails", [])) if x],
            status=xc.get("status", "draft"),
            started_at=parse_dt(xc.get("started_at")),
            created_at=parse_dt(xc.get("created_at")))
        db.add(xconfig)
        db.flush()
        for a in data.get("extraction_assignments", []):
            record_id = rid(a.get("record"))
            user_id = uid(a.get("email"))
            if record_id and user_id:
                db.add(ExtractionAssignment(
                    config_id=xconfig.id, record_id=record_id,
                    user_id=user_id))

    # chantier 9: the studies each article reports. A v1 archive carries
    # none — every row then lands on a default study created on the fly.
    from app.models import ExtractionStudy
    studies: dict[str, ExtractionStudy] = {}
    study_by_pos: dict[tuple[str, int], ExtractionStudy] = {}
    for s in data.get("extraction_studies", []):
        record_id = rid(s.get("record"))
        if record_id is None:
            continue
        row = ExtractionStudy(
            record_id=record_id, uuid=s.get("uuid") or str(uuid4()),
            label=s.get("label") or "Study 1", position=s.get("position", 0),
            study_design=s.get("study_design"),
            design_origin=s.get("design_origin"),
            created_by=uid(s.get("created_by")),
            created_at=parse_dt(s.get("created_at")))
        db.add(row)
        studies[row.uuid] = row
        study_by_pos[(s.get("record"), row.position)] = row
    db.flush()

    def sid(record_uuid, study_uuid, position):
        """The local study a serialized row points at: by uuid, then by
        (record, position), else the article's default study."""
        row = studies.get(study_uuid) if study_uuid else None
        if row is None:
            row = study_by_pos.get((record_uuid, position or 0))
        if row is None:
            record_id = rid(record_uuid)
            if record_id is None:
                return None
            row = ExtractionStudy(record_id=record_id, label="Study 1",
                                  position=position or 0)
            db.add(row)
            db.flush()
            studies[row.uuid] = row
            study_by_pos[(record_uuid, row.position)] = row
        return row.id

    for v in data.get("extraction_values", []):
        record_id, column = rid(v.get("record")), columns.get(v.get("column"))
        if record_id and column:
            db.add(ExtractionValue(
                record_id=record_id, column_id=column.id,
                study_id=sid(v.get("record"), v.get("study"),
                             v.get("study_position")),
                user_id=uid(v.get("email")), value=v.get("value") or {},
                origin=v.get("origin", "human"),
                validated=v.get("validated", False),
                imported_from=v.get("imported_from"),
                updated_at=parse_dt(v.get("updated_at"))))

    for j in data.get("jbi_appraisals", []):
        record_id = rid(j.get("record"))
        if record_id and uid(j.get("email")):
            db.add(JbiAppraisal(
                record_id=record_id, user_id=uid(j["email"]),
                study_id=sid(j.get("record"), j.get("study"),
                             j.get("study_position")),
                design=j.get("design", ""),
                instrument=j.get("instrument") or "jbi",
                answers=j.get("answers") or {},
                overall=j.get("overall", ""), comment=j.get("comment", ""),
                imported_from=j.get("imported_from"),
                updated_at=parse_dt(j.get("updated_at"))))

    # Appraisal rules are the coordinator's: a satellite appraises under the
    # same instrument and the same two-assessor requirement. Snapshots written
    # before this existed carry none of these keys, which leaves the satellite
    # in the historical "any member appraises with JBI" behaviour.
    for i in data.get("appraisal_instruments", []):
        db.add(AppraisalInstrument(
            project_id=pid, uuid=i.get("uuid") or str(uuid4()),
            key=i.get("key", ""), label=i.get("label", ""),
            citation=i.get("citation", ""), url=i.get("url", ""),
            checklists=i.get("checklists") or {},
            created_at=parse_dt(i.get("created_at"))))

    ac = data.get("appraisal_config")
    if ac:
        db.add(AppraisalConfig(
            project_id=pid, status=ac.get("status", "draft"),
            instrument=ac.get("instrument") or "jbi",
            n_assessors=ac.get("n_assessors", 1),
            assessor_ids=[x for x in (uid(e) for e
                                      in ac.get("assessor_emails", [])) if x],
            conflict_scope=ac.get("conflict_scope", "overall"),
            conflict_resolution=ac.get("conflict_resolution", "consensus"),
            started_at=parse_dt(ac.get("started_at")),
            created_at=parse_dt(ac.get("created_at"))))

    for c in data.get("appraisal_consensus", []):
        record_id = rid(c.get("record"))
        if record_id:
            db.add(AppraisalConsensus(
                project_id=pid, record_id=record_id,
                study_id=sid(c.get("record"), c.get("study"),
                             c.get("study_position")),
                design=c.get("design", ""),
                instrument=c.get("instrument") or "jbi",
                answers=c.get("answers") or {},
                overall=c.get("overall", ""), comment=c.get("comment", ""),
                resolved_by=uid(c.get("resolved_by")),
                resolved_at=parse_dt(c.get("resolved_at")),
                imported_from=c.get("imported_from"),
                updated_at=parse_dt(c.get("updated_at"))))

    sp = data.get("synthesis_plan")
    if sp:
        db.add(SynthesisPlan(
            project_id=pid, enabled=sp.get("enabled", False),
            certainty_framework=sp.get("certainty_framework") or "none",
            grouping_md=sp.get("grouping_md", ""),
            grouping_changes_md=sp.get("grouping_changes_md", ""),
            prioritisation_md=sp.get("prioritisation_md", ""),
            heterogeneity_md=sp.get("heterogeneity_md", ""),
            presentation_md=sp.get("presentation_md", ""),
            limitations_md=sp.get("limitations_md", ""),
            updated_at=parse_dt(sp.get("updated_at"))))

    for o in data.get("synthesis_outcomes", []):
        outcome = SynthesisOutcome(
            project_id=pid, uuid=o.get("uuid") or str(uuid4()),
            label=o.get("label", ""), comparison=o.get("comparison", ""),
            position=o.get("position", 0),
            intent=o.get("intent") or "association",
            target=o.get("target") or "any_effect",
            thresholds_md=o.get("thresholds_md", ""),
            direction=o.get("direction") or "unclear",
            metric=o.get("metric", ""),
            metric_rationale=o.get("metric_rationale", ""),
            synthesis_method=o.get("synthesis_method") or "narrative",
            method_rationale=o.get("method_rationale", ""),
            # a study that did not survive the archive simply stops
            # contributing; the outcome keeps the ones that did. v1 archives
            # list record uuids: those map onto each article's first study.
            study_ids=[s for s in (
                [sid(x.get("record"), x.get("study"), x.get("study_position"))
                 for x in o.get("studies", []) if isinstance(x, dict)]
                + [sid(u, None, 0) for u in o.get("record_uuids", [])]) if s],
            finding_md=o.get("finding_md", ""),
            effect_spec=({"measure": o["effect_spec"]["measure"],
                          "mapping": {role: columns[u].id for role, u in
                                      (o["effect_spec"].get("mapping") or {}).items()
                                      if u in columns}}
                         if (o.get("effect_spec") or {}).get("measure") else {}),
            created_at=parse_dt(o.get("created_at")),
            updated_at=parse_dt(o.get("updated_at")))
        db.add(outcome)
        db.flush()
        for c in o.get("certainty_assessments", []):
            db.add(CertaintyAssessment(
                outcome_id=outcome.id,
                user_id=uid(c.get("email")),
                is_consensus=c.get("is_consensus", False),
                starting_point=c.get("starting_point") or "low",
                starting_rationale=c.get("starting_rationale", ""),
                domains=c.get("domains") or {},
                upgrades=c.get("upgrades") or {},
                final=c.get("final", ""),
                statement_md=c.get("statement_md", ""),
                resolved_by=uid(c.get("resolved_by")),
                imported_from=c.get("imported_from"),
                updated_at=parse_dt(c.get("updated_at"))))

    for a in data.get("checklist_answers", []):
        db.add(ChecklistAnswer(
            project_id=pid, checklist=a.get("checklist", ""),
            item=a.get("item", ""), page_ref=a.get("page_ref", ""),
            note=a.get("note", ""),
            status_override=a.get("status_override", ""),
            updated_at=parse_dt(a.get("updated_at"))))

    for d in data.get("protocol_deviations", []):
        db.add(ProtocolDeviation(
            project_id=pid, uuid=d.get("uuid") or str(uuid4()),
            stage=d.get("stage") or "protocol",
            kind=d.get("kind") or "declared", signal=d.get("signal"),
            summary=d.get("summary", ""), rationale=d.get("rationale", ""),
            occurred_at=parse_dt(d.get("occurred_at")),
            declared_by=uid(d.get("declared_by")),
            dismissed_at=parse_dt(d.get("dismissed_at")),
            dismiss_note=d.get("dismiss_note", ""),
            created_at=parse_dt(d.get("created_at")),
            updated_at=parse_dt(d.get("updated_at"))))

    for a in data.get("pdf_annotations", []):
        record_id = rid(a.get("record"))
        if record_id:
            db.add(PdfAnnotation(
                project_id=pid, record_id=record_id,
                user_id=uid(a.get("email")), page=a.get("page", 1),
                rects=a.get("rects") or [], quote=a.get("quote", ""),
                note=a.get("note", ""), color=a.get("color", "yellow"),
                imported_from=a.get("imported_from"),
                created_at=parse_dt(a.get("created_at")),
                updated_at=parse_dt(a.get("updated_at"))))

    tags = {}
    for t in data.get("tags", []):
        row = Tag(project_id=pid, name=t["name"],
                  created_by=uid(t.get("created_by")),
                  created_at=parse_dt(t.get("created_at")))
        db.add(row)
        tags[t["name"]] = row
    db.flush()
    for rt in data.get("record_tags", []):
        tag, record_id = tags.get(rt.get("tag")), rid(rt.get("record"))
        if tag and record_id:
            db.add(RecordTag(tag_id=tag.id, record_id=record_id,
                             created_by=uid(rt.get("created_by")),
                             created_at=parse_dt(rt.get("created_at"))))

    rs = data.get("results_synthesis")
    if rs:
        db.add(ResultsSynthesis(
            project_id=pid, content_md=rs.get("content_md", ""),
            provider=rs.get("provider", ""), model=rs.get("model", ""),
            tokens_in=rs.get("tokens_in", 0),
            tokens_out=rs.get("tokens_out", 0),
            cost_usd=rs.get("cost_usd", 0.0),
            generated_by=uid(rs.get("generated_by")),
            created_at=parse_dt(rs.get("created_at"))))

    for s in data.get("report_sections", []):
        db.add(ReportSection(
            project_id=pid, kind=s.get("kind", ""), lang=s.get("lang", "en"),
            content_md=s.get("content_md", ""),
            edited_md=s.get("edited_md", ""), form=s.get("form") or {},
            provider=s.get("provider", ""), model=s.get("model", ""),
            tokens_in=s.get("tokens_in", 0), tokens_out=s.get("tokens_out", 0),
            cost_usd=s.get("cost_usd", 0.0),
            generated_by=uid(s.get("generated_by")),
            created_at=parse_dt(s.get("created_at")),
            updated_at=parse_dt(s.get("updated_at"))))

    for u in data.get("ai_usage", []):
        db.add(AiUsage(
            project_id=pid, feature=u.get("feature", ""),
            provider=u.get("provider", ""), model=u.get("model", ""),
            user_id=uid(u.get("email")), day=u.get("day", ""),
            n_calls=u.get("n_calls", 0), tokens_in=u.get("tokens_in", 0),
            tokens_out=u.get("tokens_out", 0), cost_usd=u.get("cost_usd", 0.0),
            first_at=parse_dt(u.get("first_at")),
            last_at=parse_dt(u.get("last_at"))))

    db.flush()
    return {"records": records, "sources": sources, "imports": imports,
            "equations": equations, "concepts": concepts,
            "protocols": protocols, "golden_refs": golden,
            "screening_configs": configs, "extraction_columns": columns,
            "extraction_studies": studies, "study_by_pos": study_by_pos,
            "snowball_runs": snowballs, "fulltexts": fulltexts,
            "tags": tags}


# -- files -------------------------------------------------------------------

def _import_files(zf: zipfile.ZipFile, db: Session, project: Project,
                  data: dict, maps: dict, old_pdf_dir: Path | None) -> int:
    """Extract ris_raw / protocol / pdf files into the project storage.
    Archive member names are controlled (basenames only) to avoid traversal."""
    storage = _storage(project.id)
    names = set(zf.namelist())

    for sub in ("ris_raw", "protocol"):
        target = storage / sub
        for name in names:
            if name.startswith(f"files/{sub}/") and not name.endswith("/"):
                base = Path(name).name
                target.mkdir(parents=True, exist_ok=True)
                with zf.open(name) as src, open(target / base, "wb") as dst:
                    shutil.copyfileobj(src, dst)

    pdfs_dir = storage / "pdfs"
    pdfs_missing = 0
    for f in data.get("fulltexts", []):
        uuid = f.get("record")
        ft = maps["fulltexts"].get(uuid)
        record = maps["records"].get(uuid)
        if ft is None or record is None:
            continue
        member = f"files/pdfs/{uuid}.pdf"
        target = pdfs_dir / f"{record.id}.pdf"

        def _update_ft(ft_id, changes):
            # bulk UPDATE with updated_at named explicitly: keeps the archive
            # timestamp (an ORM attribute set to an equal value registers no
            # change, so the column's onupdate would fire and bump it)
            if ft.updated_at is not None:
                changes["updated_at"] = ft.updated_at
            db.query(FullText).filter_by(id=ft_id).update(
                changes, synchronize_session=False)

        if member in names:
            pdfs_dir.mkdir(parents=True, exist_ok=True)
            with zf.open(member) as src, open(target, "wb") as dst:
                shutil.copyfileobj(src, dst)
            _update_ft(ft.id, {"file_path": str(target)})
        elif (old_pdf_dir is not None
                and (old := _find_old_pdf(old_pdf_dir, uuid)) is not None):
            pdfs_dir.mkdir(parents=True, exist_ok=True)
            shutil.move(str(old), target)
            _update_ft(ft.id, {"file_path": str(target)})
        elif f.get("has_file") and ft.status in ("retrieved", "manual"):
            _update_ft(ft.id, {"status": "pending"})  # can be re-retrieved
            pdfs_missing += 1
    if old_pdf_dir is not None and old_pdf_dir.exists():
        shutil.rmtree(old_pdf_dir, ignore_errors=True)
    db.expire_all()  # the bulk updates bypassed the identity map
    return pdfs_missing


def _find_old_pdf(old_dir: Path, record_uuid: str) -> Path | None:
    """Files set aside by _set_aside_pdfs, located via the index.json sidecar."""
    index_file = old_dir / "index.json"
    if not index_file.exists():
        return None
    index = json.loads(index_file.read_text(encoding="utf-8"))
    name = index.get(record_uuid)
    if not name:
        return None
    path = old_dir / name
    return path if path.exists() else None


# -- merge of stashed local contributions -----------------------------------

def _merge_stash(db: Session, project: Project, stash: dict, maps: dict,
                 users: dict) -> tuple[dict, list]:
    """Re-apply contributions authored on this instance after an update import.
    Votes / JBI / extraction values: newest `updated_at` wins against the
    archive's copy. AI votes: the archive's copy wins (insert only if absent).
    PDF annotations: the local author's set replaces the archive's copy.
    Skips: local skip state wins. Rows whose target uuid disappeared are
    quarantined into the report."""
    kept = {"votes": 0, "jbi": 0, "values": 0, "annotations": 0, "skips": 0,
            "tags": 0, "work_sessions": 0, "studies": 0}
    quarantined: list[dict] = []
    records = maps["records"]
    columns = maps["extraction_columns"]
    configs = maps["screening_configs"]
    studies = maps.get("extraction_studies", {})
    study_by_pos = maps.get("study_by_pos", {})
    local_users = {u.email: u for u in db.query(User)
                   .filter(User.password_hash != "")}

    def local_uid(email):
        user = local_users.get(email) if email else None
        return user.id if user else None

    # studies declared on this instance that the archive does not carry are
    # re-created (same uuid), so the local values below keep their home
    from app.models import ExtractionStudy
    for s in stash.get("studies", []):
        record = records.get(s.get("record"))
        if record is None:
            continue
        if s.get("uuid") in studies or (s["record"], s.get("position", 0)) in study_by_pos:
            continue
        row = ExtractionStudy(record_id=record.id, uuid=s["uuid"],
                              label=s.get("label") or "Study 1",
                              position=s.get("position", 0),
                              study_design=s.get("study_design"),
                              design_origin=s.get("design_origin"),
                              created_by=local_uid(s.get("email")))
        db.add(row)
        db.flush()
        studies[row.uuid] = row
        study_by_pos[(s["record"], row.position)] = row
        kept["studies"] += 1

    def study_of(entry) -> ExtractionStudy | None:
        row = studies.get(entry.get("study")) if entry.get("study") else None
        if row is None:
            row = study_by_pos.get((entry["record"], entry.get("study_position") or 0))
        if row is None:
            record = records.get(entry["record"])
            if record is None:
                return None
            row = ExtractionStudy(record_id=record.id, label="Study 1", position=0)
            db.add(row)
            db.flush()
            studies[row.uuid] = row
            study_by_pos[(entry["record"], 0)] = row
        return row

    for v in stash["votes"]:
        record = records.get(v["record"])
        if record is None:
            quarantined.append({"type": "vote", "record": v["record"],
                                "stage": v["stage"], "email": v["email"]})
            continue
        if v["is_ai"]:
            existing = (db.query(Vote)
                        .filter_by(record_id=record.id, stage=v["stage"],
                                   round=v["round"], is_ai=True).first())
            if existing is None:
                db.add(Vote(project_id=project.id, record_id=record.id,
                            stage=v["stage"], round=v["round"],
                            voter_user_id=None, is_ai=True,
                            decision=v["decision"],
                            reasons=v.get("reasons") or [],
                            justification=v.get("justification", ""),
                            criteria_eval=v.get("criteria_eval") or {},
                            confidence=v.get("confidence"),
                            generated_by=v.get("generated_by"),
                            imported_from=v.get("imported_from"),
                            created_at=parse_dt(v.get("created_at")),
                            updated_at=parse_dt(v.get("updated_at"))))
                kept["votes"] += 1
            continue
        user_id = local_uid(v["email"])
        if user_id is None:
            continue
        existing = (db.query(Vote)
                    .filter_by(record_id=record.id, stage=v["stage"],
                               round=v["round"], voter_user_id=user_id,
                               is_ai=False).first())
        stash_dt = parse_dt(v.get("updated_at"))
        if existing is None:
            db.add(Vote(project_id=project.id, record_id=record.id,
                        stage=v["stage"], round=v["round"],
                        voter_user_id=user_id, is_ai=False,
                        decision=v["decision"], reasons=v.get("reasons") or [],
                        justification=v.get("justification", ""),
                        criteria_eval=v.get("criteria_eval") or {},
                        confidence=v.get("confidence"),
                        imported_from=v.get("imported_from"),
                        created_at=parse_dt(v.get("created_at")),
                        updated_at=stash_dt))
            kept["votes"] += 1
        elif stash_dt and (existing.updated_at is None
                           or as_utc(stash_dt) > as_utc(existing.updated_at)):
            existing.decision = v["decision"]
            existing.reasons = v.get("reasons") or []
            existing.justification = v.get("justification", "")
            existing.criteria_eval = v.get("criteria_eval") or {}
            existing.imported_from = v.get("imported_from")
            existing.updated_at = stash_dt
            kept["votes"] += 1

    for j in stash["jbi"]:
        record = records.get(j["record"])
        user_id = local_uid(j["email"])
        if record is None or user_id is None:
            if record is None:
                quarantined.append({"type": "jbi", "record": j["record"],
                                    "email": j["email"]})
            continue
        study = study_of(j)
        existing = (db.query(JbiAppraisal)
                    .filter_by(study_id=study.id, user_id=user_id).first())
        stash_dt = parse_dt(j.get("updated_at"))
        if existing is None:
            db.add(JbiAppraisal(record_id=record.id, study_id=study.id,
                                user_id=user_id,
                                design=j.get("design", ""),
                                answers=j.get("answers") or {},
                                overall=j.get("overall", ""),
                                comment=j.get("comment", ""),
                                imported_from=j.get("imported_from"),
                                updated_at=stash_dt))
            kept["jbi"] += 1
        elif stash_dt and (existing.updated_at is None
                           or as_utc(stash_dt) > as_utc(existing.updated_at)):
            existing.design = j.get("design", "")
            existing.answers = j.get("answers") or {}
            existing.overall = j.get("overall", "")
            existing.comment = j.get("comment", "")
            existing.updated_at = stash_dt
            kept["jbi"] += 1

    for v in stash["values"]:
        record = records.get(v["record"])
        column = columns.get(v["column"])
        user_id = local_uid(v["email"])
        if record is None or column is None or user_id is None:
            if record is None or column is None:
                quarantined.append({"type": "extraction_value",
                                    "record": v["record"],
                                    "email": v["email"]})
            continue
        study = study_of(v)
        existing = (db.query(ExtractionValue)
                    .filter_by(study_id=study.id, column_id=column.id,
                               user_id=user_id).first())
        stash_dt = parse_dt(v.get("updated_at"))
        if existing is None:
            db.add(ExtractionValue(record_id=record.id, study_id=study.id,
                                   column_id=column.id,
                                   user_id=user_id, value=v.get("value") or {},
                                   origin=v.get("origin", "human"),
                                   validated=v.get("validated", False),
                                   imported_from=v.get("imported_from"),
                                   updated_at=stash_dt))
            kept["values"] += 1
        elif stash_dt and (existing.updated_at is None
                           or as_utc(stash_dt) > as_utc(existing.updated_at)):
            existing.value = v.get("value") or {}
            existing.origin = v.get("origin", "human")
            existing.validated = v.get("validated", False)
            existing.updated_at = stash_dt
            kept["values"] += 1

    stash_authors = {a["email"] for a in stash["annotations"]}
    for email in stash_authors:
        user_id = local_uid(email)
        if user_id is not None:  # local author: their local set is truth
            db.query(PdfAnnotation).filter_by(
                project_id=project.id, user_id=user_id).delete(
                synchronize_session=False)
    for a in stash["annotations"]:
        record = records.get(a["record"])
        user_id = local_uid(a["email"])
        if record is None or user_id is None:
            if record is None:
                quarantined.append({"type": "annotation",
                                    "record": a["record"],
                                    "email": a["email"]})
            continue
        db.add(PdfAnnotation(project_id=project.id, record_id=record.id,
                             user_id=user_id, page=a.get("page", 1),
                             rects=a.get("rects") or [],
                             quote=a.get("quote", ""),
                             note=a.get("note", ""),
                             color=a.get("color", "yellow"),
                             imported_from=a.get("imported_from"),
                             created_at=parse_dt(a.get("created_at")),
                             updated_at=parse_dt(a.get("updated_at"))))
        kept["annotations"] += 1

    for s in stash["skips"]:
        config = configs.get(s["config"])
        record = records.get(s["record"])
        user_id = local_uid(s["email"])
        if config is None or record is None or user_id is None:
            continue
        assignment = (db.query(Assignment)
                      .filter_by(config_id=config.id, record_id=record.id,
                                 user_id=user_id).first())
        if assignment is not None:
            assignment.skipped_at = parse_dt(s.get("skipped_at"))
            kept["skips"] += 1

    # local reviewers' tag attachments survive updates (until their package
    # brings them to the coordinator and back inside the snapshot itself)
    for tg in stash.get("tags", []):
        record = records.get(tg["record"])
        user_id = local_uid(tg["email"])
        if record is None or user_id is None:
            if record is None:
                quarantined.append({"type": "tag", "record": tg["record"],
                                    "email": tg["email"]})
            continue
        tag = (db.query(Tag)
               .filter_by(project_id=project.id, name=tg["tag"]).first())
        if tag is None:
            tag = Tag(project_id=project.id, name=tg["tag"],
                      created_by=user_id)
            db.add(tag)
            db.flush()
        if not (db.query(RecordTag)
                .filter_by(tag_id=tag.id, record_id=record.id).first()):
            db.add(RecordTag(tag_id=tag.id, record_id=record.id,
                             created_by=user_id,
                             created_at=parse_dt(tg.get("created_at"))))
            kept["tags"] += 1

    # local work sessions: insert the ones the archive does not carry yet
    for s in stash.get("work_sessions", []):
        user_id = local_uid(s["email"])
        if user_id is None or not s.get("uuid"):
            continue
        if db.query(WorkSession.id).filter_by(uuid=s["uuid"]).first() is not None:
            continue
        db.add(WorkSession(project_id=project.id, uuid=s["uuid"], user_id=user_id,
                           stage=s.get("stage", "ta"),
                           started_at=parse_dt(s.get("started_at")),
                           last_seen_at=parse_dt(s.get("last_seen_at")),
                           n_heartbeats=s.get("n_heartbeats", 0),
                           instance_id=s.get("instance_id") or "",
                           imported_from=s.get("imported_from")))
        kept["work_sessions"] += 1

    db.flush()
    return kept, quarantined
