# SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
# SPDX-License-Identifier: AGPL-3.0-or-later
"""M7: shared PDF annotations (highlights + notes) on a record's stored full text.

Any project member can annotate; every member sees every annotation (they are a
shared artifact for conflict resolution and extraction) — except while the
record's full-text screening is still open, when a reviewer sees only their
own (blind). The author is a pseudonym while the round keeps its reviewers
anonymous. A reviewer may delete their own; a project admin may delete any."""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.api.deps import DbDep, ProjectMemberDep, get_project
from app.models import Assignment, PdfAnnotation, Record, ScreeningConfig
from app.services.screening.anonymity import Namer, project_namer
from app.services.screening.core import record_outcome

router = APIRouter(
    prefix="/api/projects/{project_id}/records/{record_id}/annotations",
    tags=["annotations"])


class Rect(BaseModel):
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)
    w: float = Field(ge=0, le=1)
    h: float = Field(ge=0, le=1)


class AnnotationIn(BaseModel):
    page: int = Field(ge=1)
    rects: list[Rect] = Field(min_length=1)
    quote: str = Field(default="", max_length=5000)
    note: str = Field(default="", max_length=5000)
    color: str = Field(default="yellow", max_length=20)


class AnnotationOut(BaseModel):
    id: int
    record_id: int
    page: int
    rects: list
    quote: str
    note: str
    color: str
    author: str
    author_id: int | None
    created_at: str
    mine: bool


def _out(a: PdfAnnotation, names: Namer, me: int) -> AnnotationOut:
    return AnnotationOut(
        id=a.id, record_id=a.record_id, page=a.page, rects=a.rects or [],
        quote=a.quote, note=a.note, color=a.color,
        author=names(a.user_id),
        author_id=None if names.hidden else a.user_id,
        created_at=a.created_at.isoformat() if a.created_at else "",
        mine=a.user_id == me)


def _record(project_id: int, record_id: int, db) -> Record:
    record = db.get(Record, record_id)
    if record is None or record.project_id != project_id:
        raise HTTPException(status_code=404, detail="Record not found")
    return record


@router.get("", response_model=list[AnnotationOut])
def list_annotations(project_id: int, record_id: int,
                     member: ProjectMemberDep, db: DbDep):
    get_project(project_id, db)
    _record(project_id, record_id, db)
    rows = (db.query(PdfAnnotation)
            .filter_by(record_id=record_id)
            .order_by(PdfAnnotation.page, PdfAnnotation.id).all())
    if _screening_open(db, project_id, record_id):
        rows = [a for a in rows if a.user_id == member.user_id]
    names = project_namer(db, project_id)
    return [_out(a, names, member.user_id) for a in rows]


def _screening_open(db, project_id: int, record_id: int) -> bool:
    """True while an active full-text round has this record assigned and
    not yet complete — the blind window."""
    for config in (db.query(ScreeningConfig)
                   .filter_by(project_id=project_id, stage="ft",
                              status="active")):
        if not (db.query(Assignment)
                .filter_by(config_id=config.id, record_id=record_id).count()):
            continue
        if record_outcome(db, config, record_id) is None:
            return True
    return False


@router.post("", response_model=AnnotationOut)
def create_annotation(project_id: int, record_id: int, payload: AnnotationIn,
                      member: ProjectMemberDep, db: DbDep):
    get_project(project_id, db)
    _record(project_id, record_id, db)
    annotation = PdfAnnotation(
        project_id=project_id, record_id=record_id, user_id=member.user_id,
        page=payload.page, rects=[r.model_dump() for r in payload.rects],
        quote=payload.quote, note=payload.note, color=payload.color)
    db.add(annotation)
    db.commit()
    db.refresh(annotation)
    return _out(annotation, project_namer(db, project_id), member.user_id)


@router.delete("/{annotation_id}")
def delete_annotation(project_id: int, record_id: int, annotation_id: int,
                      member: ProjectMemberDep, db: DbDep):
    get_project(project_id, db)
    _record(project_id, record_id, db)  # the record must belong to this project
    annotation = db.get(PdfAnnotation, annotation_id)
    if annotation is None or annotation.record_id != record_id:
        raise HTTPException(status_code=404, detail="Annotation not found")
    if annotation.user_id != member.user_id and member.role != "admin":
        raise HTTPException(status_code=403,
                            detail="Only the author or a project admin can delete this")
    db.delete(annotation)
    db.commit()
    return {"ok": True}
