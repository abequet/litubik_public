import time

import pytest

from app.services.connectors import fetch as fetchers
from app.services.ris import ImportFileError, normalize_doi, parse_file, to_ris

RIS_SAMPLE = """TY  - JOUR
TI  - Gamification and driving: a review
AU  - Dupont, Jean
AU  - Smith, Anna
PY  - 2020/01/
DO  - https://doi.org/10.1000/RIS.1
T2  - Transportation Research
AB  - We review gamification in driving contexts.
ER  -
TY  - JOUR
T1  - Serious games for road safety
AU  - Lee, Kim
PY  - 2018
DO  - 10.1000/ris.2
JO  - Safety Science
N2  - Abstract in N2 tag.
ER  -
"""

NBIB_SAMPLE = """PMID- 12345678
TI  - Effects of gamified feedback on driving
      behaviour in young adults.
FAU - Garcia, Maria
FAU - Chen, Wei
DP  - 2019 Sep
JT  - Accident Analysis and Prevention
LID - 10.1000/nbib.1 [doi]
AB  - A driving-simulator study of gamified
      feedback.

PMID- 87654321
TI  - Second record.
AU  - Solo A
DP  - 2021
TA  - Ergonomics
AID - 10.1000/nbib.2 [doi]
"""

BIB_SAMPLE = """@article{dupont2020,
  author = {Dupont, Jean and Smith, Anna},
  title = {{Gamification} and driving},
  journal = {Transportation Research},
  year = {2020},
  doi = {10.1000/bib.1},
  abstract = {An abstract.}
}
"""

CSV_SAMPLE = ("Title;Authors;Publication Year;DOI;Source Title;Abstract\n"
              "Gamified speed feedback;\"Dupont, J.; Smith, A.\";2022;10.1000/csv.1;"
              "Ergonomics;Feedback study.\n"
              ";;;;;\n")


# ---- parsers ---------------------------------------------------------------------

def test_normalize_doi():
    assert normalize_doi("https://doi.org/10.1000/ABC") == "10.1000/abc"
    assert normalize_doi("10.1000/x y") == "10.1000/x"
    assert normalize_doi("not-a-doi") is None
    assert normalize_doi(None) is None


def test_parse_ris():
    records = parse_file("export.ris", RIS_SAMPLE.encode())
    assert len(records) == 2
    assert records[0]["doi"] == "10.1000/ris.1"
    assert records[0]["title"] == "Gamification and driving: a review"
    assert records[0]["authors"] == ["Dupont, Jean", "Smith, Anna"]
    assert records[0]["year"] == 2020
    assert records[0]["journal"] == "Transportation Research"
    assert "review gamification" in records[0]["abstract"]
    assert records[1]["doi"] == "10.1000/ris.2"
    assert records[1]["abstract"] == "Abstract in N2 tag."


def test_parse_ris_tolerant_variants():
    """Real-world RIS that rispy silently drops must still import: single-space
    tags (`TY - JOUR`) and a missing terminal `ER  -`."""
    # single-space tags (some database/tool exports)
    single = ("TY - JOUR\nAU - Doe, Jane\nTI - Single space export\n"
              "PY - 2021\nT2 - Some Journal\nDO - 10.5/single\nER -\n")
    recs = parse_file("weird.ris", single.encode())
    assert len(recs) == 1
    assert recs[0]["title"] == "Single space export"
    assert recs[0]["doi"] == "10.5/single"
    assert recs[0]["year"] == 2021
    assert recs[0]["authors"] == ["Doe, Jane"]
    assert recs[0]["journal"] == "Some Journal"

    # no ER terminators — records delimited by TY only
    no_er = ("TY  - JOUR\nTI  - First without end\nDO  - 10.5/a\n"
             "TY  - JOUR\nTI  - Second without end\nDO  - 10.5/b\n")
    recs = parse_file("noend.ris", no_er.encode())
    assert [r["title"] for r in recs] == ["First without end", "Second without end"]

    # multiline continuation still folds into the previous tag
    multi = ("TY - JOUR\nTI - Long title\nAB - Part one\n      part two here\nER -\n")
    recs = parse_file("multi.ris", multi.encode())
    assert recs[0]["abstract"] == "Part one part two here"

    # IEEE Xplore shape: CRLF records + a bare-LF separator + a stray CR glued to
    # the next TY. rispy sees only the first record unless line endings are
    # normalized — every record must be imported, not just one.
    one = "TY  - JOUR\r\nTI  - Paper {n}\r\nPY  - 20{n:02d}\r\nDO  - 10.9/{n}\r\nER  - \r\n"
    ieee = "\n\r".join(one.format(n=i) for i in range(1, 21))  # 20 records
    recs = parse_file("ieee.ris", ieee.encode())
    assert len(recs) == 20
    assert recs[0]["title"] == "Paper 1" and recs[-1]["title"] == "Paper 20"
    assert recs[5]["doi"] == "10.9/6"


