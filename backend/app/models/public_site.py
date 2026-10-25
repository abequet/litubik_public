# SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
# SPDX-License-Identifier: AGPL-3.0-or-later
"""What an instance open to the public needs beyond the review itself: the
monthly AI spending of its demo visitors, and its legal pages."""
from datetime import datetime

from sqlalchemy import (
    DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.accounts import utcnow


class DemoAiBudget(Base):
    """One row per calendar month ("YYYY-MM") and per day ("YYYY-MM-DD", UTC):
    what every sandbox account together spent on the app-wide AI key. Holds
    no personal data on purpose, so it can outlive the nightly purge of the
    accounts that spent it."""

    __tablename__ = "demo_ai_budget"

    id: Mapped[int] = mapped_column(primary_key=True)
    period: Mapped[str] = mapped_column(String(10), unique=True)
    spent_usd: Mapped[float] = mapped_column(Float, default=0.0)
    n_calls: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow)


class LegalPage(Base):
    """A legal page (notice, terms, privacy) the superadmin rewrote. Without a
    row, the page is the shipped template filled from LegalSettings."""

    __tablename__ = "legal_pages"
    __table_args__ = (UniqueConstraint("slug", "lang", name="uq_legal_page"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(20))
    lang: Mapped[str] = mapped_column(String(5))
    body_md: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow)
    updated_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"))


class LegalSettings(Base):
    """Single row (id=1): who runs this instance and where it is hosted — the
    values the legal page templates are filled with. Empty fields fall back to
    automatic defaults (app/services/legal.py)."""

    __tablename__ = "legal_settings"

    id: Mapped[int] = mapped_column(primary_key=True)  # always 1
    operator_name: Mapped[str] = mapped_column(String(200), default="")
    contact_email: Mapped[str] = mapped_column(String(255), default="")
    host_name: Mapped[str] = mapped_column(String(200), default="")
    host_address: Mapped[str] = mapped_column(String(400), default="")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow)
