# SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Search-equation generation and per-database syntax translation.

An equation variant is a snapshot: `structure` = the selected concepts with
their keywords at creation time (so a frozen equation never changes when the
concept list evolves), `params` = {year_from, year_to, languages, fields}.

`structure["concepts"]` is a list of blocks AND-ed together, each block a list
of keywords OR-ed together. Several concepts can share a block (see
`build_structure`) — that is how "Population OR Setting" is expressed without
leaving the AND-of-ORs shape the translators below assume.

`fields` (subset of title/abstract/keywords, default title+abstract) selects
where each database searches; every database has its own field-tag syntax and
not every combination exists everywhere — the mapping below uses the closest
documented tag (noted in the per-database instructions when approximate).

Every generated string stays hand-editable in the UI (stored as an override).
"""

FIELD_CHOICES = ("title", "abstract", "keywords")
DEFAULT_FIELDS = ["title", "abstract"]

# Registry of the databases we translate to. count: "api" = automatic count
# via a free API; "manual" = the app shows the string + step-by-step export
# instructions and the user types the count in.
DATABASES: list[dict] = [
    {"id": "pubmed", "label": "PubMed", "count": "api",
     "instructions": "Field mapping: title→[ti], title+abstract→[tiab] (abstract "
                     "alone is not searchable, [tiab] is used), with keywords→[tw]."},
    {"id": "openalex", "label": "OpenAlex", "count": "api",
     "instructions": "Fields map to the title.search / abstract.search / "
                     "title_and_abstract.search filters (author keywords are not "
                     "separately searchable — title+abstract is used)."},
    {"id": "semanticscholar", "label": "Semantic Scholar", "count": "api",
     "instructions": "S2 always searches title+abstract — the fields option does "
                     "not apply. Syntax: | = OR, + = AND."},
    {"id": "crossref", "label": "Crossref", "count": "api",
     "instructions": "Crossref's API has no boolean search — the string is a flat "
                     "keyword list and the count is a huge relevance-ranked "
                     "approximation. When fetching, the app re-applies the "
                     "equation's boolean logic locally on title/abstract and only "
                     "imports matching records."},
    {"id": "europepmc", "label": "Europe PMC", "count": "api",
     "instructions": "Fields map to TITLE: / ABSTRACT: (title+abstract = both, "
                     "OR-ed per term; keywords → KW:). Covers PubMed, PMC and the "
                     "bioRxiv / medRxiv / ChemRxiv / Research Square / SSRN "
                     "preprints: tick the 'Preprint' document type to include "
                     "them (SRC:PPR) — there is no separate bioRxiv card."},
    {"id": "arxiv", "label": "arXiv", "count": "api",
     "instructions": "Fields map to ti: / abs: (no author-keyword field: all: is "
                     "used when keywords are selected); the year range filters "
                     "the submission date. The API allows one request every 3 s, "
                     "so large fetches are slow. Records get the DataCite DOI "
                     "10.48550/arXiv.<id> unless the feed carries a publisher DOI."},
    {"id": "hal", "label": "HAL (open archive)", "count": "api",
     "instructions": "French open archive, all disciplines. Fields map to "
                     "title_t: / abstract_t: / keyword_t:; the year is "
                     "producedDateY_i. Many deposits are notices without a full "
                     "abstract."},
    {"id": "doaj", "label": "DOAJ", "count": "api",
     "instructions": "Articles of open-access journals only. Fields map to "
                     "bibjson.title: / bibjson.abstract: / bibjson.keywords:; the "
                     "year is bibjson.year. Language and document type cannot be "
                     "filtered; the API stops at 10,000 results per query."},
    {"id": "wos", "label": "Web of Science", "count": "manual",
     "instructions": "Web of Science > Advanced Search. Paste the query, apply the "
                     "same year range, then report the result count here. TS= covers "
                     "title, abstract and keywords. With a Web of Science Starter API "
                     "key (subscribers, through the institution's library) the card "
                     "fetches automatically; the Starter API returns no abstracts, so "
                     "screening relies on titles unless the abstracts are backfilled."},
    {"id": "scopus", "label": "Scopus", "count": "manual",
     "instructions": "Scopus > Advanced search. Paste the query, press Search, "
                     "then report the result count here."},
    {"id": "ieee", "label": "IEEE Xplore", "count": "manual",
     "instructions": "IEEE Xplore > Advanced Search > Command Search. Paste the "
                     "query, apply the year range in the sidebar, report the count."},
    {"id": "core", "label": "CORE", "count": "manual",
     "instructions": "World aggregator of open-access full texts. Needs a free CORE "
                     "API key (core.ac.uk/services/api). Fields map to title: / "
                     "abstract: (keywords are not a separate field); the year is "
                     "yearPublished. The free tier is rate-limited, so large fetches "
                     "are slow."},
    {"id": "lens", "label": "Lens.org", "count": "manual",
     "instructions": "Crossref, PubMed, OpenAlex and CORE aggregated. Needs a Lens "
                     "scholarly API token (free for non-commercial use, requested on "
                     "lens.org). Fields map to title: / abstract: / keyword:; the year "
                     "is year_published. Fetches stop at 10,000 results per query."},
    {"id": "springer", "label": "Springer Nature", "count": "manual",
     "instructions": "Springer, Nature and BMC journals. Needs a free Springer Nature "
                     "Meta API key (dev.springernature.com). Only the title is "
                     "searchable by field (title:); title+abstract searches the whole "
                     "record; keywords map to keyword:. A year range expands to one "
                     "year: term per year."},
    {"id": "ebsco", "label": "EBSCO (PsycINFO/PsycARTICLES)", "count": "manual",
     "instructions": "EBSCOhost > Advanced Search. Paste the query in the first box, "
                     "set the year limiter, report the count."},
    {"id": "acm", "label": "ACM Digital Library", "count": "manual",
     "instructions": "ACM DL > Advanced Search > 'Search Within'. Paste the "
                     "query, set 'Publication Date', report the count."},
    {"id": "trid", "label": "TRID (Transport Research)", "count": "manual",
     "url": "https://trid.trb.org/Results",
     "instructions": "TRID > the field boxes on the right of the results page. "
                     "TRID has no in-box field tags: paste the query in the box "
                     "matching the fields you selected — Title, Abstract, or "
                     "Index Terms for keywords. For any combination, paste it in "
                     "Keyword, which searches title, abstract, index terms and "
                     "notes at once and is therefore broader than title+abstract. "
                     "Year range, language and subject areas are sidebar filters, "
                     "not query syntax: apply the same year range there, then "
                     "report the count."},
    {"id": "compendex", "label": "Compendex (Engineering Village)", "count": "manual",
     "instructions": "Engineering Village > Expert search. Paste the query: each "
                     "block is written ((terms) WN KY) — KY searches subject, "
                     "title and abstract; title-only uses WN TI, abstract-only "
                     "WN AB. The year range is appended as (y0-y1 WN YR). Report "
                     "the count, then export (RIS) and drop the file."},
    {"id": "googlescholar", "label": "Google Scholar", "count": "manual",
     "instructions": "Google Scholar has no field tags (title-only adds intitle: "
                     "per term), keeps only ~256 characters and has no export — "
                     "paste the query, set the custom year range, report the "
                     "approximate count. For records, export via Zotero or "
                     "Publish-or-Perish (see M3 assisted import)."},
]

# Syntaxes a project-declared database may borrow (id → label shown in the UI).
# "generic" = plain boolean, no field tags — the safe default.
SYNTAX_CHOICES: list[dict] = (
    [{"id": "generic", "label": "Generic boolean (no field tags)"}]
    + [{"id": db["id"], "label": db["label"]} for db in DATABASES]
)

PUBMED_LANG = {"en": "english", "fr": "french", "de": "german", "es": "spanish",
               "it": "italian", "pt": "portuguese", "nl": "dutch"}
# Europe PMC LANG: codes (ISO 639-2/B)
EUROPEPMC_LANG = {"en": "eng", "fr": "fre", "de": "ger", "es": "spa",
                  "it": "ita", "pt": "por", "nl": "dut"}

# Document types, mapped to each provider's own vocabulary where it exists
# (None = the provider cannot filter this type; the type is simply not applied).
DOC_TYPES = [
    {"id": "article", "label": "Journal article",
     "pubmed": "journal article", "openalex": "article", "s2": "JournalArticle",
     "crossref": "journal-article", "wos": "Article", "scopus": "ar",
     "europepmc": 'PUB_TYPE:"journal article"', "hal": "ART"},
    {"id": "review", "label": "Review",
     "pubmed": "review", "openalex": "review", "s2": "Review",
     "crossref": None, "wos": "Review", "scopus": "re",
     "europepmc": 'PUB_TYPE:"review"', "hal": None},
    {"id": "conference", "label": "Conference paper",
     "pubmed": None, "openalex": None, "s2": "Conference",
     "crossref": "proceedings-article", "wos": "Proceedings Paper", "scopus": "cp",
     "europepmc": None, "hal": "COMM"},
    {"id": "book_chapter", "label": "Book chapter",
     "pubmed": None, "openalex": "book-chapter", "s2": "BookSection",
     "crossref": "book-chapter", "wos": "Book Chapter", "scopus": "ch",
     "europepmc": None, "hal": "COUV"},
    {"id": "preprint", "label": "Preprint",
     "pubmed": "preprint", "openalex": "preprint", "s2": None,
     "crossref": "posted-content", "wos": None, "scopus": None,
     "europepmc": "SRC:PPR", "hal": "UNDEFINED"},
]
DOC_TYPE_IDS = [d["id"] for d in DOC_TYPES]

# Disciplines = the 26 ASJC top-level fields: native on OpenAlex
# (primary_topic.field.id, live-verified) and Scopus (SUBJAREA); approximate
# on Semantic Scholar (fieldsOfStudy) and WoS (SU= research areas); the other
# databases ignore them (filter applied "when possible", as the UI says).
_ASJC = [
    (11, "Agricultural & Biological Sciences", "AGRI",
     "Agricultural and Food Sciences", "Agriculture"),
    (12, "Arts & Humanities", "ARTS", "Art", "Arts & Humanities - Other Topics"),
    (13, "Biochemistry & Molecular Biology", "BIOC", "Biology",
     "Biochemistry & Molecular Biology"),
    (14, "Business & Management", "BUSI", "Business", "Business & Economics"),
    (15, "Chemical Engineering", "CENG", None, "Engineering"),
    (16, "Chemistry", "CHEM", "Chemistry", "Chemistry"),
    (17, "Computer Science", "COMP", "Computer Science", "Computer Science"),
    (18, "Decision Sciences", "DECI", None, "Operations Research & Management Science"),
    (19, "Earth & Planetary Sciences", "EART", "Geology", "Geology"),
    (20, "Economics & Finance", "ECON", "Economics", "Business & Economics"),
    (21, "Energy", "ENER", None, "Energy & Fuels"),
    (22, "Engineering", "ENGI", "Engineering", "Engineering"),
    (23, "Environmental Science", "ENVI", "Environmental Science",
     "Environmental Sciences & Ecology"),
    (24, "Immunology & Microbiology", "IMMU", "Biology", "Immunology"),
    (25, "Materials Science", "MATE", "Materials Science", "Materials Science"),
    (26, "Mathematics", "MATH", "Mathematics", "Mathematics"),
    (27, "Medicine", "MEDI", "Medicine", "General & Internal Medicine"),
    (28, "Neuroscience", "NEUR", None, "Neurosciences & Neurology"),
    (29, "Nursing", "NURS", None, "Nursing"),
    (30, "Pharmacology & Pharmaceutics", "PHAR", None, "Pharmacology & Pharmacy"),
    (31, "Physics & Astronomy", "PHYS", "Physics", "Physics"),
    (32, "Psychology", "PSYC", "Psychology", "Psychology"),
    (33, "Social Sciences", "SOCI", "Sociology", "Social Sciences - Other Topics"),
    (34, "Veterinary", "VETE", None, "Veterinary Sciences"),
    (35, "Dentistry", "DENT", None, "Dentistry, Oral Surgery & Medicine"),
    (36, "Health Professions", "HEAL", None, "Health Care Sciences & Services"),
]
DISCIPLINES = [
    {"id": code.lower(), "label": label, "openalex": f"fields/{num}",
     "s2": s2, "scopus": code, "wos": wos}
    for num, label, code, s2, wos in _ASJC
]
DISCIPLINE_IDS = [d["id"] for d in DISCIPLINES]
_DISCIPLINES_BY_ID = {d["id"]: d for d in DISCIPLINES}
_DOC_TYPES_BY_ID = {d["id"]: d for d in DOC_TYPES}


def doc_type_values(params: dict, provider: str) -> list[str]:
    """Provider-specific values for the selected doc types (unsupported skipped)."""
    values = [(_DOC_TYPES_BY_ID[t] or {}).get(provider)
              for t in params.get("doc_types") or [] if t in _DOC_TYPES_BY_ID]
    return [v for v in values if v]


def discipline_values(params: dict, provider: str) -> list[str]:
    values = [(_DISCIPLINES_BY_ID[d] or {}).get(provider)
              for d in params.get("disciplines") or [] if d in _DISCIPLINES_BY_ID]
    return [v for v in values if v]


def build_structure(groups: list[list]) -> dict:
    """Snapshot the selected Concept rows into an equation structure.

    Each group is one block of the equation; blocks are AND-ed, keywords inside
    a block are OR-ed. A block holding several concepts ORs them together —
    which is exactly the union of their keyword lists, since
    `(a OR b) OR (c OR d)` is `(a OR b OR c OR d)`. The structure therefore
    stays the flat AND-of-ORs every translator already knows how to render;
    `members` only records which concepts were merged, for display and for the
    PRISMA-S search report.
    """
    blocks = []
    for group in groups:
        keywords, seen = [], set()
        for concept in group:
            for kw in concept.keywords:
                kw = str(kw).strip()
                if kw and kw.lower() not in seen:
                    seen.add(kw.lower())
                    keywords.append(kw)
        block = {"name": " OR ".join(c.name for c in group), "keywords": keywords,
                 "members": [{"id": c.id, "name": c.name} for c in group]}
        if len(group) == 1:  # same shape as the pre-blocks snapshots
            block["id"] = group[0].id
        blocks.append(block)
    return {"concepts": blocks}


def translate_all(structure: dict, params: dict, extra: dict | None = None) -> dict:
    """{database_id: query string} for every database in the registry.

    `extra` = {db_id: syntax} for the project's own declared databases
    (services/equations — `syntax` is a registry id or "generic")."""
    ids = {db["id"]: db["id"] for db in DATABASES}
    for db_id, syntax in (extra or {}).items():
        ids[db_id] = syntax if syntax in _TRANSLATORS else "generic"
    concepts = [c for c in structure.get("concepts", []) if c.get("keywords")]
    if not concepts:
        return {db_id: "" for db_id in ids}
    return {db_id: _TRANSLATORS[syntax](concepts, params)
            for db_id, syntax in ids.items()}


# -- helpers ------------------------------------------------------------------

def _fields(params: dict) -> frozenset:
    fields = [f for f in params.get("fields") or DEFAULT_FIELDS if f in FIELD_CHOICES]
    return frozenset(fields or DEFAULT_FIELDS)


def _quote(kw: str) -> str:
    kw = kw.strip().replace('"', '')
    return f'"{kw}"' if " " in kw else kw


def _group(keywords: list, sep: str = " OR ", wrap=_quote) -> str:
    return "(" + sep.join(wrap(k) for k in keywords) + ")"


def _years(params: dict) -> tuple:
    return params.get("year_from"), params.get("year_to")


def _generic(concepts: list) -> str:
    return " AND ".join(_group(c["keywords"]) for c in concepts)


# -- one translator per database ------------------------------------------------

def _pubmed(concepts: list, params: dict) -> str:
    fields = _fields(params)
    if "keywords" in fields:
        suffix = "[tw]"      # Text Word: title, abstract, MeSH & author keywords
    elif fields == {"title"}:
        suffix = "[ti]"
    else:
        suffix = "[tiab]"    # abstract alone is not addressable in PubMed

    def tag(kw: str) -> str:
        return f'"{kw.strip().replace(chr(34), "")}"{suffix}'
    q = " AND ".join(_group(c["keywords"], wrap=tag) for c in concepts)
    y0, y1 = _years(params)
    if y0 or y1:
        q += f' AND ("{y0 or "1800"}"[dp] : "{y1 or "3000"}"[dp])'
    langs = [PUBMED_LANG[l] for l in params.get("languages", []) if l in PUBMED_LANG]
    if langs:
        q += " AND (" + " OR ".join(f"{l}[la]" for l in langs) + ")"
    types = doc_type_values(params, "pubmed")
    if types:
        q += " AND (" + " OR ".join(f"{t}[pt]" for t in types) + ")"
    return q


def _openalex(concepts: list, params: dict) -> str:
    # boolean string; the fields choice selects the OpenAlex search filter
    # (title.search / abstract.search / title_and_abstract.search) in the
    # count connector and in M3 fetching.
    return _generic(concepts)


def _semanticscholar(concepts: list, params: dict) -> str:
    # S2 bulk-search syntax: | = OR, + = AND, quotes for phrases.
    # S2 searches title+abstract; no field selection exists.
    def grp(c):
        return "(" + " | ".join(_quote(k) for k in c["keywords"]) + ")"
    return " + ".join(grp(c) for c in concepts)


def _crossref(concepts: list, params: dict) -> str:
    # Crossref has no boolean search — flat keyword soup, count is approximate.
    return " ".join(k for c in concepts for k in c["keywords"])


def _wos(concepts: list, params: dict) -> str:
    fields = _fields(params)
    base = _generic(concepts)
    if "keywords" in fields:
        q = f"TS=({base})"           # topic = title + abstract + keywords
    elif fields == {"title"}:
        q = f"TI=({base})"
    elif fields == {"abstract"}:
        q = f"AB=({base})"
    else:
        q = f"(TI=({base}) OR AB=({base}))"
    y0, y1 = _years(params)
    if y0 or y1:
        q += f" AND PY=({y0 or 1900}-{y1 or 2100})"
    types = doc_type_values(params, "wos")
    if types:
        q += " AND DT=(" + " OR ".join(_quote(t) for t in types) + ")"
    subjects = discipline_values(params, "wos")
    if subjects:
        q += " AND SU=(" + " OR ".join(_quote(s) for s in subjects) + ")"
    return q


def _scopus(concepts: list, params: dict) -> str:
    fields = _fields(params)
    if "keywords" in fields:
        tag = "TITLE-ABS-KEY"
    elif fields == {"title"}:
        tag = "TITLE"
    elif fields == {"abstract"}:
        tag = "ABS"
    else:
        tag = "TITLE-ABS"
    q = f"{tag}({_generic(concepts)})"
    y0, y1 = _years(params)
    if y0:
        q += f" AND PUBYEAR > {int(y0) - 1}"
    if y1:
        q += f" AND PUBYEAR < {int(y1) + 1}"
    types = doc_type_values(params, "scopus")
    if types:
        q += " AND (" + " OR ".join(f"DOCTYPE({t})" for t in types) + ")"
    subjects = discipline_values(params, "scopus")
    if subjects:
        q += " AND (" + " OR ".join(f"SUBJAREA({s})" for s in subjects) + ")"
    return q


IEEE_FIELDS = {"title": "Document Title", "abstract": "Abstract",
               "keywords": "Author Keywords"}


def _ieee(concepts: list, params: dict) -> str:
    names = [IEEE_FIELDS[f] for f in ("title", "abstract", "keywords")
             if f in _fields(params)]

    def tag(kw: str) -> str:
        alts = " OR ".join(f'"{n}":{_quote(kw)}' for n in names)
        return f"({alts})" if len(names) > 1 else alts
    return " AND ".join(_group(c["keywords"], wrap=tag) for c in concepts)


EBSCO_FIELDS = {"title": "TI", "abstract": "AB", "keywords": "KW"}


def _ebsco(concepts: list, params: dict) -> str:
    tags = [EBSCO_FIELDS[f] for f in ("title", "abstract", "keywords")
            if f in _fields(params)]

    def grp(c):
        inner = " OR ".join(_quote(k) for k in c["keywords"])
        return "(" + " OR ".join(f"{t} ({inner})" for t in tags) + ")"
    return " AND ".join(grp(c) for c in concepts)


ACM_FIELDS = {"title": "Title", "abstract": "Abstract", "keywords": "Keyword"}


def _acm(concepts: list, params: dict) -> str:
    tags = [ACM_FIELDS[f] for f in ("title", "abstract", "keywords")
            if f in _fields(params)]

    def grp(c):
        inner = " OR ".join(_quote(k) for k in c["keywords"])
        return "(" + " OR ".join(f"{t}:({inner})" for t in tags) + ")"
    return " AND ".join(grp(c) for c in concepts)


def _googlescholar(concepts: list, params: dict) -> str:
    # implicit AND between groups; GS truncates queries around 256 chars.
    if _fields(params) == {"title"}:
        def tag(kw: str) -> str:
            return f"intitle:{_quote(kw)}"
        return " ".join(_group(c["keywords"], wrap=tag) for c in concepts)
    return " ".join(_group(c["keywords"]) for c in concepts)


def _compendex(concepts: list, params: dict) -> str:
    # Engineering Village expert search: ((a OR b) WN KY) AND ((c) WN KY);
    # KY = subject/title/abstract, TI = title, AB = abstract. Years are a
    # (y0-y1 WN YR) clause; languages and doc types are sidebar limiters.
    fields = _fields(params)
    if fields == {"title"}:
        code = "TI"
    elif fields == {"abstract"}:
        code = "AB"
    else:
        code = "KY"
    q = " AND ".join(f"({_group(c['keywords'])} WN {code})" for c in concepts)
    y0, y1 = _years(params)
    if y0 or y1:
        q += f" AND ({y0 or 1884}-{y1 or 2100} WN YR)"
    return q


def _trid(concepts: list, params: dict) -> str:
    # TRID takes uppercase AND/OR/NOT, quoted phrases and parentheses — the
    # shape `_generic` already produces — but has no field tag usable inside a
    # box: the fields choice picks *which* box (Title / Abstract / Index Terms,
    # or Keyword for a combination), which the instructions spell out. Years,
    # languages and subject areas are sidebar filters there, never query
    # syntax, so they stay out of the string.
    return _generic(concepts)


def _fielded(concepts: list, params: dict, title_tag: str, abstract_tag: str,
             keyword_tag: str | None) -> str:
    """Lucene / Solr style: every term carries the tag of each selected field,
    OR-ed — `(TITLE:"a b" OR ABSTRACT:"a b")` — the shape Europe PMC, arXiv,
    HAL and DOAJ all accept. A keyword tag of None folds keywords into the
    other two (the provider has no author-keyword field)."""
    fields = _fields(params)
    tags: list[str] = []
    if "title" in fields:
        tags.append(title_tag)
    if "abstract" in fields:
        tags.append(abstract_tag)
    if "keywords" in fields and keyword_tag:
        tags.append(keyword_tag)
    tags = list(dict.fromkeys(tags)) or [title_tag]

    def term(kw: str) -> str:
        q = _quote(kw)
        if len(tags) == 1:
            return f"{tags[0]}{q}"
        return "(" + " OR ".join(f"{tag}{q}" for tag in tags) + ")"
    return " AND ".join(_group(c["keywords"], wrap=term) for c in concepts)


def _europepmc(concepts: list, params: dict) -> str:
    q = _fielded(concepts, params, "TITLE:", "ABSTRACT:", "KW:")
    y0, y1 = _years(params)
    if y0 or y1:
        q += f" AND PUB_YEAR:[{y0 or 1800} TO {y1 or 3000}]"
    langs = [EUROPEPMC_LANG[l] for l in params.get("languages", []) if l in EUROPEPMC_LANG]
    if langs:
        q += " AND (" + " OR ".join(f"LANG:{l}" for l in langs) + ")"
    types = doc_type_values(params, "europepmc")
    if types:
        q += " AND (" + " OR ".join(types) + ")"
    return q


def _arxiv(concepts: list, params: dict) -> str:
    # arXiv has no keyword field: with keywords selected, search everything
    fields = _fields(params)
    if "keywords" in fields:
        q = _fielded(concepts, params, "all:", "all:", None)
    else:
        q = _fielded(concepts, params, "ti:", "abs:", None)
    y0, y1 = _years(params)
    if y0 or y1:
        q += (f" AND submittedDate:[{y0 or 1991}01010000 TO "
              f"{y1 or 2100}12312359]")
    return q


def _hal(concepts: list, params: dict) -> str:
    q = _fielded(concepts, params, "title_t:", "abstract_t:", "keyword_t:")
    y0, y1 = _years(params)
    if y0 or y1:
        q += f" AND producedDateY_i:[{y0 or 1900} TO {y1 or 2100}]"
    langs = [l for l in params.get("languages", []) if len(l) == 2]
    if langs:
        q += " AND language_s:(" + " OR ".join(langs) + ")"
    types = doc_type_values(params, "hal")
    if types:
        q += " AND docType_s:(" + " OR ".join(types) + ")"
    return q


def _doaj(concepts: list, params: dict) -> str:
    q = _fielded(concepts, params, "bibjson.title:", "bibjson.abstract:",
                 "bibjson.keywords:")
    y0, y1 = _years(params)
    if y0 or y1:
        q += f" AND bibjson.year:[{y0 or 1900} TO {y1 or 2100}]"
    return q


def _core(concepts: list, params: dict) -> str:
    q = _fielded(concepts, params, "title:", "abstract:", None)
    y0, y1 = _years(params)
    if y0:
        q += f" AND yearPublished>={int(y0)}"
    if y1:
        q += f" AND yearPublished<={int(y1)}"
    return q


def _lens(concepts: list, params: dict) -> str:
    q = _fielded(concepts, params, "title:", "abstract:", "keyword:")
    y0, y1 = _years(params)
    if y0 or y1:
        q += f" AND year_published:[{y0 or 1900} TO {y1 or 2100}]"
    return q


SPRINGER_MAX_YEARS = 40


def _springer(concepts: list, params: dict) -> str:
    fields = _fields(params)
    if fields == {"title"}:
        q = _fielded(concepts, params, "title:", "title:", None)
    elif fields == {"keywords"}:
        q = _fielded(concepts, params, "keyword:", "keyword:", None)
    else:  # no abstract field: the untagged term searches the whole record
        q = _generic(concepts)
    y0, y1 = _years(params)
    if y0 or y1:
        from datetime import date
        start = int(y0 or 1990)
        end = int(y1 or date.today().year + 1)
        years = list(range(start, min(end, start + SPRINGER_MAX_YEARS - 1) + 1))
        if years:
            q += " AND (" + " OR ".join(f"year:{y}" for y in years) + ")"
    return q


def _plain(concepts: list, params: dict) -> str:
    """Field-tag-free boolean string — the default for a project-declared
    database, whose syntax the app cannot know."""
    return _generic(concepts)


_TRANSLATORS = {
    "generic": _plain,
    "pubmed": _pubmed,
    "openalex": _openalex,
    "semanticscholar": _semanticscholar,
    "crossref": _crossref,
    "europepmc": _europepmc,
    "arxiv": _arxiv,
    "hal": _hal,
    "doaj": _doaj,
    "wos": _wos,
    "scopus": _scopus,
    "ieee": _ieee,
    "core": _core,
    "lens": _lens,
    "springer": _springer,
    "ebsco": _ebsco,
    "acm": _acm,
    "trid": _trid,
    "compendex": _compendex,
    "googlescholar": _googlescholar,
}
