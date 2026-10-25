# SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
# SPDX-License-Identifier: AGPL-3.0-or-later
"""In-app support tickets: any user reports bugs/feedback, the app admin
triages. Users see their own tickets; app admins see everything."""
import csv
import io
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.api.deps import CurrentUser, DbDep
from app.core.csvsafe import safe_row
from app.models import Project, Ticket, TicketComment, User

router = APIRouter(prefix="/api/tickets", tags=["tickets"])

KINDS = ("bug", "feedback", "feature")
SEVERITIES = ("minor", "major", "blocking")
STATUSES = ("open", "in_progress", "resolved", "closed")


class TicketIn(BaseModel):
    title: str = Field(min_length=3, max_length=255)
    body: str = ""
    kind: str = Field(default="bug", pattern="^(bug|feedback|feature)$")
    severity: str = Field(default="minor", pattern="^(minor|major|blocking)$")
    page: str = Field(default="", max_length=500)
    project_id: int | None = None


class StatusIn(BaseModel):
    status: str = Field(pattern="^(open|in_progress|resolved|closed)$")


class CommentIn(BaseModel):
    body: str = Field(min_length=1)


def _can_view(ticket: Ticket, user: User) -> bool:
    return user.is_admin or ticket.created_by == user.id


def _serialize(ticket: Ticket, users: dict[int, str],
               projects: dict[int, str], n_comments: int | None = None) -> dict:
    return {
        "id": ticket.id, "title": ticket.title, "body": ticket.body,
        "kind": ticket.kind, "severity": ticket.severity, "page": ticket.page,
        "status": ticket.status,
        "project_id": ticket.project_id,
        "project_name": projects.get(ticket.project_id or -1),
        "author": users.get(ticket.created_by or -1, "?"),
        "created_at": ticket.created_at.isoformat() if ticket.created_at else "",
        "updated_at": ticket.updated_at.isoformat() if ticket.updated_at else "",
        "n_comments": n_comments if n_comments is not None else len(ticket.comments),
    }


@router.post("")
def create_ticket(payload: TicketIn, user: CurrentUser, db: DbDep):
    from app.core.demo import DEMO_MAX_TICKETS_PER_DAY, is_demo_user
    if is_demo_user(user):
        from datetime import datetime, timedelta, timezone
        since = datetime.now(timezone.utc) - timedelta(days=1)
        sent = db.query(Ticket).filter(Ticket.created_by == user.id,
                                       Ticket.created_at >= since).count()
        if sent >= DEMO_MAX_TICKETS_PER_DAY:
            raise HTTPException(
                status_code=429,
                detail=f"Demo accounts send at most {DEMO_MAX_TICKETS_PER_DAY} "
                       "messages a day")
    if payload.project_id is not None and db.get(Project, payload.project_id) is None:
        payload.project_id = None
    ticket = Ticket(created_by=user.id, project_id=payload.project_id,
                    title=payload.title.strip(), body=payload.body.strip(),
                    kind=payload.kind, severity=payload.severity,
                    page=payload.page)
    db.add(ticket)
    db.commit()
    db.refresh(ticket)
    users = {user.id: user.display_name}
    projects = {p.id: p.name for p in db.query(Project)}
    return _serialize(ticket, users, projects, n_comments=0)


@router.get("")
def list_tickets(user: CurrentUser, db: DbDep, status: str = "",
                 kind: str = ""):
    query = db.query(Ticket)
    if not user.is_admin:
        query = query.filter(Ticket.created_by == user.id)
    if status in STATUSES:
        query = query.filter(Ticket.status == status)
    if kind in KINDS:
        query = query.filter(Ticket.kind == kind)
    tickets = query.order_by(Ticket.id.desc()).all()
    users = {u.id: u.display_name for u in db.query(User)}
    projects = {p.id: p.name for p in db.query(Project)}
    return [_serialize(t, users, projects) for t in tickets]


