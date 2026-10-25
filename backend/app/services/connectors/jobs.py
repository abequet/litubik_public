# SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Background job: run a database search for an equation and import the records."""
from datetime import datetime, timezone
from pathlib import Path

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.models import Equation, Import, Project, Record, Source
from app.services.connectors.fetch import FETCHERS, KEYED_FETCHERS
from app.services.connectors.keys import resolve_db_key
from app.services.connectors.postfilter import matches_structure
from app.services.dedup.core import run_dedup
from app.services.ris.parse import to_ris
from app.workers.runner import register_handler


def get_or_create_source(db, project_id: int, type_: str, name: str,
                         round_: int = 1) -> Source:
    source = db.query(Source).filter_by(project_id=project_id, type=type_,
                                        name=name, round=round_).first()
    if source is None:
        source = Source(project_id=project_id, type=type_, name=name, round=round_)
        db.add(source)
        db.flush()
    return source


def store_import(db, *, project_id: int, source_id: int, equation_id: int | None,
                 filename: str, records: list[dict], user_id: int | None,
                 searched_at: datetime | None = None,
                 declared_hits: int | None = None,
                 date_restricted: bool | None = None,
                 discipline_restricted: bool | None = None,
                 disciplines: list[str] | None = None,
                 doc_type_restricted: bool | None = None,
                 doc_types: list[str] | None = None,
                 search_fields: list[str] | None = None) -> Import:
    """Persist an Import row + its Records (shared by API fetches and uploads).

    `searched_at` defaults to now for an API fetch (the search *is* the
    import); an upload passes what the uploader declared, or nothing.
    `date_restricted` / `discipline_restricted`: PRISMA-S limits applied to
    this run (None = not declared); `disciplines`: the subject areas the
    search was limited to; `doc_type_restricted` / `doc_types`: the same for
    document types; `search_fields`: the fields the query ran on."""
    imp = Import(project_id=project_id, source_id=source_id, equation_id=equation_id,
                 filename=filename, n_records=len(records), imported_by=user_id,
                 searched_at=searched_at, declared_hits=declared_hits,
                 date_restricted=date_restricted,
                 discipline_restricted=discipline_restricted,
                 disciplines=disciplines or None,
                 doc_type_restricted=doc_type_restricted,
                 doc_types=doc_types or None,
                 search_fields=search_fields or None)
    db.add(imp)
    db.flush()
    for r in records:
        db.add(Record(project_id=project_id, import_id=imp.id, doi=r.get("doi"),
                      pmid=r.get("pmid"),
                      title=r.get("title", ""), authors=r.get("authors", []),
                      year=r.get("year"), journal=r.get("journal", ""),
                      abstract=r.get("abstract", ""), raw_ris=r.get("raw", "")))
    return imp


def archive_raw(project_id: int, basename: str, data: bytes) -> str:
    """Archive the raw search result under data/storage/projects/<id>/ris_raw/."""
    raw_dir = get_settings().storage_dir / str(project_id) / "ris_raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    # L5: defence in depth — strip any path components from the basename so it
    # can never escape ris_raw/ (e.g. "../../etc/x" or an absolute path).
    safe = Path(basename).name
    if not safe or safe in ("..", "."):
        safe = "search"
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    filename = f"{stamp}_{safe}"
    (raw_dir / filename).write_bytes(data)
    return filename


def equation_limits(eq_params: dict | None) -> dict:
    """The PRISMA-S limits as the API fetchers apply them from the equation's
    parameters — keyword arguments for store_import."""
    from app.services.equations.translate import (
        DEFAULT_FIELDS, DISCIPLINES, DOC_TYPES, FIELD_CHOICES,
    )
    discipline_labels = {d["id"]: d["label"] for d in DISCIPLINES}
    doc_type_labels = {d["id"]: d["label"] for d in DOC_TYPES}
    p = eq_params or {}
    disciplines = [discipline_labels.get(d, d) for d in (p.get("disciplines") or [])]
    doc_types = [doc_type_labels.get(t, t) for t in (p.get("doc_types") or [])]
    fields = [f for f in (p.get("fields") or DEFAULT_FIELDS) if f in FIELD_CHOICES]
    return {"date_restricted": bool(p.get("year_from") or p.get("year_to")),
            "discipline_restricted": bool(disciplines), "disciplines": disciplines,
            "doc_type_restricted": bool(doc_types), "doc_types": doc_types,
            "search_fields": fields or list(DEFAULT_FIELDS)}


def _effective_query(equation: Equation, database: str) -> str:
    translations = equation.translations or {}
    override = (translations.get("overrides") or {}).get(database, "")
    return override or (translations.get("auto") or {}).get(database, "")


