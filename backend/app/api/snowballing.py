# SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
# SPDX-License-Identifier: AGPL-3.0-or-later
"""M8: snowballing — iterations, citation graph, saturation status."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func

from app.api.deps import (
    DbDep, ProjectMemberDep, SatelliteGuard, get_project,
    require_project_admin,
)
from app.models import Record, SnowballRun, Source
from app.services.snowballing.service import (
    delete_iteration_round, graph_data, manual_add, pending_seed_ids,
    seed_contributions, snowball_status,
)
from app.workers.runner import runner

router = APIRouter(prefix="/api/projects/{project_id}/snowballing",
                   tags=["snowballing"], dependencies=[SatelliteGuard])


class RunIn(BaseModel):
    # empty = every FT-included record not crawled yet
    record_ids: list[int] = []
    cap: int = Field(default=5000, ge=10, le=20000)


@router.get("/status")
def status(project_id: int, member: ProjectMemberDep, db: DbDep):
    get_project(project_id, db)
    return snowball_status(db, project_id)


@router.get("/seeds")
def seeds(project_id: int, member: ProjectMemberDep, db: DbDep):
    """The records the next iteration would crawl (FT includes not yet done)."""
    get_project(project_id, db)
    ids = pending_seed_ids(db, project_id)
    records = (db.query(Record).filter(Record.id.in_(ids))
               .order_by(Record.id).all()) if ids else []
    return [{"id": r.id, "title": r.title, "doi": r.doi, "year": r.year,
             "authors": r.authors} for r in records]


@router.post("/run", dependencies=[Depends(require_project_admin)])
def run(project_id: int, payload: RunIn, member: ProjectMemberDep, db: DbDep):
    get_project(project_id, db)
    seed_ids = payload.record_ids or pending_seed_ids(db, project_id)
    if not seed_ids:
        raise HTTPException(
            status_code=400,
            detail="No new full-text-included article to snowball — finish "
                   "full-text screening first (or every include was already "
                   "crawled: saturation)")
    job = runner.submit("snowball_run",
                        {"project_id": project_id, "record_ids": payload.record_ids,
                         "cap": payload.cap, "user_id": member.user_id},
                        project_id=project_id, user_id=member.user_id)
    return {"job_id": job.id, "n_seeds": len(seed_ids)}


@router.delete("/iterations/{round}",
               dependencies=[Depends(require_project_admin)])
def delete_iteration(project_id: int, round: int, member: ProjectMemberDep,
                     db: DbDep):
    """Undo the latest snowballing iteration completely: delete the papers it
    found, their screening, its citation edges and the run row — as if the
    round never ran. Only the most recent iteration is removable (later rounds
    build on earlier ones)."""
    get_project(project_id, db)
    if (db.query(SnowballRun.id)
            .filter_by(project_id=project_id).first()) is None:
        raise HTTPException(status_code=404,
                            detail="No snowballing iteration to delete")
    # the latest round of the project, whatever created it: a search-update
    # pass after this iteration would be orphaned (its duplicates point here)
    latest = (db.query(func.max(Source.round))
              .filter(Source.project_id == project_id).scalar())
    if round != latest:
        raise HTTPException(
            status_code=409,
            detail="Only the latest round can be deleted — if a later search "
                   "update exists, delete it first on the Search page")
    if (db.query(SnowballRun.id)
            .filter_by(project_id=project_id, round=round).first()) is None:
        raise HTTPException(status_code=404,
                            detail="This round is not a snowballing iteration")
    delete_iteration_round(db, project_id, round)
    return {"ok": True, "round": round}


class ManualAddIn(BaseModel):
    seed_record_id: int
    direction: str = Field(pattern="^(backward|forward)$")
    dois: list[str] = Field(min_length=1, max_length=50)


@router.post("/manual", dependencies=[Depends(require_project_admin)])
def add_manual(project_id: int, payload: ManualAddIn, member: ProjectMemberDep,
               db: DbDep):
    """Manually add missed backward/forward articles to a crawled seed
    (metadata hydrated from OpenAlex, deduped, edges added, screening synced)."""
    get_project(project_id, db)
    try:
        return manual_add(db, project_id, payload.seed_record_id,
                          payload.direction, payload.dois, member.user_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/graph")
def graph(project_id: int, member: ProjectMemberDep, db: DbDep,
          included_only: bool = False):
    get_project(project_id, db)
    return graph_data(db, project_id, included_only=included_only)


@router.get("/contributions")
def contributions(project_id: int, member: ProjectMemberDep, db: DbDep):
    """Per-seed detail: how many backward/forward papers each crawled seed
    contributed to the citation graph."""
    get_project(project_id, db)
    return seed_contributions(db, project_id)


@router.post("/enrich-abstracts", dependencies=[Depends(require_project_admin)])
def enrich_abstracts(project_id: int, member: ProjectMemberDep, db: DbDep):
    """Backfill missing abstracts (records with a DOI and no abstract) from
    OpenAlex, Semantic Scholar, PubMed, then the publisher landing pages —
    snowballing rounds need them for T/A screening."""
    get_project(project_id, db)
    job = runner.submit("abstract_enrich", {"project_id": project_id},
                        project_id=project_id, user_id=member.user_id)
    return {"job_id": job.id}
