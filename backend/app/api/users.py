# SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Registered users, for the superadmin: who is on the instance, and which
per-user modules each of them is granted."""
from datetime import datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.api.deps import CurrentUser, DbDep
from app.models import Job, User

router = APIRouter(prefix="/api/admin/users", tags=["users"])


class AdminUserOut(BaseModel):
    id: int
    email: str
    display_name: str
    is_admin: bool
    can_download_papers: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class AdminUserPatch(BaseModel):
    can_download_papers: bool


def _require_app_admin(user: User) -> None:
    if not user.is_admin:
        raise HTTPException(status_code=403,
                            detail="Only an application admin manages users")


@router.get("", response_model=list[AdminUserOut])
def list_users(user: CurrentUser, db: DbDep):
    _require_app_admin(user)
    return db.query(User).order_by(User.display_name, User.email).all()


@router.patch("/{user_id}", response_model=AdminUserOut)
def update_user(user_id: int, payload: AdminUserPatch, user: CurrentUser,
                db: DbDep):
    _require_app_admin(user)
    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="User not found")
    target.can_download_papers = payload.can_download_papers
    db.commit()
    db.refresh(target)
    return target


# ---- what the Download papers module was used for, per user ----

class PaperDownloadUserOut(BaseModel):
    """One user's activity in the standalone module: how many runs, how many
    papers asked for and actually retrieved, when the last run was."""
    id: int | None  # None: the account has since been deleted
    email: str
    display_name: str
    is_admin: bool
    runs: int
    requested: int
    retrieved: int
    last_at: datetime | None


class PaperDownloadRunOut(BaseModel):
    id: int
    status: str
    created_at: datetime
    finished_at: datetime | None
    requested: int
    retrieved: int
    # the run's papers as the module records them: doi, title, status
    # (retrieved | not_found), via (source), filename, error
    items: list[dict]


def _run_out(job: Job) -> PaperDownloadRunOut:
    result = job.result or {}
    items = list(result.get("items") or [])
    requested = len((job.params or {}).get("dois", []))
    retrieved = (int(result.get("retrieved", 0)) if job.status == "done"
                 else sum(1 for i in items if i.get("status") == "retrieved"))
    return PaperDownloadRunOut(
        id=job.id, status=job.status, created_at=job.created_at,
        finished_at=job.finished_at, requested=requested,
        retrieved=retrieved, items=items)


@router.get("/paper-downloads", response_model=list[PaperDownloadUserOut])
def list_paper_downloads(user: CurrentUser, db: DbDep):
    """Every user who ran the Download papers module, most recent first."""
    _require_app_admin(user)
    jobs = (db.query(Job).filter_by(type="paper_download")
            .order_by(Job.id.desc()).all())
    users = {u.id: u for u in db.query(User).all()}
    rows: dict[int | None, PaperDownloadUserOut] = {}
    for job in jobs:
        owner = users.get(job.created_by)
        key = owner.id if owner else None
        row = rows.get(key)
        if row is None:
            row = rows[key] = PaperDownloadUserOut(
                id=key, email=owner.email if owner else "",
                display_name=owner.display_name if owner else "",
                is_admin=bool(owner and owner.is_admin),
                runs=0, requested=0, retrieved=0, last_at=job.created_at)
        run = _run_out(job)
        row.runs += 1
        row.requested += run.requested
        row.retrieved += run.retrieved
    return list(rows.values())


@router.get("/paper-downloads/{user_id}",
            response_model=list[PaperDownloadRunOut])
def list_user_paper_downloads(user_id: int, user: CurrentUser, db: DbDep):
    """One user's runs, most recent first, with every paper requested and
    whether it was retrieved. `user_id` 0 stands for deleted accounts."""
    _require_app_admin(user)
    query = db.query(Job).filter_by(type="paper_download")
    query = (query.filter(Job.created_by.is_(None)) if user_id == 0
             else query.filter_by(created_by=user_id))
    return [_run_out(job) for job in query.order_by(Job.id.desc()).all()]
