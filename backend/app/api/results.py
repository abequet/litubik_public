# SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
# SPDX-License-Identifier: AGPL-3.0-or-later
"""M10: results / synthesis — descriptive aggregates computed live from the
extraction table (charts data), country normalization report, JBI quality
summary, AI narrative synthesis, CSV export of the aggregated numbers."""
import csv
import io

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from app.api.deps import DbDep, ProjectMemberDep, SatelliteGuard, get_project
from app.core.csvsafe import safe_row
from app.models import ResultsSynthesis, User
from app.services.llm import pricing
from app.services.llm.base import LLMError
from app.services.results import compute, narrative

router = APIRouter(prefix="/api/projects/{project_id}/results",
                   tags=["results"], dependencies=[SatelliteGuard])


@router.get("")
def get_aggregates(project_id: int, member: ProjectMemberDep, db: DbDep):
    get_project(project_id, db)
    return compute.aggregates(db, project_id)


def _narrative_out(db, row: ResultsSynthesis | None) -> dict:
    if row is None:
        return {"narrative": None}
    author = db.get(User, row.generated_by) if row.generated_by else None
    return {"narrative": {
        "content_md": row.content_md,
        "provider": row.provider,
        "model": row.model,
        "cost": {**pricing.cost_breakdown(row.provider, row.model,
                                          row.tokens_in, row.tokens_out),
                 "estimated": False},
        "generated_by_name": author.display_name if author else "?",
        "created_at": row.created_at.isoformat() if row.created_at else "",
    }}


@router.get("/narrative")
def get_narrative(project_id: int, member: ProjectMemberDep, db: DbDep):
    get_project(project_id, db)
    row = db.query(ResultsSynthesis).filter_by(project_id=project_id).first()
    return _narrative_out(db, row)


@router.get("/narrative/estimate")
def narrative_estimate(project_id: int, member: ProjectMemberDep, db: DbDep):
    """Up-front cost estimate for the generate button (hover). None when no
    API key is configured or there is nothing to synthesize yet."""
    get_project(project_id, db)
    return {"cost": narrative.estimate_cost(db, project_id)}


@router.post("/narrative/generate")
def generate_narrative(project_id: int, member: ProjectMemberDep, db: DbDep):
    """(Re)generate the narrative synthesis — any member, like the other
    on-demand AI buttons; the author and cost are recorded."""
    get_project(project_id, db)
    try:
        row = narrative.generate(db, project_id, user_id=member.user_id)
    except LLMError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return _narrative_out(db, row)


@router.get("/export.csv")
def export_csv(project_id: int, member: ProjectMemberDep, db: DbDep):
    get_project(project_id, db)
    header, rows = compute.export_rows(db, project_id)
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(header)
    writer.writerows(safe_row(r) for r in rows)
    return StreamingResponse(
        iter([buffer.getvalue().encode("utf-8-sig")]),
        media_type="text/csv",
        headers={"Content-Disposition":
                 'attachment; filename="results_synthesis.csv"'})
