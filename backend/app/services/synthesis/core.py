# SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Reading the synthesis stage: outcomes, certainty, and what the app can
propose from what it already knows.

The proposals are the point. LitUbik holds the study designs, the critical
appraisals and the search dossier, so it can put the evidence for a GRADE
judgement in front of the assessor instead of asking them to remember it. It
puts it there and stops: `suggest_*` returns a proposal and its reasoning, the
assessor stores their decision, and a divergence between the two stays visible.
"""
from sqlalchemy.orm import Session

from app.models import (
    ExtractionStudy,
    CertaintyAssessment, Record, SynthesisOutcome, SynthesisPlan,
)
from app.services import framing
from app.services.appraisal import core as appraisal_core
from app.services.appraisal import instruments
from app.services.synthesis import grade, methods


def plan_of(db: Session, project_id: int) -> SynthesisPlan | None:
    return db.query(SynthesisPlan).filter_by(project_id=project_id).first()


def is_enabled(plan: SynthesisPlan | None) -> bool:
    return plan is not None and plan.enabled


def certainty_framework(plan: SynthesisPlan | None) -> str:
    return plan.certainty_framework if plan else grade.DEFAULT_FRAMEWORK


def outcomes_of(db: Session, project_id: int) -> list[SynthesisOutcome]:
    return (db.query(SynthesisOutcome).filter_by(project_id=project_id)
            .order_by(SynthesisOutcome.position, SynthesisOutcome.id).all())


def comparison_slot(project) -> str:
    """The label the project's question framework gives its comparator, or ""
    when it defines none.

    PICO/PICOS/SPICE have one; SPIDER and PEO do not, and asking a qualitative
    review for its "comparison" is how a tool teaches people to write "n/a".
    """
    _, fw = framing.resolve(project)
    for slot in fw.slots:
        if slot.key in ("comparison", "comparator"):
            return slot.label
    return ""


def outcome_slot(project) -> str:
    """What this project's framework calls the thing an outcome is.

    PICO says Outcome, SPIDER and SPICE say Evaluation, PEO says Outcome. The
    entity is the same; the word is the team's.
    """
    _, fw = framing.resolve(project)
    for key in ("outcome", "evaluation"):
        for slot in fw.slots:
            if slot.key == key:
                return slot.label
    return "Outcome"


def certainty_warning(project, framework: str) -> str:
    """Why GRADE may be the wrong instrument for this review — a warning, not
    a lock. The team knows its evidence better than a mapping of framework
    keys does."""
    if framework != "grade":
        return ""
    _, fw = framing.resolve(project)
    if fw.key in grade.QUALITATIVE_FRAMEWORKS:
        return (f"This review is framed on {fw.short}, which usually means a "
                f"synthesis of qualitative findings. GRADE rates certainty in "
                f"quantitative estimates; GRADE-CERQual is its counterpart for "
                f"qualitative evidence. Rating with GRADE here is possible, "
                f"but say in the synthesis limitations why it fits.")
    return ""


# -- proposals ----------------------------------------------------------------

def contributing_designs(db: Session, outcome: SynthesisOutcome) -> list[str | None]:
    ids = outcome.study_ids or []
    if not ids:
        return []
    return [s.study_design for s in
            db.query(ExtractionStudy).filter(ExtractionStudy.id.in_(ids))]


def contributing_studies(db: Session, outcome: SynthesisOutcome
                         ) -> list[tuple[ExtractionStudy, Record, int]]:
    """(study, its record, how many studies that record reports), in the
    outcome's order — the unit every certainty judgement is made over."""
    ids = outcome.study_ids or []
    if not ids:
        return []
    rows = {s.id: (s, r) for s, r in
            db.query(ExtractionStudy, Record)
            .join(Record, Record.id == ExtractionStudy.record_id)
            .filter(ExtractionStudy.id.in_(ids))}
    record_ids = {r.id for _, r in rows.values()}
    counts: dict[int, int] = {}
    for s in db.query(ExtractionStudy).filter(ExtractionStudy.record_id.in_(record_ids)):
        counts[s.record_id] = counts.get(s.record_id, 0) + 1
    return [(rows[i][0], rows[i][1], counts.get(rows[i][1].id, 1))
            for i in ids if i in rows]


def suggest_starting_point(db: Session, outcome: SynthesisOutcome) -> dict:
    proposal = grade.suggest_starting_point(
        outcome.intent, contributing_designs(db, outcome))
    return {
        "starting_point": proposal.starting_point,
        "rationale": proposal.rationale,
        "design_counts": [
            {"design": d,
             "label": instruments.DESIGNS.get(d, d) if d != "unqualified"
                      else "Design not qualified",
             "n": n}
            for d, n in sorted(proposal.design_counts.items(),
                               key=lambda kv: -kv[1])],
    }


