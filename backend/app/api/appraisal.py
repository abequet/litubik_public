# SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Critical appraisal: instrument choice, who assesses, and reconciliation.

The per-record appraisal form itself still lives on the extraction router
(/extraction/records/{id}/jbi) — it is where an assessor works. What is here is
everything *about* the appraisal: which instrument the project uses, whether
two assessors are required, which records they disagree on, and the appraisal
they settled on.
"""
import re

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.api.deps import (
    DbDep, ProjectMemberDep, SatelliteGuard, get_project, require_project_admin,
)
from app.models import (
    AppraisalConfig, AppraisalConsensus, AppraisalInstrument, ExtractionStudy,
    JbiAppraisal, Record, User,
)
from app.services.appraisal import core, instruments
from app.services.extraction import studies as ext_studies

router = APIRouter(prefix="/api/projects/{project_id}/appraisal",
                   tags=["appraisal"])

SLUG = re.compile(r"^[a-z0-9][a-z0-9_-]{0,39}$")


def _record(project_id: int, record_id: int, db: DbDep) -> Record:
    record = db.get(Record, record_id)
    if record is None or record.project_id != project_id:
        raise HTTPException(status_code=404, detail="Record not found")
    return record


def _study(project_id: int, record: Record, study_id: int | None,
           db: DbDep) -> ExtractionStudy:
    """The study a consensus request is about: `study_id`, or the article's
    first study (chantier 9)."""
    try:
        study = ext_studies.resolve_study(db, project_id, record.id, study_id)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    if study.record_id != record.id:
        raise HTTPException(status_code=404, detail="Study not found")
    return study


# ---- configuration ----------------------------------------------------------

class ConfigIn(BaseModel):
    status: str = Field(default="draft", pattern="^(draft|active)$")
    instrument: str = "jbi"
    n_assessors: int = Field(default=1, ge=1, le=2)
    assessor_ids: list[int] = Field(default_factory=list)
    conflict_scope: str = Field(default="overall",
                                pattern="^(overall|per_question)$")
    conflict_resolution: str = Field(default="consensus",
                                     pattern="^(consensus|arbiter)$")


def _config_out(db, project_id: int, config: AppraisalConfig | None) -> dict:
    inst = core.instrument_of(db, project_id)
    return {
        "status": config.status if config else "draft",
        "instrument": config.instrument if config else instruments.BUILTIN_KEY,
        "instrument_label": inst.label,
        "n_assessors": config.n_assessors if config else 1,
        "assessor_ids": (config.assessor_ids or []) if config else [],
        "conflict_scope": config.conflict_scope if config else "overall",
        "conflict_resolution": (config.conflict_resolution if config
                                else "consensus"),
        "started_at": (config.started_at.isoformat()
                       if config and config.started_at else None),
        # what the setting actually buys, so the UI can say it plainly
        "dual": core.is_dual(config),
    }


@router.get("/config")
def get_config(project_id: int, member: ProjectMemberDep, db: DbDep):
    get_project(project_id, db)
    return _config_out(db, project_id, core.config_of(db, project_id))


@router.put("/config",
            dependencies=[Depends(require_project_admin), SatelliteGuard])
def put_config(project_id: int, payload: ConfigIn, db: DbDep):
    get_project(project_id, db)
    if payload.instrument not in instruments.project_instruments(db, project_id):
        raise HTTPException(status_code=400, detail="Unknown instrument")
    config = core.config_of(db, project_id)
    if config is None:
        config = AppraisalConfig(project_id=project_id)
        db.add(config)
    was_active = config.status == "active"
    config.status = payload.status
    config.instrument = payload.instrument
    config.n_assessors = payload.n_assessors
    config.assessor_ids = payload.assessor_ids
    config.conflict_scope = payload.conflict_scope
    config.conflict_resolution = payload.conflict_resolution
    if payload.status == "active" and not was_active:
        from app.models.accounts import utcnow
        config.started_at = utcnow()
    db.commit()
    return _config_out(db, project_id, config)


# ---- instruments ------------------------------------------------------------

class InstrumentIn(BaseModel):
    key: str
    label: str = Field(min_length=1, max_length=255)
    citation: str = ""
    url: str = Field(default="", max_length=500)
    # {design: {options: "ynu"|"ynun", domains: [{label, questions: [{id, text}]}]}}
    checklists: dict = Field(default_factory=dict)


@router.get("/instruments")
def list_instruments(project_id: int, member: ProjectMemberDep, db: DbDep):
    """Every instrument this project can appraise with, built-in first."""
    get_project(project_id, db)
    catalogue = instruments.project_instruments(db, project_id)
    rows = [instruments.as_catalogue(i) for i in catalogue.values()]
    rows.sort(key=lambda r: (not r["builtin"], r["label"]))
    return {"instruments": rows,
            "designs": [{"key": k, "label": v}
                        for k, v in instruments.DESIGNS.items()],
            "option_sets": instruments.OPTION_SETS,
            "overall_options": instruments.OVERALL_OPTIONS}


def _clean_checklists(raw: dict) -> dict:
    """Keep only what the registry can actually render, and refuse an
    instrument that would render as an empty form."""
    out: dict = {}
    for design, spec in (raw or {}).items():
        if design not in instruments.DESIGNS or not isinstance(spec, dict):
            continue
        options = spec.get("options")
        if options not in instruments.OPTION_SETS:
            options = "ynun"
        domains = []
        seen_ids: set[str] = set()
        for d in spec.get("domains") or []:
            questions = []
            for q in (d.get("questions") or []):
                qid = str(q.get("id", "")).strip()[:20]
                text = str(q.get("text", "")).strip()[:1000]
                # ids are what answers are keyed by: a duplicate would make two
                # questions share one answer
                if qid and text and qid not in seen_ids:
                    seen_ids.add(qid)
                    questions.append({"id": qid, "text": text})
            if questions:
                domains.append({"label": str(d.get("label", "")).strip()[:255],
                                "questions": questions})
        if domains:
            out[design] = {"options": options, "domains": domains}
    return out


@router.put("/instruments/{key}",
            dependencies=[Depends(require_project_admin), SatelliteGuard])
def put_instrument(project_id: int, key: str, payload: InstrumentIn, db: DbDep):
    """Declare (or update) an instrument of this project's own."""
    get_project(project_id, db)
    if not SLUG.match(key):
        raise HTTPException(status_code=400,
                            detail="Key must be a lowercase slug")
    if key in instruments.BUILTIN:
        raise HTTPException(status_code=400,
                            detail="This key belongs to a built-in instrument")
    checklists = _clean_checklists(payload.checklists)
    if not checklists:
        raise HTTPException(
            status_code=400,
            detail="Declare at least one study design with one question")
    row = (db.query(AppraisalInstrument)
           .filter_by(project_id=project_id, key=key).first())
    if row is None:
        row = AppraisalInstrument(project_id=project_id, key=key)
        db.add(row)
    row.label = payload.label
    row.citation = payload.citation
    row.url = payload.url
    row.checklists = checklists
    db.commit()
    db.refresh(row)
    return instruments.as_catalogue(instruments._from_row(row))


