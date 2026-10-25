# SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Thematic map of the corpus (roadmap chantier 11): run a clustering in the
background, read the latest run (points + clusters), label clusters by hand
or with the AI, export the assignment as CSV."""
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.api.deps import DbDep, ProjectMemberDep, SatelliteGuard, get_project
from app.models import CorpusTopicRun, Record, User
from app.services.llm.base import LLMError
from app.services.topics import service
from app.services.topics.engine import MIN_DOCS
from app.workers.runner import runner

router = APIRouter(prefix="/api/projects/{project_id}/topics", tags=["topics"],
                   dependencies=[SatelliteGuard])


class RunIn(BaseModel):
    scope: str = Field(default="unique", pattern="^(unique|ta_included|ft_included)$")
    k: int | None = Field(default=None, ge=2, le=30)


class LabelIn(BaseModel):
    label: str = Field(max_length=80)


def _run(db, project_id: int, run_id: int) -> CorpusTopicRun:
    run = db.get(CorpusTopicRun, run_id)
    if run is None or run.project_id != project_id:
        raise HTTPException(status_code=404, detail="Run not found")
    return run


def _run_out(db, run: CorpusTopicRun) -> dict:
    ids = [int(p["record_id"]) for p in run.result.get("points", [])]
    rows = (db.query(Record.id, Record.title, Record.year, Record.authors)
            .filter(Record.id.in_(ids)).all()) if ids else []
    meta = {rid: {"title": title, "year": year,
                  "author": (authors or ["?"])[0] if authors else "?"}
            for rid, title, year, authors in rows}
    author = db.get(User, run.created_by) if run.created_by else None
    points = [{**p, **meta.get(int(p["record_id"]),
                               {"title": "?", "year": None, "author": "?"})}
              for p in run.result.get("points", [])
              if int(p["record_id"]) in meta]
    return {**service.run_summary(run), "points": points,
            "clusters": run.result.get("clusters", []),
            "created_by_name": author.display_name if author else "?"}


@router.get("")
def latest(project_id: int, member: ProjectMemberDep, db: DbDep,
           run_id: int | None = None):
    """The requested (or latest) run with its points, plus a short history
    and the corpus sizes per scope (for the run form)."""
    get_project(project_id, db)
    runs = (db.query(CorpusTopicRun).filter_by(project_id=project_id)
            .order_by(CorpusTopicRun.id.desc()).limit(10).all())
    run = next((r for r in runs if r.id == run_id), None) if run_id else (
        runs[0] if runs else None)
    sizes = {scope: len(service.corpus_for_scope(db, project_id, scope)[0])
             for scope in service.SCOPES}
    return {"run": _run_out(db, run) if run else None,
            "history": [service.run_summary(r) for r in runs],
            "sizes": sizes, "min_docs": MIN_DOCS}


@router.post("/run")
def start_run(project_id: int, payload: RunIn, member: ProjectMemberDep, db: DbDep):
    get_project(project_id, db)
    n = len(service.corpus_for_scope(db, project_id, payload.scope)[0])
    if n < MIN_DOCS:
        raise HTTPException(status_code=400,
                            detail=f"At least {MIN_DOCS} records are needed in this "
                                   f"scope to map themes ({n} now)")
    job = runner.submit("corpus_topics", {
        "project_id": project_id, "scope": payload.scope, "k": payload.k,
        "user_id": member.user_id,
    }, project_id=project_id, user_id=member.user_id)
    return {"job_id": job.id}


@router.get("/{run_id}/label-estimate")
def label_estimate(project_id: int, run_id: int, member: ProjectMemberDep, db: DbDep):
    run = _run(db, project_id, run_id)
    return {"cost": service.estimate_label_cost(db, run)}


@router.post("/{run_id}/label")
def label_with_ai(project_id: int, run_id: int, member: ProjectMemberDep, db: DbDep):
    run = _run(db, project_id, run_id)
    try:
        cost = service.label_clusters(db, run, member.user_id)
    except LLMError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"clusters": run.result.get("clusters", []), "cost": cost}


@router.put("/{run_id}/clusters/{cluster_id}")
def rename_cluster(project_id: int, run_id: int, cluster_id: int, payload: LabelIn,
                   member: ProjectMemberDep, db: DbDep):
    run = _run(db, project_id, run_id)
    try:
        service.set_label(db, run, cluster_id, payload.label)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {"clusters": run.result.get("clusters", [])}


@router.delete("/{run_id}")
def delete_run(project_id: int, run_id: int, member: ProjectMemberDep, db: DbDep):
    run = _run(db, project_id, run_id)
    db.delete(run)
    db.commit()
    return {"ok": True}


@router.get("/{run_id}/export.csv")
def export_csv(project_id: int, run_id: int, member: ProjectMemberDep, db: DbDep):
    run = _run(db, project_id, run_id)
    data = service.export_csv(db, run).encode("utf-8-sig")
    return StreamingResponse(
        iter([data]), media_type="text/csv",
        headers={"Content-Disposition":
                 f'attachment; filename="themes_run{run.id}.csv"'})
