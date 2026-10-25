# SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Studies within an article (roadmap chantier 9).

An article (Record) that enters extraction carries one or more
ExtractionStudy rows. Position 0 is the default study every record gets —
created eagerly by the migration for records that already had extraction
data, lazily here for the others — so a single-study article changes nothing
for the user. Values, appraisals, consensus rows and synthesis outcomes hang
off the study, never off the record directly.
"""
from sqlalchemy.orm import Session

from app.models import (
    AppraisalConsensus, ExtractionStudy, ExtractionValue, JbiAppraisal, Record,
    SynthesisOutcome,
)

DEFAULT_LABEL = "Study 1"
MAX_STUDIES = 20


def studies_for_records(db: Session, record_ids: list[int],
                        user_id: int | None = None) -> dict[int, list[ExtractionStudy]]:
    """{record_id: [studies by position]} for every record given — a record
    without any study gets its default one created on the spot."""
    out: dict[int, list[ExtractionStudy]] = {rid: [] for rid in record_ids}
    if not record_ids:
        return out
    for s in (db.query(ExtractionStudy)
              .filter(ExtractionStudy.record_id.in_(record_ids))
              .order_by(ExtractionStudy.position, ExtractionStudy.id)):
        out.setdefault(s.record_id, []).append(s)
    missing = [rid for rid, studies in out.items() if not studies]
    if missing:
        for rid in missing:
            s = ExtractionStudy(record_id=rid, label=DEFAULT_LABEL, position=0,
                                created_by=user_id)
            db.add(s)
            out[rid].append(s)
        db.flush()
        # mirror an article-level design qualified before the study existed
        for r in db.query(Record).filter(Record.id.in_(missing)):
            if r.study_design and out[r.id]:
                out[r.id][0].study_design = r.study_design
                out[r.id][0].design_origin = r.design_origin
        db.commit()
    return out


def ensure_default(db: Session, record: Record,
                   user_id: int | None = None) -> ExtractionStudy:
    return studies_for_records(db, [record.id], user_id)[record.id][0]


def get_study(db: Session, project_id: int, study_id: int) -> ExtractionStudy | None:
    row = (db.query(ExtractionStudy)
           .join(Record, Record.id == ExtractionStudy.record_id)
           .filter(ExtractionStudy.id == study_id, Record.project_id == project_id)
           .first())
    return row


def resolve_study(db: Session, project_id: int, record_id: int | None,
                  study_id: int | None, user_id: int | None = None) -> ExtractionStudy:
    """The study a request targets: an explicit study id (checked against the
    project), or the default study of the record. LookupError when neither
    resolves."""
    if study_id is not None:
        study = get_study(db, project_id, study_id)
        if study is None:
            raise LookupError("Study not found")
        return study
    record = db.get(Record, record_id) if record_id is not None else None
    if record is None or record.project_id != project_id:
        raise LookupError("Record not found")
    return ensure_default(db, record, user_id)


def add_study(db: Session, record: Record, label: str, user_id: int | None,
              design: str | None = None, origin: str | None = None) -> ExtractionStudy:
    studies = studies_for_records(db, [record.id], user_id)[record.id]
    if len(studies) >= MAX_STUDIES:
        raise ValueError(f"At most {MAX_STUDIES} studies per article")
    position = max(s.position for s in studies) + 1
    clean = " ".join((label or "").split())[:120] or f"Study {position + 1}"
    study = ExtractionStudy(record_id=record.id, label=clean, position=position,
                            study_design=design, design_origin=origin,
                            created_by=user_id)
    db.add(study)
    db.flush()
    return study


def find_by_label(db: Session, record: Record, label: str) -> ExtractionStudy | None:
    key = " ".join((label or "").split()).lower()
    if not key:
        return None
    for s in studies_for_records(db, [record.id])[record.id]:
        if s.label.strip().lower() == key:
            return s
    return None


def rename_study(db: Session, study: ExtractionStudy, label: str) -> None:
    study.label = " ".join((label or "").split())[:120] or study.label


def delete_study(db: Session, study: ExtractionStudy) -> dict:
    """Remove a study and everything keyed on it. The default study (position
    0) cannot be removed — an article always has one."""
    if study.position == 0:
        raise ValueError("The first study of an article cannot be removed")
    n_values = db.query(ExtractionValue).filter_by(study_id=study.id).count()
    n_appraisals = db.query(JbiAppraisal).filter_by(study_id=study.id).count()
    db.query(ExtractionValue).filter_by(study_id=study.id).delete(
        synchronize_session=False)
    db.query(JbiAppraisal).filter_by(study_id=study.id).delete(
        synchronize_session=False)
    db.query(AppraisalConsensus).filter_by(study_id=study.id).delete(
        synchronize_session=False)
    record = db.get(Record, study.record_id)
    if record is not None:
        for o in db.query(SynthesisOutcome).filter_by(project_id=record.project_id):
            if study.id in (o.study_ids or []):
                o.study_ids = [s for s in o.study_ids if s != study.id]
    db.delete(study)
    db.flush()
    return {"values_removed": n_values, "appraisals_removed": n_appraisals}


def set_design(db: Session, study: ExtractionStudy, design: str | None,
               origin: str | None) -> None:
    """The design belongs to the study; the record mirrors its first study's
    so article-level readers (cards, audit) keep a value to show."""
    study.study_design = design or None
    study.design_origin = origin if design else None
    if study.position == 0:
        record = db.get(Record, study.record_id)
        if record is not None:
            record.study_design = study.study_design
            record.design_origin = study.design_origin


def has_content(db: Session, study: ExtractionStudy) -> bool:
    return bool(
        db.query(ExtractionValue).filter_by(study_id=study.id).count()
        or db.query(JbiAppraisal).filter_by(study_id=study.id).count()
        or db.query(AppraisalConsensus).filter_by(study_id=study.id).count())


def study_dict(s: ExtractionStudy) -> dict:
    return {"study_id": s.id, "uuid": s.uuid, "label": s.label,
            "position": s.position, "study_design": s.study_design,
            "design_origin": s.design_origin}


def display_label(base: str, study: ExtractionStudy, n_studies: int) -> str:
    """'Author (year)' for a single-study article, 'Author (year) – label'
    when the article reports several."""
    return base if n_studies <= 1 else f"{base} – {study.label}"
