"""Raw equations typed per database, golden
references by PMID, recall per database (API and import checks), the search
date and hit count declared on an upload, uploads as update passes."""
import time
from datetime import datetime, timezone

import pytest

from app.core.db import SessionLocal
from app.models import EquationRecall, Record
from app.services.equations import recall as recall_svc
from app.services.equations.translate import translate_all
from app.services.ris.parse import normalize_pmid, parse_file

PUBMED_RAW = """("emergency response driving"[tiab] OR "ambulance driver*"[tiab])
OR (("Firefighters"[MeSH] OR firefighter*[tiab]) AND driv*[tiab] AND stress[tiab])"""

NBIB = """PMID- 30708262
TI  - The risk factors Finnish paramedics recognize when performing emergency
      response driving.
FAU - Koski, Anna
DP  - 2019 Apr
JT  - Accident; analysis and prevention
LID - 10.1016/j.aap.2019.01.021 [doi]
AB  - Qualitative content analysis of 44 paramedics.

PMID- 32568158
TI  - Physiological responses during paramedics' simulated driving tasks.
FAU - Tremblay, Mathieu
DP  - 2020
JT  - Work
AB  - Heart rate during simulated emergency driving.
"""

RIS_EBSCO = """TY  - JOUR
TI  - Perceived stress and risky driving among EMS personnel
AU  - Alasqah, W.
PY  - 2026
AN  - 42058095
ER  -
TY  - JOUR
TI  - A paper no golden ref matches
AU  - Nobody, N.
PY  - 2020
DO  - 10.9/nothing
ER  -
"""


def _login(client, who):
    email = "admin@example.com" if who == "admin" else "rev@example.com"
    client.post("/api/auth/login", json={"email": email, "password": "password123"})


@pytest.fixture
def project(user_client):
    return user_client.post("/api/projects", json={"name": "Review"}).json()


@pytest.fixture(autouse=True)
def offline_identifiers(monkeypatch):
    """No network: identifier resolution and Crossref/OpenAlex enrichment are
    stubbed. The PMID lookup "knows" one DOI."""
    known = {"30708262": "10.1016/j.aap.2019.01.021"}

    def resolve(doi, pmid, timeout=8.0):
        if doi and not pmid:
            pmid = next((p for p, d in known.items() if d == doi), None)
        elif pmid and not doi:
            doi = known.get(pmid)
        return doi, pmid, "Resolved title" if pmid in known else ""
    monkeypatch.setattr(recall_svc, "resolve_identifiers", resolve)
    monkeypatch.setattr("app.api.equations.fetch_reference", lambda doi: {})
    monkeypatch.setattr("app.services.equations.golden_meta.fetch_abstract",
                        lambda doi, timeout=8.0: "")


# ---- raw equations -----------------------------------------------------------------

def test_raw_equation_crud_and_duplicate(user_client, project):
    pid = project["id"]
    base = f"/api/projects/{pid}/equations"
    # no concept needed: the typed queries ARE the equation
    r = user_client.post(base, json={
        "label": "Eq. 6", "mode": "raw",
        "translations": {"pubmed": PUBMED_RAW, "scopus": "", "wos": "TS=(x)"},
        "params": {"year_from": None}})
    assert r.status_code == 200, r.text
    eq = r.json()
    assert eq["mode"] == "raw" and eq["structure"] == {}
    assert eq["translations"]["auto"] == {}
    assert set(eq["translations"]["overrides"]) == {"pubmed", "wos"}  # blanks dropped
    assert eq["recall"] == []

    # an empty raw equation, or an unknown database, is refused
    assert user_client.post(base, json={"label": "x", "mode": "raw",
                                        "translations": {"pubmed": "  "}}).status_code == 422
    assert user_client.post(base, json={"label": "x", "mode": "raw",
                                        "translations": {"nope": "q"}}).status_code == 400

    # update replaces the typed queries; a raw variant cannot turn into concepts
    r = user_client.put(f"{base}/{eq['id']}", json={
        "label": "Eq. 6 (v2)", "mode": "raw",
        "translations": {"pubmed": PUBMED_RAW + " NOT helicopter*[ti]"}})
    assert r.status_code == 200, r.text
    assert r.json()["translations"]["overrides"] == {
        "pubmed": PUBMED_RAW + " NOT helicopter*[ti]"}
    assert user_client.put(f"{base}/{eq['id']}", json={
        "label": "x", "concept_ids": [1]}).status_code == 400

    # the per-database editor still works on a raw variant
    r = user_client.put(f"{base}/{eq['id']}/override",
                        json={"database": "scopus", "query": "TITLE-ABS-KEY(x)"})
    assert r.json()["translations"]["overrides"]["scopus"] == "TITLE-ABS-KEY(x)"

    # Eq. 6 bis = a copy, draft, same queries, no counts
    user_client.post(f"{base}/{eq['id']}/counts/manual",
                     json={"database": "scopus", "count": 120})
    r = user_client.post(f"{base}/{eq['id']}/duplicate")
    assert r.status_code == 200, r.text
    copy = r.json()
    assert copy["label"] == "Eq. 6 (v2) (copy)" and copy["mode"] == "raw"
    assert copy["status"] == "draft" and copy["counts"] == []
    assert copy["translations"]["overrides"]["scopus"] == "TITLE-ABS-KEY(x)"
    again = user_client.post(f"{base}/{eq['id']}/duplicate").json()
    assert again["label"] == "Eq. 6 (v2) (copy 2)"

    # the search report quotes the typed query once frozen
    user_client.post(f"{base}/{eq['id']}/freeze")
    report = user_client.get(f"/api/projects/{pid}/search-report").text
    assert "NOT helicopter*[ti]" in report


