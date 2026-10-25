# SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Living review (roadmap chantier 5): the update plan, manual passes, the
history of passes. Structural (new rounds), so coordinator-only."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.api.deps import (
    DbDep, NoSandbox, ProjectMemberDep, SatelliteGuard, get_project,
    require_project_admin,
)
from app.models import Equation, Job
from app.models.living import UPDATE_INTERVALS
from app.services.connectors.fetch import FETCHERS, KEYED_FETCHERS
from app.services.living.service import (
    delete_update_round, get_plan, plan_out, runs_out, upsert_plan,
)
from app.workers.runner import runner

router = APIRouter(prefix="/api/projects/{project_id}/search",
                   tags=["living-review"], dependencies=[SatelliteGuard])


class PlanIn(BaseModel):
    enabled: bool = False
    interval_days: int = 30
    databases: list[str] = Field(default_factory=list, max_length=30)
    equation_id: int | None = None


class RunIn(BaseModel):
    databases: list[str] = Field(default_factory=list, max_length=30)
    equation_id: int | None = None
    cap: int = Field(default=5000, ge=1, le=20000)


def _check_databases(databases: list[str]) -> None:
    bad = [d for d in databases if d not in FETCHERS and d not in KEYED_FETCHERS]
    if bad:
        raise HTTPException(status_code=400,
                            detail=f"No API connector for: {', '.join(bad)}")


@router.get("/update-plan")
def read_plan(project_id: int, member: ProjectMemberDep, db: DbDep):
    get_project(project_id, db)
    out = plan_out(get_plan(db, project_id), project_id)
    out["intervals"] = list(UPDATE_INTERVALS)
    return out


# demo visitors: no scheduled searches (their project is gone by morning)
@router.put("/update-plan", dependencies=[Depends(require_project_admin), NoSandbox])
def write_plan(project_id: int, payload: PlanIn, member: ProjectMemberDep, db: DbDep):
    get_project(project_id, db)
    if payload.interval_days not in UPDATE_INTERVALS:
        raise HTTPException(status_code=422,
                            detail=f"interval_days must be one of {UPDATE_INTERVALS}")
    _check_databases(payload.databases)
    if payload.equation_id is not None:
        eq = db.get(Equation, payload.equation_id)
        if eq is None or eq.project_id != project_id:
            raise HTTPException(status_code=404, detail="Equation not found")
    if payload.enabled and not payload.databases:
        raise HTTPException(status_code=422,
                            detail="Select at least one database to enable the plan")
    plan = upsert_plan(db, project_id, enabled=payload.enabled,
                       interval_days=payload.interval_days,
                       databases=payload.databases, equation_id=payload.equation_id,
                       user_id=member.user_id)
    db.commit()
    return plan_out(plan, project_id)


@router.post("/updates/run", dependencies=[Depends(require_project_admin), NoSandbox])
def run_update(project_id: int, payload: RunIn, member: ProjectMemberDep, db: DbDep):
    get_project(project_id, db)
    plan = get_plan(db, project_id)
    databases = payload.databases or (list(plan.databases) if plan else [])
    if not databases:
        raise HTTPException(status_code=422, detail="Select at least one database")
    _check_databases(databases)
    running = (db.query(Job.id)
               .filter(Job.project_id == project_id, Job.type == "search_update",
                       Job.status.in_(["queued", "running"])).first())
    if running is not None:
        raise HTTPException(status_code=409, detail="An update pass is already running")
    job = runner.submit("search_update",
                        {"project_id": project_id, "databases": databases,
                         "equation_id": payload.equation_id, "cap": payload.cap,
                         "triggered_by": "manual", "user_id": member.user_id},
                        project_id=project_id, user_id=member.user_id)
    return {"job_id": job.id}


@router.get("/updates")
def list_updates(project_id: int, member: ProjectMemberDep, db: DbDep):
    get_project(project_id, db)
    return runs_out(db, project_id)


@router.delete("/updates/{round}", dependencies=[Depends(require_project_admin)])
def delete_update(project_id: int, round: int, member: ProjectMemberDep, db: DbDep):
    """Undo the latest update pass: its records, their screening, the run row."""
    get_project(project_id, db)
    try:
        delete_update_round(db, project_id, round)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    return {"ok": True, "round": round}
