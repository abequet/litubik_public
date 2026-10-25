# SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Deduplication engine.

Passes, in order, against the records already accepted as canonical:
1. exact DOI            -> auto-duplicate
2. exact normalized title (long enough) -> auto-duplicate
3. fuzzy title (rapidfuzz token_sort_ratio):
   >= AUTO_THRESHOLD with compatible year (±1) AND matching first author
                     -> auto-duplicate
   >= UNCERTAIN_THRESHOLD with compatible year
                     -> uncertain pair, queued for MANUAL arbitration
                        (user decision: never auto-merge uncertain pairs)

Canonical = the earliest-imported record (lowest id) — its id anchors votes,
full texts and extraction values, so identity never swaps. The CONTENT however
keeps the richest version per field: empty canonical fields (doi/year/journal/
authors/title) are filled from duplicates, and the abstract is replaced
whenever a duplicate carries a fuller one. Re-runnable after every import:
resolved duplicates stay resolved, pairs arbitrated as "distinct" are never
re-flagged, pending pairs are kept. Provenance is merged by pointing
duplicates at the canonical record (their imports/sources stay linked).
"""
import re

from rapidfuzz import fuzz, process
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import DedupPair, Import, Record, Source

AUTO_THRESHOLD = 92.0
UNCERTAIN_THRESHOLD = 85.0
MIN_TITLE_LEN = 15  # exact-title pass ignores very short titles ("Editorial")

def normalize_title(title: str) -> str:
    # strip every non-word character (unicode dashes, quotes, punctuation...)
    return " ".join(re.sub(r"[^\w\s]", " ", str(title or "").lower()).split())


def first_author_key(authors: list) -> str:
    """Family name of the first author, best effort across formats
    ('Dupont, Jean' / 'Jean Dupont' / 'Dupont J')."""
    if not authors:
        return ""
    first = str(authors[0]).strip()
    if "," in first:
        return normalize_title(first.split(",")[0])
    parts = first.split()
    return normalize_title(parts[-1]) if parts else ""


def _years_compatible(a: int | None, b: int | None) -> bool:
    if a is None or b is None:
        return True
    return abs(a - b) <= 1


def _authors_match(a: str, b: str) -> bool:
    if not a or not b:
        return False  # missing author info -> never auto-merge on fuzzy alone
    return a == b or fuzz.partial_ratio(a, b) >= 85


def merge_into(db: Session, duplicate: Record, canonical: Record):
    """Point the duplicate at its canonical record and merge the metadata so
    the canonical carries the richest version of every field."""
    duplicate.dedup_status = "duplicate"
    duplicate.canonical_id = canonical.id
    if not canonical.doi and duplicate.doi:
        canonical.doi = duplicate.doi
    if not canonical.pmid and duplicate.pmid:
        canonical.pmid = duplicate.pmid
    if canonical.year is None and duplicate.year is not None:
        canonical.year = duplicate.year
    if not canonical.journal and duplicate.journal:
        canonical.journal = duplicate.journal
    if not canonical.title and duplicate.title:
        canonical.title = duplicate.title
    if not canonical.authors and duplicate.authors:
        canonical.authors = duplicate.authors
    # abstracts differ in completeness across databases (truncation, missing
    # sections): keep the fullest one wherever it came from
    if len(duplicate.abstract or "") > len(canonical.abstract or ""):
        canonical.abstract = duplicate.abstract


def run_dedup(db: Session, project_id: int, progress=None) -> dict:
    """(Re-)run deduplication over the whole project. Returns the summary."""
    records = (db.query(Record).filter_by(project_id=project_id)
               .order_by(Record.id).all())

    # pairs the humans already ruled on
    distinct_pairs = {
        (p.record_id, p.canonical_id)
        for p in db.query(DedupPair).filter_by(project_id=project_id,
                                               status="distinct")
    }
    pending_pairs = {
        p.record_id: p
        for p in db.query(DedupPair).filter_by(project_id=project_id,
                                               status="pending")
    }

    doi_index: dict[str, Record] = {}
    pmid_index: dict[str, Record] = {}
    title_index: dict[str, Record] = {}
    canonicals: list[Record] = []
    canonical_titles: list[str] = []

    def register(record: Record, norm_title: str):
        if record.doi:
            doi_index.setdefault(record.doi, record)
        if record.pmid:
            pmid_index.setdefault(record.pmid, record)
        if len(norm_title) >= MIN_TITLE_LEN:
            title_index.setdefault(norm_title, record)
        canonicals.append(record)
        canonical_titles.append(norm_title)

    summary = {"checked": 0, "auto_duplicates": 0, "new_uncertain": 0,
               "unique": 0, "kept_pending": 0, "prior_duplicates": 0}

    for i, record in enumerate(records):
        if progress and i % 200 == 0:
            progress(i, len(records))

        if record.dedup_status == "duplicate":
            summary["prior_duplicates"] += 1
            continue  # resolved earlier — never in the candidate pool

        summary["checked"] += 1
        norm_title = normalize_title(record.title)

        # pass 1: exact DOI, then exact PMID (PubMed and EBSCO/MEDLINE
        # exports of the same paper agree on the PMID even when one of them
        # lacks the DOI)
        canonical = doi_index.get(record.doi) if record.doi else None
        reason = "doi"
        if canonical is None and record.pmid:
            canonical = pmid_index.get(record.pmid)
            reason = "pmid"
        # pass 2: exact normalized title
        if canonical is None and len(norm_title) >= MIN_TITLE_LEN:
            canonical = title_index.get(norm_title)
            reason = "title_exact"
        if canonical is not None and (record.id, canonical.id) not in distinct_pairs:
            merge_into(db, record, canonical)
            _record_merged_pair(db, project_id, record, canonical, 100.0, reason,
                                pending_pairs)
            summary["auto_duplicates"] += 1
            continue

        # pass 3: fuzzy title against accepted canonicals
        match = None
        if len(norm_title) >= MIN_TITLE_LEN and canonical_titles:
            match = process.extractOne(
                norm_title, canonical_titles,
                scorer=fuzz.token_sort_ratio,
                score_cutoff=UNCERTAIN_THRESHOLD,
            )
        if match is not None:
            score, candidate = match[1], canonicals[match[2]]
            ruled_distinct = (record.id, candidate.id) in distinct_pairs
            years_ok = _years_compatible(record.year, candidate.year)
            if not ruled_distinct and years_ok:
                if (score >= AUTO_THRESHOLD
                        and _authors_match(first_author_key(record.authors),
                                           first_author_key(candidate.authors))):
                    merge_into(db, record, candidate)
                    _record_merged_pair(db, project_id, record, candidate, score,
                                        "fuzzy_title", pending_pairs)
                    summary["auto_duplicates"] += 1
                    continue
                # uncertainty window -> manual arbitration queue
                record.dedup_status = "uncertain"
                existing = pending_pairs.get(record.id)
                if existing is None:
                    db.add(DedupPair(project_id=project_id, record_id=record.id,
                                     canonical_id=candidate.id, score=score,
                                     reason="fuzzy_title"))
                    summary["new_uncertain"] += 1
                else:
                    summary["kept_pending"] += 1
                register(record, norm_title)  # still matchable by later records
                continue

        record.dedup_status = "unique"
        record.canonical_id = None
        _drop_pending(db, pending_pairs, record)
        summary["unique"] += 1
        register(record, norm_title)

    db.commit()
    if progress:
        progress(len(records), len(records))
    return summary


def _drop_pending(db: Session, pending_pairs: dict, record: Record):
    """A record that got auto-resolved no longer needs arbitration."""
    pair = pending_pairs.pop(record.id, None)
    if pair is not None:
        db.delete(pair)


def _record_merged_pair(db: Session, project_id: int, record: Record,
                        canonical: Record, score: float, reason: str,
                        pending_pairs: dict):
    """Audit every automatic merge as a dedup_pairs row (status=merged) so the
    UI can show what was merged, into what and why."""
    pair = pending_pairs.pop(record.id, None)
    if pair is not None:
        if pair.canonical_id == canonical.id:
            pair.status = "merged"
            pair.score = score
            pair.reason = reason
            return
        db.delete(pair)
        db.flush()  # free the (record_id, canonical_id) key before inserting
    db.add(DedupPair(project_id=project_id, record_id=record.id,
                     canonical_id=canonical.id, score=score, reason=reason,
                     status="merged"))


def dedup_summary(db: Session, project_id: int) -> dict:
    """Live PRISMA-facing counters — always computed from the tables."""
    by_status = dict(
        db.query(Record.dedup_status, func.count(Record.id))
        .filter_by(project_id=project_id)
        .group_by(Record.dedup_status).all()
    )
    per_source = (
        db.query(Source.name, func.count(Record.id))
        .join(Import, Import.source_id == Source.id)
        .join(Record, Record.import_id == Import.id)
        .filter(Record.project_id == project_id)
        .group_by(Source.name).order_by(Source.name).all()
    )
    total = sum(by_status.values())
    return {
        "total": total,
        "pending": by_status.get("pending", 0),
        "unique": by_status.get("unique", 0),
        "duplicate": by_status.get("duplicate", 0),
        "uncertain": by_status.get("uncertain", 0),
        "per_source": [{"source": name, "n": n} for name, n in per_source],
        "pending_pairs": db.query(DedupPair)
                           .filter_by(project_id=project_id, status="pending")
                           .count(),
    }