def test_compendex_translation():
    structure = {"concepts": [{"name": "P", "keywords": ["older adults", "elderly"]},
                              {"name": "I", "keywords": ["gamification"]}]}
    t = translate_all(structure, {"year_from": 2010, "year_to": 2025})
    assert t["compendex"] == ('(("older adults" OR elderly) WN KY) AND '
                              '((gamification) WN KY) AND (2010-2025 WN YR)')
    assert translate_all(structure, {"fields": ["title"]})["compendex"].startswith(
        '(("older adults" OR elderly) WN TI)')


def test_draft_translation_with_ai(user_client, project, monkeypatch):
    pid = project["id"]
    base = f"/api/projects/{pid}/equations"
    eq = user_client.post(base, json={"label": "raw", "mode": "raw",
                                      "translations": {"pubmed": PUBMED_RAW}}).json()
    captured = {}

    class Translator:
        model = "fake"

        def generate(self, messages, system=None, max_tokens=4096):
            from app.services.llm.base import LLMResult
            captured["prompt"] = messages[0]["content"]
            return LLMResult(text='TITLE-ABS-KEY("emergency response driving")\n'
                                  '# MeSH term Firefighters dropped')

    user_client.put("/api/llm/credentials", json={
        "provider": "anthropic", "api_key": "sk-ant-fake-key-123"})
    monkeypatch.setattr("app.services.equations.drafting.open_provider_chain",
                        lambda *a, **kw: Translator())
    monkeypatch.setattr("app.services.llm.pricing.call_cost", lambda p, r: None)
    r = user_client.post(f"{base}/{eq['id']}/translations/draft",
                         json={"from_db": "pubmed", "to_db": "scopus"})
    assert r.status_code == 200, r.text
    assert r.json()["query"] == 'TITLE-ABS-KEY("emergency response driving")'
    assert r.json()["notes"] == ["MeSH term Firefighters dropped"]
    assert "ambulance driver*" in captured["prompt"] and "Scopus" in captured["prompt"]
    # nothing was saved: the editor decides
    assert "scopus" not in user_client.get(base).json()[0]["translations"]["overrides"]
    # no source query -> 400
    assert user_client.post(f"{base}/{eq['id']}/translations/draft",
                            json={"from_db": "wos", "to_db": "scopus"}).status_code == 400


# ---- identifiers ---------------------------------------------------------------------

def test_normalize_pmid_and_parsers():
    assert normalize_pmid("30708262") == "30708262"
    assert normalize_pmid("PMID: 30708262") == "30708262"
    assert normalize_pmid("https://pubmed.ncbi.nlm.nih.gov/30708262") == "30708262"
    assert normalize_pmid("10.1016/j.aap.2019.01.021") is None
    assert normalize_pmid("WOS:000123") is None
    assert normalize_pmid("") is None

    records = parse_file("pubmed.nbib", NBIB.encode())
    assert [r["pmid"] for r in records] == ["30708262", "32568158"]
    assert records[0]["doi"] == "10.1016/j.aap.2019.01.021"
    assert "ID  - 30708262" in records[0]["raw"]  # round-trips through RIS

    ebsco = parse_file("psycinfo.ris", RIS_EBSCO.encode())
    assert ebsco[0]["pmid"] == "42058095" and ebsco[1]["pmid"] is None
    pubmed_ris = parse_file("x.ris", records[0]["raw"].encode())
    assert pubmed_ris[0]["pmid"] == "30708262"

    csv = "Title,PMID,DOI\nA paper,12345,10.1/a\n"
    assert parse_file("x.csv", csv.encode())[0]["pmid"] == "12345"


