# SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Synthesis declaration (SWiM) and certainty of the evidence (GRADE).

Structural endpoints — the plan, the outcomes — are the coordinator's, like
every other thing that defines what the review is. A certainty assessment is
one assessor's judgement, so it follows the contribution rules instead.
"""
import csv
import io

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.api.deps import (
    DbDep, ProjectMemberDep, SatelliteGuard, get_project, require_project_admin,
)
from app.core.csvsafe import safe_row
from app.models import (
    CertaintyAssessment, ExtractionStudy, Record, SynthesisOutcome,
    SynthesisPlan, User,
)
from app.models.accounts import utcnow
from app.services.extraction import studies as ext_studies
from app.services.extraction.service import eligible_ids
from app.services.synthesis import core, effects, grade, methods, sof

router = APIRouter(prefix="/api/projects/{project_id}/synthesis",
                   tags=["synthesis"])


def _outcome(project_id: int, outcome_id: int, db) -> SynthesisOutcome:
    outcome = db.get(SynthesisOutcome, outcome_id)
    if outcome is None or outcome.project_id != project_id:
        raise HTTPException(status_code=404, detail="Outcome not found")
    return outcome


# ---- catalogue --------------------------------------------------------------

@router.get("/catalogue")
def catalogue(project_id: int, member: ProjectMemberDep, db: DbDep):
    """Everything the synthesis forms need to render: the SWiM methods with
    the question each answers, the GRADE vocabulary, and the words this
    project's own question framework uses for an outcome and a comparator."""
    project = get_project(project_id, db)
    return {
        "methods": methods.as_catalogue(),
        "directions": [{"key": k, "label": v}
                       for k, v in methods.DIRECTIONS.items()],
        "grade": grade.as_catalogue(),
        # SPIDER says "Evaluation", PEO has no comparator at all — the form
        # takes its words from the project rather than assuming PICO
        "outcome_slot": core.outcome_slot(project),
        "comparison_slot": core.comparison_slot(project),
    }


# ---- the plan (SWiM review-level items) -------------------------------------

class PlanIn(BaseModel):
    enabled: bool = False
    certainty_framework: str = "none"
    grouping_md: str = ""
    grouping_changes_md: str = ""
    prioritisation_md: str = ""
    heterogeneity_md: str = ""
    presentation_md: str = ""
    limitations_md: str = ""


def _plan_out(project, plan: SynthesisPlan | None) -> dict:
    framework = core.certainty_framework(plan)
    return {
        "enabled": core.is_enabled(plan),
        "certainty_framework": framework,
        "certainty_warning": core.certainty_warning(project, framework),
        "grouping_md": plan.grouping_md if plan else "",
        "grouping_changes_md": plan.grouping_changes_md if plan else "",
        "prioritisation_md": plan.prioritisation_md if plan else "",
        "heterogeneity_md": plan.heterogeneity_md if plan else "",
        "presentation_md": plan.presentation_md if plan else "",
        "limitations_md": plan.limitations_md if plan else "",
    }


@router.get("/plan")
def get_plan(project_id: int, member: ProjectMemberDep, db: DbDep):
    project = get_project(project_id, db)
    return _plan_out(project, core.plan_of(db, project_id))


@router.put("/plan",
            dependencies=[Depends(require_project_admin), SatelliteGuard])
def put_plan(project_id: int, payload: PlanIn, db: DbDep):
    project = get_project(project_id, db)
    if payload.certainty_framework not in grade.FRAMEWORKS:
        raise HTTPException(status_code=400,
                            detail="Unknown certainty framework")
    plan = core.plan_of(db, project_id)
    if plan is None:
        plan = SynthesisPlan(project_id=project_id)
        db.add(plan)
    for field in ("enabled", "certainty_framework", "grouping_md",
                  "grouping_changes_md", "prioritisation_md",
                  "heterogeneity_md", "presentation_md", "limitations_md"):
        setattr(plan, field, getattr(payload, field))
    db.commit()
    return _plan_out(project, plan)


# ---- outcomes ---------------------------------------------------------------

