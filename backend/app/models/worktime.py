# SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Reviewer work time (roadmap chantier 14).

One `WorkSession` is a stretch of *active* work by one member on one stage
of a project, measured from front-end heartbeats: the page sends one every
30 s while the tab is visible and the person interacted in the last minute;
a beat prolongs the open session when the previous one is less than two
minutes old, otherwise it opens a new one.

Deliberately coarse: stage and duration only — no record ids, no content.
The admin report aggregates sessions by reviewer, stage and week; a
reviewer sees their own total. Produced on whichever instance the member
works on, so the rows travel in contribution packages and snapshots.
"""
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.accounts import new_uuid, utcnow

# the stages a session can be attributed to (also the report's columns)
WORK_STAGES = ("ta", "ft", "conflicts", "dedup", "extraction", "appraisal")


class WorkSession(Base):
    __tablename__ = "work_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    # portable identity for sync (a package imported twice adds nothing)
    uuid: Mapped[str] = mapped_column(String(36), default=new_uuid, unique=True, index=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True)
    stage: Mapped[str] = mapped_column(String(20))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    n_heartbeats: Mapped[int] = mapped_column(Integer, default=0)
    # which installation measured it (the satellite's, for a satellite member)
    instance_id: Mapped[str] = mapped_column(String(64), default="")
    # sync: "author@email #seq" of the package this row came from
    imported_from: Mapped[str | None] = mapped_column(String(255))
