# SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Legal pages (legal notice, terms of use, privacy notice).

Reading is public — the pages must be reachable before signing in. Writing is
the superadmin's: the values the templates are filled with, or a page's whole
text. See app/services/legal.py.
"""
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.api.deps import CurrentUser, DbDep
from app.models import LegalPage, LegalSettings
from app.services import legal

router = APIRouter(tags=["legal"])


def _check(lang: str, slug: str) -> None:
    if lang not in legal.LANGS or slug not in legal.SLUGS:
        raise HTTPException(status_code=404, detail="No such page")


def _require_app_admin(user: CurrentUser) -> None:
    if not user.is_admin:
        raise HTTPException(status_code=403,
                            detail="Only an application admin edits the legal pages")


@router.get("/api/legal/{lang}/{slug}")
def read_page(lang: str, slug: str, db: DbDep):
    _check(lang, slug)
    if slug not in legal.available_slugs(db):
        raise HTTPException(status_code=404, detail="No such page")
    page = legal.page(db, slug, lang)
    return {"slug": slug, "lang": lang, "body_md": page["body_md"],
            "updated_at": page["updated_at"]}


class LegalSettingsIn(BaseModel):
    operator_name: str = Field(default="", max_length=200)
    contact_email: str = Field(default="", max_length=255)
    host_name: str = Field(default="", max_length=200)
    host_address: str = Field(default="", max_length=400)


def _settings_out(db) -> dict:
    row = legal.settings_row(db)
    stored = {key: getattr(row, key) if row else ""
              for key in LegalSettingsIn.model_fields}
    return {"stored": stored, "effective": legal.effective_values(db)}


@router.get("/api/admin/legal")
def admin_overview(user: CurrentUser, db: DbDep):
    _require_app_admin(user)
    custom = {(p.slug, p.lang) for p in db.query(LegalPage)}
    return {
        **_settings_out(db),
        "published": legal.available_slugs(db),
        "pages": [{"slug": slug, "lang": lang, "custom": (slug, lang) in custom}
                  for slug in legal.SLUGS for lang in legal.LANGS],
    }


@router.put("/api/admin/legal/settings")
def save_settings(payload: LegalSettingsIn, user: CurrentUser, db: DbDep):
    _require_app_admin(user)
    row = legal.settings_row(db)
    if row is None:
        row = LegalSettings(id=1)
        db.add(row)
    for key, value in payload.model_dump().items():
        setattr(row, key, value.strip())
    row.updated_at = datetime.now(timezone.utc)
    db.commit()
    return _settings_out(db)


@router.get("/api/admin/legal/{lang}/{slug}")
def admin_read_page(lang: str, slug: str, user: CurrentUser, db: DbDep):
    _require_app_admin(user)
    _check(lang, slug)
    return legal.page(db, slug, lang)


class PageIn(BaseModel):
    body_md: str = Field(min_length=1, max_length=50_000)


@router.put("/api/admin/legal/{lang}/{slug}")
def save_page(lang: str, slug: str, payload: PageIn, user: CurrentUser,
              db: DbDep):
    _require_app_admin(user)
    _check(lang, slug)
    row = db.query(LegalPage).filter_by(slug=slug, lang=lang).first()
    if row is None:
        row = LegalPage(slug=slug, lang=lang)
        db.add(row)
    row.body_md = payload.body_md
    row.updated_at = datetime.now(timezone.utc)
    row.updated_by = user.id
    db.commit()
    return legal.page(db, slug, lang)


@router.delete("/api/admin/legal/{lang}/{slug}")
def revert_page(lang: str, slug: str, user: CurrentUser, db: DbDep):
    """Back to the shipped template, filled with the instance values."""
    _require_app_admin(user)
    _check(lang, slug)
    db.query(LegalPage).filter_by(slug=slug, lang=lang).delete()
    db.commit()
    return legal.page(db, slug, lang)