def test_parse_nbib():
    records = parse_file("pubmed.nbib", NBIB_SAMPLE.encode())
    assert len(records) == 2
    assert records[0]["doi"] == "10.1000/nbib.1"
    assert records[0]["title"].endswith("young adults.")
    assert "behaviour" in records[0]["title"]  # continuation line joined
    assert records[0]["authors"] == ["Garcia, Maria", "Chen, Wei"]
    assert records[0]["year"] == 2019
    assert records[1]["journal"] == "Ergonomics"
    assert records[1]["doi"] == "10.1000/nbib.2"


def test_parse_nbib_from_txt_extension():
    records = parse_file("pubmed.txt", NBIB_SAMPLE.encode())
    assert len(records) == 2


def test_parse_bibtex():
    records = parse_file("refs.bib", BIB_SAMPLE.encode())
    assert len(records) == 1
    assert records[0]["doi"] == "10.1000/bib.1"
    assert records[0]["title"] == "Gamification and driving"
    assert records[0]["authors"] == ["Dupont, Jean", "Smith, Anna"]


def test_parse_csv():
    records = parse_file("wos.csv", CSV_SAMPLE.encode())
    assert len(records) == 1  # empty row skipped
    assert records[0]["doi"] == "10.1000/csv.1"
    assert records[0]["year"] == 2022
    assert records[0]["authors"] == ["Dupont, J.", "Smith, A."]


def test_parse_rejects_unknown_and_empty():
    with pytest.raises(ImportFileError, match="Unsupported"):
        parse_file("refs.xlsx", b"x")
    with pytest.raises(ImportFileError):
        parse_file("empty.ris", b"")


def test_to_ris_roundtrip():
    records = parse_file("export.ris", RIS_SAMPLE.encode())
    again = parse_file("again.ris", to_ris(records).encode())
    assert [r["doi"] for r in again] == [r["doi"] for r in records]
    assert [r["title"] for r in again] == [r["title"] for r in records]


def test_openalex_abstract_reconstruction():
    inverted = {"Driving": [0], "games": [2], "help.": [3], "simulator": [1]}
    assert fetchers._openalex_abstract(inverted) == "Driving simulator games help."
    assert fetchers._openalex_abstract(None) == ""


# ---- API flow ---------------------------------------------------------------------

@pytest.fixture
def project(user_client):
    return user_client.post("/api/projects", json={"name": "M3 demo"}).json()


@pytest.fixture
def equation(user_client, project):
    user_client.post(f"/api/projects/{project['id']}/concepts",
                     json={"name": "I", "keywords": ["gamification"]})
    concepts = user_client.get(f"/api/projects/{project['id']}/concepts").json()
    return user_client.post(f"/api/projects/{project['id']}/equations", json={
        "label": "final", "concept_ids": [concepts[0]["id"]], "params": {}}).json()


def _upload(client, pid, filename, content, source_name, **form):
    return client.post(
        f"/api/projects/{pid}/imports/upload",
        files={"file": (filename, content.encode(), "text/plain")},
        data={"source_name": source_name, **form},
    )


