# SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The Summary of Findings table.

CREST_Triage lists "Summary of Findings table required" among the problems it
flags, and SWiM item 8 asks for the synthesised finding *and its certainty*,
per comparison and outcome, saying which studies contribute. That is one table,
and every column of it already exists in the project: the outcomes, their
contributing studies, the participant counts in the extraction table, and the
GRADE rating.

Nothing here is typed in — same rule as the PRISMA counts and the Results
aggregates. A row the review has not filled shows as empty rather than as a
plausible blank.
"""
from sqlalchemy.orm import Session

from app.models import ExtractionColumn, ExtractionValue, SynthesisOutcome
from app.services.results.compute import consensus_cell
from app.services.synthesis import core, grade, methods

# Extraction column names read as the participant count (normalised compare).
PARTICIPANT_COLUMN_NAMES = {
    "sample size (n)", "sample size", "n", "participants",
    "number of participants", "taille de l'échantillon", "effectif",
}


def _norm(name: str) -> str:
    return " ".join((name or "").strip().lower().split())


def find_participants_column(db: Session,
                             project_id: int) -> ExtractionColumn | None:
    """The numeric extraction column that holds participant counts, if the
    project has one. Matched by name like the Results page matches its country
    column — no new setting for something the extraction template already
    names."""
    for column in (db.query(ExtractionColumn).filter_by(project_id=project_id)
                   .order_by(ExtractionColumn.position, ExtractionColumn.id)):
        if column.col_type == "number" and _norm(column.name) in PARTICIPANT_COLUMN_NAMES:
            return column
    return None


def _participants(db: Session, column: ExtractionColumn | None,
                  study_ids: list[int]) -> int | None:
    """Total participants across the contributing studies.

    None when the project has no such column, or when no contributing study
    carries an agreed value — a total built from half the studies would read as
    the whole, which is worse than an empty cell.
    """
    if column is None or not study_ids:
        return None
    by_study: dict[int, list[ExtractionValue]] = {}
    for value in (db.query(ExtractionValue)
                  .filter(ExtractionValue.column_id == column.id,
                          ExtractionValue.study_id.in_(study_ids))):
        by_study.setdefault(value.study_id, []).append(value)
    total = 0
    seen = False
    for study_id in study_ids:
        value, status = consensus_cell(by_study.get(study_id, []))
        if status == "ok" and isinstance(value, (int, float)):
            total += int(value)
            seen = True
    return total if seen else None


def rows(db: Session, project_id: int) -> dict:
    """The Summary of Findings table as data: one row per outcome."""
    outcomes = core.outcomes_of(db, project_id)
    certainty = core.effective_certainty(db, [o.id for o in outcomes])
    column = find_participants_column(db, project_id)
    plan = core.plan_of(db, project_id)
    framework = core.certainty_framework(plan)

    out = []
    for outcome in outcomes:
        rating = certainty.get(outcome.id)
        method = methods.method(outcome.synthesis_method)
        out.append({
            "outcome_id": outcome.id,
            "outcome": outcome.label,
            "comparison": outcome.comparison,
            "n_studies": len(outcome.study_ids or []),
            "n_participants": _participants(db, column, outcome.study_ids or []),
            "metric": outcome.metric,
            "synthesis_method": method.label,
            "question_answered": method.question,
            "finding_md": outcome.finding_md,
            "certainty": rating.final if rating else "",
            "certainty_label": (grade.LEVEL_LABELS.get(rating.final, "")
                                if rating else ""),
            "statement_md": rating.statement_md if rating else "",
            # A row whose certainty was never rated is reported as such: the
            # table must not read as "high certainty" by omission.
            "rated": bool(rating and rating.final),
        })
    return {
        "framework": framework,
        "framework_label": grade.FRAMEWORKS.get(framework, {}).get("label", ""),
        "participants_column": column.name if column else None,
        "rows": out,
        "n_rated": sum(1 for r in out if r["rated"]),
    }


def export_rows(db: Session, project_id: int) -> tuple[list[str], list[list]]:
    """The same table, flattened for CSV — the shape a manuscript's supplement
    takes."""
    data = rows(db, project_id)
    header = ["Comparison", "Outcome", "Studies", "Participants", "Metric",
              "Synthesis method", "Question the method answers", "Finding",
              "Certainty", "Plain-language statement"]
    body = []
    for r in data["rows"]:
        body.append([
            r["comparison"], r["outcome"], r["n_studies"],
            "" if r["n_participants"] is None else r["n_participants"],
            r["metric"], r["synthesis_method"], r["question_answered"],
            r["finding_md"],
            r["certainty_label"] or "not rated",
            r["statement_md"],
        ])
    return header, body
