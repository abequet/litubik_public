# SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Backward/forward snowballing engine — Python port of the user's
BackwardForwardSnowballing tool (the JS module is the specification).

Backward (references cited by a seed): Crossref reference[] + OpenAlex
referenced_works + Semantic Scholar /references + OpenCitations, plus DOIs
extracted from the stored PDF. Forward (articles citing the seed): OpenAlex
cites: filter + Semantic Scholar /citations + OpenCitations.

Every source is queried in full (paginated, safety-capped), then merged with a
DOI-keyed union: refs are first keyed on their normalized DOI (never collapses
two distinct DOIs, never collapses DOI-less placeholder titles), and only
DOI-less refs fall back to fuzzy title matching. DOI-only stubs are hydrated to
full metadata via OpenAlex batches.

A ref dict is {title, doi, authors: list[str], year: int|None, src: str}.
"""
import re
import time

import httpx
from rapidfuzz import fuzz

from app.core import polite
from app.services.ris.parse import normalize_doi

TIMEOUT = httpx.Timeout(45.0)

# safety caps, mirroring SNOWBALL_CONFIG in the JS tool
MAX_FORWARD_PAGES = 30      # OpenAlex cursor pages x 200 -> up to 6000 citing
MAX_S2_PAGES = 10           # S2 pages x 1000 -> up to 10000 items
S2_PAGE_LIMIT = 1000
MAX_RESOLVE_BATCHES = 20    # OpenAlex title-resolution batches x 50
PAGE_DELAY = 0.25           # polite pause between paged requests

_PLACEHOLDER = re.compile(r"^(?:untitled|n/?a|unknown(?:\s+title)?)?$", re.I)


def is_placeholder_title(title) -> bool:
    return bool(_PLACEHOLDER.match(str(title or "").strip()))


def _norm_title(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(s or "").lower())


def _similar(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return fuzz.ratio(a, b) / 100.0


def _ref(title="", doi=None, authors=None, year=None, src="") -> dict:
    return {"title": title or "Untitled", "doi": normalize_doi(doi),
            "authors": authors or [], "year": year, "src": src}


def _get(client: httpx.Client, url: str, params: dict | None = None,
         retries: int = 2):
    """GET returning parsed JSON, or None on any failure (each source is
    best-effort — the union of the others still stands, like the JS tool)."""
    for attempt in range(retries + 1):
        try:
            r = client.get(url, params=params)
        except httpx.HTTPError:
            return None
        if r.status_code in (429, 503) and attempt < retries:
            time.sleep(2.5 * (attempt + 1))
            continue
        if not r.is_success:
            return None
        try:
            return r.json()
        except ValueError:
            return None
    return None


# -- OpenAlex helpers ----------------------------------------------------------------

def _oa_work_to_ref(w: dict) -> dict:
    return _ref(
        title=w.get("title") or "Untitled",
        doi=w.get("doi"),
        authors=[(a.get("author") or {}).get("display_name", "")
                 for a in w.get("authorships") or []],
        year=w.get("publication_year"),
        src="openalex",
    )


def fetch_openalex_work(client: httpx.Client, doi: str) -> dict | None:
    return _get(client, f"https://api.openalex.org/works/doi:{doi}",
                polite.mailto())


def openalex_resolve_ids(client: httpx.Client, ids: list[str]) -> list[dict]:
    """Hydrate OpenAlex work IDs into refs (batches of 50)."""
    out: list[dict] = []
    ids = [str(x).replace("https://openalex.org/", "") for x in (ids or [])]
    for i in range(0, len(ids), 50):
        batch = ids[i:i + 50]
        data = _get(client, "https://api.openalex.org/works", {
            "filter": "ids.openalex:" + "|".join(batch), "per_page": 50,
            "select": "id,doi,title,authorships,publication_year",
            **polite.mailto()})
        if data:
            out += [_oa_work_to_ref(w) for w in (data.get("results") or [])]
        if i + 50 < len(ids):
            time.sleep(PAGE_DELAY)
    return out


def openalex_resolve_dois(client: httpx.Client, dois: list[str],
                          max_batches: int = MAX_RESOLVE_BATCHES) -> list[dict]:
    """Hydrate bare DOIs into refs (batches of 50, capped)."""
    uniq = list(dict.fromkeys(d for d in (normalize_doi(x) for x in dois or []) if d))
    out: list[dict] = []
    for b, i in enumerate(range(0, len(uniq), 50)):
        if b >= max_batches:
            break
        batch = uniq[i:i + 50]
        data = _get(client, "https://api.openalex.org/works", {
            "filter": "doi:" + "|".join(batch), "per_page": 50,
            "select": "id,doi,title,authorships,publication_year",
            **polite.mailto()})
        if data:
            out += [_oa_work_to_ref(w) for w in (data.get("results") or [])]
        if i + 50 < len(uniq):
            time.sleep(PAGE_DELAY)
    return out


def resolve_titles(client: httpx.Client, refs: list[dict]) -> list[dict]:
    """Fill real titles/authors/years for refs that only carry a DOI (frequent
    with Crossref reference lists and OpenCitations)."""
    need = [r for r in refs if r.get("doi") and is_placeholder_title(r.get("title"))]
    if not need:
        return refs
    resolved = openalex_resolve_dois(client, [r["doi"] for r in need])
    by_doi = {r["doi"]: r for r in resolved if r.get("doi")}
    for r in need:
        w = by_doi.get(r["doi"])
        if not w:
            continue
        if not is_placeholder_title(w["title"]):
            r["title"] = w["title"]
        if len(w.get("authors") or []) > len(r.get("authors") or []):
            r["authors"] = w["authors"]
        if not r.get("year") and w.get("year"):
            r["year"] = w["year"]
    return refs


def openalex_citing(client: httpx.Client, oa_id: str) -> list[dict]:
    """All works citing this OpenAlex id, cursor-paginated."""
    out: list[dict] = []
    cursor = "*"
    for _ in range(MAX_FORWARD_PAGES):
        if not cursor:
            break
        data = _get(client, "https://api.openalex.org/works", {
            "filter": f"cites:{oa_id}", "per_page": 200, "cursor": cursor,
            "select": "id,doi,title,authorships,publication_year",
            **polite.mailto()})
        if not data:
            break
        results = (data.get("results") or [])
        out += [_oa_work_to_ref(w) for w in results]
        cursor = (data.get("meta") or {}).get("next_cursor")
        if not results:
            break
        if cursor:
            time.sleep(PAGE_DELAY)
    return out


# -- Semantic Scholar ---------------------------------------------------------------

def s2_paged(client: httpx.Client, doi: str, kind: str) -> list[dict]:
    """kind = 'references' | 'citations' — dedicated paged endpoints (the nested
    ?fields=references.* form is silently capped)."""
    paper_key = "citingPaper" if kind == "citations" else "citedPaper"
    out: list[dict] = []
    offset = 0
    for _ in range(MAX_S2_PAGES):
        data = _get(client,
                    f"https://api.semanticscholar.org/graph/v1/paper/DOI:{doi}/{kind}",
                    {"fields": "title,externalIds,authors,year",
                     "offset": offset, "limit": S2_PAGE_LIMIT})
        if not data:
            break
        rows = data.get("data") or []  # S2 answers "data": null on some papers
        for row in rows:
            p = row.get(paper_key)
            if not p or not p.get("title"):
                continue
            out.append(_ref(
                title=p["title"],
                doi=(p.get("externalIds") or {}).get("DOI"),
                authors=[a.get("name", "") for a in p.get("authors") or []],
                year=p.get("year"), src="s2"))
        if data.get("next") is None or len(rows) < S2_PAGE_LIMIT:
            break
        offset = data["next"]
        time.sleep(PAGE_DELAY)
    return out


# -- OpenCitations -------------------------------------------------------------------

def opencitations(client: httpx.Client, doi: str, kind: str) -> list[dict]:
    """kind = 'references' | 'citations' — DOI-only stubs (hydrated later)."""
    data = _get(client, f"https://api.opencitations.net/index/v2/{kind}/doi:{doi}")
    if not isinstance(data, list):
        return []
    which = "citing" if kind == "citations" else "cited"
    out, seen = [], set()
    for row in data:
        field = (row or {}).get(which) or ""
        m = re.search(r"doi:(\S+)", field, re.I)
        if not m:
            continue
        d = normalize_doi(m.group(1))
        if d and d not in seen:
            seen.add(d)
            out.append(_ref(title="Untitled", doi=d, src="opencitations"))
    return out


# -- Crossref backward ----------------------------------------------------------------

def crossref_refs(client: httpx.Client, doi: str) -> list[dict]:
    data = _get(client, f"https://api.crossref.org/works/{doi}", polite.mailto())
    items = ((data or {}).get("message") or {}).get("reference") or []
    out = []
    for x in items:
        title = x.get("article-title") or ""
        authors = [x["author"]] if x.get("author") else []
        year = x.get("year")
        if not title and x.get("unstructured"):
            parsed = parse_unstructured(x["unstructured"])
            title = parsed["title"] or x["unstructured"]
            authors = authors or ([parsed["authors"]] if parsed["authors"] else [])
            year = year or parsed["year"]
        out.append(_ref(title=title or "Untitled", doi=x.get("DOI"),
                        authors=authors, year=_int_year(year), src="crossref"))
    return out


def _int_year(y) -> int | None:
    m = re.search(r"(1[89]\d{2}|20\d{2})", str(y or ""))
    return int(m.group(1)) if m else None


def parse_unstructured(raw: str) -> dict:
    """Best-effort split of an unstructured citation string
    ('Authors (Year) Title. Journal…' / 'Authors. Title. Journal year;…')."""
    clean = " ".join(str(raw or "").split())
    year = None
    m = re.search(r"\((\d{4})\)", clean)
    if m:
        year = m.group(1)
    else:
        m2 = re.search(r"[\s,](\d{4})(?=[;:,.\s]|$)", clean)
        year = m2.group(1) if m2 else None
    authors, title = "", ""
    if year:
        paren = clean.find(f"({year})")
        idx = paren if paren >= 0 else clean.find(year)
        authors = clean[:idx].strip().strip(",() ")
        after = clean[(paren + len(year) + 2) if paren >= 0 else idx + len(year):]
        after = after.lstrip(").:; ")
        m3 = re.match(r"^(.+?)\.(?:\s+[A-Z]|\s*$)", after)
        title = m3.group(1) if m3 else re.split(r"\.\s", after)[0]
    else:
        parts = re.split(r"\.\s+", clean)
        if len(parts) >= 2:
            authors, title = parts[0], parts[1]
        else:
            title = clean
    return {"title": title.strip().strip("\"'“”"), "authors": authors.strip(),
            "year": year}


# -- union / dedup (port of unionRefs) -------------------------------------------------

def union_refs(groups: list[list[dict]], title_threshold: float = 0.82) -> list[dict]:
    """Order-independent union across ref groups. DOI is the identity key
    (pass 1); only DOI-less refs fall back to fuzzy title matching (pass 2).
    Richer metadata is merged into the kept copy."""
    out: list[dict] = []
    by_doi: dict[str, dict] = {}
    doi_refs: list[dict] = []
    nodoi_norms: list[str] = []

    def merge_into(target: dict, extra: dict):
        if is_placeholder_title(target.get("title")) and not is_placeholder_title(extra.get("title")):
            target["title"] = extra["title"]
        if len(extra.get("authors") or []) > len(target.get("authors") or []):
            target["authors"] = extra["authors"]
        if not target.get("year") and extra.get("year"):
            target["year"] = extra["year"]
        if extra.get("src") and extra["src"] not in str(target.get("src", "")).split("+"):
            target["src"] = (target["src"] + "+" + extra["src"]) if target.get("src") else extra["src"]

    # pass 1 — everything with a DOI
    for group in groups:
        for r in group or []:
            nd = normalize_doi(r.get("doi"))
            if not nd:
                continue
            existing = by_doi.get(nd)
            if existing is not None:
                merge_into(existing, r)
                continue
            kept = {**r, "doi": nd}
            by_doi[nd] = kept
            doi_refs.append(kept)
            out.append(kept)
    doi_norms = ["" if is_placeholder_title(r["title"]) else _norm_title(r["title"])
                 for r in doi_refs]

    # pass 2 — DOI-less refs, fuzzy-matched against DOI'd refs then each other
    for group in groups:
        for r in group or []:
            if normalize_doi(r.get("doi")):
                continue
            if is_placeholder_title(r.get("title")):
                continue  # unidentifiable, cannot dedup safely
            norm = _norm_title(r["title"])
            if len(norm) < 8:
                out.append(r)
                continue
            matched = None
            for i, dn in enumerate(doi_norms):
                if dn and _similar(norm, dn) > title_threshold:
                    matched = doi_refs[i]
                    break
            if matched is not None:
                merge_into(matched, r)
                continue
            if any(_similar(norm, s) > title_threshold for s in nodoi_norms):
                continue
            nodoi_norms.append(norm)
            out.append(r)
    return out


# -- abstract enrichment ----------------------------------------------------------------

def _oa_abstract(inverted: dict | None) -> str:
    """OpenAlex ships abstracts as {word: [positions]}; rebuild the text."""
    if not inverted:
        return ""
    slots: dict[int, str] = {}
    for word, positions in inverted.items():
        for p in positions or []:
            slots[p] = word
    return " ".join(slots[i] for i in sorted(slots))


def _s2_batch(client: httpx.Client, batch: list[str], retries: int = 3) -> list:
    """S2 /paper/batch with backoff — the endpoint 429s aggressively without a key."""
    for attempt in range(retries + 1):
        try:
            r = client.post(
                "https://api.semanticscholar.org/graph/v1/paper/batch",
                params={"fields": "abstract,externalIds"},
                json={"ids": [f"DOI:{d}" for d in batch]})
        except httpx.HTTPError:
            return []
        if r.status_code in (429, 503) and attempt < retries:
            time.sleep(3.0 * (attempt + 1))
            continue
        if not r.is_success:
            return []
        try:
            rows = r.json()
        except ValueError:
            return []
        return rows if isinstance(rows, list) else []
    return []


def _pubmed_abstracts(client: httpx.Client, dois: list[str]) -> dict[str, str]:
    """PubMed tier: esearch DOIs (OR-batched) -> efetch XML -> {doi: abstract}.
    Catches the biomedical publishers whose abstracts OpenAlex/S2 cannot ship
    (Elsevier & co.). Best-effort like every other source."""
    import xml.etree.ElementTree as ET

    pmids: list[str] = []
    for i in range(0, len(dois), 20):
        batch = dois[i:i + 20]
        term = " OR ".join(f'"{d}"[DOI]' for d in batch)
        data = _get(client,
                    "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi",
                    {"db": "pubmed", "term": term, "retmode": "json",
                     "retmax": len(batch), **polite.ncbi_params()})
        pmids += ((data or {}).get("esearchresult") or {}).get("idlist") or []
        time.sleep(0.4)  # NCBI: max 3 req/s without a key

    out: dict[str, str] = {}
    want = set(dois)
    for i in range(0, len(pmids), 100):
        batch = pmids[i:i + 100]
        try:
            r = client.get(
                "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi",
                params={"db": "pubmed", "id": ",".join(batch), "retmode": "xml",
                        **polite.ncbi_params()})
            if not r.is_success:
                continue
            root = ET.fromstring(r.text)
        except (httpx.HTTPError, ET.ParseError):
            continue
        for art in root.iter("PubmedArticle"):
            doi = None
            for aid in art.iter("ArticleId"):
                if aid.get("IdType") == "doi":
                    doi = normalize_doi(aid.text)
            if not doi or doi not in want:
                continue
            parts = [t.text or "" for t in art.iter("AbstractText")]
            abstract = " ".join(p.strip() for p in parts if p and p.strip())
            if abstract:
                out[doi] = abstract
        time.sleep(0.4)
    return out


def fetch_abstracts(client: httpx.Client, dois: list[str],
                    max_batches: int = 100, scrape_cap: int = 150,
                    progress=None) -> dict[str, str]:
    """Abstract per DOI, best-effort, four tiers: OpenAlex batches (inverted
    index), Semantic Scholar /paper/batch, PubMed efetch, then the publisher
    landing pages (scrape_cap max; httpx + Playwright) for the
    publishers who withhold abstracts from every open API (Elsevier, Springer,
    APA, Wiley...). Returns {normalized_doi: abstract}."""
    uniq = list(dict.fromkeys(d for d in (normalize_doi(x) for x in dois or []) if d))
    out: dict[str, str] = {}
    for b, i in enumerate(range(0, len(uniq), 50)):
        if b >= max_batches:
            break
        batch = uniq[i:i + 50]
        data = _get(client, "https://api.openalex.org/works", {
            "filter": "doi:" + "|".join(batch), "per_page": 50,
            "select": "doi,abstract_inverted_index", **polite.mailto()})
        for w in (data or {}).get("results") or []:
            doi = normalize_doi(w.get("doi"))
            abstract = _oa_abstract(w.get("abstract_inverted_index"))
            if doi and abstract:
                out[doi] = abstract
        if i + 50 < len(uniq):
            time.sleep(PAGE_DELAY)

    missing = [d for d in uniq if d not in out]
    for i in range(0, len(missing), 500):
        for row in _s2_batch(client, missing[i:i + 500]):
            if not row or not row.get("abstract"):
                continue
            doi = normalize_doi((row.get("externalIds") or {}).get("DOI"))
            if doi:
                out[doi] = row["abstract"]
        if i + 500 < len(missing):
            time.sleep(PAGE_DELAY)

    missing = [d for d in uniq if d not in out]
    if missing:
        out.update(_pubmed_abstracts(client, missing))

    missing = [d for d in uniq if d not in out]
    if missing and scrape_cap > 0:
        from app.services.snowballing.scrape import page_abstracts
        out.update(page_abstracts(missing, cap=scrape_cap, progress=progress))
    return out


# -- PDF backward supplement ------------------------------------------------------------

_DOI_RE = re.compile(r"10\.\d{4,9}/[^\s,;}\])\"']+")
_REFS_HEAD = re.compile(r"^\s*(references|bibliography|r[ée]f[ée]rences|bibliographie)\b",
                        re.I | re.M)


def pdf_reference_dois(file_path: str, own_doi: str | None = None) -> list[str]:
    """DOIs found in the stored PDF's reference section (fallback: whole text),
    excluding the article's own DOI. The PDFs were retrieved/uploaded at M6."""
    import pymupdf

    try:
        with pymupdf.open(file_path) as doc:
            text = "\n".join(page.get_text() for page in doc)
    except Exception:
        return []
    tail = text
    heads = list(_REFS_HEAD.finditer(text))
    if heads:
        # last heading occurrence = the actual reference section in most layouts
        tail = text[heads[-1].start():]
    own = normalize_doi(own_doi)
    out, seen = [], set()
    for m in _DOI_RE.finditer(tail):
        d = normalize_doi(m.group(0).rstrip(".,;)]}'\""))
        if d and d != own and d not in seen:
            seen.add(d)
            out.append(d)
    return out


