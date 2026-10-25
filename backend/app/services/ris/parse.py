# SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Reference-file parsing (RIS / PubMed .nbib / BibTeX / generic CSV) and RIS export.

Every parser returns the same normalized dicts:
    {doi, title, authors: [str], year: int|None, journal, abstract, raw}
`raw` is a RIS rendering of the entry (the original uploaded file is archived
separately for audit).

Field mappings differ per export source (WoS vs EBSCO vs ACM…) — parsers are
deliberately tolerant: unknown fields are ignored, missing ones default empty.
"""
import csv
import io
import re

import rispy

IMPORT_EXTENSIONS = {".ris", ".txt", ".nbib", ".bib", ".csv"}


class ImportFileError(Exception):
    pass


def normalize_doi(value: str | None) -> str | None:
    if not value:
        return None
    doi = str(value).strip().lower()
    doi = re.sub(r"^https?://(dx\.)?doi\.org/", "", doi)
    doi = doi.strip("/ ").split(" ")[0]
    return doi if doi.startswith("10.") else None


def _year(value) -> int | None:
    m = re.search(r"(1[89]\d{2}|20\d{2})", str(value or ""))
    return int(m.group(1)) if m else None


def normalize_pmid(value) -> str | None:
    """A PubMed id as digits, from "12345678", "PMID: 12345678", "pubmed/…",
    or an EBSCO/MEDLINE accession number — anything else is not a PMID."""
    if value is None:
        return None
    text = str(value).strip()
    if re.match(r"^(https?://(dx\.)?doi\.org/)?10\.", text, flags=re.I):
        return None  # a DOI whose suffix is numeric is still a DOI
    m = re.search(r"(?:^|pmid[:\s]*|/)\s*(\d{1,9})/?\s*$", text, flags=re.I)
    if m is None:
        return None
    pmid = m.group(1).lstrip("0")
    return pmid or None


def _record(doi=None, title="", authors=None, year=None, journal="", abstract="",
            pmid=None) -> dict:
    rec = {
        "doi": normalize_doi(doi),
        "pmid": normalize_pmid(pmid),
        "title": " ".join(str(title or "").split()),
        "authors": [a for a in (authors or []) if str(a).strip()],
        "year": _year(year),
        "journal": " ".join(str(journal or "").split()),
        "abstract": str(abstract or "").strip(),
    }
    rec["raw"] = to_ris([rec])
    return rec


def to_ris(records: list[dict]) -> str:
    """Normalized records -> RIS text (archives + M11 exports)."""
    entries = []
    for r in records:
        entry = {"type_of_reference": "JOUR", "title": r.get("title", ""),
                 "authors": r.get("authors", [])}
        if r.get("year"):
            entry["year"] = str(r["year"])
        if r.get("journal"):
            entry["secondary_title"] = r["journal"]
        if r.get("abstract"):
            entry["abstract"] = r["abstract"]
        if r.get("doi"):
            entry["doi"] = r["doi"]
        if r.get("pmid"):
            entry["id"] = r["pmid"]  # RIS "ID" tag, as PubMed's own exports do
        entries.append(entry)
    return rispy.dumps(entries)


def parse_file(filename: str, data: bytes) -> list[dict]:
    """Parse an uploaded reference file into normalized records."""
    ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in IMPORT_EXTENSIONS:
        raise ImportFileError(
            f"Unsupported file type '{ext or filename}' — use .ris, .nbib, .bib or .csv")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = data.decode("latin-1")

    if ext == ".bib":
        records = _parse_bibtex(text)
    elif ext == ".csv":
        records = _parse_csv(text)
    elif ext == ".nbib" or (ext == ".txt" and "PMID- " in text[:2000]):
        records = _parse_nbib(text)
    else:
        records = _parse_ris(text)
    if not records:
        raise ImportFileError("No reference could be parsed from this file")
    return records


# -- RIS ------------------------------------------------------------------------

def _parse_ris(text: str) -> list[dict]:
    """Parse RIS with rispy (strict, well-tested for standard exports), falling
    back to a tolerant line parser when rispy yields nothing — real exports
    often use single-space tags (`TY - JOUR`) or omit the trailing `ER  -`,
    both of which rispy 0.10 silently drops."""
    # Real exports have inconsistent line endings — IEEE Xplore, for one, ends
    # records with CRLF but glues a stray CR to the next `TY`, which makes rispy
    # see only the first record. Normalize to LF so every record is recognized.
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    try:
        entries = rispy.loads(text, skip_unknown_tags=True)
    except Exception:
        entries = []
    records = []
    for e in entries:
        records.append(_record(
            doi=e.get("doi"),
            # PubMed RIS carries the PMID in ID; EBSCO's MEDLINE exports in AN
            pmid=e.get("id") or e.get("accession_number"),
            title=e.get("title") or e.get("primary_title") or "",
            authors=(e.get("authors") or e.get("first_authors") or [])
                    + (e.get("secondary_authors") or []),
            year=e.get("year") or e.get("publication_year"),
            journal=e.get("secondary_title") or e.get("journal_name")
                    or e.get("alternate_title1") or "",
            abstract=e.get("abstract") or e.get("notes_abstract") or "",
        ))
    return records or _parse_ris_lenient(text)


# Tag line: two-char RIS tag, then (per spec) two spaces + hyphen + space, but
# tolerate any spacing around the hyphen and a missing trailing space.
_RIS_TAG = re.compile(r"^([A-Z][A-Z0-9]) {0,3}-\s?(.*)$")

# Tolerant field aliases -> normalized field (first non-empty wins).
_RIS_AUTHOR = ("AU", "A1", "A2", "A3", "A4", "FAU")
_RIS_YEAR = ("PY", "Y1", "DA")
_RIS_JOURNAL = ("JO", "JF", "JA", "T2", "J2")
_RIS_DOI = ("DO", "DI")
_RIS_PMID = ("ID", "AN")


def _parse_ris_lenient(text: str) -> list[dict]:
    """Line-based RIS parser tolerant of single-space tags and missing `ER`.
    A new record begins at each `TY` tag (or after an `ER`)."""
    records: list[dict] = []
    current: dict[str, list[str]] | None = None
    last_tag: str | None = None

    def flush() -> None:
        nonlocal current
        if not current:
            current = None
            return

        def first(keys):
            for k in keys:
                if current.get(k):
                    return current[k][0]
            return ""
        authors = [a for key in _RIS_AUTHOR for a in current.get(key, [])]
        title = " ".join(current.get("TI") or current.get("T1") or [])
        abstract = " ".join(current.get("AB") or current.get("N2") or [])
        if title or authors or first(_RIS_DOI):
            records.append(_record(
                doi=first(_RIS_DOI), pmid=first(_RIS_PMID), title=title,
                authors=authors, year=first(_RIS_YEAR),
                journal=first(_RIS_JOURNAL), abstract=abstract))
        current = None

    for raw in text.splitlines():
        line = raw.lstrip("﻿").rstrip()
        m = _RIS_TAG.match(line)
        if not m:
            if current is not None and last_tag and line.strip():
                current.setdefault(last_tag, [""])
                current[last_tag][-1] = (current[last_tag][-1] + " "
                                         + line.strip()).strip()
            continue
        tag, value = m.group(1), m.group(2).strip()
        if tag == "TY":
            flush()
            current, last_tag = {}, None
            continue
        if tag == "ER":
            flush()
            last_tag = None
            continue
        if current is None:
            current = {}
        current.setdefault(tag, []).append(value)
        last_tag = tag
    flush()
    return records


# -- PubMed / MEDLINE .nbib -------------------------------------------------------

def _parse_nbib(text: str) -> list[dict]:
    records = []
    for block in re.split(r"\n\s*\n", text.strip()):
        fields: dict[str, list[str]] = {}
        tag = None
        for line in block.splitlines():
            m = re.match(r"^([A-Z0-9]{2,4})\s*- (.*)$", line)
            if m:
                tag = m.group(1)
                fields.setdefault(tag, []).append(m.group(2))
            elif tag and line.startswith("      "):
                fields[tag][-1] += " " + line.strip()
        if not fields:
            continue
        doi = None
        for key in ("LID", "AID"):
            for value in fields.get(key, []):
                if "[doi]" in value:
                    doi = value.replace("[doi]", "").strip()
        records.append(_record(
            doi=doi,
            pmid=(fields.get("PMID") or [None])[0],
            title=" ".join(fields.get("TI", [])),
            authors=fields.get("FAU") or fields.get("AU") or [],
            year=(fields.get("DP") or [""])[0],
            journal=(fields.get("JT") or fields.get("TA") or [""])[0],
            abstract=" ".join(fields.get("AB", [])),
        ))
    return records


# -- BibTeX -----------------------------------------------------------------------

def _strip_tex(value: str) -> str:
    return re.sub(r"[{}]", "", value or "").strip()


def _parse_bibtex(text: str) -> list[dict]:
    import bibtexparser
    from bibtexparser.bparser import BibTexParser

    parser = BibTexParser(common_strings=True)
    parser.ignore_nonstandard_types = False
    try:
        database = bibtexparser.loads(text, parser)
    except Exception as e:
        raise ImportFileError(f"Could not parse BibTeX: {e}") from e
    records = []
    for e in database.entries:
        authors = [a.strip() for a in
                   re.split(r"\s+and\s+", _strip_tex(e.get("author", "")))
                   if a.strip()]
        records.append(_record(
            doi=e.get("doi"),
            title=_strip_tex(e.get("title", "")),
            authors=authors,
            year=e.get("year"),
            journal=_strip_tex(e.get("journal") or e.get("booktitle") or ""),
            abstract=_strip_tex(e.get("abstract", "")),
        ))
    return records


# -- generic CSV --------------------------------------------------------------------

CSV_COLUMNS = {
    "doi": ["doi", "di"],
    "pmid": ["pmid", "pubmed id", "pubmed_id", "pm"],
    "title": ["title", "article title", "document title", "ti"],
    "authors": ["authors", "author", "au", "author full names"],
    "year": ["year", "publication year", "py", "date"],
    "journal": ["journal", "source title", "publication", "so", "journal title"],
    "abstract": ["abstract", "ab"],
}


def _parse_csv(text: str) -> list[dict]:
    # the header line is the most reliable place to detect the delimiter
    # (author cells often contain commas)
    header = text.lstrip().splitlines()[0] if text.strip() else ""
    delimiter = max(",;\t", key=header.count)
    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
    if not reader.fieldnames:
        raise ImportFileError("Empty CSV")
    mapping = {}
    lowered = {str(f).strip().lower(): f for f in reader.fieldnames}
    for target, aliases in CSV_COLUMNS.items():
        for alias in aliases:
            if alias in lowered:
                mapping[target] = lowered[alias]
                break
    if "title" not in mapping:
        raise ImportFileError(
            "CSV has no recognizable Title column (found: "
            + ", ".join(str(f) for f in reader.fieldnames) + ")")
    records = []
    for row in reader:
        get = lambda k: row.get(mapping[k], "") if k in mapping else ""  # noqa: E731
        if not str(get("title")).strip():
            continue
        records.append(_record(
            doi=get("doi"),
            pmid=get("pmid"),
            title=get("title"),
            authors=[a.strip() for a in re.split(r"[;|]", str(get("authors") or ""))
                     if a.strip()],
            year=get("year"),
            journal=get("journal"),
            abstract=get("abstract"),
        ))
    return records
