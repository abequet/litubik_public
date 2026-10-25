# SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
# SPDX-License-Identifier: AGPL-3.0-or-later
"""DOI -> full reference: Crossref metadata + APA-7 formatting.

Used when a golden-set DOI is added so the user sees the actual paper, not a
bare identifier. Lookup failures never block adding the DOI.
"""
import re

import httpx

from app.core import polite

TIMEOUT = httpx.Timeout(15.0)


def fetch_reference(doi: str) -> dict:
    """{title, year, apa} from Crossref; {} when the lookup fails."""
    try:
        with httpx.Client(timeout=TIMEOUT, headers=polite.headers(),
                          follow_redirects=True) as client:
            r = client.get(f"https://api.crossref.org/works/{doi}")
            r.raise_for_status()
            message = r.json()["message"]
    except (httpx.HTTPError, KeyError, ValueError):
        return {}
    title = (message.get("title") or [""])[0]
    year = _year(message)
    return {"title": title, "year": year, "apa": format_apa(message)}


def _year(message: dict) -> int | None:
    for key in ("published-print", "published-online", "issued"):
        parts = (message.get(key) or {}).get("date-parts") or [[]]
        if parts[0] and parts[0][0]:
            return int(parts[0][0])
    return None


def _format_authors(authors: list[dict]) -> str:
    names = []
    for a in authors:
        family = a.get("family", "").strip()
        given = a.get("given", "").strip()
        if not family:
            if a.get("name"):  # institutional author
                names.append(a["name"])
            continue
        initials = " ".join(f"{part[0]}." for part in given.replace("-", " ").split()
                            if part)
        names.append(f"{family}, {initials}" if initials else family)
    if not names:
        return ""
    if len(names) == 1:
        return names[0]
    if len(names) > 20:  # APA 7: first 19, ellipsis, last
        return ", ".join(names[:19]) + ", … " + names[-1]
    return ", ".join(names[:-1]) + ", & " + names[-1]


def format_apa(message: dict) -> str:
    """APA-7 journal-article reference (plain text) from a Crossref work."""
    authors = _format_authors(message.get("author") or [])
    year = _year(message)
    title = (message.get("title") or [""])[0].rstrip(".")
    journal = (message.get("container-title") or [""])[0]
    volume = message.get("volume", "")
    issue = message.get("issue", "")
    pages = message.get("page", "")
    doi = message.get("DOI", "")

    parts = []
    if authors:
        parts.append(authors if authors.endswith(".") else authors + ".")
    parts.append(f"({year})." if year else "(n.d.).")
    if title:
        parts.append(f"{title}.")
    tail = journal
    if volume:
        tail += f", {volume}"
        if issue:
            tail += f"({issue})"
    if pages:
        tail += f", {pages}"
    if tail:
        parts.append(f"{tail}.")
    if doi:
        parts.append(f"https://doi.org/{doi}")
    return " ".join(p for p in parts if p).strip()


# -- short citation ------------------------------------------------------------

# "(2021)." / "(2021a)." / "(n.d.)." — the date block format_apa always writes
_APA_DATE = re.compile(r"\((n\.d\.|\d{4}[a-z]?)\)\.")
# one "Family, I. I." author inside an author list
_NAMED = re.compile(r"[^,]+,\s+(?:[^\W\d_]\.[\s-]*)+")


def _family(chunk: str) -> str:
    """The family name of one APA author ("Smith, J. R." -> "Smith"); an
    institutional author has no comma and comes back whole."""
    return chunk.split(",")[0].strip(" .")


def _families(authors: str) -> list[str]:
    """Family names in order. Only the first, the last and how many there are
    matter to the caller, so middle authors come back as placeholders."""
    authors = authors.strip().rstrip(". ")
    if not authors:
        return []
    head, sep, last = authors.rpartition(", & ")
    if not sep:  # past 20 authors APA elides the middle with an ellipsis
        head, sep, last = authors.rpartition(", … ")
    if not sep:
        return [_family(authors)]
    n_head = len(_NAMED.findall(head)) or 1
    return [_family(head)] + ["…"] * (n_head - 1) + [_family(last)]


def short_citation(apa: str, year: int | None = None, title: str = "",
                   doi: str = "") -> str:
    """"Smith et al. (2021)" — the in-text form of a stored APA-7 reference.

    Read back from the `apa` string the reference already carries, so it costs
    no lookup and works on references added before this existed. Falls back on
    the title, then the DOI, when the reference has no author list."""
    apa = (apa or "").strip()
    match = _APA_DATE.search(apa)
    date = match.group(1) if match else (str(year) if year else "")
    names = _families(apa[:match.start()] if match else "")
    if names:
        if len(names) == 1:
            lead = names[0]
        elif len(names) == 2:
            lead = f"{names[0]} & {names[1]}"
        else:
            lead = f"{names[0]} et al."
        return f"{lead} ({date})" if date else lead
    label = (title or "").strip()
    if not label:
        return doi or ""
    if len(label) > 70:
        label = label[:69].rstrip() + "…"
    return f"{label} ({date})" if date else label