def test_golden_by_doi_or_pmid(user_client, project):
    pid = project["id"]
    base = f"/api/projects/{pid}/golden"
    # a PMID: the DOI and title come from PubMed (stubbed)
    r = user_client.post(base, json={"identifier": "PMID: 30708262"})
    assert r.status_code == 200, r.text
    assert r.json()["pmid"] == "30708262"
    assert r.json()["doi"] == "10.1016/j.aap.2019.01.021"
    assert r.json()["title"] == "Resolved title"
    # the same reference by its DOI is not added twice
    r = user_client.post(base, json={"doi": "https://doi.org/10.1016/j.aap.2019.01.021"})
    assert r.json()["pmid"] == "30708262"
    assert len(user_client.get(base).json()) == 1
    # a DOI unknown to PubMed keeps its DOI alone
    r = user_client.post(base, json={"identifier": "10.3233/WOR-203184"})
    assert r.json()["doi"] == "10.3233/wor-203184" and r.json()["pmid"] is None
    # garbage
    assert user_client.post(base, json={"identifier": "not an id"}).status_code == 400

    # bulk: one per line, any mix, rejects reported
    r = user_client.post(f"{base}/bulk", json={"identifiers":
        "42058095\n\n10.3389/fpubh.2026.1827749,\nWOS:junk\n30708262"})
    assert r.status_code == 200, r.text
    assert r.json()["added"] == 3 and r.json()["rejected"] == ["WOS:junk"]
    refs = user_client.get(base).json()
    assert len(refs) == 4
    assert {r["pmid"] for r in refs} == {"30708262", "42058095", None}


# ---- recall per database -----------------------------------------------------------

@pytest.fixture
def golden_project(user_client, project):
    pid = project["id"]
    for ident in ("30708262", "42058095", "10.3233/WOR-203184"):
        user_client.post(f"/api/projects/{pid}/golden", json={"identifier": ident})
    eq = user_client.post(f"/api/projects/{pid}/equations", json={
        "label": "Eq. 6", "mode": "raw",
        "translations": {"pubmed": PUBMED_RAW, "ebsco": "TI stress", "openalex": "x"}}).json()
    return {"pid": pid, "eq": eq}


def test_recall_from_imports_on_upload(user_client, golden_project):
    pid, eq = golden_project["pid"], golden_project["eq"]
    r = user_client.post(
        f"/api/projects/{pid}/imports/upload",
        files={"file": ("psycinfo.ris", RIS_EBSCO.encode(), "text/plain")},
        data={"source_name": "ebsco", "source_type": "database",
              "equation_id": str(eq["id"]), "searched_at": "2026-10-20",
              "declared_hits": "412"})
    assert r.status_code == 200, r.text
    assert r.json()["round"] == 1

    imp = user_client.get(f"/api/projects/{pid}/imports").json()[0]
    assert imp["searched_at"].startswith("2026-10-20")
    assert imp["declared_hits"] == 412

    # the import check ran: 1 of 3 golden refs is in the EBSCO export
    eqs = user_client.get(f"/api/projects/{pid}/equations").json()
    recall = eqs[0]["recall"]
    assert len(recall) == 1
    assert recall[0]["database_name"] == "ebsco" and recall[0]["method"] == "import"
    assert (recall[0]["found"], recall[0]["total"]) == (1, 3)
    missing = {m["pmid"] or m["doi"] for m in recall[0]["missing"]}
    assert missing == {"30708262", "10.3233/wor-203184"}

    # the PRISMA-S report shows the declared date and count, and the recall
    report = user_client.get(f"/api/projects/{pid}/search-report").text
    assert "| 2026-10-20 |" in report and "| 412 |" in report
    assert "## Golden-set recall per database" in report
    assert "| Eq. 6 | ebsco | import | 1/3 |" in report

    # history endpoint; a second upload adds a second row, the summary keeps the latest
    user_client.post(
        f"/api/projects/{pid}/imports/upload",
        files={"file": ("pubmed.nbib", NBIB.encode(), "text/plain")},
        data={"source_name": "pubmed", "source_type": "database",
              "equation_id": str(eq["id"])})
    history = user_client.get(f"/api/projects/{pid}/equations/{eq['id']}/recall").json()
    assert [h["database_name"] for h in history] == ["pubmed", "ebsco"]
    assert (history[0]["found"], history[0]["total"]) == (1, 3)  # Koski by PMID

    # a bad date is refused
    r = user_client.post(
        f"/api/projects/{pid}/imports/upload",
        files={"file": ("x.ris", RIS_EBSCO.encode(), "text/plain")},
        data={"source_name": "ebsco", "source_type": "database", "searched_at": "soon"})
    assert r.status_code == 400


