# SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Full paginated record fetching from the free scholarly APIs.

Each fetcher takes (query, params, cap, progress) and returns normalized
records (same shape as services.ris.parse). `cap` is the safety ceiling on the
number of records; `progress(done, total)` reports to the job runner.
"""
import json
import re
import time

import httpx

from app.core import polite
from app.core.httpcap import ResponseTooLarge, get_capped
from app.services.connectors.arxiv import parse_arxiv_feed
from app.services.equations.counts import (
    ARXIV_QUERY,
    EUROPEPMC_SEARCH,
    HAL_SEARCH,
    crossref_filters,
    doaj_url,
    openalex_filters,
    pubmed_since_params,
    s2_search_params,
)
from app.services.ris.parse import _parse_nbib, _record

TIMEOUT = httpx.Timeout(60.0)
RETRIES_ON_429 = 3


class FetchError(Exception):
    pass


def _get(client: httpx.Client, url: str, params: dict, *, as_json: bool = True,
         headers: dict | None = None):
    for attempt in range(RETRIES_ON_429 + 1):
        try:
            status, body, _headers, _url = get_capped(
                client, url, params=params, headers=headers)
        except ResponseTooLarge as e:
            raise FetchError(str(e)) from e
        except httpx.HTTPError as e:
            raise FetchError(f"Could not reach {url.split('/')[2]}: {e}") from e
        if status in (429, 503) and attempt < RETRIES_ON_429:
            time.sleep(5 * (attempt + 1))
            continue
        if status >= 400:
            raise FetchError(f"{status} from {url.split('/')[2]}: "
                             f"{body[:200].decode(errors='replace')}")
        return json.loads(body) if as_json else body.decode(errors="replace")
    raise FetchError(f"Rate-limited by {url.split('/')[2]}")


# -- PubMed (esearch history + efetch MEDLINE) -----------------------------------

EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
PUBMED_BATCH = 200


def pubmed_fetch(query: str, params: dict, cap: int, progress) -> list[dict]:
    with httpx.Client(timeout=TIMEOUT, headers=polite.headers(), follow_redirects=True) as client:
        search = _get(client, f"{EUTILS}/esearch.fcgi",
                      {"db": "pubmed", "term": query, "retmax": 0,
                       "usehistory": "y", "retmode": "json",
                       **pubmed_since_params(params),
                       **polite.ncbi_params()})["esearchresult"]
        total = min(int(search["count"]), cap)
        webenv, qk = search.get("webenv"), search.get("querykey")
        records: list[dict] = []
        while len(records) < total:
            progress(len(records), total)
            text = _get(client, f"{EUTILS}/efetch.fcgi",
                        {"db": "pubmed", "WebEnv": webenv, "query_key": qk,
                         "retstart": len(records), "retmax": PUBMED_BATCH,
                         "rettype": "medline", "retmode": "text",
                         **polite.ncbi_params()}, as_json=False)
            batch = _parse_nbib(text)
            if not batch:
                break
            records.extend(batch)
            time.sleep(0.4)  # NCBI: max 3 req/s without key
        return records[:total]


# -- OpenAlex (cursor pagination) --------------------------------------------------

OPENALEX_FIELDS = ("doi,title,authorships,publication_year,primary_location,"
                   "abstract_inverted_index")


def _openalex_abstract(inverted: dict | None) -> str:
    if not inverted:
        return ""
    positions: list[tuple[int, str]] = []
    for word, indexes in inverted.items():
        positions += [(i, word) for i in indexes]
    return " ".join(word for _, word in sorted(positions))


def openalex_fetch(query: str, params: dict, cap: int, progress) -> list[dict]:
    records: list[dict] = []
    cursor = "*"
    with httpx.Client(timeout=TIMEOUT, headers=polite.headers(), follow_redirects=True) as client:
        while cursor and len(records) < cap:
            data = _get(client, "https://api.openalex.org/works", {
                "filter": openalex_filters(query, params),
                "per-page": min(200, cap - len(records)),
                "cursor": cursor,
                "select": OPENALEX_FIELDS,
            })
            total = min(int(data["meta"]["count"]), cap)
            for w in data.get("results", []):
                journal = ((w.get("primary_location") or {}).get("source") or {}
                           ).get("display_name", "")
                records.append(_record(
                    doi=w.get("doi"),
                    title=w.get("title") or "",
                    authors=[(a.get("author") or {}).get("display_name", "")
                             for a in w.get("authorships") or []],
                    year=w.get("publication_year"),
                    journal=journal,
                    abstract=_openalex_abstract(w.get("abstract_inverted_index")),
                ))
            progress(len(records), total)
            cursor = data["meta"].get("next_cursor")
            time.sleep(0.3)
    return records[:cap]


# -- Semantic Scholar (bulk, token pagination) ---------------------------------------

def semanticscholar_fetch(query: str, params: dict, cap: int, progress) -> list[dict]:
    records: list[dict] = []
    token = None
    p = s2_search_params(query, params) | {
        "fields": "title,abstract,year,externalIds,authors,venue"}
    with httpx.Client(timeout=TIMEOUT, headers=polite.headers(), follow_redirects=True) as client:
        while len(records) < cap:
            if token:
                p["token"] = token
            data = _get(client, "https://api.semanticscholar.org/graph/v1/paper/search/bulk", p)
            total = min(int(data.get("total", 0)), cap)
            for w in data.get("data", []):
                records.append(_record(
                    doi=(w.get("externalIds") or {}).get("DOI"),
                    title=w.get("title") or "",
                    authors=[a.get("name", "") for a in w.get("authors") or []],
                    year=w.get("year"),
                    journal=w.get("venue") or "",
                    abstract=w.get("abstract") or "",
                ))
            progress(min(len(records), total), total)
            token = data.get("token")
            if not token or not data.get("data"):
                break
            time.sleep(1.0)  # unauthenticated S2 is strict
    return records[:cap]


# -- Crossref (cursor deep paging; relevance-based, approximate) ----------------------

def crossref_fetch(query: str, params: dict, cap: int, progress) -> list[dict]:
    records: list[dict] = []
    cursor = "*"
    query_param = ("query.title"
                   if set(params.get("fields") or []) == {"title"}
                   else "query.bibliographic")
    filters = crossref_filters(params)
    with httpx.Client(timeout=TIMEOUT, headers=polite.headers(), follow_redirects=True) as client:
        while cursor and len(records) < cap:
            p = {query_param: query, "rows": min(200, cap - len(records)),
                 "cursor": cursor,
                 "select": "DOI,title,author,issued,container-title,abstract"}
            if filters:
                p["filter"] = filters
            message = _get(client, "https://api.crossref.org/works", p)["message"]
            total = min(int(message.get("total-results", 0)), cap)
            items = message.get("items", [])
            if not items:
                break
            for w in items:
                year = ((w.get("issued") or {}).get("date-parts") or [[None]])[0][0]
                records.append(_record(
                    doi=w.get("DOI"),
                    title=(w.get("title") or [""])[0],
                    authors=[" ".join(filter(None, [a.get("given"), a.get("family")]))
                             for a in w.get("author") or []],
                    year=year,
                    journal=(w.get("container-title") or [""])[0],
                    # Crossref abstracts come as JATS XML — strip the markup
                    abstract=re.sub(r"<[^>]+>", " ", w.get("abstract") or ""),
                ))
            progress(len(records), total)
            cursor = message.get("next-cursor")
            time.sleep(0.3)
    return records[:cap]


# -- Europe PMC (cursorMark pagination, core result type for abstracts) ---------------

EUROPEPMC_PAGE = 1000


def _europepmc_authors(w: dict) -> list[str]:
    names = [a.get("fullName", "") for a in ((w.get("authorList") or {}).get("author") or [])]
    if any(names):
        return names
    # lite results only carry "Surname A, Surname B."
    return [s.strip() for s in (w.get("authorString") or "").rstrip(".").split(",")]


def europepmc_fetch(query: str, params: dict, cap: int, progress) -> list[dict]:
    records: list[dict] = []
    cursor = "*"
    with httpx.Client(timeout=TIMEOUT, headers=polite.headers(), follow_redirects=True) as client:
        while cursor and len(records) < cap:
            data = _get(client, EUROPEPMC_SEARCH, {
                "query": query, "format": "json", "resultType": "core",
                "pageSize": min(EUROPEPMC_PAGE, cap - len(records)),
                "cursorMark": cursor})
            total = min(int(data.get("hitCount", 0)), cap)
            results = (data.get("resultList") or {}).get("result") or []
            if not results:
                break
            for w in results:
                journal = (w.get("journalTitle")
                           or (((w.get("journalInfo") or {}).get("journal") or {})
                               .get("title")) or "")
                records.append(_record(
                    doi=w.get("doi"),
                    title=w.get("title") or "",
                    authors=_europepmc_authors(w),
                    year=w.get("pubYear"),
                    journal=journal,
                    abstract=w.get("abstractText") or "",
                ))
            progress(len(records), total)
            next_cursor = data.get("nextCursorMark")
            if len(records) >= total or not next_cursor or next_cursor == cursor:
                break
            cursor = next_cursor
            time.sleep(0.2)
    return records[:cap]


# -- arXiv (Atom feed, offset pagination, 1 request / 3 s) ----------------------------

ARXIV_PAGE = 200


def arxiv_fetch(query: str, params: dict, cap: int, progress) -> list[dict]:
    records: list[dict] = []
    start = 0
    with httpx.Client(timeout=TIMEOUT, headers=polite.headers(), follow_redirects=True) as client:
        while len(records) < cap:
            text = _get(client, ARXIV_QUERY, {
                "search_query": query, "start": start,
                "max_results": min(ARXIV_PAGE, cap - len(records))}, as_json=False)
            total, batch = parse_arxiv_feed(text)
            total = min(total, cap)
            if not batch:
                break
            records.extend(batch)
            progress(min(len(records), total), total)
            start += len(batch)
            if len(records) >= total:
                break
            time.sleep(3.0)  # arXiv API terms of use
    return records[:cap]


# -- HAL (Solr, cursorMark pagination) -------------------------------------------------

HAL_PAGE = 500
HAL_FIELDS = ("docid,doiId_s,title_s,abstract_s,authFullName_s,producedDateY_i,"
              "journalTitle_s,halId_s")


def _first(value) -> str:
    if isinstance(value, list):
        return value[0] if value else ""
    return value or ""


def hal_fetch(query: str, params: dict, cap: int, progress) -> list[dict]:
    records: list[dict] = []
    cursor = "*"
    with httpx.Client(timeout=TIMEOUT, headers=polite.headers(), follow_redirects=True) as client:
        while cursor and len(records) < cap:
            data = _get(client, HAL_SEARCH, {
                "q": query, "wt": "json", "fl": HAL_FIELDS,
                "rows": min(HAL_PAGE, cap - len(records)),
                "sort": "docid asc", "cursorMark": cursor})
            response = data.get("response") or {}
            total = min(int(response.get("numFound", 0)), cap)
            docs = response.get("docs") or []
            if not docs:
                break
            for d in docs:
                records.append(_record(
                    doi=d.get("doiId_s"),
                    title=_first(d.get("title_s")),
                    authors=d.get("authFullName_s") or [],
                    year=d.get("producedDateY_i"),
                    journal=d.get("journalTitle_s") or "",
                    abstract=_first(d.get("abstract_s")),
                ))
            progress(len(records), total)
            next_cursor = data.get("nextCursorMark")
            if len(records) >= total or not next_cursor or next_cursor == cursor:
                break
            cursor = next_cursor
            time.sleep(0.2)
    return records[:cap]


# -- DOAJ (page / pageSize, 100 max, 10,000 deep) -------------------------------------

DOAJ_PAGE = 100
DOAJ_MAX = 10_000


def doaj_fetch(query: str, params: dict, cap: int, progress) -> list[dict]:
    records: list[dict] = []
    page = 1
    url = doaj_url(query)
    with httpx.Client(timeout=TIMEOUT, headers=polite.headers(), follow_redirects=True) as client:
        while len(records) < min(cap, DOAJ_MAX):
            data = _get(client, url, {"page": page,
                                      "pageSize": min(DOAJ_PAGE, cap - len(records))})
            total = min(int(data.get("total", 0)), cap, DOAJ_MAX)
            results = data.get("results") or []
            if not results:
                break
            for w in results:
                b = w.get("bibjson") or {}
                doi = next((i.get("id") for i in b.get("identifier") or []
                            if (i.get("type") or "").lower() == "doi"), None)
                records.append(_record(
                    doi=doi,
                    title=b.get("title") or "",
                    authors=[a.get("name", "") for a in b.get("author") or []],
                    year=b.get("year"),
                    journal=(b.get("journal") or {}).get("title") or "",
                    abstract=b.get("abstract") or "",
                ))
            progress(len(records), total)
            if len(records) >= total:
                break
            page += 1
            time.sleep(0.3)
    return records[:cap]


FETCHERS = {
    "pubmed": pubmed_fetch,
    "openalex": openalex_fetch,
    "semanticscholar": semanticscholar_fetch,
    "crossref": crossref_fetch,
    "europepmc": europepmc_fetch,
    "arxiv": arxiv_fetch,
    "hal": hal_fetch,
    "doaj": doaj_fetch,
}


# -- key-activated connectors (Scopus, IEEE) --------------------------------------

from app.services.equations.counts import (  # noqa: E402
    CORE_SEARCH, IEEE_SEARCH, LENS_INCLUDE, LENS_SEARCH, SCOPUS_SEARCH,
    SPRINGER_SEARCH, WOS_SEARCH, ieee_year_params,
)


def _post(client: httpx.Client, url: str, body: dict, headers: dict | None = None) -> dict:
    """POST a JSON body (Lens); same retry policy as _get."""
    for attempt in range(RETRIES_ON_429 + 1):
        try:
            r = client.post(url, json=body, headers=headers)
        except httpx.HTTPError as e:
            raise FetchError(f"Could not reach {url.split('/')[2]}: {e}") from e
        if r.status_code in (429, 503) and attempt < RETRIES_ON_429:
            time.sleep(5 * (attempt + 1))
            continue
        if r.status_code >= 400:
            raise FetchError(f"{r.status_code} from {url.split('/')[2]}: {r.text[:200]}")
        return r.json()
    raise FetchError(f"Rate-limited by {url.split('/')[2]}")

SCOPUS_PAGE = 25   # STANDARD view page size
IEEE_PAGE = 200    # IEEE hard maximum per request


def scopus_fetch(query: str, params: dict, cap: int, progress, key: str) -> list[dict]:
    """Elsevier Scopus Search API, STANDARD view (no abstract without an
    institutional token). Offset pagination via start+count."""
    records: list[dict] = []
    start = 0
    headers = {"X-ELS-APIKey": key, "Accept": "application/json"}
    with httpx.Client(timeout=TIMEOUT, headers=polite.headers(), follow_redirects=True) as client:
        while len(records) < cap and start < 5000:
            data = _get(client, SCOPUS_SEARCH,
                        {"query": query, "count": min(SCOPUS_PAGE, cap - len(records)),
                         "start": start, "view": "STANDARD"}, headers=headers)
            results = data.get("search-results", {})
            total = min(int(results.get("opensearch:totalResults", 0)), cap)
            entries = results.get("entry", []) or []
            # Scopus signals "no results" with a single entry carrying an error field
            if len(entries) == 1 and entries[0].get("error"):
                break
            for e in entries:
                cover = e.get("prism:coverDate") or ""
                creator = e.get("dc:creator")
                records.append(_record(
                    doi=e.get("prism:doi"),
                    title=e.get("dc:title") or "",
                    authors=[creator] if creator else [],
                    year=int(cover[:4]) if cover[:4].isdigit() else None,
                    journal=e.get("prism:publicationName") or "",
                    abstract=e.get("dc:description") or "",
                ))
            progress(len(records), total)
            start += len(entries)
            if not entries or len(records) >= total:
                break
            time.sleep(0.35)
    return records[:cap]


def ieee_fetch(query: str, params: dict, cap: int, progress, key: str) -> list[dict]:
    """IEEE Xplore Metadata API. Pagination via start_record (1-based)."""
    records: list[dict] = []
    start = 1
    year = ieee_year_params(params)
    with httpx.Client(timeout=TIMEOUT, headers=polite.headers(), follow_redirects=True) as client:
        while len(records) < cap:
            data = _get(client, IEEE_SEARCH, {
                "apikey": key, "querytext": query,
                "max_records": min(IEEE_PAGE, cap - len(records)),
                "start_record": start, "format": "json", **year})
            total = min(int(data.get("total_records", 0)), cap)
            articles = data.get("articles", []) or []
            if not articles:
                break
            for a in articles:
                authors = [au.get("full_name", "")
                           for au in ((a.get("authors") or {}).get("authors") or [])]
                records.append(_record(
                    doi=a.get("doi"),
                    title=a.get("title") or "",
                    authors=[x for x in authors if x],
                    year=a.get("publication_year"),
                    journal=a.get("publication_title") or "",
                    abstract=a.get("abstract") or "",
                ))
            progress(len(records), total)
            start += len(articles)
            if len(records) >= total:
                break
            time.sleep(0.35)
    return records[:cap]


# -- chantier 6b: CORE (offset), Lens (offset ≤ 10 000), Springer (s/p), WoS Starter (page) --

CORE_PAGE = 100
LENS_PAGE = 100
LENS_MAX = 10_000
SPRINGER_PAGE = 50
WOS_PAGE = 50


def core_fetch(query: str, params: dict, cap: int, progress, key: str) -> list[dict]:
    records: list[dict] = []
    offset = 0
    headers = {"Authorization": f"Bearer {key}"}
    with httpx.Client(timeout=TIMEOUT, headers=polite.headers(), follow_redirects=True) as client:
        while len(records) < cap:
            data = _get(client, CORE_SEARCH,
                        {"q": query, "limit": min(CORE_PAGE, cap - len(records)),
                         "offset": offset}, headers=headers)
            total = min(int(data.get("totalHits", 0)), cap)
            results = data.get("results") or []
            if not results:
                break
            for w in results:
                journal = ((w.get("journals") or [{}])[0].get("title")
                           or w.get("publisher") or "")
                records.append(_record(
                    doi=w.get("doi"),
                    title=w.get("title") or "",
                    authors=[a.get("name", "") for a in w.get("authors") or []],
                    year=w.get("yearPublished"),
                    journal=journal,
                    abstract=w.get("abstract") or "",
                ))
            progress(len(records), total)
            offset += len(results)
            if len(records) >= total:
                break
            time.sleep(1.5)  # free-tier quota
    return records[:cap]


def _lens_author(a: dict) -> str:
    name = a.get("display_name") or " ".join(
        filter(None, [a.get("first_name"), a.get("last_name")]))
    return name or ""


def lens_fetch(query: str, params: dict, cap: int, progress, key: str) -> list[dict]:
    records: list[dict] = []
    offset = 0
    headers = {"Authorization": f"Bearer {key}"}
    with httpx.Client(timeout=TIMEOUT, headers=polite.headers(), follow_redirects=True) as client:
        while len(records) < min(cap, LENS_MAX):
            data = _post(client, LENS_SEARCH,
                         {"query": query, "size": min(LENS_PAGE, cap - len(records)),
                          "from": offset, "include": LENS_INCLUDE}, headers=headers)
            total = min(int(data.get("total", 0)), cap, LENS_MAX)
            items = data.get("data") or []
            if not items:
                break
            for w in items:
                doi = next((x.get("value") for x in w.get("external_ids") or []
                            if (x.get("type") or "").lower() == "doi"), None)
                records.append(_record(
                    doi=doi,
                    title=w.get("title") or "",
                    authors=[_lens_author(a) for a in w.get("authors") or []],
                    year=w.get("year_published"),
                    journal=(w.get("source") or {}).get("title") or "",
                    abstract=w.get("abstract") or "",
                ))
            progress(len(records), total)
            offset += len(items)
            if len(records) >= total:
                break
            time.sleep(0.5)
    return records[:cap]


def springer_fetch(query: str, params: dict, cap: int, progress, key: str) -> list[dict]:
    records: list[dict] = []
    start = 1
    with httpx.Client(timeout=TIMEOUT, headers=polite.headers(), follow_redirects=True) as client:
        while len(records) < cap:
            data = _get(client, SPRINGER_SEARCH,
                        {"q": query, "api_key": key, "s": start,
                         "p": min(SPRINGER_PAGE, cap - len(records))})
            total = min(int((data.get("result") or [{}])[0].get("total", 0)), cap)
            items = data.get("records") or []
            if not items:
                break
            for w in items:
                pub = w.get("publicationDate") or ""
                records.append(_record(
                    doi=w.get("doi"),
                    title=w.get("title") or "",
                    authors=[c.get("creator", "") for c in w.get("creators") or []],
                    year=int(pub[:4]) if pub[:4].isdigit() else None,
                    journal=w.get("publicationName") or "",
                    abstract=w.get("abstract") or "",
                ))
            progress(len(records), total)
            start += len(items)
            if len(records) >= total:
                break
            time.sleep(0.3)
    return records[:cap]


def wos_fetch(query: str, params: dict, cap: int, progress, key: str) -> list[dict]:
    """Web of Science Starter: no abstracts in the response (titles only)."""
    records: list[dict] = []
    page = 1
    headers = {"X-ApiKey": key}
    with httpx.Client(timeout=TIMEOUT, headers=polite.headers(), follow_redirects=True) as client:
        while len(records) < cap:
            data = _get(client, WOS_SEARCH,
                        {"db": "WOS", "q": query, "page": page,
                         "limit": min(WOS_PAGE, cap - len(records))}, headers=headers)
            total = min(int((data.get("metadata") or {}).get("total", 0)), cap)
            hits = data.get("hits") or []
            if not hits:
                break
            for h in hits:
                source = h.get("source") or {}
                records.append(_record(
                    doi=(h.get("identifiers") or {}).get("doi"),
                    title=h.get("title") or "",
                    authors=[a.get("displayName", "") for a in
                             ((h.get("names") or {}).get("authors") or [])],
                    year=source.get("publishYear"),
                    journal=source.get("sourceTitle") or "",
                    abstract="",
                ))
            progress(len(records), total)
            page += 1
            if len(records) >= total:
                break
            time.sleep(0.5)
    return records[:cap]


# provider -> fetcher(query, params, cap, progress, key)
KEYED_FETCHERS = {
    "scopus": scopus_fetch,
    "ieee": ieee_fetch,
    "core": core_fetch,
    "lens": lens_fetch,
    "springer": springer_fetch,
    "wos": wos_fetch,
}