def test_manual_import_flow(user_client, project, equation):
    pid = project["id"]
    r = _upload(user_client, pid, "wos_export.ris", RIS_SAMPLE, "wos",
                source_type="database", equation_id=str(equation["id"]))
    assert r.status_code == 200, r.text
    assert r.json()["n_records"] == 2

    imports = user_client.get(f"/api/projects/{pid}/imports").json()
    assert len(imports) == 1
    assert imports[0]["source_name"] == "wos"
    assert imports[0]["source_type"] == "database"
    assert imports[0]["equation_label"] == "final"
    assert imports[0]["n_records"] == 2

    records = user_client.get(f"/api/projects/{pid}/records").json()
    assert records["total"] == 2
    assert {r["source_name"] for r in records["items"]} == {"wos"}
    assert records["items"][0]["dedup_status"] == "pending"

    # search filter
    filtered = user_client.get(f"/api/projects/{pid}/records",
                               params={"q": "serious games"}).json()
    assert filtered["total"] == 1

    # a second upload to the same source reuses it
    _upload(user_client, pid, "wos2.ris", RIS_SAMPLE, "wos", source_type="database")
    imports = user_client.get(f"/api/projects/{pid}/imports").json()
    assert len(imports) == 2

    # delete an import removes its records
    r = user_client.delete(f"/api/projects/{pid}/imports/{imports[0]['id']}")
    assert r.status_code == 200
    assert user_client.get(f"/api/projects/{pid}/records").json()["total"] == 2


def test_records_source_filter_and_sort(user_client, project, equation):
    pid = project["id"]
    _upload(user_client, pid, "wos.ris", RIS_SAMPLE, "wos", source_type="database")
    _upload(user_client, pid, "scopus.ris", RIS_SAMPLE, "scopus", source_type="database")

    r = user_client.get(f"/api/projects/{pid}/records/sources").json()
    assert r["sources"] == ["scopus", "wos"]

    filtered = user_client.get(f"/api/projects/{pid}/records",
                               params={"source": "wos"}).json()
    assert filtered["total"] == 2
    assert all(item["source_name"] == "wos" for item in filtered["items"])

    by_source = user_client.get(f"/api/projects/{pid}/records",
                                params={"sort": "source"}).json()
    assert [i["source_name"] for i in by_source["items"]] == \
        ["scopus", "scopus", "wos", "wos"]
    by_year = user_client.get(f"/api/projects/{pid}/records",
                              params={"sort": "year"}).json()
    assert [i["year"] for i in by_year["items"]] == [2020, 2020, 2018, 2018]


def test_records_equation_filter(user_client, project, equation):
    pid = project["id"]
    # a second equation with its own import — must be excluded when scoping eq1
    concepts = user_client.get(f"/api/projects/{pid}/concepts").json()
    eq2 = user_client.post(f"/api/projects/{pid}/equations", json={
        "label": "alt", "concept_ids": [concepts[0]["id"]], "params": {}}).json()

    _upload(user_client, pid, "wos.ris", RIS_SAMPLE, "wos", source_type="database",
            equation_id=str(equation["id"]))                       # 2, eq1
    _upload(user_client, pid, "hand.ris", RIS_SAMPLE, "hand search")  # 2, free
    _upload(user_client, pid, "scopus.ris", RIS_SAMPLE, "scopus",
            source_type="database", equation_id=str(eq2["id"]))    # 2, eq2

    all_records = user_client.get(f"/api/projects/{pid}/records").json()
    assert all_records["total"] == 6
    # scoping to eq1 keeps its records + the free import, drops eq2's records
    scoped = user_client.get(f"/api/projects/{pid}/records",
                             params={"equation_id": equation["id"]}).json()
    assert scoped["total"] == 4
    assert {i["source_name"] for i in scoped["items"]} == {"wos", "hand search"}

    imports = user_client.get(f"/api/projects/{pid}/imports").json()
    by_source = {i["source_name"]: i for i in imports}
    assert by_source["wos"]["equation_id"] == equation["id"]
    assert by_source["hand search"]["equation_id"] is None


def test_upload_rejects_bad_file(user_client, project):
    r = _upload(user_client, project["id"], "junk.ris", "garbage content", "misc")
    assert r.status_code == 400


def test_matches_structure():
    from app.services.connectors.postfilter import matches_structure
    structure = {"concepts": [
        {"keywords": ["gamification", "serious games"]},
        {"keywords": ["driving"]},
    ]}
    ok = {"title": "Gamification of driving feedback", "abstract": ""}
    partial = {"title": "Serious games in education", "abstract": "no cars here"}
    junk = {"title": "Special Report", "abstract": ""}
    assert matches_structure(ok, structure)
    assert not matches_structure(partial, structure)   # second concept missing
    assert not matches_structure(junk, structure)
    # abstract can satisfy a concept unless the equation is title-only
    via_abstract = {"title": "Serious games study", "abstract": "a driving simulator"}
    assert matches_structure(via_abstract, structure)
    assert not matches_structure(via_abstract, structure, fields=["title"])


