# SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Reviewer work time (roadmap chantier 14).

- `POST heartbeat`: any member, from the work pages — the only write.
- `GET me`: a member's own measured total (transparency: the tracked person
  sees what is tracked).
- `GET report`, `GET export.csv`: project admin only — aggregates by reviewer,
  stage and week; never a time per individual record.

Heartbeats are a per-user contribution like votes, so they are accepted on a
satellite instance too (no SatelliteGuard) and travel in packages."""
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.api.deps import DbDep, ProjectMemberDep, get_project, require_project_admin
from app.core.instance import get_instance_id
from app.models.worktime import WORK_STAGES
from app.services.worktime.estimate import DEFAULT_CAP_S, DEFAULT_GAP_S
from app.services.worktime.report import (
    SOURCES, build_report, export_csv, my_total,
)
from app.services.worktime.sessions import record_heartbeat, session_seconds

router = APIRouter(prefix="/api/projects/{project_id}/worktime", tags=["worktime"])


class HeartbeatIn(BaseModel):
    stage: str


@router.post("/heartbeat")
def heartbeat(project_id: int, body: HeartbeatIn, member: ProjectMemberDep, db: DbDep):
    get_project(project_id, db)
    if body.stage not in WORK_STAGES:
        raise HTTPException(status_code=422, detail="Unknown stage")
    session = record_heartbeat(db, project_id, member.user_id, body.stage,
                               instance_id=get_instance_id(db))
    db.commit()
    return {"ok": True, "session_seconds": session_seconds(session)}


@router.get("/me")
def me(project_id: int, member: ProjectMemberDep, db: DbDep):
    get_project(project_id, db)
    return my_total(db, project_id, member.user_id)


def _params(source: str, gap: int, cap: int) -> tuple[str, int, int]:
    if source not in SOURCES:
        raise HTTPException(status_code=422, detail="source must be measured or estimated")
    return source, gap, cap


@router.get("/report", dependencies=[Depends(require_project_admin)])
def report(project_id: int, db: DbDep,
           source: str = "measured",
           gap: int = Query(DEFAULT_GAP_S, ge=60, le=7200),
           cap: int = Query(DEFAULT_CAP_S, ge=10, le=7200)):
    get_project(project_id, db)
    return build_report(db, project_id, *_params(source, gap, cap))


@router.get("/export.csv", dependencies=[Depends(require_project_admin)])
def export(project_id: int, db: DbDep,
           source: str = "measured",
           gap: int = Query(DEFAULT_GAP_S, ge=60, le=7200),
           cap: int = Query(DEFAULT_CAP_S, ge=10, le=7200)):
    get_project(project_id, db)
    text = export_csv(db, project_id, *_params(source, gap, cap))
    return StreamingResponse(
        iter([text.encode("utf-8-sig")]),
        media_type="text/csv",
        headers={"Content-Disposition":
                 f'attachment; filename="worktime-{source}.csv"'})
