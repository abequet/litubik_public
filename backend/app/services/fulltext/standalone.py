# SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Standalone paper download: a pasted list of DOIs, outside any project.

Same source cascade and same file naming as the project batch retrieval
(`process_doi`), but nothing is attached to a record: the PDFs land in a
per-job scratch folder the submitter then downloads from — the PDF itself when
there is one, a zip when there are several.
"""
import re
import shutil
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from app.core.db import SessionLocal
from app.models import FulltextConfig
from app.services.fulltext.jobs import MAX_PARALLEL_RECORDS
from app.services.fulltext.service import _decrypt_institutions, _pdf_is_blank
from app.workers.runner import register_handler

MAX_DOIS = 200
# scratch folders are swept on the next submission once they are this old
KEEP_SECONDS = 24 * 3600

_DOI_RE = re.compile(r"10\.\d{4,9}/[^\s,;\"'<>]+", re.IGNORECASE)


def parse_dois(text: str) -> list[str]:
    """Every DOI found in a pasted blob — bare, `doi:`-prefixed or as a
    doi.org URL, separated by anything. Order kept, duplicates dropped."""
    seen: dict[str, str] = {}
    for match in _DOI_RE.findall(text or ""):
        doi = match.rstrip(".,;]}")
        # a closing parenthesis belongs to the DOI only if it was opened there
        while doi.endswith(")") and doi.count(")") > doi.count("("):
            doi = doi[:-1].rstrip(".,;]}")
        seen.setdefault(doi.lower(), doi)
    return list(seen.values())


def scratch_root() -> Path:
    # system temp, not the data dir: these files are nobody's data and must
    # stay out of instance backups
    path = Path(tempfile.gettempdir()) / "litubik_paper_downloads"
    path.mkdir(parents=True, exist_ok=True)
    return path


def job_dir(job_id: int) -> Path:
    return scratch_root() / str(job_id)


def sweep_old_downloads() -> None:
    cutoff = time.time() - KEEP_SECONDS
    for child in scratch_root().iterdir():
        try:
            if child.is_dir() and child.stat().st_mtime < cutoff:
                shutil.rmtree(child, ignore_errors=True)
        except OSError:
            continue


def _download_one(doi: str, settings: dict) -> tuple[dict, bytes | None]:
    from app.services.fulltext.downloader import process_doi

    try:
        result, pdf_bytes = process_doi(
            doi, email=settings["email"],
            institutions=settings["institutions"] or None,
            use_extensions=settings["use_extensions"])
    except Exception as e:  # one crashed download must not sink the batch
        return {"doi": doi, "error": str(e)}, None
    if pdf_bytes and _pdf_is_blank(pdf_bytes):
        result["error"] = (f"Blank/empty PDF discarded "
                           f"(source: {result.get('source') or 'unknown'})")
        return result, None
    return result, pdf_bytes


@register_handler("paper_download")
def paper_download_handler(job_id: int, params: dict, progress) -> dict:
    from app.services.fulltext.ephemeral import pop_institutions

    dois: list[str] = params["dois"]
    ephemeral = pop_institutions(params.get("institutions_token"))
    with SessionLocal() as db:
        global_cfg = db.query(FulltextConfig).filter_by(project_id=None).first()
        settings = {
            "email": ((global_cfg and global_cfg.unpaywall_email)
                      or params.get("fallback_email", "")),
            # the caller's own access first, then the app-wide institutions
            "institutions": ephemeral + _decrypt_institutions(global_cfg),
            "use_extensions": params.get("use_extensions", True),
        }

    target = job_dir(job_id)
    # job ids restart after a database reset/restore: never serve the leftovers
    # of an older run that had the same id
    shutil.rmtree(target, ignore_errors=True)
    target.mkdir(parents=True, exist_ok=True)
    total = len(dois)
    items: dict[str, dict] = {}
    taken: set[str] = set()
    progress(0, total, f"Queued {total} DOIs — {MAX_PARALLEL_RECORDS} at a time...")
    executor = ThreadPoolExecutor(max_workers=min(MAX_PARALLEL_RECORDS, total),
                                  thread_name_prefix="paper-dl")
    futures = {executor.submit(_download_one, doi, settings): doi for doi in dois}
    try:
        for done, future in enumerate(as_completed(futures), start=1):
            doi = futures[future]
            result, pdf_bytes = future.result()
            label = result.get("title") or doi
            label = label[:60] + "…" if len(label) > 60 else label
            item = {"doi": doi, "title": result.get("title") or "",
                    "status": "not_found", "via": "", "filename": "",
                    "oa_url": result.get("oa_url") or "", "error": ""}
            if pdf_bytes:
                # same naming as the batch retrieval; suffix the collisions
                stem = Path(result.get("filename") or "paper.pdf").stem
                base, n = stem, 1
                while stem.lower() in taken:
                    n += 1
                    stem = f"{base}_{n}"
                taken.add(stem.lower())
                (target / f"{stem}.pdf").write_bytes(pdf_bytes)
                item.update(status="retrieved", via=result.get("source") or "",
                            filename=f"{stem}.pdf")
                detail = f"✓ {label} (via {item['via'] or '?'})"
            else:
                item["error"] = result.get("error") or "No PDF found"
                detail = f"✗ {label} — {item['error'][:80]}"
            items[doi] = item
            # progress raises JobCancelled if the user cancelled the job
            progress(done, total, detail)
    finally:
        executor.shutdown(wait=False, cancel_futures=True)

    ordered = [items[doi] for doi in dois if doi in items]
    retrieved = sum(1 for i in ordered if i["status"] == "retrieved")
    progress(total, total, "Done")
    return {"processed": total, "retrieved": retrieved,
            "not_found": total - retrieved, "items": ordered}
