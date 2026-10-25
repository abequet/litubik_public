# SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Two assessors, one appraisal: allocation, disagreement, consensus.

The shape mirrors `services/screening/core.py` on purpose — a team that has
already run a dual screening round should recognise everything here — but the
unit is a study (chantier 9: an article may report several) rather than a
(record, stage, round) triple: a study is appraised once, not once per phase.

The rule the whole module serves: what each assessor said is never overwritten.
A disagreement is a fact about the review, and the agreed appraisal lives in
its own row.
"""
from sqlalchemy.orm import Session

from app.models import (
    AppraisalConfig, AppraisalConsensus, ExtractionStudy, JbiAppraisal, Record,
)
from app.services.appraisal import instruments


def config_of(db: Session, project_id: int) -> AppraisalConfig | None:
    return db.query(AppraisalConfig).filter_by(project_id=project_id).first()


def is_active(config: AppraisalConfig | None) -> bool:
    return config is not None and config.status == "active"


def is_dual(config: AppraisalConfig | None) -> bool:
    return is_active(config) and config.n_assessors >= 2


def instrument_of(db: Session, project_id: int) -> instruments.Instrument:
    config = config_of(db, project_id)
    return instruments.instrument(db, project_id,
                                  config.instrument if config else None)


def _answer(entry) -> str:
    return str((entry or {}).get("answer", "")) if isinstance(entry, dict) else ""


def disagreements(inst: instruments.Instrument, design: str | None,
                  appraisals: list[JbiAppraisal], scope: str) -> list[str]:
    """What two assessors disagree on: `["overall"]`, or the question ids.

    Blank answers are not disagreement — an assessor who has not answered a
    question yet has not contradicted anyone. Only two positions actually held
    can conflict, which is also why a single appraisal never conflicts with
    itself.
    """
    if len(appraisals) < 2:
        return []
    out: list[str] = []
    overalls = {a.overall for a in appraisals if a.overall}
    if inst.overall and len(overalls) > 1:
        out.append("overall")
    if scope == "per_question":
        for qid in instruments.question_ids(inst, design):
            given = {_answer((a.answers or {}).get(qid)) for a in appraisals}
            given.discard("")
            if len(given) > 1:
                out.append(qid)
    return out


def study_state(db: Session, project_id: int, study: ExtractionStudy,
                config: AppraisalConfig | None,
                inst: instruments.Instrument) -> dict:
    """Where one study stands: who appraised it, what they disagree on, and
    whether a consensus has been recorded."""
    appraisals = db.query(JbiAppraisal).filter_by(study_id=study.id).all()
    consensus = (db.query(AppraisalConsensus)
                 .filter_by(study_id=study.id).first())
    scope = config.conflict_scope if config else "overall"
    conflicts = (disagreements(inst, study.study_design, appraisals, scope)
                 if is_dual(config) else [])
    return {
        "record_id": study.record_id,
        "study_id": study.id,
        "n_appraisals": len(appraisals),
        "assessor_ids": [a.user_id for a in appraisals],
        "conflicts": conflicts,
        "resolved": consensus is not None,
        "status": ("resolved" if consensus is not None
                   else "conflict" if conflicts
                   else "complete" if _complete(config, inst, study.study_design,
                                                appraisals)
                   else "pending"),
    }


def record_state(db: Session, project_id: int, record: Record,
                 config: AppraisalConfig | None,
                 inst: instruments.Instrument) -> dict:
    """The state of the article's first study (pre-study callers)."""
    from app.services.extraction import studies as ext_studies
    study = ext_studies.ensure_default(db, record)
    return study_state(db, project_id, study, config, inst)


def _complete(config: AppraisalConfig | None, inst: instruments.Instrument,
              design: str | None, appraisals: list[JbiAppraisal]) -> bool:
    needed = config.n_assessors if is_active(config) else 1
    return sum(1 for a in appraisals
               if instruments.is_complete(inst, design, a.answers, a.overall)
               ) >= needed


def open_conflicts(db: Session, project_id: int) -> list[dict]:
    """Studies whose assessors disagree and that nobody has reconciled yet.

    Returns [] when the project is not running a dual appraisal — there is no
    such thing as a disagreement with oneself, and showing an empty tab is
    kinder than showing a tab that cannot fill.
    """
    config = config_of(db, project_id)
    if not is_dual(config):
        return []
    inst = instruments.instrument(db, project_id, config.instrument)
    resolved = {c.study_id for c in db.query(AppraisalConsensus)
                .filter_by(project_id=project_id)}
    by_study: dict[int, list[JbiAppraisal]] = {}
    for a in (db.query(JbiAppraisal)
              .join(Record, Record.id == JbiAppraisal.record_id)
              .filter(Record.project_id == project_id)):
        by_study.setdefault(a.study_id, []).append(a)
    if not by_study:
        return []
    n_studies: dict[int, int] = {}
    for s in (db.query(ExtractionStudy)
              .join(Record, Record.id == ExtractionStudy.record_id)
              .filter(Record.project_id == project_id)):
        n_studies[s.record_id] = n_studies.get(s.record_id, 0) + 1
    out = []
    for study, record in (db.query(ExtractionStudy, Record)
                          .join(Record, Record.id == ExtractionStudy.record_id)
                          .filter(ExtractionStudy.id.in_(by_study))
                          .order_by(Record.id, ExtractionStudy.position)):
        if study.id in resolved:
            continue
        items = disagreements(inst, study.study_design,
                              by_study[study.id], config.conflict_scope)
        if items:
            out.append({"record_id": record.id, "study_id": study.id,
                        "study_label": study.label,
                        "n_studies": n_studies.get(record.id, 1),
                        "title": record.title, "year": record.year,
                        "design": study.study_design, "conflicts": items})
    return out


def effective_appraisals(db: Session, study_ids: list[int]) -> dict[int, dict]:
    """The appraisal that counts, per study, for every aggregate downstream.

    Precedence: the consensus row when two assessors settled one, otherwise the
    pooled individual appraisals. Same principle as `consensus_cell()` for the
    extraction table — one value per study, and the disagreement counted rather
    than averaged away.

    Returns {study_id: {design, instrument, answers, overall, source,
    n_assessors}} where source is "consensus" or "individual".
    """
    if not study_ids:
        return {}
    out: dict[int, dict] = {}
    for c in (db.query(AppraisalConsensus)
              .filter(AppraisalConsensus.study_id.in_(study_ids))):
        out[c.study_id] = {
            "design": c.design, "instrument": c.instrument,
            "answers": c.answers or {}, "overall": c.overall,
            "source": "consensus", "n_assessors": 0,
        }
    pooled: dict[int, list[JbiAppraisal]] = {}
    for a in (db.query(JbiAppraisal)
              .filter(JbiAppraisal.study_id.in_(study_ids))):
        pooled.setdefault(a.study_id, []).append(a)
    for study_id, items in pooled.items():
        if study_id in out:
            # the consensus wins, but the fact that N people assessed it is
            # itself reportable (JBI's own checklist asks whether appraisal was
            # done by two or more reviewers independently)
            out[study_id]["n_assessors"] = len(items)
            continue
        answered = [a for a in items if a.answers or a.overall]
        if not answered:
            continue
        first = answered[0]
        out[study_id] = {
            "design": first.design, "instrument": first.instrument,
            "answers": first.answers or {}, "overall": first.overall,
            "source": "individual", "n_assessors": len(answered),
            # every assessor's answers, so a per-domain view can pool them
            # exactly as it did before the consensus row existed
            "all_answers": [a.answers or {} for a in answered],
        }
    return out