def test_recall_job_asks_each_api(user_client, golden_project, monkeypatch):
    pid, eq = golden_project["pid"], golden_project["eq"]
    asked = []

    def pubmed_found(query, params, ref):
        asked.append(("pubmed", ref.pmid))
        assert query.startswith(PUBMED_RAW[:20])
        return ref.pmid == "30708262"

    def openalex_found(query, params, ref):
        asked.append(("openalex", ref.doi))
        return True if ref.doi else None  # 42058095 has no DOI here
    monkeypatch.setitem(recall_svc.CHECKERS, "pubmed", pubmed_found)
    monkeypatch.setitem(recall_svc.CHECKERS, "openalex", openalex_found)
    monkeypatch.setattr(time, "sleep", lambda s: None)

    from app.services.equations.jobs import golden_check_handler
    result = golden_check_handler(0, {"equation_id": eq["id"],
                                      "databases": ["pubmed", "openalex"]},
                                  lambda *a: None)
    assert result["results"]["pubmed"] == {"found": 1, "total": 3, "method": "api"}
    # a ref with no DOI is a miss for a DOI-filtered API, not an error
    assert result["results"]["openalex"]["found"] == 2
    assert ("pubmed", None) in asked or ("pubmed", "42058095") in asked

    eqs = user_client.get(f"/api/projects/{pid}/equations").json()
    by_db = {(r["database_name"], r["method"]): r for r in eqs[0]["recall"]}
    assert by_db[("pubmed", "api")]["found"] == 1
    assert by_db[("openalex", "api")]["found"] == 2
    # the OpenAlex summary the AI advisor reads is still maintained
    assert eqs[0]["golden_results"]["found"] == 2

    # the endpoint refuses a database with no identifier filter
    r = user_client.post(f"/api/projects/{pid}/equations/{eq['id']}/golden-check",
                         json={"databases": ["ebsco"]})
    assert r.status_code == 400
    assert user_client.get(f"/api/projects/{pid}/equations/recall/databases").json()[
        "api"] == ["pubmed", "openalex", "europepmc"]


def test_pmid_is_a_dedup_key(user_client, project):
    pid = project["id"]
    pubmed_only = """TY  - JOUR
TI  - Perceived stress and risky driving among EMS personnel (PubMed copy)
AU  - Alasqah, W.
PY  - 2026
ID  - 42058095
ER  -
"""
    for name, content in (("ebsco", RIS_EBSCO), ("pubmed", pubmed_only)):
        user_client.post(f"/api/projects/{pid}/imports/upload",
                         files={"file": (f"{name}.ris", content.encode(), "text/plain")},
                         data={"source_name": name, "source_type": "database"})
    from app.services.dedup.core import run_dedup
    with SessionLocal() as db:
        summary = run_dedup(db, pid, None)
        db.commit()
        dup = (db.query(Record).filter_by(project_id=pid)
               .filter(Record.dedup_status == "duplicate").all())
        assert len(dup) == 1 and dup[0].pmid == "42058095"
    assert summary["auto_duplicates"] == 1


# ---- uploads as update passes --------------------------------------------------------