class OutcomeIn(BaseModel):
    label: str = Field(min_length=1, max_length=255)
    comparison: str = Field(default="", max_length=255)
    intent: str = Field(default="association", pattern="^(causation|association)$")
    target: str = Field(default="any_effect",
                        pattern="^(any_effect|important_effect|magnitude)$")
    thresholds_md: str = ""
    direction: str = Field(default="unclear",
                           pattern="^(decrease|increase|no_effect|unclear)$")
    metric: str = Field(default="", max_length=255)
    metric_rationale: str = ""
    synthesis_method: str = "narrative"
    method_rationale: str = ""
    # contributing studies (chantier 9); `record_ids` is still accepted and
    # means "the first study of each of these articles"
    study_ids: list[int] = Field(default_factory=list)
    record_ids: list[int] = Field(default_factory=list)
    finding_md: str = ""
    position: int | None = None


@router.get("/outcomes")
def list_outcomes(project_id: int, member: ProjectMemberDep, db: DbDep):
    get_project(project_id, db)
    outcomes = core.outcomes_of(db, project_id)
    certainty = core.effective_certainty(db, [o.id for o in outcomes])
    return {"outcomes": [core.outcome_dict(db, o, certainty.get(o.id))
                         for o in outcomes]}


@router.get("/eligible-records")
def eligible_records(project_id: int, member: ProjectMemberDep, db: DbDep):
    """The corpus an outcome can draw its contributing studies from — every
    study of the full-text-included set, the same corpus the Results page
    aggregates. `records` keeps the per-article view."""
    get_project(project_id, db)
    ids = eligible_ids(db, project_id)
    records = {r.id: r for r in db.query(Record).filter(Record.id.in_(ids))} \
        if ids else {}
    by_record = ext_studies.studies_for_records(db, ids, member.user_id)
    studies = []
    for rid in ids:
        if rid not in records:
            continue
        for s in by_record.get(rid, []):
            studies.append({
                "study_id": s.id, "record_id": rid, "label": s.label,
                "n_studies": len(by_record[rid]),
                "title": records[rid].title, "year": records[rid].year,
                "design": s.study_design})
    return {"studies": studies, "records": [
        {"record_id": rid, "title": records[rid].title,
         "year": records[rid].year, "design": records[rid].study_design}
        for rid in ids if rid in records]}


def _clean_study_ids(db, project_id: int, study_ids: list[int],
                     record_ids: list[int]) -> list[int]:
    """Keep only studies of the included corpus, in the order given (study
    ids first, then the first study of each legacy record id). An outcome
    contributed to by an excluded record would make its certainty rating
    meaningless."""
    allowed = set(eligible_ids(db, project_id))
    out: list[int] = []
    if study_ids:
        rows = {s.id: s for s in db.query(ExtractionStudy)
                .filter(ExtractionStudy.id.in_(study_ids))}
        out += [sid for sid in dict.fromkeys(study_ids)
                if sid in rows and rows[sid].record_id in allowed]
    for rid in dict.fromkeys(record_ids):
        if rid in allowed:
            record = db.get(Record, rid)
            if record is not None:
                sid = ext_studies.ensure_default(db, record).id
                if sid not in out:
                    out.append(sid)
    return out


@router.post("/outcomes",
             dependencies=[Depends(require_project_admin), SatelliteGuard])
def create_outcome(project_id: int, payload: OutcomeIn, db: DbDep):
    get_project(project_id, db)
    if payload.synthesis_method not in methods.METHODS:
        raise HTTPException(status_code=400, detail="Unknown synthesis method")
    n = db.query(SynthesisOutcome).filter_by(project_id=project_id).count()
    outcome = SynthesisOutcome(
        project_id=project_id, label=payload.label,
        comparison=payload.comparison, intent=payload.intent,
        target=payload.target, thresholds_md=payload.thresholds_md,
        direction=payload.direction, metric=payload.metric,
        metric_rationale=payload.metric_rationale,
        synthesis_method=payload.synthesis_method,
        method_rationale=payload.method_rationale,
        study_ids=_clean_study_ids(db, project_id, payload.study_ids,
                                   payload.record_ids),
        finding_md=payload.finding_md,
        position=payload.position if payload.position is not None else n)
    db.add(outcome)
    db.commit()
    return core.outcome_dict(db, outcome)


@router.put("/outcomes/{outcome_id}",
            dependencies=[Depends(require_project_admin), SatelliteGuard])