def test_crossref_fetch_is_postfiltered(user_client, project, equation, monkeypatch):
    pid = project["id"]

    def fake_crossref(query, params, cap, progress):
        return [
            {"doi": "10.1/match", "title": "Gamification everywhere", "authors": [],
             "year": 2020, "journal": "", "abstract": "", "raw": ""},
            {"doi": "10.1/junk", "title": "Special Report", "authors": [],
             "year": 2013, "journal": "Emergency Medicine News", "abstract": "",
             "raw": ""},
        ]

    monkeypatch.setitem(fetchers.FETCHERS, "crossref", fake_crossref)
    r = user_client.post(f"/api/projects/{pid}/search/fetch", json={
        "equation_id": equation["id"], "database": "crossref", "cap": 100})
    job_id = r.json()["job_id"]
    for _ in range(100):
        job = user_client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in ("done", "failed"):
            break
        time.sleep(0.05)
    assert job["status"] == "done", job.get("error")
    assert job["result"]["n_scanned"] == 2
    assert job["result"]["n_records"] == 1  # "Special Report" filtered out
    records = user_client.get(f"/api/projects/{pid}/records").json()
    assert [r["doi"] for r in records["items"]] == ["10.1/match"]


def test_jobs_list_endpoint(user_client, project, equation, monkeypatch):
    pid = project["id"]
    monkeypatch.setitem(fetchers.FETCHERS, "pubmed",
                        lambda q, p, cap, progress: [])
    user_client.post(f"/api/projects/{pid}/search/fetch", json={
        "equation_id": equation["id"], "database": "pubmed"})
    for _ in range(100):
        jobs = user_client.get(f"/api/jobs?project_id={pid}").json()
        if jobs and jobs[0]["status"] in ("done", "failed"):
            break
        time.sleep(0.05)
    assert jobs[0]["type"] == "search_fetch"
    assert jobs[0]["params"]["database"] == "pubmed"
    active = user_client.get(f"/api/jobs?project_id={pid}&active=true").json()
    assert active == []  # finished


def test_fetch_job_with_mocked_fetcher(user_client, project, equation, monkeypatch):
    pid = project["id"]

    def fake_fetch(query, params, cap, progress):
        assert "gamification" in query
        # the frozen equation's params reach the fetcher (fields, filters...)
        assert params["fields"] == ["title", "abstract"]
        progress(2, 2)
        return parse_file("x.ris", RIS_SAMPLE.encode())[:cap]

    monkeypatch.setitem(fetchers.FETCHERS, "pubmed", fake_fetch)
    # the job module imported FETCHERS by reference — same dict, so setitem works
    r = user_client.post(f"/api/projects/{pid}/search/fetch", json={
        "equation_id": equation["id"], "database": "pubmed", "cap": 100})
    assert r.status_code == 200, r.text
    job_id = r.json()["job_id"]
    for _ in range(100):
        job = user_client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in ("done", "failed"):
            break
        time.sleep(0.05)
    assert job["status"] == "done", job.get("error")
    assert job["result"]["n_records"] == 2

    imports = user_client.get(f"/api/projects/{pid}/imports").json()
    assert imports[0]["source_name"] == "pubmed"
    assert imports[0]["filename"].endswith("pubmed.ris")
    records = user_client.get(f"/api/projects/{pid}/records").json()
    assert records["total"] == 2


def test_fetch_rejects_manual_database(user_client, project, equation):
    r = user_client.post(f"/api/projects/{project['id']}/search/fetch", json={
        "equation_id": equation["id"], "database": "wos"})
    assert r.status_code == 400


def test_search_report(user_client, project, equation):
    pid = project["id"]
    user_client.post(f"/api/projects/{pid}/equations/{equation['id']}/freeze")
    _upload(user_client, pid, "wos.ris", RIS_SAMPLE, "wos", source_type="database",
            equation_id=str(equation["id"]))
    report = user_client.get(f"/api/projects/{pid}/search-report").text
    assert "# Search report" in report
    assert "Frozen equation — final" in report
    assert "(gamification)" in report          # the query itself
    assert "| wos | database | final |" in report
    assert "Total records identified: 2" in report


