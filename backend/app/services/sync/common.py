# SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Shared sync plumbing: user-facing errors and the exchange journal."""
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import SyncEvent


class SnapshotError(Exception):
    """User-facing sync failure (surfaces as the job/API error message)."""


def log_event(db: Session, project_id: int, direction: str, kind: str,
              author_email: str = "", instance_id: str = "", seq: int = 0,
              based_on: int = 0, filename: str = "",
              counts: dict | None = None, warnings: list | None = None,
              user_id: int | None = None) -> SyncEvent:
    event = SyncEvent(project_id=project_id, direction=direction, kind=kind,
                      author_email=author_email, instance_id=instance_id,
                      seq=seq, based_on_version=based_on, filename=filename,
                      counts=counts or {}, warnings=warnings or [],
                      created_by=user_id)
    db.add(event)
    return event


def next_contrib_seq(db: Session, project_id: int, author_email: str) -> int:
    """Per-author outbound package counter, derived from the export journal."""
    current = (db.query(func.max(SyncEvent.seq))
               .filter_by(project_id=project_id, direction="export",
                          kind="contributions", author_email=author_email)
               .scalar())
    return (current or 0) + 1
