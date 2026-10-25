# SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Background job: batch full-text retrieval for a project."""
from concurrent.futures import ThreadPoolExecutor, as_completed

from app.core.db import SessionLocal
from app.core.demo import (DEMO_MAX_RETRIEVE_RECORDS, sandbox_owner,
                           sandbox_storage_error)
from app.models import FullText, Record
from app.services.fulltext.service import (
    included_record_ids,
    pdf_dir,
    resolve_config,
    retrieve_one,
)
from app.workers.runner import register_handler

# Records downloaded concurrently. Each record already fans out across its
# sources inside process_doi (tiers 2/3 run in a per-record thread pool), so a
# handful of records at a time saturates the network without hammering any
# single provider (Unpaywall, CrossRef, publisher pages…).
MAX_PARALLEL_RECORDS = 4


def _retrieve_and_store(project_id: int, record_id: int, settings: dict) -> dict | None:
    """Download one record and persist the outcome. Runs in a worker thread,
    so it opens its own DB session."""
    with SessionLocal() as db:
        record = db.get(Record, record_id)
        if record is None or record.project_id != project_id:
            return None
        title = record.title or record.doi or f"record {record_id}"
        full = (sandbox_storage_error(project_id, 0)
                if settings.get("sandbox") else None)
        if full:
            return {"status": "not_found", "via": "", "error": full,
                    "title": title}
        try:
            outcome = retrieve_one(db, project_id, record, settings)
        except Exception as e:  # one crashed download must not sink the batch
            outcome = {"status": "not_found", "via": "", "filename": "",
                       "oa_url": "", "size_kb": None, "error": str(e)}
        ft = db.query(FullText).filter_by(record_id=record_id).first()
        if ft is None:
            ft = FullText(record_id=record_id)
            db.add(ft)
        ft.status = outcome["status"]
        ft.via = outcome["via"]
        ft.filename = outcome["filename"]
        ft.oa_url = outcome["oa_url"]
        ft.size_kb = outcome["size_kb"]
        ft.error = outcome["error"]
        if outcome["status"] == "retrieved":
            ft.file_path = str(pdf_dir(project_id) / f"{record_id}.pdf")
        db.commit()
    return {"status": outcome["status"], "via": outcome["via"],
            "error": outcome["error"], "title": title}


@register_handler("fulltext_retrieve")
def fulltext_retrieve_handler(job_id: int, params: dict, progress) -> dict:
    project_id = params["project_id"]
    # M4b: caller's browser-held institutional credentials, retrieved from the
    # in-memory stash (single use — never persisted with the job params)
    from app.services.fulltext.ephemeral import pop_institutions
    ephemeral = pop_institutions(params.get("institutions_token"))
    with SessionLocal() as db:
        # demo instances: a visitor's run, or any run in a visitor's project,
        # stays on the open sources — the PDFs land where the visitor reads them
        sandbox = (bool(params.get("sandbox"))
                   or sandbox_owner(db, project_id) is not None)
        settings = resolve_config(db, project_id,
                                  fallback_email=params.get("fallback_email", ""),
                                  sandbox=sandbox)
        if ephemeral and not sandbox:
            # tried before the server-stored ones: the caller launched this run
            # precisely because their institution covers the missing PDFs
            settings["institutions"] = ephemeral + settings.get("institutions", [])
        # M6: demo accounts never reach the optional extension (decided API-side)
        settings["use_extensions"] = (params.get("use_extensions", True)
                                      and not sandbox)
        settings["sandbox"] = sandbox
        record_ids = params.get("record_ids")
        if record_ids:
            # the ids come from the client: keep this project's records only,
            # or a member of one project could rewrite another's full texts
            # (and read their titles in the progress stream)
            owned = {rid for (rid,) in db.query(Record.id).filter(
                Record.project_id == project_id, Record.id.in_(record_ids))}
            record_ids = [r for r in record_ids if r in owned]
        else:
            record_ids = included_record_ids(db, project_id)
        # skip records already retrieved/manual unless re-requested
        if not params.get("force"):
            already = {ft.record_id for ft in db.query(FullText)
                       .filter(FullText.record_id.in_(record_ids),
                               FullText.status.in_(["retrieved", "manual"]))}
            record_ids = [r for r in record_ids if r not in already]
        if sandbox:
            record_ids = record_ids[:DEMO_MAX_RETRIEVE_RECORDS]

    counts = {"retrieved": 0, "not_found": 0}
    total = len(record_ids)
    if record_ids:
        progress(0, total,
                 f"Queued {total} records — {MAX_PARALLEL_RECORDS} at a time...")
        executor = ThreadPoolExecutor(max_workers=min(MAX_PARALLEL_RECORDS, total),
                                      thread_name_prefix="ft-retrieve")
        futures = [executor.submit(_retrieve_and_store, project_id, rid, settings)
                   for rid in record_ids]
        try:
            for done, future in enumerate(as_completed(futures), start=1):
                outcome = future.result()
                detail = f"Retrieving {done}/{total}..."
                if outcome:
                    counts[outcome["status"]] = counts.get(outcome["status"], 0) + 1
                    title = (outcome["title"][:60] + "…"
                             if len(outcome["title"]) > 60 else outcome["title"])
                    if outcome["status"] == "retrieved":
                        detail = f"✓ {title} (via {outcome['via'] or '?'})"
                    else:
                        why = (outcome["error"] or "no source had it")[:80]
                        detail = f"✗ {title} — {why}"
                # progress raises JobCancelled if the user cancelled the job
                progress(done, total, detail)
        finally:
            # on cancel/failure: drop queued downloads, let in-flight ones end
            executor.shutdown(wait=False, cancel_futures=True)

    progress(total, total, "Done")
    return {"processed": total, **counts}