def test_reviewer_cannot_import(user_client, project):
    pid = project["id"]
    user_client.post("/api/auth/register", json={
        "email": "rev3@example.com", "password": "password123", "display_name": "R"})
    user_client.post("/api/auth/login", json={
        "email": "admin@example.com", "password": "password123"})
    user_client.post(f"/api/projects/{pid}/members",
                     json={"email": "rev3@example.com", "role": "reviewer"})
    user_client.post("/api/auth/login", json={
        "email": "rev3@example.com", "password": "password123"})
    r = _upload(user_client, pid, "x.ris", RIS_SAMPLE, "wos")
    assert r.status_code == 403
    assert user_client.get(f"/api/projects/{pid}/records").status_code == 200


# ---- PRISMA-S limits declared with an upload ----------------------------------------

def test_upload_declares_date_and_discipline_limits(user_client, project, equation):
    pid = project["id"]
    user_client.post(f"/api/projects/{pid}/equations/{equation['id']}/freeze")
    r = _upload(user_client, pid, "scopus.ris", RIS_SAMPLE, "scopus",
                source_type="database", equation_id=str(equation["id"]),
                date_restricted="true", discipline_restricted="false",
                doc_type_restricted="false", search_fields="abstract,title,bogus")
    assert r.status_code == 200, r.text
    # a second file with nothing declared
    _upload(user_client, pid, "wos.ris", RIS_SAMPLE, "wos", source_type="database")
    # a free import (other source) declares the disciplines it was limited to;
    # naming them implies the discipline limit was applied
    r = _upload(user_client, pid, "hand.ris", RIS_SAMPLE, "hand search",
                source_type="manual", date_restricted="false",
                disciplines=" Psychology, Engineering ,,Transportation ",
                doc_types="Article, Review", search_fields="fulltext")
    assert r.status_code == 200, r.text

    imports = {i["source_name"]: i
               for i in user_client.get(f"/api/projects/{pid}/imports").json()}
    assert imports["scopus"]["date_restricted"] is True
    assert imports["scopus"]["discipline_restricted"] is False
    assert imports["wos"]["date_restricted"] is None
    assert imports["wos"]["discipline_restricted"] is None
    assert imports["scopus"]["disciplines"] is None
    assert imports["hand search"]["date_restricted"] is False
    assert imports["hand search"]["discipline_restricted"] is True
    assert imports["hand search"]["disciplines"] == [
        "Psychology", "Engineering", "Transportation"]
    # doc types work like disciplines; search fields keep the known ids, in order
    assert imports["scopus"]["doc_type_restricted"] is False
    assert imports["scopus"]["search_fields"] == ["title", "abstract"]
    assert imports["wos"]["doc_type_restricted"] is None
    assert imports["wos"]["search_fields"] is None
    assert imports["hand search"]["doc_type_restricted"] is True
    assert imports["hand search"]["doc_types"] == ["Article", "Review"]
    assert imports["hand search"]["search_fields"] == ["fulltext"]

    report = user_client.get(f"/api/projects/{pid}/search-report").text
    assert "| Date limit | Discipline limit | Disciplines |" in report
    assert "| scopus | database | final |" in report
    assert "| Doc-type limit | Doc types | Search fields |" in report
    assert "| 2 | yes | no | — | no | — | title, abstract |" in report
    assert "| 2 | — | — | — | — | — | — |" in report
    assert ("| 2 | no | yes | Psychology; Engineering; Transportation | "
            "yes | Article; Review | full text |") in report


def test_api_fetch_records_limits_from_the_equation(user_client, project,
                                                     equation, monkeypatch):
    """An API fetch applies the equation's year range and disciplines itself,
    so the import records them without asking."""
    pid = project["id"]
    concepts = user_client.get(f"/api/projects/{pid}/concepts").json()
    r = user_client.put(f"/api/projects/{pid}/equations/{equation['id']}", json={
        "label": "final", "concept_ids": [concepts[0]["id"]],
        "params": {"year_from": 2015, "year_to": 2024, "fields": ["title", "abstract"],
                   "disciplines": ["psyc", "engi"], "doc_types": ["review"]}})
    assert r.status_code == 200, r.text
    monkeypatch.setitem(fetchers.FETCHERS, "pubmed",
                        lambda q, p, cap, progress: parse_file("x.ris", RIS_SAMPLE.encode()))
    r = user_client.post(f"/api/projects/{pid}/search/fetch", json={
        "equation_id": equation["id"], "database": "pubmed", "cap": 100})
    job_id = r.json()["job_id"]
    for _ in range(100):
        job = user_client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in ("done", "failed"):
            break
        time.sleep(0.05)
    assert job["status"] == "done", job.get("error")
    imp = user_client.get(f"/api/projects/{pid}/imports").json()[0]
    assert imp["date_restricted"] is True
    assert imp["discipline_restricted"] is True
    assert imp["disciplines"] == ["Psychology", "Engineering"]
    assert imp["doc_type_restricted"] is True
    assert imp["doc_types"] == ["Review"]
    assert imp["search_fields"] == ["title", "abstract"]


