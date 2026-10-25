# SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Measured work time: heartbeats folded into sessions.

The front end beats every HEARTBEAT_S seconds while the page is visible and
the person interacted in the last minute. A beat extends the open session
of the same (project, user, stage) when its last beat is less than GAP_S
old; otherwise it opens a new session. A session's duration counts the
window after its last beat too (the beat announces "working for the next
30 s"), so a single beat is worth one interval, not zero.
"""
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models.accounts import utcnow
from app.models.worktime import WORK_STAGES, WorkSession


def as_utc(dt: datetime) -> datetime:
    """SQLite hands naive datetimes back; every value here is UTC."""
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)

HEARTBEAT_S = 30
GAP_S = 120


def record_heartbeat(db: Session, project_id: int, user_id: int, stage: str,
                     instance_id: str = "", now: datetime | None = None) -> WorkSession:
    if stage not in WORK_STAGES:
        raise ValueError(f"unknown stage {stage!r}")
    now = now or utcnow()
    open_session = (db.query(WorkSession)
                    .filter_by(project_id=project_id, user_id=user_id, stage=stage)
                    .order_by(WorkSession.last_seen_at.desc())
                    .first())
    if (open_session is not None
            and as_utc(open_session.last_seen_at) >= now - timedelta(seconds=GAP_S)
            and as_utc(open_session.last_seen_at) <= now):
        open_session.last_seen_at = now
        open_session.n_heartbeats += 1
        return open_session
    session = WorkSession(project_id=project_id, user_id=user_id, stage=stage,
                          started_at=now, last_seen_at=now, n_heartbeats=1,
                          instance_id=instance_id)
    db.add(session)
    db.flush()
    return session


def session_seconds(s: WorkSession) -> int:
    """Duration credited to a session: first beat to last beat, plus the
    interval the last beat announced."""
    span = (as_utc(s.last_seen_at) - as_utc(s.started_at)).total_seconds()
    return int(max(0.0, span) + HEARTBEAT_S)


def is_closed(s: WorkSession, now: datetime | None = None) -> bool:
    """A session nobody beat for GAP_S is over — the only ones worth syncing
    (an open session would change the package hash every 30 s)."""
    now = now or utcnow()
    return as_utc(s.last_seen_at) < now - timedelta(seconds=GAP_S)


def measured_sessions(db: Session, project_id: int) -> list[dict]:
    """Every session of a project as plain dicts for the report."""
    return [
        {"user_id": s.user_id, "stage": s.stage,
         "started_at": as_utc(s.started_at), "ended_at": as_utc(s.last_seen_at),
         "seconds": session_seconds(s), "n_acts": None}
        for s in db.query(WorkSession).filter_by(project_id=project_id)
        .order_by(WorkSession.started_at)
    ]
