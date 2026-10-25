# SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
# SPDX-License-Identifier: AGPL-3.0-or-later
"""AI translation of a record's title/abstract — a reading aid for reviewers.

No SatelliteGuard: reading is not structural, and a reviewer on a satellite
needs it as much as anyone. (A translation made there lives until the next
snapshot import, which brings the coordinator's records back.)
"""
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.api.deps import DbDep, ProjectMemberDep
from app.models import Record
from app.services.llm import LLMError
from app.services.translation import translate_record

router = APIRouter(prefix="/api/projects/{project_id}/records",
                   tags=["translation"])


class TranslateIn(BaseModel):
    lang: Literal["en", "fr"]


@router.post("/{record_id}/translate")
def translate(project_id: int, record_id: int, payload: TranslateIn,
              member: ProjectMemberDep, db: DbDep):
    """The record's title + abstract in `lang`: the team's cached translation
    when there is one, a fresh AI translation otherwise. Open to every project
    member. The abstract itself is never modified."""
    record = db.get(Record, record_id)
    if record is None or record.project_id != project_id:
        raise HTTPException(status_code=404, detail="Record not found")
    if not (record.title or "").strip() and not (record.abstract or "").strip():
        raise HTTPException(status_code=400, detail="Nothing to translate")
    try:
        return translate_record(db, project_id, record, payload.lang,
                                member.user_id)
    except LLMError as e:
        # no key configured is the caller's to fix (400); the rest is upstream
        status = 400 if "No API key" in str(e) else 502
        raise HTTPException(status_code=status, detail=str(e))
