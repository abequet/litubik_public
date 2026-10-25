# SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Sync exchange journal (phase 2)."""
from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.accounts import utcnow


class SyncEvent(Base):
    """One line per snapshot/contribution exchange, both directions — the
    audit trail shown on the Synchronisation page. Local only (never travels).
    Outbound contribution packages also derive their per-author `seq` from the
    export events recorded here."""

    __tablename__ = "sync_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    direction: Mapped[str] = mapped_column(String(10))  # export | import
    kind: Mapped[str] = mapped_column(String(15))  # snapshot | contributions
    # whose data: snapshot exporter, or the contribution package's author
    author_email: Mapped[str] = mapped_column(String(255), default="")
    instance_id: Mapped[str] = mapped_column(String(36), default="")
    seq: Mapped[int] = mapped_column(Integer, default=0)
    based_on_version: Mapped[int] = mapped_column(Integer, default=0)
    filename: Mapped[str] = mapped_column(String(500), default="")
    counts: Mapped[dict] = mapped_column(JSON, default=dict)
    warnings: Mapped[list] = mapped_column(JSON, default=list)
    # the local user who clicked (exporter or importer)
    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow)
