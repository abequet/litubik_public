# SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Silent abstract backfill.

Several sources deliver records without an abstract (WoS Starter, Scopus
without an institutional token, many manual exports), and title/abstract
screening needs one. Every search, upload or Zotero import schedules an
`abstract_backfill` job on its own records: open APIs only (OpenAlex,
Semantic Scholar, PubMed — the tiers of `fetch_abstracts`), no publisher
scraping, no UI. Records with a PMID but no DOI are left alone: PubMed
exports already carry their abstract.

The manual `abstract_enrich` job (Snowballing page) shares `fill_abstracts`
and adds the publisher-page tier on top.
"""
from app.core.config import get_settings
from app.core.db import SessionLocal
from app.models import Record
from app.services.ris.parse import normalize_doi
from app.services.snowballing.core import fetch_abstracts, make_client
from app.workers.runner import register_handler


def missing_abstract_rows(db, project_id: int,
                          import_ids: list[int] | None = None) -> list[tuple[int, str]]:
    """(record_id, doi) of the records with a DOI and no abstract — of the
    given imports, or of the whole project."""
    query = (db.query(Record.id, Record.doi)
             .filter(Record.project_id == project_id,
                     Record.doi.isnot(None), Record.doi != "",
                     Record.abstract == ""))
    if import_ids is not None:
        query = query.filter(Record.import_id.in_(import_ids))
    return [(rid, doi) for rid, doi in query.order_by(Record.id).all()]


def fill_abstracts(rows: list[tuple[int, str]], *, scrape_cap: int,
                   progress) -> int:
    """Fetch and store the abstracts of these (record_id, doi) rows; a record
    that gained an abstract meanwhile is never overwritten. Returns the number
    filled."""
    if not rows:
        return 0
    progress(0, len(rows), f"Fetching abstracts for {len(rows)} records...")
    dois = [doi for _, doi in rows]
    with make_client() as client:
        abstracts = fetch_abstracts(
            client, dois, max_batches=len(dois) // 50 + 1,
            scrape_cap=scrape_cap,
            progress=lambda msg: progress(0, len(rows), msg))
    filled = 0
    with SessionLocal() as db:
        for i, (record_id, doi) in enumerate(rows):
            abstract = abstracts.get(normalize_doi(doi) or "")
            if not abstract:
                continue
            record = db.get(Record, record_id)
            if record is not None and not record.abstract:
                record.abstract = abstract
                filled += 1
            if filled and filled % 200 == 0:
                db.commit()
                progress(i, len(rows), f"Saved {filled} abstracts...")
        db.commit()
    progress(len(rows), len(rows), "Done")
    return filled


@register_handler("abstract_backfill")
def abstract_backfill_handler(job_id: int, params: dict, progress) -> dict:
    """Open-API backfill of the abstracts missing from the given imports."""
    project_id = params["project_id"]
    import_ids = [int(i) for i in params.get("import_ids") or []]
    with SessionLocal() as db:
        rows = missing_abstract_rows(db, project_id, import_ids or None)
    filled = fill_abstracts(rows, scrape_cap=0, progress=progress)
    return {"targets": len(rows), "filled": filled}


def schedule_backfill(project_id: int, import_ids: list[int],
                      user_id: int | None) -> int | None:
    """Queue the silent backfill for these imports if anything is missing.
    Returns the job id, or None when there was nothing to fetch."""
    from app.workers.runner import runner
    if not get_settings().abstract_backfill:
        return None
    with SessionLocal() as db:
        if not missing_abstract_rows(db, project_id, import_ids):
            return None
    job = runner.submit("abstract_backfill",
                        {"project_id": project_id, "import_ids": list(import_ids)},
                        project_id=project_id, user_id=user_id)
    return job.id