def test_upload_as_update_pass(user_client, project):
    """`round_mode=update`: the export is a re-run of the search — it lands
    in a new round, is deduplicated, and opens the next screening round like
    an API fetch during screening. The default keeps a late export in the
    initial search (its records join the active round's queues)."""
    pid = project["id"]
    user_client.post("/api/auth/register", json={
        "email": "rev@example.com", "password": "password123", "display_name": "R"})
    rev = user_client.get("/api/auth/me").json()
    _login(user_client, "admin")
    me = user_client.get("/api/auth/me").json()
    user_client.post(f"/api/projects/{pid}/members",
                     json={"email": "rev@example.com", "role": "reviewer"})
    eq = user_client.post(f"/api/projects/{pid}/equations", json={
        "label": "raw", "mode": "raw", "translations": {"pubmed": "x[tiab]"}}).json()
    user_client.post(f"/api/projects/{pid}/imports/upload",
                     files={"file": ("pubmed.nbib", NBIB.encode(), "text/plain")},
                     data={"source_name": "pubmed", "source_type": "database",
                           "equation_id": str(eq["id"])})
    from app.services.dedup.core import run_dedup
    with SessionLocal() as db:
        run_dedup(db, pid, None)
        db.commit()
    user_client.post(f"/api/projects/{pid}/protocols/upload",
                     files={"file": ("p.md", b"# P", "text/markdown")})
    prot = user_client.get(f"/api/projects/{pid}/protocols").json()[0]
    user_client.put(f"/api/projects/{pid}/protocols/{prot['id']}", json={
        "protocol_md": "# P", "criteria": [
            {"code": "E1", "type": "exclude", "label": "off topic", "description": ""}]})
    user_client.post(f"/api/projects/{pid}/protocols/{prot['id']}/validate")
    user_client.put(f"/api/projects/{pid}/screening/config", json={
        "stage": "ta", "allocation": "all", "conflict_resolution": "consensus",
        "reviewer_ids": [me["id"], rev["id"]]})
    assert user_client.post(f"/api/projects/{pid}/screening/start").status_code == 200

    # update: a new round (2), deduplicated, two new unique records, next T/A round open
    r = user_client.post(f"/api/projects/{pid}/imports/upload",
                         files={"file": ("ebsco.ris", RIS_EBSCO.encode(), "text/plain")},
                         data={"source_name": "ebsco", "source_type": "database",
                               "equation_id": str(eq["id"]), "searched_at": "2026-11-02",
                               "round_mode": "update"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["round"] == 2 and body["n_new_unique"] == 2 and body["ta_round_started"]
    runs = user_client.get(f"/api/projects/{pid}/search/updates").json()
    assert runs and runs[-1]["triggered_by"] == "upload" and runs[-1]["databases"] == ["ebsco"]
    assert user_client.get(f"/api/projects/{pid}/imports").json()[0]["round"] == 2

    # default: a late export of the initial search stays in round 1, even
    # though a round is active (test_screening covers the queue side)
    r = user_client.post(f"/api/projects/{pid}/imports/upload",
                         files={"file": ("late.ris", RIS_EBSCO.encode(), "text/plain")},
                         data={"source_name": "trid", "source_type": "database"})
    assert r.json()["round"] == 1 and "n_new_unique" not in r.json()


def test_snowball_seeds_stay_in_their_project(user_client, project):
    pid = project["id"]
    other = user_client.post("/api/projects", json={"name": "other"}).json()["id"]
    user_client.post(f"/api/projects/{other}/imports/upload",
                     files={"file": ("x.ris", RIS_EBSCO.encode(), "text/plain")},
                     data={"source_name": "manual", "source_type": "manual"})
    with SessionLocal() as db:
        foreign = [r.id for r in db.query(Record).filter_by(project_id=other)]
    from app.services.snowballing.jobs import snowball_run_handler
    with pytest.raises(ValueError, match="belongs to this project"):
        snowball_run_handler(0, {"project_id": pid, "record_ids": foreign},
                             lambda *a: None)


def test_recall_rows_travel_in_snapshots(user_client, golden_project):
    from app.models import Project
    from app.services.sync.serialize import serialize_project
    pid, eq = golden_project["pid"], golden_project["eq"]
    with SessionLocal() as db:
        db.add(EquationRecall(equation_id=eq["id"], database_name="pubmed",
                              method="api", total=3, found=2,
                              missing=[{"doi": None, "pmid": "42058095", "citation": "x"}],
                              checked_at=datetime.now(timezone.utc)))
        db.commit()
        data = serialize_project(db, db.get(Project, pid))
    equation = next(e for e in data["equations"] if e["label"] == "Eq. 6")
    assert equation["mode"] == "raw"
    assert equation["recalls"][0]["found"] == 2
    assert {g["pmid"] for g in data["golden_refs"]} == {"30708262", "42058095", None}
