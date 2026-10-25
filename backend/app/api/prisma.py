# SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Live PRISMA 2020 flow counters (M10 will add SVG/PNG/PDF export)."""
from fastapi import APIRouter

from app.api.deps import DbDep, ProjectMemberDep, get_project
from app.services.prisma import prisma_counts
from app.services.prisma.reviewers import reviewer_summary

router = APIRouter(prefix="/api/projects/{project_id}/prisma", tags=["prisma"])


@router.get("")
def prisma(project_id: int, member: ProjectMemberDep, db: DbDep):
    get_project(project_id, db)
    return prisma_counts(db, project_id)


@router.get("/reviewers")
def reviewers(project_id: int, member: ProjectMemberDep, db: DbDep):
    """Each member's work summed over every screening round, plus their
    duplicate rulings, conflict resolutions, extraction and appraisal."""
    get_project(project_id, db)
    return reviewer_summary(db, project_id)
