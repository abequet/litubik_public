# SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Project-declared databases: the registry of built-in databases, extended
per project with the sources a team adds by hand (a national portal, a
publisher platform, a grey-literature repository…).

A declared database is assisted-manual only — the app shows the query in the
syntax it borrows and the export file is imported under its slug."""
import re

from sqlalchemy.orm import Session

from app.models import CustomDatabase, Equation
from app.services.equations.translate import DATABASES, translate_all

BUILTIN_IDS = {db["id"] for db in DATABASES} | {"generic"}

DEFAULT_INSTRUCTIONS = (
    "Open the database's advanced search, paste the query, apply the same year "
    "range, then report the result count here and import the export file."
)


def slugify(label: str, taken: set[str]) -> str:
    """A short, stable, collision-free id for a hand-declared database — it
    becomes the source name of every import, so it must never collide with a
    built-in database or with another declared one."""
    base = re.sub(r"[^a-z0-9]+", "-", label.strip().lower()).strip("-")[:40]
    base = base or "database"
    if base not in taken and base not in BUILTIN_IDS:
        return base
    for n in range(2, 100):
        candidate = f"{base}-{n}"
        if candidate not in taken and candidate not in BUILTIN_IDS:
            return candidate
    raise ValueError("too many databases with this name")


def list_custom(db: Session, project_id: int) -> list[CustomDatabase]:
    return (db.query(CustomDatabase).filter_by(project_id=project_id)
            .order_by(CustomDatabase.created_at, CustomDatabase.id).all())


def custom_syntaxes(db: Session, project_id: int) -> dict[str, str]:
    """{db_id: syntax} — what `translate_all(extra=…)` expects."""
    return {c.db_id: c.syntax for c in list_custom(db, project_id)}


def as_registry_entry(row: CustomDatabase) -> dict:
    """A declared database in the same shape as a built-in registry entry, so
    the Equations and Search pages render it without knowing the difference."""
    return {
        "id": row.db_id,
        "label": row.label,
        "count": "manual",
        "instructions": row.instructions or DEFAULT_INSTRUCTIONS,
        "custom": True,
        "custom_id": row.id,
        "syntax": row.syntax,
        "url": row.url,
    }


def selected_database_ids(db: Session, project_id: int) -> set[str] | None:
    """The ids a project chose to search (Project.databases), None = all."""
    from app.models import Project
    project = db.get(Project, project_id)
    if project is None or not project.databases:
        return None
    return set(project.databases)


def all_project_databases(db: Session, project_id: int) -> list[dict]:
    """Built-in registry (unchanged shape) + this project's own databases,
    whatever the project selected — the settings page lists everything."""
    return ([dict(d) for d in DATABASES]
            + [as_registry_entry(c) for c in list_custom(db, project_id)])


def project_databases(db: Session, project_id: int) -> list[dict]:
    """The databases this review searches: the selection when the project
    made one (its own declared databases always count), else everything."""
    entries = all_project_databases(db, project_id)
    selected = selected_database_ids(db, project_id)
    if selected is None:
        return entries
    return [d for d in entries if d["id"] in selected or d.get("custom")]


def refresh_equation_translations(db: Session, project_id: int) -> None:
    """Add/refresh the auto translation of every declared database on every
    equation of the project — including frozen ones, where it only adds a
    string for a source that did not exist when the equation was frozen
    (manual overrides are left untouched)."""
    extra = custom_syntaxes(db, project_id)
    for equation in db.query(Equation).filter_by(project_id=project_id).all():
        translations = dict(equation.translations or {})
        auto = dict(translations.get("auto") or {})
        fresh = translate_all(equation.structure or {}, equation.params or {},
                              extra=extra)
        # only the declared databases are (re)computed here
        for db_id in extra:
            auto[db_id] = fresh.get(db_id, "")
        for stale in [k for k in auto if k not in BUILTIN_IDS and k not in extra]:
            del auto[stale]
        translations["auto"] = auto
        overrides = dict(translations.get("overrides") or {})
        for stale in [k for k in overrides
                      if k not in BUILTIN_IDS and k not in extra]:
            del overrides[stale]
        translations["overrides"] = overrides
        equation.translations = translations