@router.delete("/instruments/{key}",
               dependencies=[Depends(require_project_admin), SatelliteGuard])
def delete_instrument(project_id: int, key: str, db: DbDep):
    get_project(project_id, db)
    row = (db.query(AppraisalInstrument)
           .filter_by(project_id=project_id, key=key).first())
    if row is None:
        raise HTTPException(status_code=404, detail="Instrument not found")
    config = core.config_of(db, project_id)
    if config and config.instrument == key:
        raise HTTPException(
            status_code=400,
            detail="This is the instrument the project appraises with — "
                   "switch to another one first")
    db.delete(row)
    db.commit()
    return {"ok": True}


# ---- disagreements and consensus --------------------------------------------

@router.get("/conflicts")
def list_conflicts(project_id: int, member: ProjectMemberDep, db: DbDep):
    """Records whose two assessors disagree and that nobody reconciled yet.

    Empty when the project does not run a dual appraisal — there is no
    disagreement to find, and the tab says so rather than looking broken.
    """
    get_project(project_id, db)
    config = core.config_of(db, project_id)
    return {"dual": core.is_dual(config),
            "conflicts": core.open_conflicts(db, project_id)}


class ConsensusIn(BaseModel):
    answers: dict = Field(default_factory=dict)
    overall: str = Field(default="", pattern="^(include|exclude|seek_info|)$")
    comment: str = ""


def _appraisal_out(a: JbiAppraisal, names: dict[int, str]) -> dict:
    return {"user_id": a.user_id, "user": names.get(a.user_id, "?"),
            "design": a.design, "instrument": a.instrument,
            "answers": a.answers or {}, "overall": a.overall,
            "comment": a.comment,
            "updated_at": a.updated_at.isoformat() if a.updated_at else ""}


