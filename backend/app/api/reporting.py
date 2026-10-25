# SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Reporting: the two write-ups a finished review owes its manuscript.

- the **Methods** section, drafted from the pipeline's audit trail;
- the **AI disclosure** statement, drafted from the project's AI-use journal
  through a DAISY-style form the author reviews first.

Both are project-level artifacts, so the endpoints sit behind SatelliteGuard
like the Results synthesis: a satellite holds a copy of the review, not the
authority to publish its reporting.
"""
import csv
import io
from datetime import datetime

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.api.deps import DbDep, ProjectMemberDep, SatelliteGuard, get_project
from app.core.csvsafe import safe_row
from app.models import (
    REPORT_KINDS, ChecklistAnswer, ProtocolDeviation, ReportSection,
    User,
)
from app.models.accounts import utcnow
from app.services.llm import pricing
from app.services.llm.base import LLMError
from app.services.reporting import (
    ai_audit, audit, checklists, deviations, generate as gen,
)

router = APIRouter(prefix="/api/projects/{project_id}/reporting",
                   tags=["reporting"], dependencies=[SatelliteGuard])


class GenerateIn(BaseModel):
    lang: str = Field(default="en", pattern="^(en|fr)$")
    # ai_disclosure only: the author's reviewed answers to the DAISY-style form
    form: dict | None = None


class EditIn(BaseModel):
    edited_md: str = ""


def _check_kind(kind: str) -> str:
    if kind not in REPORT_KINDS:
        raise HTTPException(status_code=404, detail="Unknown report section")
    return kind


def _section_out(db, row: ReportSection | None) -> dict | None:
    if row is None:
        return None
    author = db.get(User, row.generated_by) if row.generated_by else None
    return {
        "kind": row.kind,
        "lang": row.lang,
        "content_md": row.content_md,
        "edited_md": row.edited_md,
        "form": row.form or {},
        "cost": {**pricing.cost_breakdown(row.provider, row.model,
                                          row.tokens_in, row.tokens_out),
                 "estimated": False},
        "generated_by_name": author.display_name if author else "?",
        "created_at": row.created_at.isoformat() if row.created_at else "",
        "updated_at": row.updated_at.isoformat() if row.updated_at else "",
    }


@router.get("/sections")
def get_sections(project_id: int, member: ProjectMemberDep, db: DbDep):
    """Both stored write-ups (null when never generated)."""
    get_project(project_id, db)
    rows = {r.kind: r for r in db.query(ReportSection)
            .filter_by(project_id=project_id)}
    return {kind: _section_out(db, rows.get(kind)) for kind in REPORT_KINDS}


@router.get("/dossier")
def get_dossier(project_id: int, member: ProjectMemberDep, db: DbDep):
    """The audit trail the Methods paragraph is written from — shown in the UI
    so the author can check the facts before, not after, generating."""
    get_project(project_id, db)
    return audit.review_dossier(db, project_id)


@router.get("/ai-usage")
def get_ai_usage(project_id: int, member: ProjectMemberDep, db: DbDep):
    """The AI-use journal, the outcome evidence, and the pre-filled form."""
    get_project(project_id, db)
    return ai_audit.ai_dossier(db, project_id)


@router.get("/{kind}/estimate")
def estimate(project_id: int, kind: str, member: ProjectMemberDep, db: DbDep,
             lang: str = "en"):
    get_project(project_id, db)
    _check_kind(kind)
    return {"cost": gen.estimate_cost(db, project_id, kind,
                                      lang if lang in ("en", "fr") else "en")}


@router.post("/{kind}/generate")
def generate_section(project_id: int, kind: str, payload: GenerateIn,
                     member: ProjectMemberDep, db: DbDep):
    """(Re)generate a write-up — any member, like the other on-demand AI
    buttons. The author's edited version is left untouched."""
    get_project(project_id, db)
    _check_kind(kind)
    try:
        row = gen.generate(db, project_id, kind, user_id=member.user_id,
                           lang=payload.lang, form=payload.form)
    except LLMError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return _section_out(db, row)


@router.put("/{kind}")
def save_edit(project_id: int, kind: str, payload: EditIn,
              member: ProjectMemberDep, db: DbDep):
    """Store the author's edited version of a write-up."""
    get_project(project_id, db)
    _check_kind(kind)
    row = gen.save_edit(db, project_id, kind, payload.edited_md)
    return _section_out(db, row)


# ---- protocol deviations (PRISMA 24c, SWiM 1b) -------------------------------

class DeviationIn(BaseModel):
    stage: str = Field(default="protocol", max_length=20)
    summary: str = Field(default="", max_length=4000)
    rationale: str = Field(default="", max_length=4000)
    # set when the row answers a detected signal; "" for a purely declared one
    signal: str = Field(default="", max_length=120)
    occurred_at: datetime | None = None


class DismissIn(BaseModel):
    signal: str = Field(min_length=1, max_length=120)
    summary: str = Field(default="", max_length=4000)
    note: str = Field(default="", max_length=4000)
    occurred_at: datetime | None = None


