# SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Bulk PDF import: match uploaded PDFs to the project's records.

Matching order, most to least reliable:
1. DOI found in the text of the first pages (published PDFs carry it on p.1);
2. DOI embedded in the filename (exports often replace '/' with '_' or '-');
3. title found in the first page's text (normalized substring / fuzzy);
4. filename vs title fuzzy (Zotero-style 'Author - Year - Title.pdf').

A confident match is stored immediately (like a manual upload,
via='bulk_import'). Anything ambiguous or unmatched is reported back with
top candidates — the browser still holds the files and lets the user assign
each one by hand through the existing per-record upload endpoint, so no
temporary server-side storage is needed.
"""
import re

from rapidfuzz import fuzz
from sqlalchemy.orm import Session

from app.models import FullText, Record
from app.services.fulltext.service import pdf_dir
from app.services.ris.parse import normalize_doi

# strong-link thresholds (below the fuzzy ones we only report candidates)
TITLE_TEXT_MIN = 93
FILENAME_MIN = 88
CANDIDATE_MIN = 55

# tolerant prefix (registrants are 4-9 digits, but normalize_doi accepts any)
_DOI_RE = re.compile(r"10\.\d+/[^\s\"'<>]+")


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(text or "").lower()).strip()


def _first_pages_text(data: bytes, max_pages: int = 2) -> str:
    import fitz
    try:
        with fitz.open(stream=data, filetype="pdf") as doc:
            return "\n".join(page.get_text()
                             for page in list(doc)[:max_pages])
    except Exception:
        return ""


def build_index(db: Session, project_id: int) -> dict:
    """Match targets: every non-duplicate record of the project."""
    records = (db.query(Record)
               .filter(Record.project_id == project_id,
                       Record.dedup_status != "duplicate").all())
    by_doi = {}
    titled = []
    for r in records:
        if r.doi:
            by_doi.setdefault(r.doi, r)
        key = _norm(r.title)
        if len(key) >= 15:
            titled.append((r, key))
    with_pdf = {ft.record_id for ft in
                db.query(FullText).filter(
                    FullText.record_id.in_([r.id for r in records]))
                if ft.file_path} if records else set()
    return {"by_doi": by_doi, "titled": titled, "with_pdf": with_pdf}


def _doi_in_text(text: str, by_doi: dict[str, Record]) -> Record | None:
    for raw in _DOI_RE.findall(text[:20000]):
        doi = normalize_doi(raw.rstrip(".,;)"))
        if doi and doi in by_doi:
            return by_doi[doi]
    return None


def _doi_in_filename(filename: str, by_doi: dict[str, Record]) -> Record | None:
    name = filename.lower()
    for doi, record in by_doi.items():
        if doi in name or doi.replace("/", "_") in name \
                or doi.replace("/", "-") in name:
            return record
    return None


def _scored_titles(query: str, titled: list) -> list[tuple[Record, float]]:
    scores = [(r, fuzz.partial_ratio(key, query)) for r, key in titled]
    scores.sort(key=lambda x: -x[1])
    return scores


def match_pdf(filename: str, data: bytes, index: dict) -> dict:
    """-> {record, method, candidates:[(record, score)]}; record None if no
    confident single match."""
    text = _first_pages_text(data)

    record = _doi_in_text(text, index["by_doi"])
    if record is not None:
        return {"record": record, "method": "doi_text", "candidates": []}

    record = _doi_in_filename(filename, index["by_doi"])
    if record is not None:
        return {"record": record, "method": "doi_name", "candidates": []}

    # title inside the first page's text — the title is printed on page 1,
    # so a normalized (near-)substring is a strong signal
    norm_text = _norm(text)[:5000]
    if norm_text and index["titled"]:
        scores = _scored_titles(norm_text, index["titled"])
        best, best_score = scores[0]
        runner_up = scores[1][1] if len(scores) > 1 else 0
        if best_score >= TITLE_TEXT_MIN and runner_up < TITLE_TEXT_MIN:
            return {"record": best, "method": "title_text", "candidates": []}

    # filename vs 'Author - Year - Title' patterns
    stem = _norm(re.sub(r"\.pdf$", "", filename, flags=re.I))
    candidates: list[tuple[Record, float]] = []
    if stem and index["titled"]:
        scores = [(r, fuzz.token_set_ratio(key, stem))
                  for r, key in index["titled"]]
        scores.sort(key=lambda x: -x[1])
        best, best_score = scores[0]
        runner_up = scores[1][1] if len(scores) > 1 else 0
        if best_score >= FILENAME_MIN and runner_up < FILENAME_MIN:
            return {"record": best, "method": "title_name", "candidates": []}
        candidates = [(r, s) for r, s in scores[:3] if s >= CANDIDATE_MIN]
    if not candidates and norm_text and index["titled"]:
        candidates = [(r, s) for r, s in
                      _scored_titles(norm_text, index["titled"])[:3]
                      if s >= CANDIDATE_MIN]
    return {"record": None, "method": "", "candidates": candidates}


def store_pdf(db: Session, project_id: int, record: Record, filename: str,
              data: bytes, via: str = "bulk_import") -> FullText:
    """Write the file and upsert the FullText row (same shape as the manual
    per-record upload)."""
    target = pdf_dir(project_id) / f"{record.id}.pdf"
    target.write_bytes(data)
    ft = db.query(FullText).filter_by(record_id=record.id).first()
    if ft is None:
        ft = FullText(record_id=record.id)
        db.add(ft)
    ft.status = "manual"
    ft.via = via
    ft.filename = filename.replace("\\", "/").rsplit("/", 1)[-1][:500]
    ft.file_path = str(target)
    ft.size_kb = round(len(data) / 1024)
    ft.error = ""
    return ft
