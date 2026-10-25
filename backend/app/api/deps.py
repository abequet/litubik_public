# SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
# SPDX-License-Identifier: AGPL-3.0-or-later
from typing import Annotated

from fastapi import Cookie, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import AUTH_COOKIE_NAME, decode_access_token, session_user
from app.models import Project, ProjectMember, User

DbDep = Annotated[Session, Depends(get_db)]


def get_current_user(
    db: DbDep,
    token: Annotated[str | None, Cookie(alias=AUTH_COOKIE_NAME)] = None,
) -> User:
    payload = decode_access_token(token) if token else None
    user = session_user(db, payload)
    if user is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def get_project_member(project_id: int, user: CurrentUser, db: DbDep) -> ProjectMember:
    member = (
        db.query(ProjectMember)
        .filter_by(project_id=project_id, user_id=user.id)
        .first()
    )
    if member is None and not user.is_admin:
        raise HTTPException(status_code=403, detail="Not a member of this project")
    if member is None:  # app admin gets implicit admin access
        member = ProjectMember(project_id=project_id, user_id=user.id, role="admin")
    return member


ProjectMemberDep = Annotated[ProjectMember, Depends(get_project_member)]


def require_project_admin(member: ProjectMemberDep) -> ProjectMember:
    if member.role != "admin":
        raise HTTPException(status_code=403, detail="Project admin role required")
    return member


def get_project(project_id: int, db: DbDep) -> Project:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


def satellite_write_guard(project_id: int, request: Request, db: DbDep) -> None:
    """Sync: the structural state of a satellite project belongs to the
    coordinator instance — mutating requests are rejected here, reads pass.
    Attached router-wide to the fully structural routers, per-endpoint on the
    mixed ones (screening/extraction keep their per-user contribution routes)."""
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return
    project = db.get(Project, project_id)
    if project is not None and project.sync_role == "satellite":
        raise HTTPException(
            status_code=403,
            detail="Géré par le coordinateur — cette action est verrouillée "
                   "sur une instance satellite")


SatelliteGuard = Depends(satellite_write_guard)


# Demo instances: what a visitor's sandbox account may not reach at all — the
# features that store third-party secrets or e-mails (keys, institutional
# logins, project members), touch the server's file system (sync folders,
# snapshots) or turn the instance into a free proxy. Inert on a normal
# instance and for trusted accounts (core/demo.is_demo_user).
DEMO_UNAVAILABLE = ("Not available on the demo instance — install LitUbik "
                    "to use this feature")


def forbid_sandbox(user: CurrentUser) -> None:
    from app.core.demo import is_demo_user
    if is_demo_user(user):
        raise HTTPException(status_code=403, detail=DEMO_UNAVAILABLE)


def forbid_sandbox_writes(request: Request, user: CurrentUser) -> None:
    """Same, for the mutating requests only: a settings page a visitor may
    still open reads fine, every change is refused."""
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        forbid_sandbox(user)


NoSandbox = Depends(forbid_sandbox)
NoSandboxWrites = Depends(forbid_sandbox_writes)