@router.get("/deviations")
def list_deviations(project_id: int, member: ProjectMemberDep, db: DbDep):
    """What the tables suggest changed mid-review, and what the team declared.

    A signal is a question, never a verdict: amending a protocol is legitimate,
    and only the team has the reason a reader needs.
    """
    get_project(project_id, db)
    return deviations.register(db, project_id)


@router.post("/deviations")
def declare_deviation(project_id: int, payload: DeviationIn,
                      member: ProjectMemberDep, db: DbDep):
    get_project(project_id, db)
    if payload.stage not in deviations.STAGES:
        raise HTTPException(status_code=400, detail="Unknown stage")
    row = ProtocolDeviation(
        project_id=project_id, stage=payload.stage,
        kind="detected" if payload.signal else "declared",
        signal=payload.signal or None, summary=payload.summary,
        rationale=payload.rationale, occurred_at=payload.occurred_at,
        declared_by=member.user_id)
    db.add(row)
    db.commit()
    return deviations.register(db, project_id)


@router.post("/deviations/dismiss")
def dismiss_signal(project_id: int, payload: DismissIn,
                   member: ProjectMemberDep, db: DbDep):
    """"We looked at this and it was not a deviation" — recorded rather than
    forgotten, so the same signal is not re-litigated at the next reading."""
    get_project(project_id, db)
    row = ProtocolDeviation(
        project_id=project_id, stage="protocol", kind="detected",
        signal=payload.signal, summary=payload.summary,
        occurred_at=payload.occurred_at, declared_by=member.user_id,
        dismissed_at=utcnow(), dismiss_note=payload.note)
    db.add(row)
    db.commit()
    return deviations.register(db, project_id)


@router.put("/deviations/{deviation_id}")
def update_deviation(project_id: int, deviation_id: int, payload: DeviationIn,
                     member: ProjectMemberDep, db: DbDep):
    get_project(project_id, db)
    row = db.get(ProtocolDeviation, deviation_id)
    if row is None or row.project_id != project_id:
        raise HTTPException(status_code=404, detail="Deviation not found")
    if payload.stage not in deviations.STAGES:
        raise HTTPException(status_code=400, detail="Unknown stage")
    row.stage = payload.stage
    row.summary = payload.summary
    row.rationale = payload.rationale
    if payload.occurred_at is not None:
        row.occurred_at = payload.occurred_at
    db.commit()
    return deviations.register(db, project_id)


@router.delete("/deviations/{deviation_id}")
def delete_deviation(project_id: int, deviation_id: int,
                     member: ProjectMemberDep, db: DbDep):
    get_project(project_id, db)
    row = db.get(ProtocolDeviation, deviation_id)
    if row is None or row.project_id != project_id:
        raise HTTPException(status_code=404, detail="Deviation not found")
    db.delete(row)
    db.commit()
    return deviations.register(db, project_id)


# ---- reporting checklists (PRISMA 2020, SWiM) + triage triggers ---------------

class ChecklistAnswerIn(BaseModel):
    checklist: str = Field(pattern="^(prisma2020|swim)$")
    item: str = Field(min_length=1, max_length=10)
    page_ref: str = Field(default="", max_length=120)
    note: str = Field(default="", max_length=4000)
    status_override: str = Field(default="",
                                 pattern="^(evidenced|author|not_done|n_a|)$")


@router.get("/checklists")
def get_checklists(project_id: int, member: ProjectMemberDep, db: DbDep):
    """The reporting checklists, each item resolved against what the pipeline
    recorded, plus the problems editorial triage looks for.

    Nothing here judges the review: an item says what happened, and where
    nothing happened it says that — which is the difference between a filled
    checklist and a claimed one.
    """
    get_project(project_id, db)
    return checklists.report(db, project_id)


@router.put("/checklists/answer")
def put_checklist_answer(project_id: int, payload: ChecklistAnswerIn,
                         member: ProjectMemberDep, db: DbDep):
    get_project(project_id, db)
    row = (db.query(ChecklistAnswer)
           .filter_by(project_id=project_id, checklist=payload.checklist,
                      item=payload.item).first())
    if row is None:
        row = ChecklistAnswer(project_id=project_id,
                              checklist=payload.checklist, item=payload.item)
        db.add(row)
    row.page_ref = payload.page_ref
    row.note = payload.note
    row.status_override = payload.status_override
    db.commit()
    return checklists.report(db, project_id)


@router.get("/checklists/{checklist}.csv")
def export_checklist(project_id: int, checklist: str,
                     member: ProjectMemberDep, db: DbDep):
    """The filled checklist as the supplementary file journals ask for."""
    get_project(project_id, db)
    try:
        header, rows = checklists.export_rows(db, project_id, checklist)
    except KeyError:
        raise HTTPException(status_code=404,
                            detail="This checklist does not apply to this review")
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(header)
    writer.writerows(safe_row(r) for r in rows)
    return StreamingResponse(
        iter([buffer.getvalue().encode("utf-8-sig")]),
        media_type="text/csv",
        headers={"Content-Disposition":
                 f'attachment; filename="{checklist}_checklist.csv"'})