# ---- silent abstract backfill -------------------------------------------------------

RIS_NO_ABSTRACT = """TY  - JOUR
TI  - Title without abstract one
AU  - Dupont, Jean
PY  - 2020
DO  - 10.1000/na.1
ER  -
TY  - JOUR
TI  - Title without abstract two
AU  - Smith, Anna
PY  - 2021
DO  - 10.1000/na.2
ER  -
TY  - JOUR
TI  - Title with its abstract
AU  - Lee, Kim
PY  - 2021
DO  - 10.1000/na.3
AB  - Already there.
ER  -
"""


def _enable_backfill(monkeypatch, found: dict):
    from app.core.config import get_settings
    monkeypatch.setattr(get_settings(), "abstract_backfill", True)
    calls = []

    def fake_fetch(client, dois, **kw):
        calls.append(list(dois))
        assert kw.get("scrape_cap") == 0  # open APIs only, never the publisher pages
        return found
    monkeypatch.setattr("app.services.connectors.abstracts.fetch_abstracts", fake_fetch)
    return calls


def _await_backfill(client, pid):
    for _ in range(200):
        jobs = [j for j in client.get(f"/api/jobs?project_id={pid}").json()
                if j["type"] == "abstract_backfill"]
        if jobs and jobs[0]["status"] in ("done", "failed"):
            return jobs[0]
        time.sleep(0.05)
    raise AssertionError("backfill job never finished")


def test_upload_backfills_missing_abstracts_silently(user_client, project, monkeypatch):
    pid = project["id"]
    calls = _enable_backfill(monkeypatch, {"10.1000/na.1": "Fetched one.",
                                           "10.1000/na.3": "Must not overwrite."})
    r = _upload(user_client, pid, "wos.ris", RIS_NO_ABSTRACT, "wos",
                source_type="database")
    assert r.status_code == 200, r.text
    job = _await_backfill(user_client, pid)
    assert job["status"] == "done", job.get("error")
    assert job["result"] == {"targets": 2, "filled": 1}
    # only the records without an abstract were asked for
    assert sorted(calls[0]) == ["10.1000/na.1", "10.1000/na.2"]

    by_doi = {r["doi"]: r["abstract"] for r in
              user_client.get(f"/api/projects/{pid}/records").json()["items"]}
    assert by_doi["10.1000/na.1"] == "Fetched one."
    assert by_doi["10.1000/na.2"] == ""
    assert by_doi["10.1000/na.3"] == "Already there."


def test_no_backfill_job_when_nothing_is_missing(user_client, project, monkeypatch):
    pid = project["id"]
    _enable_backfill(monkeypatch, {})
    _upload(user_client, pid, "wos.ris", RIS_SAMPLE, "wos", source_type="database")
    time.sleep(0.2)
    jobs = user_client.get(f"/api/jobs?project_id={pid}").json()
    assert [j for j in jobs if j["type"] == "abstract_backfill"] == []


def test_api_fetch_schedules_the_backfill(user_client, project, equation, monkeypatch):
    pid = project["id"]
    _enable_backfill(monkeypatch, {"10.1000/na.2": "From the API."})
    monkeypatch.setitem(fetchers.FETCHERS, "pubmed",
                        lambda q, p, cap, progress: parse_file("x.ris", RIS_NO_ABSTRACT.encode()))
    user_client.post(f"/api/projects/{pid}/search/fetch", json={
        "equation_id": equation["id"], "database": "pubmed", "cap": 100})
    job = _await_backfill(user_client, pid)
    assert job["result"] == {"targets": 2, "filled": 1}
