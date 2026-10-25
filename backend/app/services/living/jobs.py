# SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Background job: one search-update pass (living review).

For every API database of the plan (or of the manual request), re-run the
frozen equation restricted to what the database indexed since the previous
pass, import the records under the *next round*, deduplicate against the
whole corpus, open the next title/abstract screening round with the previous
round's rules, write the audit row and notify the members.
"""
from datetime import datetime, time, timezone

from app.core.db import SessionLocal
from app.models import Equation, Project
from app.models.accounts import utcnow
from app.services.connectors.fetch import FETCHERS, KEYED_FETCHERS
from app.services.connectors.jobs import (
    _effective_query, archive_raw, get_or_create_source, store_import,
)
from app.services.connectors.keys import resolve_db_key
from app.services.connectors.postfilter import matches_structure
from app.services.dedup.core import run_dedup
from app.services.living.service import (
    count_new_unique, default_equation_id, default_since, get_plan,
    notify_members, open_next_screening_round, record_update_run,
)
from app.services.living.since import since_date, since_query
from app.services.ris.parse import to_ris
from app.services.snowballing.service import next_round
from app.workers.runner import register_handler


@register_handler("search_update")
def search_update_handler(job_id: int, params: dict, progress) -> dict:
    project_id = int(params["project_id"])
    cap = int(params.get("cap") or 5000)
    triggered_by = params.get("triggered_by") or "manual"
    started_at = utcnow()

    with SessionLocal() as db:
        project = db.get(Project, project_id)
        if project is None:
            raise ValueError("Project not found")
        plan = get_plan(db, project_id)
        databases = list(params.get("databases") or (plan.databases if plan else []))
        equation_id = (params.get("equation_id")
                       or (plan.equation_id if plan else None)
                       or default_equation_id(db, project_id))
        equation = db.get(Equation, equation_id) if equation_id else None
        if equation is None or equation.project_id != project_id:
            raise ValueError("No equation to re-run — freeze one first")
        if not databases:
            raise ValueError("No database selected for the update")
        if params.get("since"):
            d = since_date({"since": params["since"]})
            since = datetime.combine(d, time.min, tzinfo=timezone.utc) if d else None
        else:
            since = default_since(db, project_id)
        queries = {name: _effective_query(equation, name) for name in databases}
        keys = {name: resolve_db_key(db, project_id, name)
                for name in databases if name in KEYED_FETCHERS}
        eq_params = dict(equation.params or {})
        structure = equation.structure or {}
        round_ = next_round(db, project_id)
        project_name = project.name

    if since is not None:
        eq_params["since"] = since.isoformat()

    import_ids: list[int] = []
    errors: dict[str, str] = {}
    n_fetched = 0
    for i, name in enumerate(databases):
        progress(i, len(databases), f"Updating {name} ({i + 1}/{len(databases)})...")
        query = queries.get(name, "")
        if not query.strip():
            errors[name] = "no query on this equation"
            continue
        if name not in FETCHERS and name not in KEYED_FETCHERS:
            errors[name] = "no API fetcher"
            continue
        if name in KEYED_FETCHERS and not keys.get(name):
            errors[name] = "no API key"
            continue
        query = since_query(name, query, since.date() if since else None)

        def fetch_progress(done: int, total: int, _name=name, _i=i):
            progress(_i, len(databases), f"Fetching from {_name} ({done}/{total})...")

        try:
            if name in KEYED_FETCHERS:
                records = KEYED_FETCHERS[name](query, eq_params, cap, fetch_progress,
                                               keys[name])
            else:
                records = FETCHERS[name](query, eq_params, cap, fetch_progress)
        except Exception as e:  # one database down must not void the pass
            errors[name] = str(e)[:300]
            continue
        if name == "crossref":
            records = [r for r in records
                       if matches_structure(r, structure, eq_params.get("fields"))]
        n_fetched += len(records)
        filename = archive_raw(project_id, f"{name}_update_r{round_}.ris",
                               to_ris(records).encode("utf-8"))
        with SessionLocal() as db:
            source = get_or_create_source(db, project_id, "database", name, round_)
            from app.services.connectors.jobs import equation_limits
            imp = store_import(db, project_id=project_id, source_id=source.id,
                               equation_id=equation_id, filename=filename,
                               records=records, user_id=params.get("user_id"),
                               **equation_limits(eq_params))
            db.commit()
            import_ids.append(imp.id)

    if not import_ids:
        raise ValueError("Nothing fetched: " + "; ".join(
            f"{k}: {v}" for k, v in errors.items()) if errors else "Nothing fetched")

    def dedup_progress(done: int, total: int):
        progress(done, total, f"Deduplicating ({done}/{total})...")

    with SessionLocal() as db:
        run_dedup(db, project_id, dedup_progress)

    from app.services.connectors.abstracts import schedule_backfill
    schedule_backfill(project_id, import_ids, params.get("user_id"))

    with SessionLocal() as db:
        n_new_unique = count_new_unique(db, import_ids)
        ta_started = False
        if n_new_unique:
            ta_started = open_next_screening_round(db, project_id, round_)
        run = record_update_run(
            db, project_id, round_=round_, databases=databases, since_at=since,
            n_fetched=n_fetched, n_new_unique=n_new_unique,
            triggered_by=triggered_by, errors=errors,
            user_id=params.get("user_id"), started_at=started_at)
        notify_members(db, project_id, "search_update", {
            "project_name": project_name, "round": round_,
            "n_fetched": n_fetched, "n_new_unique": n_new_unique,
            "databases": databases, "ta_started": ta_started,
            "triggered_by": triggered_by})
        db.commit()
        run_id = run.id

    progress(len(databases), len(databases), "Done")
    return {"round": round_, "n_fetched": n_fetched, "n_new_unique": n_new_unique,
            "databases": databases, "errors": errors, "ta_round_started": ta_started,
            "run_id": run_id, "since": since.isoformat() if since else None}