@register_handler("search_fetch")
def search_fetch_handler(job_id: int, params: dict, progress) -> dict:
    database = params["database"]
    cap = int(params.get("cap") or 5000)
    if database not in FETCHERS and database not in KEYED_FETCHERS:
        raise ValueError(f"No API fetcher for '{database}'")

    with SessionLocal() as db:
        equation = db.get(Equation, params["equation_id"])
        if equation is None:
            raise ValueError("Equation not found")
        project_id = equation.project_id
        # demo instances: a visitor's search brings at most as many records
        # as one of their uploads may, and never more than their project holds
        from app.core import demo
        room = demo.sandbox_records_room(db, project_id)
        if room is not None:
            if room == 0:
                raise ValueError(f"Demo projects hold at most {demo.DEMO_MAX_PROJECT_RECORDS} references — this one is full")
            cap = min(cap, demo.DEMO_MAX_IMPORT_RECORDS, room)
        query = _effective_query(equation, database)
        if not query.strip():
            raise ValueError(f"No {database} query on this equation")
        eq_params = equation.params or {}
        structure = equation.structure or {}
        key = (resolve_db_key(db, project_id, database)
               if database in KEYED_FETCHERS else None)
    if database in KEYED_FETCHERS and not key:
        raise ValueError(f"No API key configured for {database}")

    progress(0, 0, f"Searching {database}...")

    def fetch_progress(done: int, total: int):
        progress(done, total, f"Fetching from {database} ({done}/{total})...")

    if database in KEYED_FETCHERS:
        records = KEYED_FETCHERS[database](query, eq_params, cap, fetch_progress, key)
    else:
        records = FETCHERS[database](query, eq_params, cap, fetch_progress)

    n_scanned = len(records)
    if database == "crossref":
        # Crossref cannot evaluate booleans server-side — apply the equation's
        # boolean structure locally on title/abstract.
        records = [r for r in records
                   if matches_structure(r, structure, eq_params.get("fields"))]
        progress(len(records), len(records),
                 f"Kept {len(records)}/{n_scanned} records matching the equation...")

    progress(len(records), len(records), "Archiving raw RIS...")
    filename = archive_raw(project_id, f"{database}.ris",
                           to_ris(records).encode("utf-8"))

    # Living review: while a title/abstract round is active, a new fetch is an
    # update pass — its records land in a new round with their own screening
    # round, so PRISMA keeps the passes apart. Before any screening, the
    # fetch simply extends round 1 (sync_assignments handles late imports).
    from app.services.living.service import (
        count_new_unique, notify_members, open_next_screening_round,
        record_update_run, ta_round_active,
    )
    from app.services.snowballing.service import next_round
    with SessionLocal() as db:
        update_pass = ta_round_active(db, project_id)
        round_ = next_round(db, project_id) if update_pass else 1
        source = get_or_create_source(db, project_id, "database", database, round_)
        imp = store_import(db, project_id=project_id, source_id=source.id,
                           equation_id=params["equation_id"], filename=filename,
                           records=records, user_id=params.get("user_id"),
                           searched_at=datetime.now(timezone.utc),
                           declared_hits=n_scanned,
                           **equation_limits(eq_params))
        db.commit()
        import_id = imp.id
        # golden-set recall on what this search actually brought back (the
        # API check asks the database; this one looks at the records)
        from app.services.equations.recall import recall_from_imports
        recall_from_imports(db, params["equation_id"], database)
        db.commit()

    # dedup right away, so the new records are screenable without a manual step
    def dedup_progress(done: int, total: int):
        progress(done, total, f"Deduplicating ({done}/{total})...")

    with SessionLocal() as db:
        run_dedup(db, project_id, dedup_progress)

    # silent abstract backfill on this import (open APIs only, no UI)
    from app.services.connectors.abstracts import schedule_backfill
    schedule_backfill(project_id, [import_id], params.get("user_id"))

    result = {"n_records": len(records), "n_scanned": n_scanned,
              "import_id": import_id, "archived": filename, "round": round_}
    if update_pass:
        with SessionLocal() as db:
            n_new_unique = count_new_unique(db, [import_id])
            ta_started = False
            if n_new_unique:
                ta_started = open_next_screening_round(db, project_id, round_)
            record_update_run(db, project_id, round_=round_, databases=[database],
                              since_at=None, n_fetched=len(records),
                              n_new_unique=n_new_unique, triggered_by="fetch",
                              errors=None, user_id=params.get("user_id"))
            project_name = db.get(Project, project_id).name
            notify_members(db, project_id, "search_update", {
                "project_name": project_name, "round": round_,
                "n_fetched": len(records), "n_new_unique": n_new_unique,
                "databases": [database], "ta_started": ta_started,
                "triggered_by": "fetch"}, exclude_user=params.get("user_id"))
            db.commit()
        result.update({"n_new_unique": n_new_unique, "ta_round_started": ta_started})

    progress(len(records), len(records), "Done")
    return result