@router.get("/records/{record_id}/consensus")
def get_consensus(project_id: int, record_id: int, member: ProjectMemberDep,
                  db: DbDep, study_id: int | None = None):
    """Everything needed to reconcile one study: each assessor's appraisal
    side by side, what they disagree on, and the consensus so far."""
    get_project(project_id, db)
    record = _record(project_id, record_id, db)
    study = _study(project_id, record, study_id, db)
    config = core.config_of(db, project_id)
    inst = core.instrument_of(db, project_id)
    names = {u.id: u.display_name for u in db.query(User)}
    appraisals = db.query(JbiAppraisal).filter_by(study_id=study.id).all()
    row = db.query(AppraisalConsensus).filter_by(study_id=study.id).first()
    return {
        "record_id": record.id, "title": record.title,
        "study": ext_studies.study_dict(study),
        "design": study.study_design,
        "instrument": instruments.summary(inst),
        "checklist": instruments.checklist_for(inst, study.study_design),
        "conflicts": core.disagreements(inst, study.study_design, appraisals,
                                        config.conflict_scope if config
                                        else "overall"),
        "appraisals": [_appraisal_out(a, names) for a in appraisals],
        "consensus": None if row is None else {
            "answers": row.answers or {}, "overall": row.overall,
            "comment": row.comment,
            "resolved_by": names.get(row.resolved_by, "?"),
            "resolved_at": (row.resolved_at.isoformat()
                            if row.resolved_at else ""),
        },
        "can_resolve": _may_resolve(config, member),
    }


def _may_resolve(config: AppraisalConfig | None, member) -> bool:
    if member.role == "admin":
        return True
    if config is None or config.conflict_resolution == "arbiter":
        return False
    return member.user_id in (config.assessor_ids or [])


@router.put("/records/{record_id}/consensus", dependencies=[SatelliteGuard])
def put_consensus(project_id: int, record_id: int, payload: ConsensusIn,
                  member: ProjectMemberDep, db: DbDep,
                  study_id: int | None = None):
    get_project(project_id, db)
    record = _record(project_id, record_id, db)
    study = _study(project_id, record, study_id, db)
    config = core.config_of(db, project_id)
    if not core.is_dual(config):
        raise HTTPException(
            status_code=400,
            detail="This project does not run a two-assessor appraisal")
    if not _may_resolve(config, member):
        raise HTTPException(
            status_code=403,
            detail="Arbiter mode: only a project admin resolves"
                   if config.conflict_resolution == "arbiter"
                   else "Consensus mode: only the assessors resolve")
    inst = core.instrument_of(db, project_id)
    checklist = instruments.checklist_for(inst, study.study_design)
    if checklist is None:
        raise HTTPException(status_code=400,
                            detail="No checklist for this study design")
    valid_ids = set(instruments.question_ids(inst, study.study_design))
    valid_answers = set(checklist["options"])
    answers = {}
    for qid, entry in (payload.answers or {}).items():
        if qid not in valid_ids or not isinstance(entry, dict):
            continue
        answer = str(entry.get("answer", ""))
        if answer and answer not in valid_answers:
            raise HTTPException(status_code=400,
                                detail=f"Invalid answer for {qid}: {answer}")
        answers[qid] = {"answer": answer,
                        "comment": str(entry.get("comment", ""))}
    from app.models.accounts import utcnow
    row = db.query(AppraisalConsensus).filter_by(study_id=study.id).first()
    if row is None:
        row = AppraisalConsensus(project_id=project_id, record_id=record.id,
                                 study_id=study.id)
        db.add(row)
    row.design = study.study_design or ""
    row.instrument = inst.key
    row.answers = answers
    row.overall = payload.overall if inst.overall else ""
    row.comment = payload.comment
    row.resolved_by = member.user_id
    row.resolved_at = utcnow()
    db.commit()
    return {"ok": True}


@router.delete("/records/{record_id}/consensus", dependencies=[SatelliteGuard])
def delete_consensus(project_id: int, record_id: int,
                     member: ProjectMemberDep, db: DbDep,
                     study_id: int | None = None):
    """Reopen a study: the individual appraisals were never touched, so
    dropping the consensus row puts the disagreement back on the list."""
    get_project(project_id, db)
    record = _record(project_id, record_id, db)
    study = _study(project_id, record, study_id, db)
    config = core.config_of(db, project_id)
    if not _may_resolve(config, member):
        raise HTTPException(status_code=403, detail="Not allowed to reopen")
    row = db.query(AppraisalConsensus).filter_by(study_id=study.id).first()
    if row is not None:
        db.delete(row)
        db.commit()
    return {"ok": True}
