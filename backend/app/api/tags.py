# SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tags on papers (tickets #16/#T13): per-project label list + attachments.

Tags are orthogonal to screening — attaching one never changes a vote or a
PRISMA number. The canonical use case is keeping papers around even when
excluded ("Intro/Discussion"); the list view + CSV export make that shelf
usable for the manuscript.
"""
import csv
import io

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import func

from app.api.deps import DbDep, ProjectMemberDep, get_project
from app.core.csvsafe import safe_row
from app.models import Record, RecordTag, ScreeningConfig, Tag
from app.services.screening import screening_outcomes

# NOT satellite-locked: tags are collaborative labels every reviewer applies
# during screening; a reviewer's attachments travel back to the coordinator in
# their contribution packages (replace-by-author, see services/sync).
router = APIRouter(prefix="/api/projects/{project_id}/tags", tags=["tags"])


class TagIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)


def _tag_out(tag: Tag, n_records: int) -> dict:
    return {"id": tag.id, "name": tag.name, "n_records": n_records}


def _counts(db, project_id: int) -> dict[int, int]:
    return dict(db.query(RecordTag.tag_id, func.count(RecordTag.id))
                .join(Tag, Tag.id == RecordTag.tag_id)
                .filter(Tag.project_id == project_id)
                .group_by(RecordTag.tag_id).all())


def _get_tag(db, project_id: int, tag_id: int) -> Tag:
    tag = db.get(Tag, tag_id)
    if tag is None or tag.project_id != project_id:
        raise HTTPException(status_code=404, detail="Tag not found")
    return tag


def _get_or_create(db, project_id: int, name: str, user_id: int) -> Tag:
    name = name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Empty tag name")
    tag = (db.query(Tag).filter(Tag.project_id == project_id,
                                func.lower(Tag.name) == name.lower()).first())
    if tag is None:
        tag = Tag(project_id=project_id, name=name, created_by=user_id)
        db.add(tag)
        db.flush()
    return tag


def _screening_status(db, project_id: int) -> dict[int, str]:
    """Best-known pipeline standing per record, so the tag list can show that
    a shelved paper was excluded (the whole point of the shelf)."""
    status: dict[int, str] = {}
    for config in (db.query(ScreeningConfig)
                   .filter_by(project_id=project_id, status="active")
                   .order_by(ScreeningConfig.stage, ScreeningConfig.round)):
        for rid, decision in screening_outcomes(db, config).items():
            if config.stage == "ta":
                status[rid] = ("excluded (title/abstract)"
                               if decision == "exclude" else "full text")
            else:
                status[rid] = ("excluded (full text)"
                               if decision == "exclude" else "included")
    return status


# ---- tag list ------------------------------------------------------------------


@router.get("")
def list_tags(project_id: int, member: ProjectMemberDep, db: DbDep):
    get_project(project_id, db)
    counts = _counts(db, project_id)
    tags = (db.query(Tag).filter_by(project_id=project_id)
            .order_by(func.lower(Tag.name)).all())
    return [_tag_out(t, counts.get(t.id, 0)) for t in tags]


@router.post("")
def create_tag(project_id: int, payload: TagIn, member: ProjectMemberDep,
               db: DbDep):
    get_project(project_id, db)
    tag = _get_or_create(db, project_id, payload.name, member.user_id)
    db.commit()
    return _tag_out(tag, _counts(db, project_id).get(tag.id, 0))


@router.put("/{tag_id}")
def rename_tag(project_id: int, tag_id: int, payload: TagIn,
               member: ProjectMemberDep, db: DbDep):
    tag = _get_tag(db, project_id, tag_id)
    name = payload.name.strip()
    clash = (db.query(Tag)
             .filter(Tag.project_id == project_id, Tag.id != tag_id,
                     func.lower(Tag.name) == name.lower()).first())
    if clash is not None:
        raise HTTPException(status_code=409,
                            detail=f"A tag named “{clash.name}” already exists")
    tag.name = name
    db.commit()
    return _tag_out(tag, _counts(db, project_id).get(tag.id, 0))


@router.delete("/{tag_id}")
def delete_tag(project_id: int, tag_id: int, member: ProjectMemberDep,
               db: DbDep):
    tag = _get_tag(db, project_id, tag_id)
    db.query(RecordTag).filter_by(tag_id=tag.id).delete()
    db.delete(tag)
    db.commit()
    return {"ok": True}


# ---- attachments ---------------------------------------------------------------


@router.get("/records/{record_id}")
def record_tags(project_id: int, record_id: int, member: ProjectMemberDep,
                db: DbDep):
    rows = (db.query(Tag)
            .join(RecordTag, RecordTag.tag_id == Tag.id)
            .filter(Tag.project_id == project_id,
                    RecordTag.record_id == record_id)
            .order_by(func.lower(Tag.name)).all())
    return [{"id": t.id, "name": t.name} for t in rows]


@router.post("/records/{record_id}")
def attach_tag(project_id: int, record_id: int, payload: TagIn,
               member: ProjectMemberDep, db: DbDep):
    """Attach by name — creates the tag on the fly ("+ new tag" UX)."""
    record = db.get(Record, record_id)
    if record is None or record.project_id != project_id:
        raise HTTPException(status_code=404, detail="Record not found")
    tag = _get_or_create(db, project_id, payload.name, member.user_id)
    exists = (db.query(RecordTag)
              .filter_by(tag_id=tag.id, record_id=record_id).first())
    if exists is None:
        db.add(RecordTag(tag_id=tag.id, record_id=record_id,
                         created_by=member.user_id))
    db.commit()
    return record_tags(project_id, record_id, member, db)


@router.delete("/records/{record_id}/{tag_id}")
def detach_tag(project_id: int, record_id: int, tag_id: int,
               member: ProjectMemberDep, db: DbDep):
    tag = _get_tag(db, project_id, tag_id)
    (db.query(RecordTag).filter_by(tag_id=tag.id, record_id=record_id)
     .delete())
    db.commit()
    return record_tags(project_id, record_id, member, db)


# ---- tagged-papers list + export -------------------------------------------------


def _tagged_rows(db, project_id: int, tag_id: int | None) -> list[dict]:
    query = (db.query(Record, Tag)
             .join(RecordTag, RecordTag.record_id == Record.id)
             .join(Tag, Tag.id == RecordTag.tag_id)
             .filter(Tag.project_id == project_id))
    if tag_id is not None:
        query = query.filter(Tag.id == tag_id)
    by_record: dict[int, dict] = {}
    for record, tag in query.all():
        row = by_record.setdefault(record.id, {
            "record_id": record.id, "title": record.title,
            "authors": record.authors or [], "year": record.year,
            "journal": record.journal, "doi": record.doi, "tags": [],
        })
        row["tags"].append(tag.name)
    status = _screening_status(db, project_id)
    rows = list(by_record.values())
    for row in rows:
        row["tags"].sort(key=str.lower)
        row["status"] = status.get(row["record_id"], "not screened yet")
    rows.sort(key=lambda r: ((r["year"] or 0) * -1, r["title"].lower()))
    return rows


@router.get("/records")
def tagged_records(project_id: int, member: ProjectMemberDep, db: DbDep,
                   tag_id: int | None = None):
    get_project(project_id, db)
    return _tagged_rows(db, project_id, tag_id)


@router.get("/records.csv")
def tagged_records_csv(project_id: int, member: ProjectMemberDep, db: DbDep,
                       tag_id: int | None = None):
    get_project(project_id, db)
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(["Tags", "Title", "Authors", "Year", "Journal", "DOI",
                     "Screening status"])
    for row in _tagged_rows(db, project_id, tag_id):
        writer.writerow(safe_row([
            "; ".join(row["tags"]), row["title"],
            "; ".join(row["authors"]), row["year"] or "",
            row["journal"], row["doi"] or "", row["status"]]))
    return StreamingResponse(
        iter([buffer.getvalue().encode("utf-8-sig")]),
        media_type="text/csv",
        headers={"Content-Disposition":
                 'attachment; filename="tagged_papers.csv"'})