@router.get("/summary")
def summary(user: CurrentUser, db: DbDep):
    """Open-ticket count for the header badge (admin: all; user: own)."""
    query = db.query(Ticket).filter(Ticket.status.in_(["open", "in_progress"]))
    if not user.is_admin:
        query = query.filter(Ticket.created_by == user.id)
    return {"open": query.count()}


@router.get("/export.csv")
def export_tickets(user: CurrentUser, db: DbDep, status: str = "",
                   kind: str = ""):
    """Full ticket dump (with comments) for the app admin."""
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="App admin only")
    query = db.query(Ticket)
    if status in STATUSES:
        query = query.filter(Ticket.status == status)
    if kind in KINDS:
        query = query.filter(Ticket.kind == kind)
    tickets = query.order_by(Ticket.id.desc()).all()
    users = {u.id: u.display_name for u in db.query(User)}
    projects = {p.id: p.name for p in db.query(Project)}
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(["Id", "Kind", "Severity", "Status", "Title", "Body",
                     "Author", "Project", "Page", "Created", "Updated",
                     "Comments"])
    for t in tickets:
        comments = "\n".join(
            f"[{c.created_at.isoformat() if c.created_at else ''}] "
            f"{users.get(c.user_id or -1, '?')}: {c.body}"
            for c in t.comments)
        writer.writerow(safe_row([
            t.id, t.kind, t.severity, t.status, t.title, t.body,
            users.get(t.created_by or -1, "?"),
            projects.get(t.project_id or -1) or "",
            t.page,
            t.created_at.isoformat() if t.created_at else "",
            t.updated_at.isoformat() if t.updated_at else "",
            comments]))
    return StreamingResponse(
        iter([buffer.getvalue().encode("utf-8-sig")]),
        media_type="text/csv",
        headers={"Content-Disposition":
                 'attachment; filename="tickets.csv"'})


@router.get("/{ticket_id}")
def get_ticket(ticket_id: int, user: CurrentUser, db: DbDep):
    ticket = db.get(Ticket, ticket_id)
    if ticket is None or not _can_view(ticket, user):
        raise HTTPException(status_code=404, detail="Ticket not found")
    users = {u.id: u.display_name for u in db.query(User)}
    projects = {p.id: p.name for p in db.query(Project)}
    data = _serialize(ticket, users, projects)
    data["comments"] = [{
        "id": c.id, "author": users.get(c.user_id or -1, "?"), "body": c.body,
        "created_at": c.created_at.isoformat() if c.created_at else "",
        "mine": c.user_id == user.id,
    } for c in ticket.comments]
    return data


@router.put("/{ticket_id}/status")
def set_status(ticket_id: int, payload: StatusIn, user: CurrentUser, db: DbDep):
    ticket = db.get(Ticket, ticket_id)
    if ticket is None or not _can_view(ticket, user):
        raise HTTPException(status_code=404, detail="Ticket not found")
    # admin: any transition; author: may only close their own ticket
    if not user.is_admin and payload.status != "closed":
        raise HTTPException(status_code=403,
                            detail="Only the app admin changes ticket status "
                                   "(you can close your own ticket)")
    ticket.status = payload.status
    ticket.updated_at = datetime.now(timezone.utc)
    db.commit()
    return {"ok": True, "status": ticket.status}


@router.post("/{ticket_id}/comments")
def add_comment(ticket_id: int, payload: CommentIn, user: CurrentUser, db: DbDep):
    ticket = db.get(Ticket, ticket_id)
    if ticket is None or not _can_view(ticket, user):
        raise HTTPException(status_code=404, detail="Ticket not found")
    comment = TicketComment(ticket_id=ticket.id, user_id=user.id,
                            body=payload.body.strip())
    ticket.updated_at = datetime.now(timezone.utc)
    db.add(comment)
    db.commit()
    return {"id": comment.id, "author": user.display_name, "body": comment.body,
            "created_at": comment.created_at.isoformat(), "mine": True}
