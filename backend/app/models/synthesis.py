# SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
# SPDX-License-Identifier: AGPL-3.0-or-later
"""How the review synthesised its evidence, and how certain it is of it.

Three tables, all inert until a project turns the stage on:

- `SynthesisPlan` — the review-level SWiM items (Campbell et al., BMJ
  2020;368:l6890): how studies were grouped and why, what changed since the
  protocol, how results were prioritised, how heterogeneity was examined, how
  the data is presented, and what the synthesis cannot support.
- `SynthesisOutcome` — one reported result. This is the object LitUbik never
  had: before it, the included corpus was structured by nothing but extraction
  columns, so there was no unit to declare a synthesis method for, and nothing
  to rate certainty *of*. GRADE is per outcome, computed over the studies that
  contribute to that outcome — not over the corpus.
- `CertaintyAssessment` — one assessor's GRADE rating of one outcome, plus the
  consensus row when two assessors settled one. Same separation as
  AppraisalConsensus vs JbiAppraisal: what each said is never overwritten.
"""
from datetime import datetime

from sqlalchemy import (
    JSON, Boolean, DateTime, ForeignKey, Integer, String, Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.accounts import new_uuid, utcnow


class SynthesisPlan(Base):
    """The SWiM items that describe the synthesis as a whole (items 1, 4, 5,
    7 and 9). Per-outcome items live on SynthesisOutcome.

    Free markdown on purpose: these are reporting items, and SWiM is explicit
    that it does not prescribe how a synthesis is conducted. A structured form
    would quietly become a method.
    """
    __tablename__ = "synthesis_plans"
    __table_args__ = (UniqueConstraint("project_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"))
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    # Which framework rates the certainty of this review's findings
    # (services/synthesis/grade.py FRAMEWORKS): "none" | "grade".
    certainty_framework: Mapped[str] = mapped_column(String(20), default="none")
    grouping_md: Mapped[str] = mapped_column(Text, default="")          # SWiM 1a
    grouping_changes_md: Mapped[str] = mapped_column(Text, default="")  # SWiM 1b
    prioritisation_md: Mapped[str] = mapped_column(Text, default="")    # SWiM 4
    heterogeneity_md: Mapped[str] = mapped_column(Text, default="")     # SWiM 5
    presentation_md: Mapped[str] = mapped_column(Text, default="")      # SWiM 7
    limitations_md: Mapped[str] = mapped_column(Text, default="")       # SWiM 9
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class SynthesisOutcome(Base):
    """One reported result of the review: a comparison × outcome pair."""

    __tablename__ = "synthesis_outcomes"

    id: Mapped[int] = mapped_column(primary_key=True)
    uuid: Mapped[str] = mapped_column(String(36), default=new_uuid,
                                      unique=True, index=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    label: Mapped[str] = mapped_column(String(255))
    # Empty for the question frameworks that define no comparator (SPIDER,
    # PEO): the field is hidden rather than left to be filled with "n/a".
    comparison: Mapped[str] = mapped_column(String(255), default="")
    position: Mapped[int] = mapped_column(Integer, default=0)

    # GRADE step 1 and 2 — the two decisions that change the rating before any
    # domain is judged, which is why they are stored, not inferred.
    intent: Mapped[str] = mapped_column(String(20), default="association")
    target: Mapped[str] = mapped_column(String(30), default="any_effect")
    thresholds_md: Mapped[str] = mapped_column(Text, default="")
    # Direction of the observed effect: needed to phrase the GRADE informative
    # statement ("reduces" vs "increases"). "unclear" is an answer.
    direction: Mapped[str] = mapped_column(String(20), default="unclear")

    # SWiM items 2 and 3
    metric: Mapped[str] = mapped_column(String(255), default="")
    metric_rationale: Mapped[str] = mapped_column(Text, default="")
    synthesis_method: Mapped[str] = mapped_column(String(40), default="narrative")
    method_rationale: Mapped[str] = mapped_column(Text, default="")

    # The studies that contribute to THIS outcome — GRADE rates the evidence
    # behind one estimate, not the corpus (6 studies for one outcome and 14 for
    # another is the paper's own example). ExtractionStudy ids (chantier 9:
    # an article may report several); kept as JSON rather than an association
    # table because the list is edited as a whole.
    study_ids: Mapped[list] = mapped_column(JSON, default=list)
    # Meta-analysis bridge (chantier 10): {measure: SMD|MD|OR|RR|COR,
    # mapping: {role: column_id}} — which extraction columns hold each
    # study's inputs. Empty when the outcome is not quantitative.
    effect_spec: Mapped[dict] = mapped_column(JSON, default=dict)
    # Free text for what the synthesis found, when no metric fits.
    finding_md: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),
                                                 default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class CertaintyAssessment(Base):
    """A GRADE rating of one outcome, by one assessor or agreed between two."""

    __tablename__ = "certainty_assessments"
    __table_args__ = (UniqueConstraint("outcome_id", "user_id", "is_consensus"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    outcome_id: Mapped[int] = mapped_column(
        ForeignKey("synthesis_outcomes.id", ondelete="CASCADE"), index=True)
    # NULL on the consensus row: it belongs to the review, not to a person
    # (resolved_by records who wrote it).
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"))
    is_consensus: Mapped[bool] = mapped_column(Boolean, default=False)

    starting_point: Mapped[str] = mapped_column(String(10), default="low")
    starting_rationale: Mapped[str] = mapped_column(Text, default="")
    # {domain_key: {judgement: none|serious|very_serious, note: str}}
    domains: Mapped[dict] = mapped_column(JSON, default=dict)
    # {domain_key: {applied: bool, note: str}}
    upgrades: Mapped[dict] = mapped_column(JSON, default=dict)
    # What the assessor decided. The arithmetic proposal is recomputed on
    # read; storing only the decision is what lets the two differ visibly, as
    # GRADE expects them to.
    final: Mapped[str] = mapped_column(String(10), default="")
    statement_md: Mapped[str] = mapped_column(Text, default="")
    resolved_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"))
    imported_from: Mapped[str | None] = mapped_column(String(255))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow)
