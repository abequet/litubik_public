# SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Reporting: what the review actually did, and what the AI actually did.

Two tables:

- `AiUsage` — the AI-use journal. Every LLM call made for a project lands here,
  aggregated per (feature, provider/model, author, day) so a 5 000-title triage
  costs one row instead of 5 000. It exists because a disclosure statement
  written from memory under-reports: prior work shows authors misattribute and
  forget AI contributions (the ghostwriter effect), and several LitUbik AI
  helpers (keyword suggestions, strategy advice) otherwise leave no trace at
  all once their output has been edited by a human.
- `ReportSection` — the two generated write-ups (Methods paragraph, AI
  disclosure statement). Both keep the auto-generated text AND the author's
  edited version side by side: the generated text is evidence of what the
  journal says, the edited one is what the author signs.
"""
from datetime import datetime

from sqlalchemy import (
    JSON, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.accounts import new_uuid, utcnow

# The two write-ups a project can generate.
REPORT_KINDS = ("methods", "ai_disclosure")


class AiUsage(Base):
    """One day of one AI feature, by one member, on one model.

    Aggregated on purpose: the disclosure needs "screening suggestions, 412
    calls, ChatGPT 5.2, between the 3rd and the 9th of March", not 412 rows.
    Per-call detail that matters (which record, which decision, whether a human
    accepted it) already lives in the pipeline tables it wrote to.
    """

    __tablename__ = "ai_usage"
    __table_args__ = (
        UniqueConstraint("project_id", "feature", "provider", "model",
                         "user_id", "day", name="uq_ai_usage_bucket"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int | None] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    # prompt key from services/llm/prompts.py (or a reporting_* key)
    feature: Mapped[str] = mapped_column(String(40), index=True)
    provider: Mapped[str] = mapped_column(String(30), default="")
    model: Mapped[str] = mapped_column(String(100), default="")
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"))
    day: Mapped[str] = mapped_column(String(10))  # UTC "YYYY-MM-DD"
    n_calls: Mapped[int] = mapped_column(Integer, default=0)
    tokens_in: Mapped[int] = mapped_column(Integer, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    first_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow)
    last_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow)
    # sync: "author@email #seq" of the contribution package this row came from
    imported_from: Mapped[str | None] = mapped_column(String(255))


class ProtocolDeviation(Base):
    """A way the review departed from what its protocol said, and why.

    Two kinds share the table. `detected` rows come from a signal the pipeline
    tables carry — criteria edited mid-screening, an equation frozen after
    imports — that a human has answered. `declared` rows are the ones a team
    writes itself, for the changes no table can see (a regrouping decided in a
    meeting, a synthesis method abandoned).

    `signal` is the machine key of the detection this row answers, and it is
    what stops an answered signal from being offered again at every page load.
    NULL on a purely declared deviation.

    `dismissed_at` is not a delete: "we looked at this and it was not a
    deviation" is itself a finding, and losing it would mean re-litigating the
    same signal at the next reading.
    """

    __tablename__ = "protocol_deviations"

    id: Mapped[int] = mapped_column(primary_key=True)
    uuid: Mapped[str] = mapped_column(String(36), default=new_uuid,
                                      unique=True, index=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    stage: Mapped[str] = mapped_column(String(20), default="protocol")
    kind: Mapped[str] = mapped_column(String(10), default="declared")
    signal: Mapped[str | None] = mapped_column(String(120))
    summary: Mapped[str] = mapped_column(Text, default="")
    # The reason. Empty is allowed while drafting, but a deviation without one
    # tells a reader nothing they could not already see.
    rationale: Mapped[str] = mapped_column(Text, default="")
    occurred_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    declared_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"))
    dismissed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True))
    dismiss_note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),
                                                 default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class ChecklistAnswer(Base):
    """What the author adds to a pre-filled reporting checklist.

    The app fills what it can prove; this table holds the rest — the page where
    an item is reported, a note for the items that live outside the software
    (funding, competing interests, the discussion), and the occasional status
    the author overrides because only they know an item does not apply to
    their review.

    The override is deliberately one-directional in spirit: it lets a human say
    "not applicable" or "reported on page 7", never lets the app claim
    something it did not observe.
    """

    __tablename__ = "checklist_answers"
    __table_args__ = (UniqueConstraint("project_id", "checklist", "item"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    checklist: Mapped[str] = mapped_column(String(20))  # prisma2020 | swim
    item: Mapped[str] = mapped_column(String(10))       # "13a", "24c"…
    page_ref: Mapped[str] = mapped_column(String(120), default="")
    note: Mapped[str] = mapped_column(Text, default="")
    status_override: Mapped[str] = mapped_column(String(20), default="")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class ReportSection(Base):
    """One generated write-up per project and kind (methods | ai_disclosure).

    Regenerating overwrites `content_md` and leaves `edited_md` alone unless the
    author asks for a reset — the edited text is the one they take
    responsibility for, and losing it to a stray click would be worse than
    keeping a stale pair.
    """

    __tablename__ = "report_sections"
    __table_args__ = (UniqueConstraint("project_id", "kind"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(20))
    lang: Mapped[str] = mapped_column(String(5), default="en")
    content_md: Mapped[str] = mapped_column(Text, default="")   # AI-generated
    edited_md: Mapped[str] = mapped_column(Text, default="")    # author's version
    # ai_disclosure: the DAISY-style form as answered when generating (the
    # structured layer the statement was written from)
    form: Mapped[dict] = mapped_column(JSON, default=dict)
    provider: Mapped[str] = mapped_column(String(30), default="")
    model: Mapped[str] = mapped_column(String(100), default="")
    tokens_in: Mapped[int] = mapped_column(Integer, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    generated_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow)