# -- per-seed crawls --------------------------------------------------------------------

def backward_refs(client: httpx.Client, doi: str,
                  pdf_path: str | None = None) -> list[dict]:
    """References cited by the seed: Crossref + OpenAlex + S2 + OpenCitations
    (+ DOIs harvested from the stored PDF), unioned and hydrated."""
    cr = crossref_refs(client, doi) if doi else []
    oa: list[dict] = []
    if doi:
        work = fetch_openalex_work(client, doi)
        oa = openalex_resolve_ids(client, (work or {}).get("referenced_works") or [])
    s2 = s2_paged(client, doi, "references") if doi else []
    oc = opencitations(client, doi, "references") if doi else []
    pdf = []
    if pdf_path:
        pdf = [_ref(title="Untitled", doi=d, src="pdf")
               for d in pdf_reference_dois(pdf_path, own_doi=doi)]
    merged = union_refs([oa, s2, cr, oc, pdf])
    return resolve_titles(client, merged)


def forward_refs(client: httpx.Client, doi: str) -> list[dict]:
    """Articles citing the seed: OpenAlex + S2 + OpenCitations, unioned."""
    oa: list[dict] = []
    work = fetch_openalex_work(client, doi)
    oa_id = str((work or {}).get("id") or "").replace("https://openalex.org/", "")
    if oa_id:
        oa = openalex_citing(client, oa_id)
    s2 = s2_paged(client, doi, "citations")
    oc = opencitations(client, doi, "citations")
    merged = union_refs([oa, s2, oc])
    return resolve_titles(client, merged)


def make_client() -> httpx.Client:
    return httpx.Client(timeout=TIMEOUT, headers=polite.headers(), follow_redirects=True)
