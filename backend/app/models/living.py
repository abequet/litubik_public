# SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Living review (roadmap chantier 5): scheduled search updates and in-app
notifications.

A *search update* is a new pass of the frozen equation over the API
databases, restricted to what the databases indexed since the previous pass.
It creates a new round (Source.round = next round, type stays `database`),
deduplicates against the whole corpus and opens the next title/abstract
screening round with the previous round's rules — exactly what a snowballing
iteration does. `SearchUpdateRun` is the audit row that owns the round, the
counterpart of `SnowballRun`; PRISMA and the deletion guard find a round's
kind by looking for its run row.

`Notification` is per instance and per user (never synced): "37 new candidates
to screen" after a pass, read from the header bell and the project card.
"""
from datetime import datetime

from sqlalchemy import (
    Boolean, DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.accounts import new_uuid, utcnow

UPDATE_INTERVALS = (7, 14, 30, 90)


class SearchUpdatePlan(Base):
    __tablename__ = "search_update_plans"
    __table_args__ = (UniqueConstraint("project_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    uuid: Mapped[str] = mapped_column(String(36), default=new_uuid, unique=True, index=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    interval_days: Mapped[int] = mapped_column(Integer, default=30)
    # API databases to re-run (ids of the catalogue / keyed providers)
    databases: Mapped[list] = mapped_column(JSON, default=list)
    equation_id: Mapped[int | None] = mapped_column(
        ForeignKey("equations.id", ondelete="SET NULL"))
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class SearchUpdateRun(Base):
    __tablename__ = "search_update_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    uuid: Mapped[str] = mapped_column(String(36), default=new_uuid, unique=True, index=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    round: Mapped[int] = mapped_column(Integer)  # round of the created records
    databases: Mapped[list] = mapped_column(JSON, default=list)
    # records indexed since this instant were asked for (None = full re-run)
    since_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    n_fetched: Mapped[int] = mapped_column(Integer, default=0)
    n_new_unique: Mapped[int] = mapped_column(Integer, default=0)
    # schedule (plan due) | manual (button) | fetch (a "fetch now" while a
    # title/abstract round was active)
    triggered_by: Mapped[str] = mapped_column(String(10), default="manual")
    errors: Mapped[dict] = mapped_column(JSON, default=dict)  # database -> message
    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True)
    project_id: Mapped[int | None] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(40))  # search_update | ...
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
