# SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Per-project AI prompt transparency (M2): any member can read the effective
instruction block of each AI feature; a project admin can override it or reset
it to the shipped default. Only the instruction part is editable — dynamic
context and JSON output schemas stay in code."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.api.deps import (
    CurrentUser, DbDep, NoSandboxWrites, ProjectMemberDep, require_project_admin,
)
from app.models import PromptOverride
from app.services.llm.prompts import PROMPTS

# demo visitors keep the built-in prompts: the app-wide key they run on
# must not become a general-purpose LLM proxy
router = APIRouter(prefix="/api/projects/{project_id}/prompts", tags=["prompts"],
                   dependencies=[NoSandboxWrites])


class PromptOut(BaseModel):
    key: str
    label: str
    description: str
    default_text: str
    override_text: str | None = None
    effective_text: str


class PromptIn(BaseModel):
    text: str = Field(min_length=1, max_length=20000)


@router.get("", response_model=list[PromptOut])
def list_prompts(project_id: int, member: ProjectMemberDep, db: DbDep):
    overrides = {row.feature_key: row.text for row in
                 db.query(PromptOverride).filter_by(project_id=project_id)}
    out = []
    for spec in PROMPTS.values():
        override = overrides.get(spec.key)
        override = override if override and override.strip() else None
        out.append(PromptOut(key=spec.key, label=spec.label,
                             description=spec.description,
                             default_text=spec.text, override_text=override,
                             effective_text=override or spec.text))
    return out


@router.put("/{feature_key}", response_model=PromptOut,
            dependencies=[Depends(require_project_admin)])
def set_prompt(project_id: int, feature_key: str, payload: PromptIn,
               user: CurrentUser, db: DbDep):
    spec = PROMPTS.get(feature_key)
    if spec is None:
        raise HTTPException(status_code=404, detail="Unknown AI feature")
    row = (db.query(PromptOverride)
           .filter_by(project_id=project_id, feature_key=feature_key).first())
    if row is None:
        row = PromptOverride(project_id=project_id, feature_key=feature_key)
        db.add(row)
    row.text = payload.text
    row.updated_by = user.id
    db.commit()
    return PromptOut(key=spec.key, label=spec.label,
                     description=spec.description, default_text=spec.text,
                     override_text=row.text, effective_text=row.text)


@router.delete("/{feature_key}", response_model=PromptOut,
               dependencies=[Depends(require_project_admin)])
def reset_prompt(project_id: int, feature_key: str, user: CurrentUser,
                 db: DbDep):
    """Reset to the shipped default (removes the override)."""
    spec = PROMPTS.get(feature_key)
    if spec is None:
        raise HTTPException(status_code=404, detail="Unknown AI feature")
    row = (db.query(PromptOverride)
           .filter_by(project_id=project_id, feature_key=feature_key).first())
    if row is not None:
        db.delete(row)
        db.commit()
    return PromptOut(key=spec.key, label=spec.label,
                     description=spec.description, default_text=spec.text,
                     override_text=None, effective_text=spec.text)
