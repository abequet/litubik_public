# SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Standalone "download papers" module: pasted DOIs → one PDF or a zip.

Lives outside any project (workspace section of the sidebar): the job carries
no project_id, so it and its files are only reachable by their submitter.
"""
import os
import tempfile
import zipfile
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from starlette.background import BackgroundTask

from app.api.deps import CurrentUser, DbDep, NoSandbox
from app.api.fulltext import Institution, _reject_internal_url
from app.models import Job, User
from app.services.fulltext.standalone import (
    MAX_DOIS, job_dir, parse_dois, sweep_old_downloads,
)
from app.workers.runner import runner

# never for demo visitors, even if the box was ticked for the account
router = APIRouter(prefix="/api/paper-download", tags=["paper-download"],
                   dependencies=[NoSandbox])

# everyone but the superadmin: papers per sliding hour
HOURLY_QUOTA = 5
QUOTA_WINDOW = timedelta(hours=1)


class DownloadIn(BaseModel):
    text: str = Field(default="", max_length=100_000)
    # the caller's browser-held institutional credentials — never persisted,
    # handed to the job through an in-memory token (same as project retrieval)
    institutions: list[Institution] = []


def _require_access(user: User) -> None:
    """The module is opt-in per user: the superadmin ticks who gets it."""
    if not (user.is_admin or user.can_download_papers):
        raise HTTPException(
            status_code=403,
            detail="The Download papers module is not enabled for your account")


def _quota(user: User, db: DbDep) -> dict:
    """Papers a non-superadmin may still request in the sliding hour. A
    finished run costs what it actually retrieved; a run still going (or
    cancelled midway) costs everything it asked for."""
    if user.is_admin:
        return {"limit": None, "used": 0, "remaining": None, "resets_at": None}
    now = datetime.now(timezone.utc)
    used, oldest = 0, None
    jobs = (db.query(Job).filter_by(type="paper_download", created_by=user.id)
            .order_by(Job.id.desc()).limit(100).all())
    for job in jobs:
        created = job.created_at
        if created.tzinfo is None:  # SQLite hands back naive UTC datetimes
            created = created.replace(tzinfo=timezone.utc)
        if now - created >= QUOTA_WINDOW:
            break
        if job.status == "failed":
            continue
        cost = (int((job.result or {}).get("retrieved", 0))
                if job.status == "done"
                else len((job.params or {}).get("dois", [])))
        if cost:
            used += cost
            oldest = created
    return {"limit": HOURLY_QUOTA, "used": used,
            "remaining": max(HOURLY_QUOTA - used, 0),
            "resets_at": (oldest + QUOTA_WINDOW).isoformat() if oldest else None}


@router.get("/quota")
def get_quota(user: CurrentUser, db: DbDep):
    _require_access(user)
    return _quota(user, db)


@router.post("")
def start_download(payload: DownloadIn, user: CurrentUser, db: DbDep):
    _require_access(user)
    dois = parse_dois(payload.text)
    if not dois:
        raise HTTPException(status_code=400, detail="No DOI found in the text")
    if len(dois) > MAX_DOIS:
        raise HTTPException(
            status_code=400,
            detail=f"Too many DOIs ({len(dois)}) — {MAX_DOIS} at most per run")
    remaining = _quota(user, db)["remaining"]
    if remaining is not None and len(dois) > remaining:
        raise HTTPException(
            status_code=429,
            detail=f"Hourly limit: {HOURLY_QUOTA} papers per hour — "
                   f"{remaining} left right now, {len(dois)} requested")
    for inst in payload.institutions:
        _reject_internal_url(inst.ezproxy_url,
                             f"URL EZProxy de « {inst.name or '?'} »")
    sweep_old_downloads()
    from app.core.demo import is_demo_user
    params = {"dois": dois, "fallback_email": user.email,
              "use_extensions": not is_demo_user(user)}
    ephemeral = [inst.model_dump() for inst in payload.institutions
                 if inst.ezproxy_url and inst.password]
    if ephemeral:
        from app.services.fulltext.ephemeral import stash_institutions
        params["institutions_token"] = stash_institutions(ephemeral)
    job = runner.submit("paper_download", params, project_id=None,
                        user_id=user.id)
    return {"job_id": job.id, "count": len(dois)}


@router.get("/{job_id}/file")
def download_file(job_id: int, user: CurrentUser, db: DbDep):
    """The run's PDFs: the PDF itself when there is exactly one, a zip
    otherwise. Only the submitter can fetch them."""
    _require_access(user)
    job = db.get(Job, job_id)
    if (job is None or job.type != "paper_download"
            or job.created_by != user.id):
        raise HTTPException(status_code=404, detail="Download not found")
    folder = job_dir(job_id)
    pdfs = sorted(folder.glob("*.pdf")) if folder.is_dir() else []
    if not pdfs:
        raise HTTPException(
            status_code=404,
            detail="No PDF available — nothing was retrieved, or the files "
                   "expired (they are kept 24 hours)")
    if len(pdfs) == 1:
        return FileResponse(pdfs[0], media_type="application/pdf",
                            filename=pdfs[0].name)

    handle, tmp_path = tempfile.mkstemp(prefix="litubik_papers_", suffix=".zip")
    os.close(handle)
    try:
        # PDFs are already compressed: level 1 is enough
        with zipfile.ZipFile(tmp_path, "w", zipfile.ZIP_DEFLATED,
                             compresslevel=1) as archive:
            for path in pdfs:
                archive.write(path, arcname=path.name)
    except Exception:
        os.unlink(tmp_path)
        raise
    return FileResponse(
        tmp_path, media_type="application/zip",
        filename=f"papers_{date.today().isoformat()}.zip",
        background=BackgroundTask(os.unlink, tmp_path))
