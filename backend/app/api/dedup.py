# SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
# SPDX-License-Identifier: AGPL-3.0-or-later
"""M4: deduplication — run, live summary, manual arbitration of uncertain pairs."""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.api.deps import (
    DbDep, ProjectMemberDep, SatelliteGuard, get_project,
    require_project_admin,
)
from app.models import DedupPair, Import, Record, Source
from app.services.dedup import dedup_summary, merge_into
from app.services.translation import valid_translations
from app.workers.runner import runner

router = APIRouter(prefix="/api/projects/{project_id}/dedup", tags=["dedup"],
                   dependencies=[SatelliteGuard])


class RecordSide(BaseModel):
    id: int
    doi: str | None
    title: str
    authors: list
    year: int | None
    journal: str
    abstract: str
    sources: list[str]
    # cached AI translations of the FULL title/abstract, per language
    translations: dict = {}


class PairOut(BaseModel):
    id: int
    score: float
    reason: str
    record: RecordSide
    canonical: RecordSide


class ResolveIn(BaseModel):
    decision: str = Field(pattern="^(merge|distinct)$")


def _sources_of(db, record: Record) -> list[str]:
    """Source names that found this record (its own import + its duplicates')."""
    dup_ids = [rid for (rid,) in
               db.query(Record.id).filter_by(canonical_id=record.id)]
    rows = (db.query(Source.name)
            .join(Import, Import.source_id == Source.id)
            .join(Record, Record.import_id == Import.id)
            .filter(Record.id.in_([record.id] + dup_ids))
            .distinct().all())
    return sorted(name for (name,) in rows)


def _side(db, record: Record) -> RecordSide:
    return RecordSide(
        id=record.id, doi=record.doi, title=record.title, authors=record.authors,
        year=record.year, journal=record.journal,
        abstract=(record.abstract[:600] + "…") if len(record.abstract) > 600
                 else record.abstract,
        sources=_sources_of(db, record),
        translations=valid_translations(record),
    )


@router.post("/run", dependencies=[Depends(require_project_admin)])
def run(project_id: int, member: ProjectMemberDep, db: DbDep):
    """Launch deduplication over the whole project (safe to re-run anytime)."""
    get_project(project_id, db)
    job = runner.submit("dedup_run", {"project_id": project_id},
                        project_id=project_id, user_id=member.user_id)
    return {"job_id": job.id}


@router.get("/summary")
def summary(project_id: int, member: ProjectMemberDep, db: DbDep):
    get_project(project_id, db)
    return dedup_summary(db, project_id)


@router.get("/pairs", response_model=list[PairOut])
def pending_pairs(project_id: int, member: ProjectMemberDep, db: DbDep,
                  limit: int = 50):
    get_project(project_id, db)
    pairs = (db.query(DedupPair)
             .filter_by(project_id=project_id, status="pending")
             .order_by(DedupPair.score.desc())
             .limit(min(max(limit, 1), 200)).all())
    out = []
    for pair in pairs:
        record = db.get(Record, pair.record_id)
        canonical = db.get(Record, pair.canonical_id)
        if record is None or canonical is None:
            continue
        out.append(PairOut(id=pair.id, score=pair.score, reason=pair.reason,
                           record=_side(db, record), canonical=_side(db, canonical)))
    return out


class MergedOut(BaseModel):
    pair_id: int | None
    reason: str
    score: float | None
    manual: bool
    duplicate: RecordSide
    canonical: RecordSide


@router.get("/duplicates", response_model=list[MergedOut])
def merged_duplicates(project_id: int, member: ProjectMemberDep, db: DbDep,
                      limit: int = 200):
    """Every merge performed (automatic passes and manual arbitrations)."""
    get_project(project_id, db)
    duplicates = (db.query(Record)
                  .filter_by(project_id=project_id, dedup_status="duplicate")
                  .order_by(Record.id.desc())
                  .limit(min(max(limit, 1), 500)).all())
    pairs = {p.record_id: p for p in
             db.query(DedupPair).filter_by(project_id=project_id, status="merged")}
    out = []
    for record in duplicates:
        canonical = db.get(Record, record.canonical_id) if record.canonical_id else None
        if canonical is None:
            continue
        pair = pairs.get(record.id)
        out.append(MergedOut(
            pair_id=pair.id if pair else None,
            reason=pair.reason if pair else "auto",
            score=pair.score if pair else None,
            manual=bool(pair and pair.resolved_by is not None),
            duplicate=_side(db, record), canonical=_side(db, canonical)))
    return out


@router.post("/pairs/{pair_id}/resolve",
             dependencies=[Depends(require_project_admin)])
def resolve_pair(project_id: int, pair_id: int, payload: ResolveIn,
                 member: ProjectMemberDep, db: DbDep):
    """Manual arbitration: merge (same article) or distinct (keep both)."""
    pair = db.get(DedupPair, pair_id)
    if pair is None or pair.project_id != project_id:
        raise HTTPException(status_code=404, detail="Pair not found")
    if pair.status != "pending":
        raise HTTPException(status_code=400, detail="Pair already resolved")
    record = db.get(Record, pair.record_id)
    canonical = db.get(Record, pair.canonical_id)
    if record is None or canonical is None:
        raise HTTPException(status_code=404, detail="Record vanished")

    if payload.decision == "merge":
        merge_into(db, record, canonical)
        pair.status = "merged"
    else:
        record.dedup_status = "unique"
        record.canonical_id = None
        pair.status = "distinct"
    pair.resolved_by = member.user_id
    pair.resolved_at = datetime.now(timezone.utc)
    db.commit()
    return {"ok": True, "remaining": db.query(DedupPair)
            .filter_by(project_id=project_id, status="pending").count()}
