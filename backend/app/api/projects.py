# SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
# SPDX-License-Identifier: AGPL-3.0-or-later
import shutil
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr, Field

from app.api.deps import (
    CurrentUser, DbDep, NoSandbox, ProjectMemberDep, SatelliteGuard, get_project,
    require_project_admin,
)
from app.core.config import get_settings
from app.models import Project, ProjectInvitation, ProjectMember, User
from app.services import framing, registration

router = APIRouter(prefix="/api/projects", tags=["projects"])


class ProjectIn(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str = ""


class ProjectOut(BaseModel):
    id: int
    name: str
    description: str
    research_question: str = ""
    # how the review frames itself — drives vocabulary, not the pipeline
    review_type: str = framing.DEFAULT_REVIEW_TYPE
    question_framework: str = framing.DEFAULT_FRAMEWORK
    # PRISMA 2020 item 24a/24b — "" = never answered, "none" = answered "not
    # registered" (which the manuscript must state, not omit)
    registry: str = ""
    registration_id: str = ""
    registration_url: str = ""
    registered_at: datetime | None = None
    protocol_url: str = ""
    # AI keys: open only the best-ranked key, never another provider
    llm_no_fallback: bool = False
    # AI routing: reviewers (not only project admins) may change the
    # provider/model/effort per task
    llm_reviewers_can_route: bool = False
    # the databases this review searches (registry ids); null = every database
    databases: list[str] | None = None
    created_at: datetime
    archived_at: datetime | None = None
    my_role: str = "reviewer"
    sync_role: str = "coordinator"  # satellite = imported snapshot (sync)

    model_config = {"from_attributes": True}


def _out(project: Project, role: str) -> ProjectOut:
    """Single place where a Project becomes a ProjectOut — every endpoint used
    to build it by hand and each dropped a different field."""
    return ProjectOut.model_validate(project).model_copy(update={"my_role": role})


class ProjectUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    research_question: str | None = None
    review_type: str | None = None
    question_framework: str | None = None
    registry: str | None = None
    registration_id: str | None = Field(default=None, max_length=120)
    registration_url: str | None = Field(default=None, max_length=500)
    registered_at: datetime | None = None
    protocol_url: str | None = Field(default=None, max_length=500)
    llm_no_fallback: bool | None = None
    llm_reviewers_can_route: bool | None = None
    # the databases this review searches; null (sent explicitly) = all
    databases: list[str] | None = Field(default=None, max_length=60)


class MemberOut(BaseModel):
    user_id: int | None  # None only for legacy e-mail invitations
    email: str
    display_name: str
    role: str
    # member = registered · awaiting = account created by the admin, claimed
    # when the person registers with this email · invited = legacy rows
    status: str = "member"


class MemberIn(BaseModel):
    email: EmailStr
    role: str = Field(pattern="^(admin|reviewer)$")


@router.get("", response_model=list[ProjectOut])
def list_projects(user: CurrentUser, db: DbDep, archived: bool = False):
    """Active projects by default; pass archived=true for the archive."""
    query = db.query(Project, ProjectMember.role).join(
        ProjectMember, ProjectMember.project_id == Project.id
    )
    if user.is_admin:
        # app admin sees everything; role falls back to admin where not a member
        rows = []
        memberships = {m.project_id: m.role for m in user.memberships}
        for project in db.query(Project).order_by(Project.created_at.desc()):
            rows.append((project, memberships.get(project.id, "admin")))
    else:
        rows = (
            query.filter(ProjectMember.user_id == user.id)
            .order_by(Project.created_at.desc())
            .all()
        )
    return [_out(p, role) for p, role in rows
            if (p.archived_at is not None) == archived]


@router.post("", response_model=ProjectOut)
def create_project(payload: ProjectIn, user: CurrentUser, db: DbDep):
    # M6: sandbox accounts of a demo instance are capped (reset does the rest)
    from app.core.demo import DEMO_MAX_PROJECTS, is_demo_user
    if is_demo_user(user) and (db.query(Project)
                               .filter_by(created_by=user.id)
                               .count() >= DEMO_MAX_PROJECTS):
        raise HTTPException(
            status_code=403,
            detail=f"Demo accounts are limited to {DEMO_MAX_PROJECTS} projects")
    project = Project(name=payload.name, description=payload.description,
                      created_by=user.id)
    db.add(project)
    db.flush()
    db.add(ProjectMember(project_id=project.id, user_id=user.id, role="admin"))
    db.commit()
    db.refresh(project)
    return _out(project, "admin")


@router.put("/{project_id}", response_model=ProjectOut,
            dependencies=[Depends(require_project_admin), SatelliteGuard])
def update_project(project_id: int, payload: ProjectUpdate, db: DbDep):
    project = get_project(project_id, db)
    if payload.review_type is not None and payload.review_type not in framing.REVIEW_TYPES:
        raise HTTPException(status_code=400,
                            detail=f"Unknown review type: {payload.review_type}")
    if (payload.question_framework is not None
            and payload.question_framework not in framing.FRAMEWORKS):
        raise HTTPException(
            status_code=400,
            detail=f"Unknown question framework: {payload.question_framework}")
    if payload.registry is not None and payload.registry not in registration.VALID_KEYS:
        raise HTTPException(status_code=400,
                            detail=f"Unknown registry: {payload.registry}")
    for field in ("name", "description", "research_question", "review_type",
                  "question_framework", "registry", "registration_id",
                  "registration_url", "protocol_url", "llm_no_fallback",
                  "llm_reviewers_can_route"):
        value = getattr(payload, field)
        if value is not None:
            setattr(project, field, value)
    # A date is the one field a team legitimately clears, so "sent as null"
    # has to mean something other than "left out" for it.
    if "registered_at" in payload.model_fields_set:
        project.registered_at = payload.registered_at
    # same for the database selection: null = back to "every database"
    if "databases" in payload.model_fields_set:
        if payload.databases is None:
            project.databases = None
        else:
            from app.services.equations import all_project_databases
            known = {d["id"] for d in all_project_databases(db, project_id)}
            unknown = sorted(set(payload.databases) - known)
            if unknown:
                raise HTTPException(status_code=400,
                                    detail=f"Unknown database: {', '.join(unknown)}")
            chosen = list(dict.fromkeys(payload.databases))
            project.databases = chosen or None
    # An unregistered review has no identifier and no date to carry around;
    # leaving stale ones would put them in the Methods draft.
    if project.registry in ("", "none"):
        project.registration_id = ""
        project.registration_url = ""
        project.registered_at = None
    db.commit()
    db.refresh(project)
    return _out(project, "admin")


@router.post("/{project_id}/archive", response_model=ProjectOut,
             dependencies=[Depends(require_project_admin)])
def archive_project(project_id: int, db: DbDep):
    """Soft delete: hide the project from the main list (reversible)."""
    project = get_project(project_id, db)
    project.archived_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(project)
    return _out(project, "admin")


@router.post("/{project_id}/unarchive", response_model=ProjectOut,
             dependencies=[Depends(require_project_admin)])
def unarchive_project(project_id: int, db: DbDep):
    """Restore an archived project to the active list."""
    project = get_project(project_id, db)
    project.archived_at = None
    db.commit()
    db.refresh(project)
    return _out(project, "admin")


@router.delete("/{project_id}", dependencies=[Depends(require_project_admin)])
def delete_project(project_id: int, db: DbDep):
    """Permanent delete (from the archive). All project-scoped tables cascade at
    the DB level (foreign_keys=ON); stored files are removed from disk too."""
    project = get_project(project_id, db)
    db.delete(project)
    db.commit()
    storage = get_settings().storage_dir / str(project_id)
    if storage.exists():
        shutil.rmtree(storage, ignore_errors=True)
    return {"ok": True}


class HighlightsIn(BaseModel):
    green: list[str] = Field(default_factory=list, max_length=500)
    red: list[str] = Field(default_factory=list, max_length=500)


def _clean_words(words: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for w in words:
        w = w.strip()
        if w and w.lower() not in seen:
            seen.add(w.lower())
            out.append(w[:80])
    return out


@router.get("/{project_id}/highlights")
def get_highlights(project_id: int, member: ProjectMemberDep, db: DbDep):
    """T14: hand-curated highlight lists for the screening screens."""
    project = get_project(project_id, db)
    h = project.highlights or {}
    return {"green": h.get("green") or [], "red": h.get("red") or []}


@router.put("/{project_id}/highlights",
            dependencies=[Depends(require_project_admin), SatelliteGuard])
def set_highlights(project_id: int, payload: HighlightsIn, db: DbDep):
    project = get_project(project_id, db)
    project.highlights = {"green": _clean_words(payload.green),
                          "red": _clean_words(payload.red)}
    db.commit()
    return project.highlights


@router.get("/{project_id}/progress")
def progress(project_id: int, user: CurrentUser, db: DbDep):
    """Pipeline position for the menu: current step, completed steps, and the
    per-round state of the screening stages (snowballing sub-steps)."""
    from app.api.deps import get_project_member
    from app.services.progress import project_progress
    get_project_member(project_id, user, db)  # membership check
    get_project(project_id, db)
    return project_progress(db, project_id)


@router.get("/{project_id}/members", response_model=list[MemberOut])
def list_members(project_id: int, member: ProjectMemberDep, db: DbDep):
    get_project(project_id, db)
    rows = (
        db.query(ProjectMember, User)
        .join(User, User.id == ProjectMember.user_id)
        .filter(ProjectMember.project_id == project_id)
        .all()
    )
    members = [
        MemberOut(user_id=u.id, email=u.email, display_name=u.display_name,
                  role=m.role,
                  status="member" if u.password_hash else "awaiting")
        for m, u in rows
    ]
    invitations = (db.query(ProjectInvitation)
                   .filter_by(project_id=project_id)
                   .order_by(ProjectInvitation.created_at).all())
    members += [
        MemberOut(user_id=None, email=i.email, display_name="(invited)",
                  role=i.role, status="invited")
        for i in invitations
    ]
    return members


# demo visitors add nobody: an invitation stores a third party's e-mail
@router.post("/{project_id}/members", response_model=MemberOut,
             dependencies=[Depends(require_project_admin), SatelliteGuard,
                           NoSandbox])
def add_member(project_id: int, payload: MemberIn, user: CurrentUser, db: DbDep):
    """Add a member. An unknown email gets an *awaiting-registration* account
    right away (empty password hash — same claimable mechanism as the sync
    shadow accounts): the person is immediately selectable as a screening
    reviewer, travels in snapshots, and takes the account over (choosing
    their display name) by registering with this email. No email is sent."""
    get_project(project_id, db)
    email = payload.email.lower()
    target = db.query(User).filter_by(email=email).first()
    created = target is None
    if created:
        target = User(email=email, password_hash="",
                      display_name=email.split("@")[0])
        db.add(target)
        db.flush()
    # M6 demo instances: a member invited by a trusted account is allowlisted
    # automatically — otherwise the daily reset would purge their account and
    # votes. Sandbox inviters don't get this power (it would let any visitor
    # allowlist arbitrary emails): their awaiting invitees stay sandbox
    # accounts. The auto-allowlisted entry shows up as "invited by a project
    # admin" on the superadmin's demo-access page.
    if get_settings().demo_mode:
        from app.core.demo import is_demo_user
        if not is_demo_user(user):
            from app.models import TrustedEmail
            if db.query(TrustedEmail).filter_by(email=email).first() is None:
                db.add(TrustedEmail(email=email, added_by=user.id,
                                    source="invite"))
            target.is_trusted = True
        elif created:
            target.is_trusted = False
    existing = db.query(ProjectMember).filter_by(
        project_id=project_id, user_id=target.id).first()
    if existing:
        existing.role = payload.role
    else:
        db.add(ProjectMember(project_id=project_id, user_id=target.id,
                             role=payload.role))
    db.commit()
    return MemberOut(user_id=target.id, email=target.email,
                     display_name=target.display_name, role=payload.role,
                     status="member" if target.password_hash else "awaiting")


@router.delete("/{project_id}/invitations",
               dependencies=[Depends(require_project_admin), SatelliteGuard])
def delete_invitation(project_id: int, email: str, db: DbDep):
    invitation = db.query(ProjectInvitation).filter_by(
        project_id=project_id, email=email.lower()).first()
    if invitation is None:
        raise HTTPException(status_code=404, detail="Invitation not found")
    db.delete(invitation)
    db.commit()
    return {"ok": True}


@router.delete("/{project_id}/members/{user_id}",
               dependencies=[Depends(require_project_admin), SatelliteGuard])
def remove_member(project_id: int, user_id: int, db: DbDep):
    member = db.query(ProjectMember).filter_by(
        project_id=project_id, user_id=user_id).first()
    if member is None:
        raise HTTPException(status_code=404, detail="Member not found")
    admins = db.query(ProjectMember).filter_by(project_id=project_id, role="admin").count()
    if member.role == "admin" and admins <= 1:
        raise HTTPException(status_code=400, detail="Cannot remove the last project admin")
    db.delete(member)
    db.commit()
    return {"ok": True}
