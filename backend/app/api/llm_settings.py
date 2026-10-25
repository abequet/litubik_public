# SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
# SPDX-License-Identifier: AGPL-3.0-or-later
"""LLM provider credentials: stored encrypted, global or per-project.

Keys are write-only: the API never returns a stored key, only a masked hint.
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator

from app.api.deps import CurrentUser, DbDep, NoSandboxWrites
from app.core.crypto import encrypt_secret
from app.models import LLMCredential, LLMTaskRoute, Project, ProjectMember
from app.services.llm.credentials import _ranked_candidates, endpoint_allowed
from app.services.llm.registry import (
    DEFAULT_EFFORT, DEFAULT_LOCAL_URL, DEFAULT_MODELS, EFFORTS, PROVIDER_META,
    PROVIDERS, SUGGESTED_MODELS, TIER_MODELS, TIERS, needs_key, needs_url,
)
from app.services.llm.routing import effective_routes
from app.services.llm.tasks import TASK_BY_KEY
from app.workers.runner import runner

# demo visitors store no AI key and set no route: they run on the app-wide
# key within the demo budget (services/llm/demo_budget.py)
router = APIRouter(prefix="/api/llm", tags=["llm"],
                   dependencies=[NoSandboxWrites])


def _require_scope_admin(user, db, project_id: int | None) -> None:
    """Global keys belong to the app admin; project keys to project admins
    (the app admin passes everywhere)."""
    if user.is_admin:
        return
    if project_id is None:
        raise HTTPException(status_code=403,
                            detail="Only an application admin manages global AI keys")
    member = db.query(ProjectMember).filter_by(
        project_id=project_id, user_id=user.id).first()
    if member is None or member.role != "admin":
        raise HTTPException(status_code=403, detail="Project admin role required")


def _require_member(user, db, project_id: int) -> None:
    if user.is_admin:
        return
    member = db.query(ProjectMember).filter_by(
        project_id=project_id, user_id=user.id).first()
    if member is None:
        raise HTTPException(status_code=403, detail="Not a member of this project")


class CredentialIn(BaseModel):
    provider: str
    # optional for providers that need none (a local server): see upsert
    api_key: str = ""
    default_model: str = ""
    project_id: int | None = None
    # endpoint of a self-hosted server; only meaningful when needs_url
    base_url: str = Field(default="", max_length=300)

    @field_validator("provider")
    @classmethod
    def _known_provider(cls, v: str) -> str:
        if v not in PROVIDERS:
            raise ValueError(f"Unknown LLM provider: {v}")
        return v

    @field_validator("base_url")
    @classmethod
    def _url_shape(cls, v: str) -> str:
        v = v.strip().rstrip("/")
        if v and not v.startswith(("http://", "https://")):
            raise ValueError("The endpoint URL must start with http:// or https://")
        return v


class CredentialOut(BaseModel):
    id: int
    provider: str
    default_model: str
    project_id: int | None
    key_hint: str
    is_default: bool = False
    base_url: str = ""


def _hint(key_encrypted: str) -> str:
    # We never store or return the key itself; just signal that one exists.
    return "•••• (stored)"


def _out(c: LLMCredential) -> CredentialOut:
    return CredentialOut(id=c.id, provider=c.provider, default_model=c.default_model,
                         project_id=c.project_id, key_hint=_hint(c.api_key_encrypted),
                         is_default=c.is_default, base_url=c.base_url or "")


def _require_route_editor(user, db, project_id: int | None) -> None:
    """Who may change the per-task AI routing: app admin everywhere; project
    admins in their project; project reviewers too when the project opted in
    (`llm_reviewers_can_route`)."""
    if user.is_admin:
        return
    if project_id is None:
        raise HTTPException(status_code=403,
                            detail="Only an application admin manages global AI routing")
    member = db.query(ProjectMember).filter_by(
        project_id=project_id, user_id=user.id).first()
    if member is None:
        raise HTTPException(status_code=403, detail="Not a member of this project")
    if member.role == "admin":
        return
    project = db.get(Project, project_id)
    if project is None or not project.llm_reviewers_can_route:
        raise HTTPException(
            status_code=403,
            detail="Only a project admin changes the AI models of this project")


@router.get("/providers")
def providers():
    return {
        "providers": PROVIDERS,
        "meta": PROVIDER_META,
        "default_models": DEFAULT_MODELS,
        "suggested_models": SUGGESTED_MODELS,
        "default_local_url": DEFAULT_LOCAL_URL,
        "tiers": TIERS,
        "tier_models": TIER_MODELS,
        "efforts": EFFORTS,
        "default_effort": DEFAULT_EFFORT,
    }


@router.get("/routes")
def list_routes(user: CurrentUser, db: DbDep, project_id: int | None = None):
    """Per-task routing of one scope: the rows stored for this scope and the
    effective (provider, model, effort) each task would run on from it."""
    if project_id is not None:
        _require_member(user, db, project_id)
    candidates = _ranked_candidates(db, project_id)
    return {
        "routes": effective_routes(db, project_id, candidates),
        "available_providers": sorted({c.provider for c in candidates},
                                      key=PROVIDERS.index),
    }


class RouteIn(BaseModel):
    task: str
    provider: str
    model: str = Field(min_length=1, max_length=120)
    effort: str = DEFAULT_EFFORT
    project_id: int | None = None

    @field_validator("task")
    @classmethod
    def _known_task(cls, v: str) -> str:
        if v not in TASK_BY_KEY:
            raise ValueError(f"Unknown AI task: {v}")
        return v

    @field_validator("provider")
    @classmethod
    def _known_provider(cls, v: str) -> str:
        if v not in PROVIDERS:
            raise ValueError(f"Unknown LLM provider: {v}")
        return v

    @field_validator("effort")
    @classmethod
    def _known_effort(cls, v: str) -> str:
        if v not in EFFORTS:
            raise ValueError(f"Unknown effort level: {v}")
        return v


@router.put("/routes")
def upsert_route(payload: RouteIn, user: CurrentUser, db: DbDep):
    _require_route_editor(user, db, payload.project_id)
    row = db.query(LLMTaskRoute).filter_by(
        project_id=payload.project_id, task=payload.task).first()
    if row is None:
        row = LLMTaskRoute(project_id=payload.project_id, task=payload.task)
        db.add(row)
    row.provider = payload.provider
    row.model = payload.model.strip()
    row.effort = payload.effort
    row.updated_by = user.id
    db.commit()
    return {"ok": True, "task": row.task, "provider": row.provider,
            "model": row.model, "effort": row.effort}


@router.delete("/routes/{task}")
def delete_route(task: str, user: CurrentUser, db: DbDep,
                 project_id: int | None = None):
    """Back to the inherited routing (global row for a project, tier default
    for the app)."""
    _require_route_editor(user, db, project_id)
    row = db.query(LLMTaskRoute).filter_by(project_id=project_id, task=task).first()
    if row is not None:
        db.delete(row)
        db.commit()
    return {"ok": True}


@router.get("/credentials", response_model=list[CredentialOut])
def list_credentials(user: CurrentUser, db: DbDep, project_id: int | None = None):
    # global hints are readable by anyone (never the key itself); project
    # credentials only by members of that project
    if project_id is not None:
        _require_member(user, db, project_id)
    query = db.query(LLMCredential)
    query = query.filter(LLMCredential.project_id == project_id)
    return [_out(c) for c in query.all()]


@router.put("/credentials", response_model=CredentialOut)
def upsert_credential(payload: CredentialIn, user: CurrentUser, db: DbDep):
    _require_scope_admin(user, db, payload.project_id)
    api_key = payload.api_key.strip()
    if needs_key(payload.provider) and len(api_key) < 8:
        raise HTTPException(status_code=422,
                            detail="An API key of at least 8 characters is required")
    credential = db.query(LLMCredential).filter_by(
        provider=payload.provider, project_id=payload.project_id).first()
    model = payload.default_model.strip() or DEFAULT_MODELS[payload.provider]
    if credential is None:
        credential = LLMCredential(provider=payload.provider,
                                   project_id=payload.project_id)
        # sync: project keys have an owner who decides about sharing them
        if payload.project_id is not None:
            credential.owner_user_id = user.id
        db.add(credential)
    # a keyless provider stores a placeholder (the column stays NOT NULL); an
    # empty key sent for a stored credential keeps the key (URL/model edit)
    if api_key or not credential.api_key_encrypted:
        credential.api_key_encrypted = encrypt_secret(api_key or "none")
    credential.default_model = model
    credential.base_url = ((payload.base_url or DEFAULT_LOCAL_URL)
                           if needs_url(payload.provider) else None)
    if not endpoint_allowed(credential.base_url, credential.project_id):
        db.rollback()
        raise HTTPException(
            status_code=400,
            detail="On this instance a project key's endpoint must be a "
                   "public address (not localhost or a private network)")
    db.commit()
    db.refresh(credential)
    return _out(credential)


class ModelIn(BaseModel):
    default_model: str = Field(min_length=1, max_length=100)


@router.post("/credentials/{credential_id}/model")
def set_model(credential_id: int, payload: ModelIn, user: CurrentUser, db: DbDep):
    """Change only the default model of a stored credential (without re-entering
    the key). Backs the AI-Settings 'Save model' button."""
    credential = db.get(LLMCredential, credential_id)
    if credential is None:
        raise HTTPException(status_code=404, detail="Credential not found")
    _require_scope_admin(user, db, credential.project_id)
    credential.default_model = payload.default_model.strip()
    db.commit()
    return {"ok": True, "default_model": credential.default_model}


@router.post("/credentials/{credential_id}/default")
def set_default_credential(credential_id: int, user: CurrentUser, db: DbDep):
    """Make this credential the one AI jobs pick within its scope (its
    project, or app-wide for a global key). One default per scope."""
    credential = db.get(LLMCredential, credential_id)
    if credential is None:
        raise HTTPException(status_code=404, detail="Credential not found")
    _require_scope_admin(user, db, credential.project_id)
    for sibling in db.query(LLMCredential).filter(
            LLMCredential.project_id.is_(None) if credential.project_id is None
            else LLMCredential.project_id == credential.project_id):
        sibling.is_default = sibling.id == credential.id
    db.commit()
    return {"ok": True, "id": credential.id}


@router.delete("/credentials/{credential_id}")
def delete_credential(credential_id: int, user: CurrentUser, db: DbDep):
    credential = db.get(LLMCredential, credential_id)
    if credential is None:
        raise HTTPException(status_code=404, detail="Credential not found")
    _require_scope_admin(user, db, credential.project_id)
    db.delete(credential)
    db.commit()
    return {"ok": True}


@router.post("/credentials/{credential_id}/test")
def test_credential(credential_id: int, user: CurrentUser, db: DbDep):
    """Launch a background job that makes a tiny LLM call with this key."""
    credential = db.get(LLMCredential, credential_id)
    if credential is None:
        raise HTTPException(status_code=404, detail="Credential not found")
    _require_scope_admin(user, db, credential.project_id)
    job = runner.submit("llm_test", {"credential_id": credential_id},
                        project_id=credential.project_id, user_id=user.id)
    return {"job_id": job.id}
