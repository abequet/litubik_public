# SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Catalogue of review types and question frameworks (read-only).

The same catalogue drives what the AI is told and what the UI labels say, so it
is served rather than duplicated in the frontend. Labels are the English source
strings — the frontend runs them through t() like it already does for the AI
prompt labels.
"""
from fastapi import APIRouter
from pydantic import BaseModel

from app.api.deps import CurrentUser
from app.services import framing

router = APIRouter(prefix="/api/framings", tags=["framings"])


class SlotOut(BaseModel):
    key: str
    letter: str
    label: str
    hint: str


class FrameworkOut(BaseModel):
    key: str
    short: str
    label: str
    citation: str
    slots: list[SlotOut]


class ReviewTypeOut(BaseModel):
    key: str
    label: str
    citation: str
    default_framework: str
    default_template: str
    tooling_note: str


class FramingsOut(BaseModel):
    review_types: list[ReviewTypeOut]
    frameworks: list[FrameworkOut]
    default_review_type: str
    default_framework: str


@router.get("", response_model=FramingsOut)
def list_framings(user: CurrentUser):
    return FramingsOut(
        review_types=[ReviewTypeOut(key=r.key, label=r.label,
                                    citation=r.citation,
                                    default_framework=r.default_framework,
                                    default_template=r.default_template,
                                    tooling_note=r.tooling_note)
                      for r in framing.REVIEW_TYPES.values()],
        frameworks=[FrameworkOut(key=f.key, short=f.short, label=f.label,
                                 citation=f.citation,
                                 slots=[SlotOut(key=s.key, letter=s.letter,
                                                label=s.label, hint=s.hint)
                                        for s in f.slots])
                    for f in framing.FRAMEWORKS.values()],
        default_review_type=framing.DEFAULT_REVIEW_TYPE,
        default_framework=framing.DEFAULT_FRAMEWORK,
    )