def update_outcome(project_id: int, outcome_id: int, payload: OutcomeIn,
                   db: DbDep):
    get_project(project_id, db)
    outcome = _outcome(project_id, outcome_id, db)
    if payload.synthesis_method not in methods.METHODS:
        raise HTTPException(status_code=400, detail="Unknown synthesis method")
    for field in ("label", "comparison", "intent", "target", "thresholds_md",
                  "direction", "metric", "metric_rationale",
                  "synthesis_method", "method_rationale", "finding_md"):
        setattr(outcome, field, getattr(payload, field))
    outcome.study_ids = _clean_study_ids(db, project_id, payload.study_ids,
                                         payload.record_ids)
    if payload.position is not None:
        outcome.position = payload.position
    db.commit()
    return core.outcome_dict(db, outcome)


# ---- effect sizes (chantier 10) ----------------------------------------------------

class EffectSpecIn(BaseModel):
    measure: str = ""
    mapping: dict[str, int | None] = Field(default_factory=dict)


@router.get("/effects/measures")
def effect_measures(project_id: int, member: ProjectMemberDep, db: DbDep):
    """The measures LitUbik computes, their input roles, and the project's
    numeric columns a role can be mapped to."""
    get_project(project_id, db)
    from app.models import ExtractionColumn
    columns = (db.query(ExtractionColumn)
               .filter_by(project_id=project_id, col_type="number")
               .order_by(ExtractionColumn.position, ExtractionColumn.id).all())
    return {"measures": [{"key": k, "label": v["label"], "kind": v["kind"],
                          "roles": list(v["roles"]), "log_scale": v["log"]}
                         for k, v in effects.MEASURES.items()],
            "role_labels": effects.ROLE_LABELS,
            "columns": [{"id": c.id, "name": c.name} for c in columns]}


@router.put("/outcomes/{outcome_id}/effects",
            dependencies=[Depends(require_project_admin), SatelliteGuard])
def put_effect_spec(project_id: int, outcome_id: int, payload: EffectSpecIn,
                    db: DbDep):
    get_project(project_id, db)
    outcome = _outcome(project_id, outcome_id, db)
    try:
        outcome.effect_spec = effects.clean_spec(db, project_id, payload.model_dump())
    except effects.EffectError as e:
        raise HTTPException(status_code=400, detail=str(e))
    db.commit()
    return effects.compute(db, outcome)


@router.get("/outcomes/{outcome_id}/effects")
def get_effects(project_id: int, outcome_id: int, member: ProjectMemberDep,
                db: DbDep):
    """Per-study effect sizes (yi, vi, 95 % CI) of one outcome, with the
    studies whose inputs are missing listed as such. No pooling."""
    get_project(project_id, db)
    return effects.compute(db, _outcome(project_id, outcome_id, db))


def _csv_bytes(header: list[str], rows: list[list]) -> bytes:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(header)
    writer.writerows(safe_row(r) for r in rows)
    return buffer.getvalue().encode("utf-8-sig")


@router.get("/outcomes/{outcome_id}/export/metafor.zip")
def export_metafor(project_id: int, outcome_id: int, member: ProjectMemberDep,
                   db: DbDep):
    """data.csv (tidy, one row per study) + analysis.R (escalc check, rma,
    forest, funnel) for one outcome."""
    import zipfile
    get_project(project_id, db)
    result = effects.compute(db, _outcome(project_id, outcome_id, db))
    header, rows = effects.tidy_rows(result)
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("data.csv", _csv_bytes(header, rows).decode("utf-8-sig"))
        zf.writestr("analysis.R", effects.r_script(result))
    out.seek(0)
    return StreamingResponse(
        out, media_type="application/zip",
        headers={"Content-Disposition":
                 f'attachment; filename="metafor_outcome{outcome_id}.zip"'})


@router.get("/outcomes/{outcome_id}/export/revman.csv")
def export_revman(project_id: int, outcome_id: int, member: ProjectMemberDep,
                  db: DbDep):
    """RevMan Web study-results layout: one row per arm per study."""
    get_project(project_id, db)
    result = effects.compute(db, _outcome(project_id, outcome_id, db))
    header, rows = effects.revman_rows(result)
    return StreamingResponse(
        iter([_csv_bytes(header, rows)]), media_type="text/csv",
        headers={"Content-Disposition":
                 f'attachment; filename="revman_outcome{outcome_id}.csv"'})


