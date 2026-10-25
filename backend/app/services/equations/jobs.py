# SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Background jobs: API counts for an equation, golden-set recall per database."""
import time

from app.core.db import SessionLocal
from app.models import Equation, EquationCount, GoldenRef
from app.services.connectors.keys import resolve_db_key
from app.services.equations import counts as counters
from app.workers.runner import register_handler


def _effective_query(equation: Equation, database: str) -> str:
    translations = equation.translations or {}
    override = (translations.get("overrides") or {}).get(database, "")
    return override or (translations.get("auto") or {}).get(database, "")


@register_handler("equation_counts")
def equation_counts_handler(job_id: int, params: dict, progress) -> dict:
    """Fetch result counts for one equation on the requested API databases."""
    with SessionLocal() as db:
        equation = db.get(Equation, params["equation_id"])
        if equation is None:
            raise ValueError("Equation not found")
        project_id = equation.project_id
        # keyed connectors (Scopus/IEEE) are usable only where a key is configured
        keys = {p: resolve_db_key(db, project_id, p)
                for p in counters.KEYED_COUNTERS}
        databases = [d for d in params["databases"]
                     if d in counters.COUNTERS
                     or (d in counters.KEYED_COUNTERS and keys.get(d))]
        queries = {d: _effective_query(equation, d) for d in databases}
        eq_params = equation.params or {}

    results: dict[str, dict] = {}
    for i, database in enumerate(databases):
        progress(i, len(databases), f"Counting on {database}...")
        query = queries[database]
        if not query.strip():
            results[database] = {"error": "empty query"}
            continue
        try:
            if database in counters.KEYED_COUNTERS:
                n = counters.KEYED_COUNTERS[database](query, eq_params, keys[database])
            else:
                n = counters.COUNTERS[database](query, eq_params)
        except counters.CountError as e:
            results[database] = {"error": str(e)}
            continue
        results[database] = {"count": n}
        with SessionLocal() as db:
            db.add(EquationCount(equation_id=params["equation_id"],
                                 database_name=database, count=n, method="api"))
            db.commit()
        time.sleep(0.4)  # stay well under the public API rate limits
    progress(len(databases), len(databases), "Done")
    return {"results": results}


@register_handler("equation_draft_all")
def equation_draft_all_handler(job_id: int, params: dict, progress) -> dict:
    """Draft the syntax of every target database of a raw equation from the
    query typed for `from_db`, one LLM call each, stored as unreviewed AI
    drafts. A failing database does not stop the others."""
    from app.services.equations import drafting, project_databases
    from app.services.llm.base import LLMError

    with SessionLocal() as db:
        equation = db.get(Equation, params["equation_id"])
        if equation is None:
            raise ValueError("Equation not found")
        project_id = equation.project_id
        registry = {d["id"]: d for d in project_databases(db, project_id)}
        from_db = params.get("from_db") or "pubmed"
        wanted = params.get("databases") or drafting.targets(
            equation, registry, from_db, params.get("mode") or "missing")
        wanted = [d for d in wanted if d in registry and d != from_db]

    drafted, errors = [], {}
    for i, to_db in enumerate(wanted):
        progress(i, len(wanted), f"Drafting the {registry[to_db]['label']} syntax...")
        with SessionLocal() as db:
            equation = db.get(Equation, params["equation_id"])
            if equation is None or equation.status == "frozen":
                break
            try:
                result = drafting.draft_query(db, project_id, equation, registry,
                                              from_db, to_db, params.get("user_id"))
            except (ValueError, LLMError) as e:
                errors[to_db] = str(e)
                continue
            if not result["query"]:
                errors[to_db] = "empty draft"
                continue
            drafting.store_draft(equation, to_db, from_db, result)
            db.commit()
            drafted.append(to_db)
    progress(len(wanted), len(wanted), "Done")
    return {"drafted": drafted, "errors": errors, "from_db": from_db}


@register_handler("golden_check")
def golden_check_handler(job_id: int, params: dict, progress) -> dict:
    """Golden-set recall of one equation, database by database: the API
    check on every requested database that supports it, then the import
    check on every source with records. One EquationRecall row each."""
    from app.services.equations import recall as recall_svc

    results: dict[str, dict] = {}
    with SessionLocal() as db:
        equation = db.get(Equation, params["equation_id"])
        if equation is None:
            raise ValueError("Equation not found")
        if not db.query(GoldenRef).filter_by(project_id=equation.project_id).count():
            raise ValueError("Golden set is empty — add reference DOIs or PMIDs first")
        project_id = equation.project_id
        checkable = recall_svc.api_checkable(db, project_id)
        databases = [d for d in (params.get("databases") or checkable)
                     if d in checkable]
        keys = {d: resolve_db_key(db, project_id, d)
                for d in databases if d in recall_svc.KEYED_CHECKERS}
        imported = recall_svc.imported_databases(db, equation)

    n_steps = len(databases) + len(imported)
    for i, database in enumerate(databases):
        progress(i, n_steps, f"Asking {database}...")
        with SessionLocal() as db:
            equation = db.get(Equation, params["equation_id"])
            try:
                row = recall_svc.recall_via_api(
                    db, equation, database, key=keys.get(database),
                    progress=lambda a, b, msg: progress(i, n_steps, msg))
            except (ValueError, counters.CountError) as e:
                results[database] = {"error": str(e)}
                continue
            db.commit()
            results[database] = {"found": row.found, "total": row.total,
                                 "method": "api"}
    for j, database in enumerate(imported):
        progress(len(databases) + j, n_steps, f"Looking into the {database} import...")
        with SessionLocal() as db:
            row = recall_svc.recall_from_imports(db, params["equation_id"], database)
            if row is not None:
                db.commit()
                results[f"{database} (import)"] = {
                    "found": row.found, "total": row.total, "method": "import"}
    progress(n_steps, n_steps, "Done")
    return {"results": results}
