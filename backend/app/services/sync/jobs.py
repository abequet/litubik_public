# SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Job handlers for snapshot export/import (long-running: zip + thousands of
rows), wired to the standard runner + SSE progress."""
from pathlib import Path

from app.core.db import SessionLocal
from app.models import Project, User
from app.services.sync.snapshot import (
    SnapshotError, build_snapshot, import_snapshot,
)
from app.workers.runner import register_handler, runner


@register_handler("sync_publish_folder")
def publish_folder_handler(job_id: int, params: dict, progress) -> dict:
    from app.services.sync.folder import publish_snapshot_to_folder
    with SessionLocal() as db:
        project = db.get(Project, params["project_id"])
        exporter = db.get(User, params["user_id"])
        if project is None or exporter is None:
            raise SnapshotError("Projet ou utilisateur introuvable")
        return publish_snapshot_to_folder(
            db, project, exporter,
            include_pdfs=params.get("include_pdfs", True), progress=progress)


@register_handler("sync_export_snapshot")
def export_snapshot_handler(job_id: int, params: dict, progress) -> dict:
    with SessionLocal() as db:
        project = db.get(Project, params["project_id"])
        exporter = db.get(User, params["user_id"])
        if project is None or exporter is None:
            raise SnapshotError("Projet ou utilisateur introuvable")
        path = build_snapshot(db, project,
                              include_pdfs=params.get("include_pdfs", True),
                              exporter=exporter, progress=progress,
                              public=params.get("public", False),
                              pseudonymize=params.get("pseudonymize", False))
        return {
            "path": str(path),
            "filename": path.name,
            "size_kb": round(path.stat().st_size / 1024),
            "snapshot_version": project.snapshot_version,
        }


@register_handler("sync_import_snapshot")
def import_snapshot_handler(job_id: int, params: dict, progress) -> dict:
    zip_path = Path(params["path"])
    # the import runs as ONE write transaction: progress must not write to the
    # jobs table from another connection (SQLite would deadlock on the lock
    # this very transaction holds) — SSE-only progress instead
    light_progress = runner.transient_progress(job_id, "sync_import_snapshot")
    try:
        with SessionLocal() as db:
            importer = db.get(User, params["user_id"])
            if importer is None:
                raise SnapshotError("Utilisateur introuvable")
            report = import_snapshot(db, zip_path, importer, light_progress,
                                     restore_own=params.get("restore_own",
                                                            False))
            if params.get("link_folder"):  # join-folder: one-step bootstrap
                project = db.get(Project, report["project_id"])
                if project is not None and not project.sync_dir:
                    project.sync_dir = params["link_folder"]
                    db.commit()
                report["folder_linked"] = params["link_folder"]
            return report
    finally:
        if not params.get("keep_file"):  # keep folder-sync archives in place
            zip_path.unlink(missing_ok=True)  # uploaded temp file
