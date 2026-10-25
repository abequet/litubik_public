# SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Date restriction of an update pass: "records the database indexed since
the previous pass".

Two mechanisms, chosen per provider:
- the parameter-based APIs (PubMed, OpenAlex, Crossref, Semantic Scholar)
  read `params["since"]` inside their own filter helpers (`equations/counts.py`),
  so the fetcher signatures stay `fn(query, params, cap, progress[, key])`;
- the query-syntax APIs get an extra clause appended to the translated query
  here. Semantic Scholar and IEEE Xplore cannot filter by indexing date:
  S2 is restricted to the year, IEEE re-fetches everything — dedup absorbs
  the overlap in both cases.
"""
from datetime import date, datetime


def since_date(params: dict) -> date | None:
    raw = params.get("since")
    if not raw:
        return None
    if isinstance(raw, datetime):
        return raw.date()
    if isinstance(raw, date):
        return raw
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00")).date()
    except ValueError:
        return None


def since_query(database: str, query: str, since: date | None) -> str:
    """The translated query with the provider's own "indexed since" clause."""
    if since is None or not query.strip():
        return query
    iso = since.isoformat()
    compact = since.strftime("%Y%m%d")
    if database == "europepmc":
        return f"({query}) AND FIRST_IDATE:[{iso} TO 3000-12-31]"
    if database == "arxiv":
        return f"({query}) AND submittedDate:[{compact}0000 TO 210012312359]"
    if database == "hal":
        return f"({query}) AND submittedDate_tdate:[{iso}T00:00:00Z TO *]"
    if database == "doaj":
        return f"({query}) AND created_date:[{iso}T00:00:00Z TO *]"
    if database == "scopus":
        return f"({query}) AND LOAD-DATE AFT {compact}"
    if database == "core":
        return f"({query}) AND createdDate>=\"{iso}\""
    if database == "lens":
        return f"({query}) AND created:[{iso} TO *]"
    return query


# providers whose restriction is exact (indexing date); the others over-fetch
EXACT_SINCE = frozenset({"pubmed", "openalex", "crossref", "europepmc", "arxiv",
                         "hal", "doaj", "scopus", "core", "lens"})
