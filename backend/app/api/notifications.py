# SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
# SPDX-License-Identifier: AGPL-3.0-or-later
"""In-app notifications (living review): the header bell and the project
card badge. Per user, per instance — never synced."""
from fastapi import APIRouter, HTTPException, Query

from app.api.deps import CurrentUser, DbDep
from app.models import Notification
from app.models.accounts import utcnow

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


def _out(n: Notification) -> dict:
    return {"id": n.id, "project_id": n.project_id, "kind": n.kind,
            "payload": n.payload or {},
            "created_at": n.created_at.isoformat() if n.created_at else None,
            "read_at": n.read_at.isoformat() if n.read_at else None}


@router.get("")
def list_notifications(user: CurrentUser, db: DbDep,
                       unread: bool = False,
                       limit: int = Query(30, ge=1, le=200)):
    query = db.query(Notification).filter_by(user_id=user.id)
    if unread:
        query = query.filter(Notification.read_at.is_(None))
    rows = query.order_by(Notification.created_at.desc()).limit(limit).all()
    return [_out(n) for n in rows]


@router.get("/summary")
def summary(user: CurrentUser, db: DbDep):
    """Unread count, overall and per project (for the project cards)."""
    by_project: dict[str, int] = {}
    total = 0
    for n in (db.query(Notification)
              .filter_by(user_id=user.id).filter(Notification.read_at.is_(None))):
        total += 1
        if n.project_id is not None:
            by_project[str(n.project_id)] = by_project.get(str(n.project_id), 0) + 1
    return {"unread": total, "by_project": by_project}


@router.post("/{notification_id}/read")
def mark_read(notification_id: int, user: CurrentUser, db: DbDep):
    n = db.get(Notification, notification_id)
    if n is None or n.user_id != user.id:
        raise HTTPException(status_code=404, detail="Notification not found")
    if n.read_at is None:
        n.read_at = utcnow()
        db.commit()
    return _out(n)


@router.post("/read-all")
def mark_all_read(user: CurrentUser, db: DbDep, project_id: int | None = None):
    query = (db.query(Notification).filter_by(user_id=user.id)
             .filter(Notification.read_at.is_(None)))
    if project_id is not None:
        query = query.filter(Notification.project_id == project_id)
    n = 0
    for row in query:
        row.read_at = utcnow()
        n += 1
    db.commit()
    return {"marked": n}
