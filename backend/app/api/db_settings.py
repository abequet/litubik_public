# SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Bibliographic-database API keys (Scopus, IEEE), stored encrypted.

Global keys (project_id NULL) are managed by an app admin; project-scoped keys
(M4b) by that project's admins and they override the global one for counts and
fetching. Keys are write-only: the API returns only whether one is stored,
never the key."""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.api.deps import CurrentUser, DbDep, NoSandboxWrites
from app.core.crypto import decrypt_secret, encrypt_secret
from app.models import DatabaseCredential, ProjectMember
from app.services.connectors.keys import KEYED_PROVIDERS, PROVIDER_PATTERN
from app.services.equations.counts import CountError, KEYED_COUNTERS

# demo visitors store no keys (they would be third-party secrets on a
# public instance); they search the open databases only
router = APIRouter(prefix="/api/database-credentials", tags=["database-keys"],
                   dependencies=[NoSandboxWrites])

_PROVIDER_LABELS = {"scopus": "Scopus (Elsevier)", "ieee": "IEEE Xplore",
                    "core": "CORE", "lens": "Lens.org",
                    "springer": "Springer Nature",
                    "wos": "Web of Science Starter"}
# tiny title queries just to validate a key against each provider
_TEST_QUERY = {"scopus": "TITLE(cancer)", "ieee": '"Document Title":cancer',
               "core": 'title:"cancer"', "lens": "title:cancer",
               "springer": 'title:"cancer"', "wos": "TI=(cancer)"}
# M4b: shown in the UI helper — how to obtain each key (through the
# institution's subscription for Scopus, IEEE and WoS; free registration for
# CORE and Springer Nature; a request form for Lens)
_PROVIDER_HELP = {
    "scopus": "https://dev.elsevier.com/",
    "ieee": "https://developer.ieee.org/",
    "core": "https://core.ac.uk/services/api",
    "lens": "https://www.lens.org/lens/user/subscriptions#scholar",
    "springer": "https://dev.springernature.com/",
    "wos": "https://developer.clarivate.com/apis/wos-starter",
}


class KeyIn(BaseModel):
    provider: str = Field(pattern=PROVIDER_PATTERN)
    api_key: str = Field(min_length=6, max_length=200)
    project_id: int | None = None


class KeyOut(BaseModel):
    provider: str
    label: str
    configured: bool
    key_hint: str
    project_id: int | None = None
    # for a project listing: a global key exists and applies as fallback
    global_configured: bool = False
    help_url: str = ""


class DatabaseOut(BaseModel):
    """One database of the project, keyed or not — the settings page lists them
    all so nothing looks missing (Web of Science, EBSCO… have no public API
    here and stay assisted-manual)."""
    id: str
    label: str
    # "api_key" = automatic once a key is stored; "api" = automatic, free;
    # "manual" = assisted manual export/import
    mode: str
    custom: bool = False
    custom_id: int | None = None
    syntax: str = ""
    url: str = ""
    # whether the project searches it (Project.databases; everything is
    # selected when the project made no selection)
    selected: bool = True


def _require_scope_admin(user: CurrentUser, db, project_id: int | None):
    """Global keys belong to the app admin; project keys to project admins
    (the app admin passes everywhere)."""
    if user.is_admin:
        return
    if project_id is None:
        raise HTTPException(status_code=403,
                            detail="Only an application admin manages database keys")
    member = db.query(ProjectMember).filter_by(
        project_id=project_id, user_id=user.id).first()
    if member is None or member.role != "admin":
        raise HTTPException(status_code=403, detail="Project admin role required")


def _require_member(user: CurrentUser, db, project_id: int):
    if user.is_admin:
        return
    member = db.query(ProjectMember).filter_by(
        project_id=project_id, user_id=user.id).first()
    if member is None:
        raise HTTPException(status_code=403, detail="Not a member of this project")


def _row(db, provider: str, project_id: int | None) -> DatabaseCredential | None:
    return db.query(DatabaseCredential).filter_by(
        project_id=project_id, provider=provider).first()


@router.get("", response_model=list[KeyOut])
def list_keys(user: CurrentUser, db: DbDep, project_id: int | None = None):
    if project_id is not None:
        _require_member(user, db, project_id)
    # M6 demo: the app-wide key does NOT apply to visitor sandboxes — don't
    # show the "app-wide key active" badge there
    from app.core.demo import project_allows_global_keys
    global_applies = (project_id is not None
                      and project_allows_global_keys(db, project_id))
    out = []
    for provider in KEYED_PROVIDERS:
        row = _row(db, provider, project_id)
        out.append(KeyOut(
            provider=provider, label=_PROVIDER_LABELS[provider],
            configured=row is not None,
            key_hint="•••• (stored)" if row else "",
            project_id=project_id,
            global_configured=(global_applies
                               and _row(db, provider, None) is not None),
            help_url=_PROVIDER_HELP.get(provider, "")))
    return out


@router.get("/databases", response_model=list[DatabaseOut])
def list_databases(user: CurrentUser, db: DbDep, project_id: int | None = None,
                   all: bool = False):
    """Every database available to the project: the ones that accept an API
    key, the free automatic ones, the assisted-manual ones (Web of Science,
    EBSCO, ACM…) and the project's own declared databases. `all=true` lists
    the whole registry whatever the project selected (the settings page),
    with `selected` telling which ones the review searches."""
    if project_id is not None:
        _require_member(user, db, project_id)
    from app.services.equations import (
        DATABASES, all_project_databases, project_databases,
        selected_database_ids,
    )
    if project_id is None:
        entries, selected = [dict(d) for d in DATABASES], None
    elif all:
        entries = all_project_databases(db, project_id)
        selected = selected_database_ids(db, project_id)
    else:
        entries, selected = project_databases(db, project_id), None
    out = []
    for d in entries:
        if d["id"] in KEYED_PROVIDERS:
            mode = "api_key"
        elif d["count"] == "api":
            mode = "api"
        else:
            mode = "manual"
        out.append(DatabaseOut(
            id=d["id"], label=d["label"], mode=mode,
            custom=bool(d.get("custom")), custom_id=d.get("custom_id"),
            syntax=d.get("syntax", ""), url=d.get("url", ""),
            selected=(selected is None or d["id"] in selected or bool(d.get("custom")))))
    return out


@router.put("", response_model=KeyOut)
def upsert_key(payload: KeyIn, user: CurrentUser, db: DbDep):
    _require_scope_admin(user, db, payload.project_id)
    row = _row(db, payload.provider, payload.project_id)
    if row is None:
        row = DatabaseCredential(project_id=payload.project_id,
                                 provider=payload.provider)
        if payload.project_id is not None:
            row.owner_user_id = user.id
        db.add(row)
    row.api_key_encrypted = encrypt_secret(payload.api_key.strip())
    db.commit()
    return KeyOut(provider=payload.provider, label=_PROVIDER_LABELS[payload.provider],
                  configured=True, key_hint="•••• (stored)",
                  project_id=payload.project_id,
                  help_url=_PROVIDER_HELP.get(payload.provider, ""))


@router.delete("/{provider}")
def delete_key(provider: str, user: CurrentUser, db: DbDep,
               project_id: int | None = None):
    _require_scope_admin(user, db, project_id)
    row = _row(db, provider, project_id)
    if row is None:
        raise HTTPException(status_code=404, detail="No key stored")
    db.delete(row)
    db.commit()
    return {"ok": True}


@router.post("/{provider}/test")
def test_key(provider: str, user: CurrentUser, db: DbDep,
             project_id: int | None = None):
    """Validate the stored key with one tiny live query."""
    _require_scope_admin(user, db, project_id)
    if provider not in KEYED_COUNTERS:
        raise HTTPException(status_code=404, detail="Unknown provider")
    row = _row(db, provider, project_id)
    if row is None:
        raise HTTPException(status_code=400, detail="No key stored")
    key = decrypt_secret(row.api_key_encrypted)
    if not key:
        raise HTTPException(status_code=400,
                            detail="Could not decrypt the key (app secret changed?)")
    try:
        n = KEYED_COUNTERS[provider](_TEST_QUERY[provider], {}, key)
    except CountError as e:
        return {"ok": False, "detail": str(e)}
    return {"ok": True, "detail": f"Key works — sample query returned {n} records"}
