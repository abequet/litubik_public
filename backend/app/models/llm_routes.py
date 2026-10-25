# SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Per-task AI routing: which provider, model and effort a task runs on.

project_id NULL = app-wide default (app admin); a project row overrides it for
that project. Tasks without a row run on the tier model of the best-ranked
credential (services/llm/registry.TIER_MODELS)."""
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.accounts import utcnow


class LLMTaskRoute(Base):
    __tablename__ = "llm_task_routes"
    __table_args__ = (UniqueConstraint("project_id", "task"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int | None] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=True, index=True)
    task: Mapped[str] = mapped_column(String(40))       # services/llm/tasks.py key
    provider: Mapped[str] = mapped_column(String(20))   # registry.PROVIDERS
    model: Mapped[str] = mapped_column(String(120))
    effort: Mapped[str] = mapped_column(String(10), default="medium")
    updated_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow)
