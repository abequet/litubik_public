# SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Golden-set recall per database.

A protocol's acceptance test for a search equation reads "every golden
reference is retrieved in every database where it is indexed". Two ways to
answer it, both recorded as `EquationRecall` rows so each variant keeps a
history per database:

- `api`: ask the database directly whether its search for the equation
  retrieves each golden reference — the equation AND an identifier filter.
  PubMed (by PMID), OpenAlex, Europe PMC and Scopus (by DOI), WoS Starter (by
  DOI) support it; the other connectors have no identifier filter.
- `import`: look the golden references up among the records imported under
  that source for the equation — the only check possible for a database
  without an API (EBSCO, TRID, ACM, Compendex…), and a useful second opinion
  for an API fetch (it checks what actually came back, caps included).

Identifiers: a golden ref may carry a DOI, a PMID or both; a record matches
on either. Resolution of the missing identifier goes through NCBI E-utilities
(`resolve_identifiers`), best effort.
"""
import time
from datetime import datetime, timezone

import httpx
from sqlalchemy.orm import Session

from app.core import polite
from app.models import Equation, EquationRecall, GoldenRef, Import, Record, Source
from app.services.equations import counts as counters
from app.services.equations.apa import short_citation
from app.services.ris.parse import normalize_doi, normalize_pmid

EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"


def effective_query(equation: Equation, database: str) -> str:
    translations = equation.translations or {}
    override = (translations.get("overrides") or {}).get(database, "")
    return override or (translations.get("auto") or {}).get(database, "")


# -- identifiers ---------------------------------------------------------------------

def parse_identifier(text: str) -> tuple[str | None, str | None]:
    """"10.1000/x", "https://doi.org/10.1000/x", "12345678", "PMID: 12345678"
    -> (doi, pmid). Anything else -> (None, None)."""
    text = (text or "").strip()
    return normalize_doi(text), normalize_pmid(text)


def resolve_identifiers(doi: str | None, pmid: str | None,
                        timeout: float = 8.0) -> tuple[str | None, str | None, str]:
    """Fill in the missing one of (doi, pmid) through NCBI, best effort: a
    reference outside PubMed simply keeps its DOI alone. Also returns the
    PubMed title when the lookup went through esummary (else "")."""
    title = ""
    if doi and pmid:
        return doi, pmid, title
    try:
        with httpx.Client(timeout=timeout, headers=polite.headers(),
                          follow_redirects=True) as client:
            if doi and not pmid:
                r = client.get(f"{EUTILS}/esearch.fcgi",
                               params={"db": "pubmed", "term": f'"{doi}"[doi]',
                                       "retmode": "json", "retmax": 1,
                                       **polite.ncbi_params()})
                ids = r.json().get("esearchresult", {}).get("idlist", []) if r.is_success else []
                pmid = normalize_pmid(ids[0]) if ids else None
            elif pmid and not doi:
                r = client.get(f"{EUTILS}/esummary.fcgi",
                               params={"db": "pubmed", "id": pmid, "retmode": "json",
                                       **polite.ncbi_params()})
                if r.is_success:
                    doc = (r.json().get("result") or {}).get(pmid) or {}
                    title = str(doc.get("title") or "")
                    for aid in doc.get("articleids") or []:
                        if aid.get("idtype") == "doi":
                            doi = normalize_doi(aid.get("value"))
                            break
    except Exception:  # network hiccup: the user can retry, nothing is lost
        pass
    return doi, pmid, title


def golden_citation(ref: GoldenRef) -> str:
    return short_citation(ref.apa, ref.year, ref.title, ref.doi or ref.pmid or "")


def _missing_entry(ref: GoldenRef) -> dict:
    return {"doi": ref.doi, "pmid": ref.pmid, "citation": golden_citation(ref)}


# -- API checks -------------------------------------------------------------------------

def _pubmed_found(query: str, params: dict, ref: GoldenRef) -> bool | None:
    if not ref.pmid:
        return None  # not identifiable on PubMed
    data = counters._get(f"{EUTILS}/esearch.fcgi",
                         {"db": "pubmed", "term": f"({query}) AND {ref.pmid}[uid]",
                          "retmax": 0, "retmode": "json",
                          **polite.ncbi_params()})
    return int(data["esearchresult"]["count"]) > 0


def _openalex_found(query: str, params: dict, ref: GoldenRef) -> bool | None:
    if not ref.doi:
        return None
    return counters.golden_ref_found(query, params, ref.doi)


def _europepmc_found(query: str, params: dict, ref: GoldenRef) -> bool | None:
    if not ref.doi:
        return None
    data = counters._get(counters.EUROPEPMC_SEARCH,
                         {"query": f'({query}) AND DOI:"{ref.doi}"',
                          "format": "json", "resultType": "lite", "pageSize": 1})
    return int(data.get("hitCount", 0)) > 0


def _scopus_found(query: str, params: dict, ref: GoldenRef, key: str) -> bool | None:
    if not ref.doi:
        return None
    return counters.scopus_count(f'({query}) AND DOI("{ref.doi}")', params, key) > 0


def _wos_found(query: str, params: dict, ref: GoldenRef, key: str) -> bool | None:
    if not ref.doi:
        return None
    return counters.wos_count(f'({query}) AND DO=("{ref.doi}")', params, key) > 0


CHECKERS = {
    "pubmed": _pubmed_found,
    "openalex": _openalex_found,
    "europepmc": _europepmc_found,
}
KEYED_CHECKERS = {
    "scopus": _scopus_found,
    "wos": _wos_found,
}


def api_checkable(db: Session, project_id: int) -> list[str]:
    """Databases the API recall can run on, keys included where configured,
    among the databases the review searches."""
    from app.services.connectors.keys import available_db_keys
    from app.services.equations import project_databases
    searched = {d["id"] for d in project_databases(db, project_id)}
    keyed = [d for d in KEYED_CHECKERS if d in available_db_keys(db, project_id)]
    return [d for d in list(CHECKERS) + sorted(keyed) if d in searched]


def _store(db: Session, equation_id: int, database: str, method: str,
           refs: list[GoldenRef], found: list[GoldenRef],
           missing: list[GoldenRef]) -> EquationRecall:
    row = EquationRecall(equation_id=equation_id, database_name=database,
                         method=method, total=len(refs), found=len(found),
                         missing=[_missing_entry(r) for r in missing],
                         checked_at=datetime.now(timezone.utc))
    db.add(row)
    db.flush()
    return row


def recall_via_api(db: Session, equation: Equation, database: str,
                   key: str | None = None, progress=None) -> EquationRecall:
    """Ask `database` about every golden ref; refs without the identifier the
    database needs count as missed (the protocol wants them found wherever
    they are indexed, and an unresolvable id is a finding in itself)."""
    refs = (db.query(GoldenRef).filter_by(project_id=equation.project_id)
            .order_by(GoldenRef.added_at).all())
    if not refs:
        raise ValueError("Golden set is empty — add reference DOIs or PMIDs first")
    query = effective_query(equation, database)
    if not query.strip():
        raise ValueError(f"No {database} query on this equation")
    params = equation.params or {}
    found, missing = [], []
    for i, ref in enumerate(refs):
        if progress:
            progress(i, len(refs), f"{database}: checking {golden_citation(ref)}...")
        try:
            if database in KEYED_CHECKERS:
                ok = KEYED_CHECKERS[database](query, params, ref, key or "")
            else:
                ok = CHECKERS[database](query, params, ref)
        except counters.CountError:
            ok = False
        (found if ok else missing).append(ref)
        time.sleep(0.3)
    row = _store(db, equation.id, database, "api", refs, found, missing)
    if database == "openalex":  # the AI advisor still reads this summary
        equation.golden_results = {
            "checked_at": row.checked_at.isoformat(), "database": "openalex",
            "total": len(refs), "found": len(found),
            "missing": [r.doi or r.pmid for r in missing],
            "found_refs": [{"doi": r.doi or r.pmid, "citation": golden_citation(r)}
                           for r in found]}
    return row


# -- import checks ----------------------------------------------------------------------

def _source_record_ids(db: Session, equation: Equation, database: str) -> list[str]:
    """DOIs and PMIDs of the records imported under `database` for this
    equation (any import of that source when none names the equation)."""
    base = (db.query(Record.doi, Record.pmid)
            .join(Import, Import.id == Record.import_id)
            .join(Source, Source.id == Import.source_id)
            .filter(Record.project_id == equation.project_id,
                    Source.name == database))
    rows = base.filter(Import.equation_id == equation.id).all()
    if not rows:
        rows = base.filter(Import.equation_id.is_(None)).all()
    keys = []
    for doi, pmid in rows:
        if doi:
            keys.append("doi:" + doi)
        if pmid:
            keys.append("pmid:" + pmid)
    return keys


def recall_from_imports(db: Session, equation_id: int, database: str) -> EquationRecall | None:
    """Golden refs present among the records imported under `database` for
    the equation. None when the golden set or the imports are empty."""
    equation = db.get(Equation, equation_id)
    if equation is None:
        return None
    refs = (db.query(GoldenRef).filter_by(project_id=equation.project_id)
            .order_by(GoldenRef.added_at).all())
    if not refs:
        return None
    keys = set(_source_record_ids(db, equation, database))
    if not keys:
        return None
    found = [r for r in refs
             if (r.doi and "doi:" + r.doi in keys) or (r.pmid and "pmid:" + r.pmid in keys)]
    missing = [r for r in refs if r not in found]
    return _store(db, equation.id, database, "import", refs, found, missing)


def imported_databases(db: Session, equation: Equation) -> list[str]:
    """Source names with at least one import usable for the import check."""
    names = (db.query(Source.name)
             .join(Import, Import.source_id == Source.id)
             .filter(Import.project_id == equation.project_id,
                     Source.type == "database")
             .distinct().all())
    return sorted(n for (n,) in names)


def latest_per_database(equation: Equation) -> list[EquationRecall]:
    """The most recent check per (database, method), newest first."""
    latest: dict[tuple[str, str], EquationRecall] = {}
    for r in sorted(equation.recalls, key=lambda r: (r.checked_at, r.id)):
        latest[(r.database_name, r.method)] = r
    return sorted(latest.values(), key=lambda r: (r.database_name, r.method))