@router.get("/export/effects.csv")
def export_all_effects(project_id: int, member: ProjectMemberDep, db: DbDep):
    """Every quantitative outcome of the project in one long CSV (the same
    columns as data.csv, stacked, raw inputs widened to every role)."""
    get_project(project_id, db)
    roles = list(effects.ROLE_LABELS)
    header = ["outcome_id", "outcome", "comparison", "measure", "study_id",
              "study_label", "record_id", "doi", "year", "design",
              *roles, "yi", "vi", "ci_low", "ci_high", "problems"]
    rows = []
    for outcome in core.outcomes_of(db, project_id):
        if not (outcome.effect_spec or {}).get("measure"):
            continue
        result = effects.compute(db, outcome)
        for s in result["studies"]:
            rows.append([result["outcome_id"], result["label"], result["comparison"],
                         result["measure"], s["study_id"], s["label"], s["record_id"],
                         s["doi"] or "", s["year"] or "", s["design"] or "",
                         *[("" if s["raw"].get(r) is None else s["raw"][r]) for r in roles],
                         s.get("yi", ""), s.get("vi", ""), s.get("ci_low", ""),
                         s.get("ci_high", ""), "; ".join(s["problems"])])
    return StreamingResponse(
        iter([_csv_bytes(header, rows)]), media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="effect_sizes.csv"'})


@router.delete("/outcomes/{outcome_id}",
               dependencies=[Depends(require_project_admin), SatelliteGuard])
def delete_outcome(project_id: int, outcome_id: int, db: DbDep):
    get_project(project_id, db)
    db.delete(_outcome(project_id, outcome_id, db))
    db.commit()
    return {"ok": True}


# ---- certainty --------------------------------------------------------------

class CertaintyIn(BaseModel):
    starting_point: str = Field(default="low", pattern="^(high|low)$")
    starting_rationale: str = ""
    # {domain: {judgement: none|serious|very_serious, note}}
    domains: dict = Field(default_factory=dict)
    # {domain: {applied: bool, note}}
    upgrades: dict = Field(default_factory=dict)
    final: str = Field(default="", pattern="^(high|moderate|low|very_low|)$")
    statement_md: str = ""
    is_consensus: bool = False


def _clean_domains(raw: dict) -> dict:
    out = {}
    for key, _, _ in grade.DOWNGRADE_DOMAINS:
        entry = (raw or {}).get(key) or {}
        judgement = str(entry.get("judgement", "none"))
        out[key] = {
            "judgement": judgement if judgement in grade.JUDGEMENTS else "none",
            "note": str(entry.get("note", ""))[:4000],
        }
    return out


def _clean_upgrades(raw: dict) -> dict:
    out = {}
    for key, _, _ in grade.UPGRADE_DOMAINS:
        entry = (raw or {}).get(key) or {}
        out[key] = {"applied": bool(entry.get("applied")),
                    "note": str(entry.get("note", ""))[:4000]}
    return out


def _assessment_out(row: CertaintyAssessment, names: dict[int, str]) -> dict:
    suggested = grade.suggest_final(row.starting_point, row.domains,
                                    row.upgrades)
    return {
        "id": row.id, "user_id": row.user_id,
        "user": names.get(row.user_id, "") if row.user_id else "",
        "is_consensus": row.is_consensus,
        "starting_point": row.starting_point,
        "starting_rationale": row.starting_rationale,
        "domains": row.domains or {}, "upgrades": row.upgrades or {},
        "final": row.final,
        "final_label": grade.LEVEL_LABELS.get(row.final, ""),
        # What the arithmetic would give. Shown beside the decision, never
        # substituted for it: GRADE expects two half-serious concerns in
        # different domains to be able to cost one level between them.
        "suggested_final": suggested,
        "suggested_label": grade.LEVEL_LABELS.get(suggested, ""),
        "diverges": bool(row.final) and row.final != suggested,
        "statement_md": row.statement_md,
        "updated_at": row.updated_at.isoformat() if row.updated_at else "",
    }


@router.get("/outcomes/{outcome_id}/certainty")
def get_certainty(project_id: int, outcome_id: int, member: ProjectMemberDep,
                  db: DbDep):
    """One outcome's certainty screen: every assessment, plus the evidence the
    app can put in front of the assessor for each GRADE domain."""
    project = get_project(project_id, db)
    outcome = _outcome(project_id, outcome_id, db)
    plan = core.plan_of(db, project_id)
    framework = core.certainty_framework(plan)
    names = {u.id: u.display_name for u in db.query(User)}
    rows = core.assessments_of(db, outcome.id)
    return {
        "outcome": core.outcome_dict(db, outcome),
        "framework": framework,
        "certainty_warning": core.certainty_warning(project, framework),
        "assessments": [_assessment_out(r, names) for r in rows],
        "mine": next((_assessment_out(r, names) for r in rows
                      if r.user_id == member.user_id and not r.is_consensus),
                     None),
        "consensus": next((_assessment_out(r, names) for r in rows
                           if r.is_consensus), None),
        # proposals, each with the reasoning that motivates it
        "suggestions": {
            "starting_point": core.suggest_starting_point(db, outcome),
            "risk_of_bias": core.risk_of_bias_evidence(db, project_id, outcome),
            "publication_bias": core.publication_bias_evidence(db, project_id),
        },
        "can_write_consensus": member.role == "admin",
    }


@router.put("/outcomes/{outcome_id}/certainty", dependencies=[SatelliteGuard])
def put_certainty(project_id: int, outcome_id: int, payload: CertaintyIn,
                  member: ProjectMemberDep, db: DbDep):
    get_project(project_id, db)
    outcome = _outcome(project_id, outcome_id, db)
    plan = core.plan_of(db, project_id)
    if core.certainty_framework(plan) == "none":
        raise HTTPException(
            status_code=400,
            detail="This project rates no certainty — pick a framework in the "
                   "synthesis plan first")
    if payload.is_consensus and member.role != "admin":
        raise HTTPException(status_code=403,
                            detail="Only a project admin records the agreed "
                                   "rating")
    query = db.query(CertaintyAssessment).filter_by(
        outcome_id=outcome.id, is_consensus=payload.is_consensus)
    row = (query.filter_by(user_id=None).first() if payload.is_consensus
           else query.filter_by(user_id=member.user_id).first())
    if row is None:
        row = CertaintyAssessment(
            outcome_id=outcome.id,
            user_id=None if payload.is_consensus else member.user_id,
            is_consensus=payload.is_consensus)
        db.add(row)
    row.starting_point = payload.starting_point
    row.starting_rationale = payload.starting_rationale
    row.domains = _clean_domains(payload.domains)
    row.upgrades = _clean_upgrades(payload.upgrades)
    row.final = payload.final
    row.statement_md = payload.statement_md
    if payload.is_consensus:
        row.resolved_by = member.user_id
    row.updated_at = utcnow()
    db.commit()
    names = {u.id: u.display_name for u in db.query(User)}
    return _assessment_out(row, names)


@router.get("/outcomes/{outcome_id}/statement")
def suggest_statement(project_id: int, outcome_id: int,
                      member: ProjectMemberDep, db: DbDep, final: str = ""):
    """The GRADE guideline-26 sentence for this outcome at a given level —
    a draft for the assessor to edit, returned on demand, never stored."""
    get_project(project_id, db)
    outcome = _outcome(project_id, outcome_id, db)
    level = final if final in grade.LEVELS else "low"
    return {"statement": core.suggest_statement(outcome, level)}


# ---- Summary of Findings ----------------------------------------------------

@router.get("/sof")
def summary_of_findings(project_id: int, member: ProjectMemberDep, db: DbDep):
    get_project(project_id, db)
    return sof.rows(db, project_id)


@router.get("/sof.csv")
def summary_of_findings_csv(project_id: int, member: ProjectMemberDep,
                            db: DbDep):
    get_project(project_id, db)
    header, body = sof.export_rows(db, project_id)
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(header)
    writer.writerows(safe_row(r) for r in body)
    return StreamingResponse(
        iter([buffer.getvalue().encode("utf-8-sig")]),
        media_type="text/csv",
        headers={"Content-Disposition":
                 'attachment; filename="summary_of_findings.csv"'})
