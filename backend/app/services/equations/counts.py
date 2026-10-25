# SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Result-count estimation via the free scholarly APIs (no key required).

Each counter takes the translated query for its database plus the equation
params and returns the number of matching records.
"""
import time
from urllib.parse import quote

import httpx

from app.core import polite
from app.services.equations.translate import discipline_values, doc_type_values
from app.services.living.since import since_date

TIMEOUT = httpx.Timeout(30.0)
RETRIES_ON_429 = 2


class CountError(Exception):
    pass


def _post_json(url: str, body: dict, extra_headers: dict | None = None) -> dict:
    """POST a JSON body (Lens takes its query that way); same retries as _get."""
    headers = {**polite.headers(), **(extra_headers or {})}
    try:
        with httpx.Client(timeout=TIMEOUT, headers=headers,
                          follow_redirects=True) as client:
            for attempt in range(RETRIES_ON_429 + 1):
                r = client.post(url, json=body)
                if r.status_code in (429, 503) and attempt < RETRIES_ON_429:
                    time.sleep(3 * (attempt + 1))
                    continue
                r.raise_for_status()
                return r.json()
    except httpx.HTTPStatusError as e:
        body_text = " ".join(e.response.text.split())[:160]
        raise CountError(f"{e.response.status_code} from {url.split('/')[2]}"
                         + (f": {body_text}" if body_text else "")) from e
    except httpx.HTTPError as e:
        raise CountError(f"Could not reach {url.split('/')[2]}: {e}") from e
    raise CountError(f"Unreachable: {url}")


def _get(url: str, params: dict, extra_headers: dict | None = None,
         as_json: bool = True):
    headers = {**polite.headers(), **(extra_headers or {})}
    try:
        with httpx.Client(timeout=TIMEOUT, headers=headers,
                          follow_redirects=True) as client:
            for attempt in range(RETRIES_ON_429 + 1):
                r = client.get(url, params=params)
                if r.status_code in (429, 503) and attempt < RETRIES_ON_429:
                    time.sleep(3 * (attempt + 1))
                    continue
                r.raise_for_status()
                return r.json() if as_json else r.text
    except httpx.HTTPStatusError as e:
        body = " ".join(e.response.text.split())[:160]
        raise CountError(f"{e.response.status_code} from {url.split('/')[2]}"
                         + (f": {body}" if body else "")) from e
    except httpx.HTTPError as e:
        raise CountError(f"Could not reach {url.split('/')[2]}: {e}") from e
    raise CountError(f"Unreachable: {url}")


def pubmed_since_params(params: dict) -> dict:
    """Living review: only records that entered PubMed since the previous
    pass (Entrez date), as esearch parameters."""
    since = since_date(params)
    if since is None:
        return {}
    return {"datetype": "edat", "mindate": since.strftime("%Y/%m/%d"),
            "maxdate": "3000/12/31"}


def pubmed_count(query: str, params: dict) -> int:
    data = _get("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi",
                {"db": "pubmed", "term": query, "retmax": 0, "retmode": "json",
                 **pubmed_since_params(params), **polite.ncbi_params()})
    return int(data["esearchresult"]["count"])


def openalex_search_filter(params: dict) -> str:
    """OpenAlex filter key matching the equation's fields choice (author
    keywords are not separately searchable — title+abstract is the closest)."""
    fields = set(params.get("fields") or ["title", "abstract"])
    fields.discard("keywords")
    if fields == {"title"}:
        return "title.search"
    if fields == {"abstract"}:
        return "abstract.search"
    return "title_and_abstract.search"


def openalex_filters(query: str, params: dict, extra: str = "") -> str:
    filters = [f"{openalex_search_filter(params)}:{query}"]
    if params.get("year_from"):
        filters.append(f"from_publication_date:{params['year_from']}-01-01")
    if params.get("year_to"):
        filters.append(f"to_publication_date:{params['year_to']}-12-31")
    if params.get("languages"):
        filters.append("language:" + "|".join(params["languages"]))
    types = doc_type_values(params, "openalex")
    if types:
        filters.append("type:" + "|".join(types))
    fields = discipline_values(params, "openalex")
    if fields:
        filters.append("primary_topic.field.id:" + "|".join(fields))
    since = since_date(params)
    if since is not None:
        filters.append(f"from_created_date:{since.isoformat()}")
    if extra:
        filters.append(extra)
    return ",".join(filters)


def openalex_count(query: str, params: dict) -> int:
    data = _get("https://api.openalex.org/works",
                {"filter": openalex_filters(query, params), "per-page": 1})
    return int(data["meta"]["count"])


def s2_search_params(query: str, params: dict) -> dict:
    """Shared S2 bulk-search parameters (counts and full fetch)."""
    p: dict = {"query": query}
    y0, y1 = params.get("year_from"), params.get("year_to")
    since = since_date(params)
    if since is not None:  # S2 has no indexing date: the year is the closest
        y0 = max(int(y0 or 0), since.year)
    if y0 or y1:
        p["year"] = f"{y0 or ''}-{y1 or ''}"
    types = doc_type_values(params, "s2")
    if types:
        p["publicationTypes"] = ",".join(types)
    fields = discipline_values(params, "s2")
    if fields:
        p["fieldsOfStudy"] = ",".join(fields)
    return p


def crossref_filters(params: dict) -> str:
    filters = []
    if params.get("year_from"):
        filters.append(f"from-pub-date:{params['year_from']}-01-01")
    if params.get("year_to"):
        filters.append(f"until-pub-date:{params['year_to']}-12-31")
    filters += [f"type:{t}" for t in doc_type_values(params, "crossref")]
    since = since_date(params)
    if since is not None:
        filters.append(f"from-created-date:{since.isoformat()}")
    return ",".join(filters)


def semanticscholar_count(query: str, params: dict) -> int:
    p = s2_search_params(query, params) | {"fields": "title", "limit": 1}
    data = _get("https://api.semanticscholar.org/graph/v1/paper/search/bulk", p)
    return int(data.get("total", 0))


def crossref_count(query: str, params: dict) -> int:
    query_param = ("query.title"
                   if set(params.get("fields") or []) == {"title"}
                   else "query.bibliographic")
    p: dict = {query_param: query, "rows": 0}
    filters = crossref_filters(params)
    if filters:
        p["filter"] = filters
    data = _get("https://api.crossref.org/works", p)
    return int(data["message"]["total-results"])


# -- open connectors without a key (chantier 6a) ----------------------------------

EUROPEPMC_SEARCH = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
ARXIV_QUERY = "https://export.arxiv.org/api/query"
HAL_SEARCH = "https://api.archives-ouvertes.fr/search/"
DOAJ_SEARCH = "https://doaj.org/api/search/articles/"


def doaj_url(query: str) -> str:
    """DOAJ takes the Elasticsearch query string in the URL path."""
    return DOAJ_SEARCH + quote(query, safe="")


def europepmc_count(query: str, params: dict) -> int:
    data = _get(EUROPEPMC_SEARCH, {"query": query, "format": "json",
                                   "resultType": "lite", "pageSize": 1})
    return int(data.get("hitCount", 0))


def arxiv_count(query: str, params: dict) -> int:
    # imported here: the connectors package pulls fetch.py, which imports us
    from app.services.connectors.arxiv import parse_arxiv_feed
    text = _get(ARXIV_QUERY, {"search_query": query, "start": 0, "max_results": 1},
                as_json=False)
    total, _records = parse_arxiv_feed(text)
    return total


def hal_count(query: str, params: dict) -> int:
    data = _get(HAL_SEARCH, {"q": query, "wt": "json", "rows": 0})
    return int(data["response"]["numFound"])


def doaj_count(query: str, params: dict) -> int:
    data = _get(doaj_url(query), {"page": 1, "pageSize": 1})
    return int(data.get("total", 0))


COUNTERS = {
    "pubmed": pubmed_count,
    "openalex": openalex_count,
    "semanticscholar": semanticscholar_count,
    "crossref": crossref_count,
    "europepmc": europepmc_count,
    "arxiv": arxiv_count,
    "hal": hal_count,
    "doaj": doaj_count,
}


# -- key-activated connectors (Scopus, IEEE) --------------------------------------

SCOPUS_SEARCH = "https://api.elsevier.com/content/search/scopus"
IEEE_SEARCH = "https://ieeexploreapi.ieee.org/api/v1/search/articles"


def ieee_year_params(params: dict) -> dict:
    """IEEE takes the year range as start_year/end_year (not inside querytext)."""
    p: dict = {}
    if params.get("year_from"):
        p["start_year"] = int(params["year_from"])
    if params.get("year_to"):
        p["end_year"] = int(params["year_to"])
    return p


def scopus_count(query: str, params: dict, key: str) -> int:
    # PUBYEAR / DOCTYPE / SUBJAREA are already embedded in the translated query.
    data = _get(SCOPUS_SEARCH, {"query": query, "count": 1},
                extra_headers={"X-ELS-APIKey": key, "Accept": "application/json"})
    return int(data["search-results"]["opensearch:totalResults"])


def ieee_count(query: str, params: dict, key: str) -> int:
    p = {"apikey": key, "querytext": query, "max_records": 1,
         "start_record": 1, "format": "json", **ieee_year_params(params)}
    data = _get(IEEE_SEARCH, p)
    return int(data.get("total_records", 0))


# -- chantier 6b: CORE, Lens.org, Springer Nature, Web of Science Starter ----------------

CORE_SEARCH = "https://api.core.ac.uk/v3/search/works"
LENS_SEARCH = "https://api.lens.org/scholarly/search"
SPRINGER_SEARCH = "https://api.springernature.com/meta/v2/json"
WOS_SEARCH = "https://api.clarivate.com/apis/wos-starter/v1/documents"
LENS_INCLUDE = ["lens_id", "title", "abstract", "authors", "year_published",
                "source.title", "external_ids"]


def core_count(query: str, params: dict, key: str) -> int:
    data = _get(CORE_SEARCH, {"q": query, "limit": 1},
                extra_headers={"Authorization": f"Bearer {key}"})
    return int(data.get("totalHits", 0))


def lens_count(query: str, params: dict, key: str) -> int:
    data = _post_json(LENS_SEARCH, {"query": query, "size": 1, "include": ["lens_id"]},
                      extra_headers={"Authorization": f"Bearer {key}"})
    return int(data.get("total", 0))


def springer_count(query: str, params: dict, key: str) -> int:
    data = _get(SPRINGER_SEARCH, {"q": query, "api_key": key, "s": 1, "p": 1})
    result = (data.get("result") or [{}])[0]
    return int(result.get("total", 0))


def wos_count(query: str, params: dict, key: str) -> int:
    data = _get(WOS_SEARCH, {"db": "WOS", "q": query, "limit": 1, "page": 1},
                extra_headers={"X-ApiKey": key})
    return int((data.get("metadata") or {}).get("total", 0))


# provider -> counter(query, params, key)
KEYED_COUNTERS = {
    "scopus": scopus_count,
    "ieee": ieee_count,
    "core": core_count,
    "lens": lens_count,
    "springer": springer_count,
    "wos": wos_count,
}


def golden_ref_found(query: str, params: dict, doi: str) -> bool:
    """Does the OpenAlex search for this equation retrieve the given DOI?"""
    doi = doi.lower().removeprefix("https://doi.org/").strip("/ ")
    data = _get("https://api.openalex.org/works",
                {"filter": openalex_filters(query, params, extra=f"doi:{doi}"),
                 "per-page": 1})
    return int(data["meta"]["count"]) > 0
