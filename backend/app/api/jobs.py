# SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
# SPDX-License-Identifier: AGPL-3.0-or-later
import asyncio
import json
from datetime import datetime

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from app.api.deps import CurrentUser, DbDep
from app.models import Job, ProjectMember, User
from app.workers.runner import runner

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


def _assert_job_access(job: Job, user: User, db: DbDep) -> None:
    """A job carrying a project_id is only visible to that project's members
    (app admin passes). Project-less jobs (rare, e.g. snapshot bootstrap) stay
    scoped to their submitter."""
    if user.is_admin:
        return
    if job.project_id is not None:
        member = (db.query(ProjectMember)
                  .filter_by(project_id=job.project_id, user_id=user.id)
                  .first())
        if member is None:
            raise HTTPException(status_code=404, detail="Job not found")
    elif job.created_by not in (None, user.id):
        raise HTTPException(status_code=404, detail="Job not found")


class JobOut(BaseModel):
    id: int
    type: str
    status: str
    progress: int
    total: int
    message: str
    params: dict
    result: dict
    error: str
    project_id: int | None
    created_at: datetime

    model_config = {"from_attributes": True}


@router.get("", response_model=list[JobOut])
def list_jobs(user: CurrentUser, db: DbDep, project_id: int | None = None,
              active: bool = False, limit: int = 20):
    """Recent jobs; active=true keeps only queued/running ones (used to
    re-attach progress display after navigating away). Non-admins only ever
    see the jobs of projects they belong to (plus their own project-less
    jobs) — never a global cross-tenant listing."""
    query = db.query(Job).order_by(Job.created_at.desc())
    if project_id is not None:
        # membership check before returning another tenant's job params/results
        if not user.is_admin:
            member = (db.query(ProjectMember)
                      .filter_by(project_id=project_id, user_id=user.id)
                      .first())
            if member is None:
                raise HTTPException(status_code=403,
                                    detail="Not a member of this project")
        query = query.filter(Job.project_id == project_id)
    elif not user.is_admin:
        # no project filter: restrict to the caller's own projects + own jobs
        my_projects = [m.project_id for m in
                       db.query(ProjectMember.project_id)
                       .filter_by(user_id=user.id)]
        query = query.filter(
            (Job.project_id.in_(my_projects)) | (Job.created_by == user.id))
    if active:
        query = query.filter(Job.status.in_(["queued", "running"]))
    return query.limit(min(max(limit, 1), 100)).all()


@router.get("/{job_id}", response_model=JobOut)
def get_job(job_id: int, user: CurrentUser, db: DbDep):
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    _assert_job_access(job, user, db)
    return job


@router.post("/{job_id}/cancel")
def cancel_job(job_id: int, user: CurrentUser, db: DbDep):
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    _assert_job_access(job, user, db)
    if job.status not in ("queued", "running"):
        raise HTTPException(status_code=400, detail="Job is not running")
    runner.cancel(job_id)
    return {"ok": True}


@router.get("/{job_id}/stream")
async def stream_job(job_id: int, request: Request, user: CurrentUser,
                     db: DbDep):
    """SSE stream of job progress; closes when the job reaches a final state."""
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    _assert_job_access(job, user, db)

    queue = runner.subscribe(job_id)

    async def event_generator():
        try:
            # initial snapshot so late subscribers see current state
            yield {"data": json.dumps({
                "id": job.id, "type": job.type, "status": job.status,
                "progress": job.progress, "total": job.total,
                "message": job.message, "error": job.error,
            })}
            if job.status in ("done", "failed", "cancelled"):
                return
            while True:
                if await request.is_disconnected():
                    return
                try:
                    payload = await asyncio.wait_for(queue.get(), timeout=15)
                except asyncio.TimeoutError:
                    yield {"comment": "keepalive"}
                    continue
                yield {"data": json.dumps(payload)}
                if payload["status"] in ("done", "failed", "cancelled"):
                    return
        finally:
            runner.unsubscribe(job_id, queue)

    return EventSourceResponse(event_generator())
