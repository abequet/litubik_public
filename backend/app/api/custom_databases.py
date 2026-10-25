# SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Databases a project declares by hand, on top of the built-in registry.

Every review has its own sources — a national portal (Cairn, Érudit), a
publisher platform, a domain repository (TRID, ERIC) or grey literature. They
are assisted-manual: the app shows the query in the syntax the source borrows,
the team exports from the database and imports the file under its slug, and
the records land in the PRISMA counts like any other source."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.api.deps import (
    DbDep, ProjectMemberDep, SatelliteGuard, get_project, require_project_admin,
)
from app.models import CustomDatabase, Import, Source
from app.services.equations.custom import (
    DEFAULT_INSTRUCTIONS, list_custom, refresh_equation_translations, slugify,
)
from app.services.equations.translate import SYNTAX_CHOICES

router = APIRouter(prefix="/api/projects/{project_id}/custom-databases",
                   tags=["custom-databases"], dependencies=[SatelliteGuard])

SYNTAX_IDS = {s["id"] for s in SYNTAX_CHOICES}


class CustomDatabaseIn(BaseModel):
    label: str = Field(min_length=2, max_length=120)
    syntax: str = "generic"
    instructions: str = Field(default="", max_length=2000)
    url: str = Field(default="", max_length=500)


class CustomDatabaseOut(BaseModel):
    id: int
    db_id: str
    label: str
    syntax: str
    instructions: str
    url: str
    n_imports: int = 0


def _out(row: CustomDatabase, n_imports: int = 0) -> CustomDatabaseOut:
    return CustomDatabaseOut(
        id=row.id, db_id=row.db_id, label=row.label, syntax=row.syntax,
        instructions=row.instructions or DEFAULT_INSTRUCTIONS, url=row.url,
        n_imports=n_imports)


def _clean(payload: CustomDatabaseIn) -> tuple[str, str, str, str]:
    label = payload.label.strip()
    if not label:
        raise HTTPException(status_code=400, detail="A name is required")
    syntax = payload.syntax if payload.syntax in SYNTAX_IDS else "generic"
    url = payload.url.strip()
    if url and not url.startswith(("http://", "https://")):
        raise HTTPException(status_code=400,
                            detail="The link must start with http:// or https://")
    return label, syntax, payload.instructions.strip(), url


def _row(project_id: int, custom_id: int, db) -> CustomDatabase:
    row = db.get(CustomDatabase, custom_id)
    if row is None or row.project_id != project_id:
        raise HTTPException(status_code=404, detail="Database not found")
    return row


def _import_counts(project_id: int, db) -> dict[str, int]:
    rows = (db.query(Source.name, Import.id)
            .join(Import, Import.source_id == Source.id)
            .filter(Source.project_id == project_id).all())
    counts: dict[str, int] = {}
    for name, _ in rows:
        counts[name] = counts.get(name, 0) + 1
    return counts


@router.get("/syntaxes")
def syntaxes(project_id: int, member: ProjectMemberDep, db: DbDep):
    """Query syntaxes a declared database can borrow (the app cannot know the
    real one, so the team picks the closest)."""
    return {"syntaxes": SYNTAX_CHOICES}


@router.get("", response_model=list[CustomDatabaseOut])
def list_databases(project_id: int, member: ProjectMemberDep, db: DbDep):
    get_project(project_id, db)
    counts = _import_counts(project_id, db)
    return [_out(c, counts.get(c.db_id, 0)) for c in list_custom(db, project_id)]


@router.post("", response_model=CustomDatabaseOut,
             dependencies=[Depends(require_project_admin)])
def create_database(project_id: int, payload: CustomDatabaseIn, db: DbDep):
    get_project(project_id, db)
    label, syntax, instructions, url = _clean(payload)
    existing = list_custom(db, project_id)
    if any(c.label.lower() == label.lower() for c in existing):
        raise HTTPException(status_code=400,
                            detail="This project already has a database with that name")
    row = CustomDatabase(
        project_id=project_id, db_id=slugify(label, {c.db_id for c in existing}),
        label=label, syntax=syntax, instructions=instructions, url=url)
    db.add(row)
    db.flush()
    refresh_equation_translations(db, project_id)
    db.commit()
    db.refresh(row)
    return _out(row)


@router.put("/{custom_id}", response_model=CustomDatabaseOut,
            dependencies=[Depends(require_project_admin)])
def update_database(project_id: int, custom_id: int, payload: CustomDatabaseIn,
                    db: DbDep):
    """The slug never changes — imports already traced under it must keep
    pointing at this database."""
    get_project(project_id, db)
    row = _row(project_id, custom_id, db)
    label, syntax, instructions, url = _clean(payload)
    if any(c.id != row.id and c.label.lower() == label.lower()
           for c in list_custom(db, project_id)):
        raise HTTPException(status_code=400,
                            detail="This project already has a database with that name")
    row.label, row.syntax = label, syntax
    row.instructions, row.url = instructions, url
    db.flush()
    refresh_equation_translations(db, project_id)
    db.commit()
    db.refresh(row)
    return _out(row)


@router.delete("/{custom_id}", dependencies=[Depends(require_project_admin)])
def delete_database(project_id: int, custom_id: int, db: DbDep):
    """Removing a declared database only removes the card: records already
    imported from it keep their source and stay in the PRISMA counts."""
    get_project(project_id, db)
    row = _row(project_id, custom_id, db)
    db.delete(row)
    db.flush()
    refresh_equation_translations(db, project_id)
    db.commit()
    return {"ok": True}
