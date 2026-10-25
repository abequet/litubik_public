# SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
# SPDX-License-Identifier: AGPL-3.0-or-later
"""In-app support tickets: bug reports and feedback from the reviewers,
triaged by the app admin (real-time feedback loop while the tool is used)."""
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models.accounts import new_uuid, utcnow


class Ticket(Base):
    __tablename__ = "tickets"

    id: Mapped[int] = mapped_column(primary_key=True)
    # sync: tickets travel in their author's contribution packages
    uuid: Mapped[str] = mapped_column(String(36), default=new_uuid,
                                      unique=True, index=True)
    imported_from: Mapped[str | None] = mapped_column(String(255))
    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"))
    # optional link to the project the user was working in when reporting
    project_id: Mapped[int | None] = mapped_column(
        ForeignKey("projects.id", ondelete="SET NULL"), nullable=True)
    title: Mapped[str] = mapped_column(String(255))
    body: Mapped[str] = mapped_column(Text, default="")
    kind: Mapped[str] = mapped_column(String(20), default="bug")  # bug | feedback | feature
    severity: Mapped[str] = mapped_column(String(20), default="minor")  # minor | major | blocking
    page: Mapped[str] = mapped_column(String(500), default="")  # app route when reported
    status: Mapped[str] = mapped_column(
        String(20), default="open", index=True)  # open | in_progress | resolved | closed
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    comments: Mapped[list["TicketComment"]] = relationship(
        cascade="all, delete-orphan", order_by="TicketComment.id")


class TicketComment(Base):
    __tablename__ = "ticket_comments"

    id: Mapped[int] = mapped_column(primary_key=True)
    uuid: Mapped[str] = mapped_column(String(36), default=new_uuid,
                                      unique=True, index=True)
    imported_from: Mapped[str | None] = mapped_column(String(255))
    ticket_id: Mapped[int] = mapped_column(
        ForeignKey("tickets.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"))
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
