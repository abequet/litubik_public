# SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
# SPDX-License-Identifier: AGPL-3.0-or-later
"""M10 results: the one stored artifact of the Results stage — the AI-generated
narrative synthesis. Every other number on the page is computed live from the
tables (see services/results/compute.py)."""
from datetime import datetime

from sqlalchemy import (
    DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.accounts import utcnow


class ResultsSynthesis(Base):
    """One per project; regenerating overwrites (the previous text cost money
    too, but two competing narratives would be worse than none)."""
    __tablename__ = "results_syntheses"
    __table_args__ = (UniqueConstraint("project_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"))
    content_md: Mapped[str] = mapped_column(Text, default="")
    provider: Mapped[str] = mapped_column(String(30), default="")
    model: Mapped[str] = mapped_column(String(100), default="")
    tokens_in: Mapped[int] = mapped_column(Integer, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    generated_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow)
