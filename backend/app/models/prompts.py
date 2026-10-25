# SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Per-project overrides of the AI instruction blocks (transparency, M2).

The defaults live in code (app/services/llm/prompts.py); a project admin can
inspect and override the instruction part of each AI feature. Dynamic context
(protocol text, checklists, evidence tables) and the JSON output schemas are
appended by the call sites and are never editable."""
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.accounts import utcnow


class PromptOverride(Base):
    __tablename__ = "prompt_overrides"
    __table_args__ = (UniqueConstraint("project_id", "feature_key"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    feature_key: Mapped[str] = mapped_column(String(60))
    text: Mapped[str] = mapped_column(Text, default="")
    updated_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow)