def risk_of_bias_evidence(db: Session, project_id: int,
                          outcome: SynthesisOutcome) -> dict:
    """What the study-level appraisals say about the studies behind THIS
    outcome — the input GRADE's risk-of-bias domain is meant to read.

    Returns the per-study appraisal that counted (consensus when two assessors
    settled one), plus the two facts that qualify the whole domain: whether an
    instrument was applied at all, and whether appraisal was duplicated. A
    domain judged "no serious concern" on an appraisal that never happened is
    exactly what editorial triage looks for.
    """
    ids = outcome.study_ids or []
    inst = appraisal_core.instrument_of(db, project_id)
    config = appraisal_core.config_of(db, project_id)
    effective = appraisal_core.effective_appraisals(db, ids)
    studies = []
    for study, record, n_studies in contributing_studies(db, outcome):
        entry = effective.get(study.id)
        score = (instruments.score(inst, entry["design"], entry["answers"])
                 if entry else None)
        studies.append({
            "record_id": record.id,
            "study_id": study.id,
            "study_label": study.label if n_studies > 1 else "",
            "title": (record.title or "")[:160]
                     + (f" – {study.label}" if n_studies > 1 else ""),
            "design": study.study_design,
            "appraised": entry is not None,
            "overall": entry["overall"] if entry else "",
            "source": entry["source"] if entry else "",
            "n_yes": score["n_yes"] if score else None,
            "n_questions": score["n_questions"] if score else None,
        })
    n_appraised = sum(1 for s in studies if s["appraised"])
    return {
        "instrument": inst.label,
        "dual_assessment": appraisal_core.is_dual(config),
        "n_studies": len(studies),
        "n_appraised": n_appraised,
        "studies": studies,
        "note": ("No contributing study has been appraised, so there is "
                 "nothing to base this domain on."
                 if n_appraised == 0 else
                 f"{n_appraised} of {len(studies)} contributing studies were "
                 f"appraised with {inst.label}"
                 + ("; two assessors worked independently."
                    if appraisal_core.is_dual(config)
                    else " by a single assessor.")),
    }


def publication_bias_evidence(db: Session, project_id: int) -> dict:
    """The search as it was actually run, shown next to the publication-bias
    domain — the paper is explicit that a comprehensive search is what
    supports a judgement of no serious concern here."""
    from app.services.reporting.audit import _search
    search = _search(db, project_id)
    databases = sorted({c["database"] for e in search["equations"]
                        for c in e["counts"]})
    return {
        "databases": databases,
        "n_databases": len(databases),
        "frozen_equation": search["frozen_equation"],
        "n_imports": len(search["imports"]),
        "grey_literature": False,  # LitUbik has no grey-literature channel yet
        "note": ("The search covered "
                 + (", ".join(databases) if databases else "no database yet")
                 + ". LitUbik has no grey-literature or trial-registry "
                   "channel, so searches of those, if any, were run outside "
                   "the app and are not evidenced here."),
    }


def suggest_statement(outcome: SynthesisOutcome, final: str) -> str:
    return grade.informative_statement(
        outcome.intent, outcome.direction, final, outcome.label,
        outcome.comparison)


# -- assembling ---------------------------------------------------------------

def assessments_of(db: Session, outcome_id: int) -> list[CertaintyAssessment]:
    return (db.query(CertaintyAssessment).filter_by(outcome_id=outcome_id)
            .order_by(CertaintyAssessment.is_consensus,
                      CertaintyAssessment.id).all())


def effective_certainty(db: Session,
                        outcome_ids: list[int]) -> dict[int, CertaintyAssessment]:
    """The rating that counts per outcome: the consensus one when it exists,
    otherwise the single assessment. Same precedence as everywhere else."""
    if not outcome_ids:
        return {}
    out: dict[int, CertaintyAssessment] = {}
    for row in (db.query(CertaintyAssessment)
                .filter(CertaintyAssessment.outcome_id.in_(outcome_ids))
                .order_by(CertaintyAssessment.is_consensus)):
        # is_consensus sorts False first, so a consensus row overwrites
        if row.final:
            out[row.outcome_id] = row
    return out


def outcome_dict(db: Session, outcome: SynthesisOutcome,
                 certainty: CertaintyAssessment | None = None) -> dict:
    method = methods.method(outcome.synthesis_method)
    return {
        "id": outcome.id, "uuid": outcome.uuid, "label": outcome.label,
        "comparison": outcome.comparison, "position": outcome.position,
        "intent": outcome.intent, "target": outcome.target,
        "thresholds_md": outcome.thresholds_md, "direction": outcome.direction,
        "metric": outcome.metric, "metric_rationale": outcome.metric_rationale,
        "synthesis_method": method.key,
        "synthesis_method_label": method.label,
        "synthesis_method_question": method.question,
        "method_rationale": outcome.method_rationale,
        "study_ids": outcome.study_ids or [],
        # the articles behind those studies (one article may carry several)
        "record_ids": list(dict.fromkeys(
            r.id for _, r, _ in contributing_studies(db, outcome))),
        "n_studies": len(outcome.study_ids or []),
        "effect_spec": outcome.effect_spec or {},
        "finding_md": outcome.finding_md,
        "certainty": None if certainty is None else {
            "final": certainty.final,
            "label": grade.LEVEL_LABELS.get(certainty.final, ""),
            "statement_md": certainty.statement_md,
            "is_consensus": certainty.is_consensus,
        },
    }
