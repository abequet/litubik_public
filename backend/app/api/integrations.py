# SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Personal integrations (roadmap chantier 4): a user's Zotero API key and
library choice, the collections of that library, and the project-level jobs
that pull a collection in or push the project's references out.

The key is personal (one per account, Fernet-encrypted like the other stored
keys) and never shared through sync. Import is a project-admin action and a
structural write (SatelliteGuard); export writes to the member's own Zotero
library, so any member may run it."""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.api.deps import (
    CurrentUser, DbDep, NoSandbox, NoSandboxWrites, ProjectMemberDep,
    SatelliteGuard, get_project,
    require_project_admin,
)
from app.api.export import SCOPES
from app.core.crypto import decrypt_secret, encrypt_secret
from app.models import Equation, UserIntegration
from app.services.integrations.zotero import (
    KEY_SETTINGS_URL, ZoteroClient, ZoteroError,
)
from app.services.integrations.zotero_jobs import PROVIDER, library_prefix
from app.workers.runner import runner

# demo visitors: no Zotero (it needs their personal API key)
router = APIRouter(prefix="/api/integrations/zotero", tags=["integrations"],
                   dependencies=[NoSandboxWrites])
project_router = APIRouter(prefix="/api/projects/{project_id}/zotero",
                           tags=["integrations"], dependencies=[NoSandbox])


class ZoteroStatus(BaseModel):
    configured: bool
    library_type: str | None = None
    library_id: int | None = None
    library_name: str | None = None
    username: str | None = None
    write: bool = False
    updated_at: datetime | None = None
    key_url: str = KEY_SETTINGS_URL


class ZoteroLibrary(BaseModel):
    type: str
    id: int
    name: str
    write: bool


class ZoteroProbe(BaseModel):
    user_id: int
    username: str
    libraries: list[ZoteroLibrary]


class ZoteroProbeIn(BaseModel):
    api_key: str | None = Field(default=None, max_length=200)


class ZoteroSaveIn(BaseModel):
    api_key: str | None = Field(default=None, max_length=200)
    library_type: str = Field(pattern="^(user|group)$")
    library_id: int


class ZoteroCollection(BaseModel):
    key: str
    name: str
    depth: int
    n_items: int


def _row(db, user_id: int) -> UserIntegration | None:
    return (db.query(UserIntegration)
            .filter_by(user_id=user_id, provider=PROVIDER).first())


def _key(db, user: CurrentUser, supplied: str | None) -> str:
    if supplied and supplied.strip():
        return supplied.strip()
    row = _row(db, user.id)
    key = decrypt_secret(row.api_key_encrypted) if row else None
    if not key:
        raise HTTPException(status_code=400, detail="Paste your Zotero API key first")
    return key


def _status(row: UserIntegration | None) -> ZoteroStatus:
    if row is None:
        return ZoteroStatus(configured=False)
    c = row.config or {}
    return ZoteroStatus(configured=True, library_type=c.get("library_type"),
                        library_id=c.get("library_id"),
                        library_name=c.get("library_name"),
                        username=c.get("username"), write=bool(c.get("write")),
                        updated_at=row.updated_at)


@router.get("", response_model=ZoteroStatus)
def zotero_status(user: CurrentUser, db: DbDep):
    return _status(_row(db, user.id))


@router.post("/probe", response_model=ZoteroProbe)
def zotero_probe(payload: ZoteroProbeIn, user: CurrentUser, db: DbDep):
    """Check a key (pasted, or the stored one) and list the libraries it opens."""
    key = _key(db, user, payload.api_key)
    try:
        return ZoteroClient(key).libraries()
    except ZoteroError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:  # network
        raise HTTPException(status_code=502, detail=f"Zotero unreachable: {e}")


@router.put("", response_model=ZoteroStatus)
def zotero_save(payload: ZoteroSaveIn, user: CurrentUser, db: DbDep):
    """Store the key (or keep the stored one) and the chosen library. The key
    is verified again so the saved library is one it really opens."""
    key = _key(db, user, payload.api_key)
    try:
        probe = ZoteroClient(key).libraries()
    except ZoteroError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Zotero unreachable: {e}")
    lib = next((l for l in probe["libraries"]
                if l["type"] == payload.library_type and l["id"] == payload.library_id),
               None)
    if lib is None:
        raise HTTPException(status_code=400,
                            detail="This key does not open the chosen library")
    row = _row(db, user.id)
    if row is None:
        row = UserIntegration(user_id=user.id, provider=PROVIDER,
                              api_key_encrypted=encrypt_secret(key), config={})
        db.add(row)
    elif payload.api_key and payload.api_key.strip():
        row.api_key_encrypted = encrypt_secret(key)
    row.config = {"library_type": lib["type"], "library_id": lib["id"],
                  "library_name": lib["name"], "write": lib["write"],
                  "username": probe["username"], "zotero_user_id": probe["user_id"]}
    db.commit()
    db.refresh(row)
    return _status(row)


@router.delete("")
def zotero_remove(user: CurrentUser, db: DbDep):
    row = _row(db, user.id)
    if row is not None:
        db.delete(row)
        db.commit()
    return {"ok": True}


@router.get("/collections", response_model=list[ZoteroCollection])
def zotero_collections(user: CurrentUser, db: DbDep):
    row = _row(db, user.id)
    if row is None or not (row.config or {}).get("library_id"):
        raise HTTPException(status_code=400,
                            detail="Connect your Zotero library first (My integrations)")
    key = decrypt_secret(row.api_key_encrypted)
    if not key:
        raise HTTPException(status_code=400,
                            detail="The stored Zotero key cannot be decrypted — enter it again")
    try:
        return ZoteroClient(key).collections(library_prefix(row.config))
    except ZoteroError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Zotero unreachable: {e}")


# -- project-level jobs --------------------------------------------------------

class ZoteroImportIn(BaseModel):
    collection_key: str | None = Field(default=None, max_length=16)
    collection_name: str = Field(default="library", max_length=200)
    source_type: str = Field(default="manual", pattern="^(database|manual)$")
    source_name: str | None = Field(default=None, max_length=100)
    equation_id: int | None = None
    with_pdfs: bool = False


class ZoteroExportIn(BaseModel):
    scope: str = "all"
    collection_key: str | None = Field(default=None, max_length=16)
    collection_name: str | None = Field(default=None, max_length=200)


def _require_integration(db, user_id: int, *, write: bool = False) -> UserIntegration:
    row = _row(db, user_id)
    if row is None or not (row.config or {}).get("library_id"):
        raise HTTPException(status_code=400,
                            detail="Connect your Zotero library first (My integrations)")
    if write and not (row.config or {}).get("write"):
        raise HTTPException(status_code=400,
                            detail="Your Zotero key has no write access to this "
                                   "library — create a key with write access")
    return row


@project_router.post("/import", dependencies=[SatelliteGuard])
def zotero_import(project_id: int, payload: ZoteroImportIn, member: ProjectMemberDep,
                  db: DbDep, _admin=Depends(require_project_admin)):
    """Pull a Zotero collection (or the whole library) into the project as a
    traced import — background job."""
    get_project(project_id, db)
    _require_integration(db, member.user_id)
    if payload.equation_id is not None:
        equation = db.get(Equation, payload.equation_id)
        if equation is None or equation.project_id != project_id:
            raise HTTPException(status_code=404, detail="Equation not found")
    from app.core.demo import DEMO_MAX_IMPORT_RECORDS, is_demo_user
    from app.models import User
    cap = DEMO_MAX_IMPORT_RECORDS if is_demo_user(db.get(User, member.user_id)) else None
    name = payload.collection_name.strip() or "library"
    job = runner.submit("zotero_import", {
        "project_id": project_id, "user_id": member.user_id,
        "collection_key": payload.collection_key, "collection_name": name,
        "source_type": payload.source_type,
        "source_name": (payload.source_name or "").strip() or None,
        "equation_id": payload.equation_id, "with_pdfs": payload.with_pdfs,
        "cap": cap,
    }, project_id=project_id, user_id=member.user_id)
    return {"job_id": job.id}


@project_router.post("/export")
def zotero_export(project_id: int, payload: ZoteroExportIn, member: ProjectMemberDep,
                  db: DbDep):
    """Push the scoped references into the member's Zotero library —
    background job; items already linked are updated, not duplicated."""
    get_project(project_id, db)
    if payload.scope not in SCOPES:
        raise HTTPException(status_code=400, detail=f"scope must be one of {SCOPES}")
    _require_integration(db, member.user_id, write=True)
    job = runner.submit("zotero_export", {
        "project_id": project_id, "user_id": member.user_id,
        "scope": payload.scope, "collection_key": payload.collection_key,
        "collection_name": payload.collection_name,
    }, project_id=project_id, user_id=member.user_id)
    return {"job_id": job.id}
