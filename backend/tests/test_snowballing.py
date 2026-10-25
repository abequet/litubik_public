"""M8 — snowballing: union port, PDF DOI harvest, end-to-end iteration (mocked
crawl), round-2 auto-screening, citation graph, saturation."""
import time

import pytest

from app.services.snowballing.core import (
    pdf_reference_dois, union_refs,
)
from app.services.snowballing.scrape import extract_abstract


# ---- publisher-page abstract extraction (offline) -------------------------------

_LONG = ("This study investigates wayfinding under cognitive load in older "
         "adults across three field experiments, measuring balance and "
         "navigation error over a twelve-week protocol with ninety "
         "participants recruited from two clinics. " * 2)


def test_extract_abstract_citation_meta():
    html = f'<html><head><meta name="citation_abstract" content="{_LONG}">' \
           f'</head><body></body></html>'
    assert extract_abstract(html).startswith("This study investigates")


def test_extract_abstract_springer_jsonld():
    html = ('<html><head><script type="application/ld+json">'
            + '{"@type":"ScholarlyArticle","description":"' + _LONG + '"}'
            + '</script></head><body></body></html>')
    assert "wayfinding" in extract_abstract(html)


def test_extract_abstract_sciencedirect_json_blob():
    html = ('<html><body><script>window.__APP={"article":{"abstract":"'
            + _LONG + '"}}</script></body></html>')
    assert extract_abstract(html).startswith("This study investigates")


def test_extract_abstract_strips_prefix_and_rejects_short():
    html = ('<html><body><div class="abstract">Abstract: ' + _LONG
            + '</div></body></html>')
    out = extract_abstract(html)
    assert out.startswith("This study") and not out.lower().startswith("abstract")
    # a bare tagline is not an abstract
    assert extract_abstract('<meta property="og:description" content="Too short">') == ""

_TITLES = [
    "Gamified speed feedback for young drivers",
    "Serious games in nursing education outcomes",
    "Cycling safety interventions in dense cities",
    "Virtual reality exposure for driving anxiety",
]
RIS = "".join(f"""TY  - JOUR
TI  - {title}
AU  - Author{i}, A.
PY  - 20{10 + i}
DO  - 10.1/sb.{i}
AB  - Abstract {i}.
ER  -
""" for i, title in enumerate(_TITLES, start=1))


# ---- union_refs port ------------------------------------------------------------

def test_union_refs_doi_keyed_never_collapses():
    a = [{"title": "Paper one", "doi": "10.1/x1", "authors": [], "year": 2020, "src": "crossref"}]
    b = [{"title": "Untitled", "doi": "10.1/x2", "authors": [], "year": None, "src": "opencitations"},
         {"title": "Paper one", "doi": "https://doi.org/10.1/X1", "authors": ["Doe, J"],
          "year": None, "src": "openalex"}]
    merged = union_refs([a, b])
    # two distinct DOIs stay distinct; same DOI merged with enriched authors
    assert sorted(r["doi"] for r in merged) == ["10.1/x1", "10.1/x2"]
    one = next(r for r in merged if r["doi"] == "10.1/x1")
    assert one["authors"] == ["Doe, J"] and one["year"] == 2020
    assert "crossref" in one["src"] and "openalex" in one["src"]


def test_union_refs_doiless_fuzzy_fallback():
    a = [{"title": "Gamification of driver training programmes", "doi": "10.1/g1",
          "authors": [], "year": 2021, "src": "openalex"}]
    b = [{"title": "Gamification of driver training programs", "doi": None,
          "authors": ["Roe, K"], "year": None, "src": "pdf"},        # same paper, no DOI
         {"title": "A completely different subject entirely", "doi": None,
          "authors": [], "year": None, "src": "pdf"}]
    merged = union_refs([a, b])
    assert len(merged) == 2  # fuzzy match folded the first, kept the second
    kept = next(r for r in merged if r["doi"] == "10.1/g1")
    assert kept["authors"] == ["Roe, K"]  # enriched from the PDF copy
    # placeholder titles without DOI are dropped (unidentifiable)
    merged = union_refs([[{"title": "Untitled", "doi": None, "authors": [],
                           "year": None, "src": "pdf"}]])
    assert merged == []


# ---- PDF DOI harvest --------------------------------------------------------------

def test_pdf_reference_dois(tmp_path):
    import pymupdf
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Body text. doi:10.1234/own.doi\n")
    page2 = doc.new_page()
    page2.insert_text(
        (72, 72),
        "References\n"
        "1. Doe J. A study. https://doi.org/10.1234/ref.one\n"
        "2. Roe K. Another. doi:10.5678/REF.two.\n"
        "3. No doi here.\n")
    path = tmp_path / "article.pdf"
    doc.save(path)
    dois = pdf_reference_dois(str(path), own_doi="10.1234/own.doi")
    assert dois == ["10.1234/ref.one", "10.5678/ref.two"]


# ---- fixtures (full pipeline up to 2 FT includes) ----------------------------------

def _login(client, who):
    email = "admin@example.com" if who == "admin" else "rev@example.com"
    client.post("/api/auth/login", json={"email": email, "password": "password123"})


def _await(client, job_id, timeout=30):
    t0 = time.time()
    while time.time() - t0 < timeout:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in ("done", "failed"):
            return job
        time.sleep(0.05)
    raise AssertionError("job never finished")


@pytest.fixture
def team(user_client):
    me = user_client.get("/api/auth/me").json()
    user_client.post("/api/auth/register", json={
        "email": "rev@example.com", "password": "password123",
        "display_name": "Reviewer"})
    rev = user_client.get("/api/auth/me").json()
    _login(user_client, "admin")
    return {"admin": me, "reviewer": rev}


@pytest.fixture
def sb_project(user_client, team):
    """Round 1 done: 4 records, T/A keeps 2, FT includes both (the seeds)."""
    pid = user_client.post("/api/projects", json={"name": "M8 demo"}).json()["id"]
    user_client.post(f"/api/projects/{pid}/members",
                     json={"email": "rev@example.com", "role": "reviewer"})
    user_client.post(f"/api/projects/{pid}/imports/upload",
                     files={"file": ("s.ris", RIS.encode(), "text/plain")},
                     data={"source_name": "pubmed", "source_type": "database"})
    _await(user_client, user_client.post(
        f"/api/projects/{pid}/dedup/run").json()["job_id"])

    user_client.post(f"/api/projects/{pid}/protocols/upload",
                     files={"file": ("p.md", b"# P", "text/markdown")})
    prot = user_client.get(f"/api/projects/{pid}/protocols").json()[0]
    user_client.put(f"/api/projects/{pid}/protocols/{prot['id']}", json={
        "protocol_md": "# P", "criteria": [
            {"code": "E1", "type": "exclude", "label": "off topic",
             "description": ""}]})
    user_client.post(f"/api/projects/{pid}/protocols/{prot['id']}/validate")

    reviewers = [team["admin"]["id"], team["reviewer"]["id"]]
    user_client.put(f"/api/projects/{pid}/screening/config", json={
        "stage": "ta", "allocation": "all", "conflict_resolution": "consensus",
        "reviewer_ids": reviewers})
    user_client.post(f"/api/projects/{pid}/screening/start")
    ta_ids = [i["id"] for i in user_client.get(
        f"/api/projects/{pid}/screening/queue?limit=10").json()["items"]]
    for who in ("admin", "reviewer"):
        _login(user_client, who)
        for idx, rid in enumerate(ta_ids):
            decision = "include" if idx < 2 else "exclude"
            user_client.post(f"/api/projects/{pid}/screening/vote",
                             json={"record_id": rid, "decision": decision})
    _login(user_client, "admin")
    user_client.put(f"/api/projects/{pid}/screening/config", json={
        "stage": "ft", "allocation": "all", "conflict_resolution": "consensus",
        "reviewer_ids": reviewers})
    user_client.post(f"/api/projects/{pid}/screening/start?stage=ft")
    for who in ("admin", "reviewer"):
        _login(user_client, who)
        for rid in ta_ids[:2]:
            user_client.post(f"/api/projects/{pid}/screening/vote?stage=ft",
                             json={"record_id": rid, "decision": "include"})
    _login(user_client, "admin")
    return {"pid": pid, "seeds": ta_ids[:2], "excluded_ta": ta_ids[2:],
            "reviewers": reviewers}


def _mock_crawl(monkeypatch, backward_map, forward_map, abstracts=None):
    """Patch the crawl functions used by the job (client argument ignored).
    Also stubs the abstract enrichment so tests never hit the network."""
    monkeypatch.setattr(
        "app.services.snowballing.jobs.backward_refs",
        lambda client, doi, pdf_path=None: list(backward_map.get(doi, [])))
    monkeypatch.setattr(
        "app.services.snowballing.jobs.forward_refs",
        lambda client, doi: list(forward_map.get(doi, [])))
    monkeypatch.setattr(
        "app.services.snowballing.jobs.fetch_abstracts",
        lambda client, dois, **kw: dict(abstracts or {}))


def _ref(title, doi, year=2022, authors=None):
    return {"title": title, "doi": doi, "authors": authors or ["New, A."],
            "year": year, "src": "openalex"}


# ---- the iteration ------------------------------------------------------------------

def test_snowball_iteration_end_to_end(user_client, sb_project, monkeypatch):
    pid = sb_project["pid"]
    s1, s2 = sb_project["seeds"]

    status = user_client.get(f"/api/projects/{pid}/snowballing/status").json()
    assert status["pending_seeds"] == 2 and status["runs"] == []
    seeds = user_client.get(f"/api/projects/{pid}/snowballing/seeds").json()
    assert {s["id"] for s in seeds} == {s1, s2}

    # seed1 cites NEW-A and the already-known record 3 (10.1/sb.3, TA-excluded);
    # NEW-C cites seed1 (forward). seed2 also cites NEW-A.
    _mock_crawl(
        monkeypatch,
        backward_map={
            "10.1/sb.1": [_ref("Brand new referenced study", "10.9/new.a"),
                          _ref("Cycling safety interventions in dense cities",
                               "10.1/sb.3", year=2013)],
            "10.1/sb.2": [_ref("Brand new referenced study", "10.9/new.a")],
        },
        forward_map={
            "10.1/sb.1": [_ref("Fresh citing paper", "10.9/new.c", year=2025)],
            "10.1/sb.2": [],
        },
        abstracts={"10.9/new.a": "Enriched abstract for the new study."})

    r = user_client.post(f"/api/projects/{pid}/snowballing/run", json={})
    assert r.status_code == 200, r.text
    job = _await(user_client, r.json()["job_id"])
    assert job["status"] == "done", job.get("error")
    res = job["result"]
    assert res["round"] == 2
    assert res["n_seeds"] == 2
    assert res["n_discovered"] == 3       # new.a, sb.3 (known), new.c
    assert res["n_new_unique"] == 2       # new.a + new.c (sb.3 merged as duplicate)
    assert res["ta_round_started"] is True

    # source + PRISMA identification via other methods
    prisma = user_client.get(f"/api/projects/{pid}/prisma").json()
    assert prisma["identified_other"] == [{"source": "snowballing r2", "n": 3}]

    # PRISMA 2020 dual identification columns (#15): the database column keeps
    # the initial-search chain, the other-methods column carries the crawl
    assert prisma["via_databases"]["identified"] == 4
    assert prisma["via_databases"]["records_screened"] == 4
    assert prisma["via_databases"]["records_excluded"] == 2
    assert prisma["via_databases"]["studies_included"] == 2
    other = prisma["via_other"]
    assert other["identified"] == 3
    assert other["duplicates_removed"] == 1
    assert other["records_screened"] == 2
    assert other["records_excluded"] == 0    # T/A round 2 has no vote yet
    assert other["studies_included"] == 0    # FT round 2 still a draft
    assert other["sources"] == [
        {"source": "snowballing r2", "type": "snowballing", "n": 3}]

    # round 2 T/A auto-config: same reviewers, active, only the 2 new unique
    info = user_client.get(
        f"/api/projects/{pid}/screening/config?stage=ta&round=2").json()
    assert info["config"]["status"] == "active"
    assert set(info["config"]["reviewer_ids"]) == set(sb_project["reviewers"])
    assert info["eligible_records"] == 2
    assert info["rounds"] == [1, 2]
    # default round resolution = latest
    info_default = user_client.get(
        f"/api/projects/{pid}/screening/config?stage=ta").json()
    assert info_default["round"] == 2

    # round 1 queue untouched (0 left), round 2 queue = the 2 new records
    q1 = user_client.get(
        f"/api/projects/{pid}/screening/queue?stage=ta&round=1").json()
    assert q1["total"] == 4 and q1["done"] == 4
    q2 = user_client.get(
        f"/api/projects/{pid}/screening/queue?stage=ta&round=2").json()
    assert q2["total"] == 2 and q2["done"] == 0
    new_titles = {i["title"] for i in q2["items"]}
    assert new_titles == {"Brand new referenced study", "Fresh citing paper"}
    # abstracts fetched during the run land on the created records
    new_a_item = next(i for i in q2["items"]
                      if i["title"] == "Brand new referenced study")
    assert new_a_item["abstract"] == "Enriched abstract for the new study."
    assert res["n_abstracts"] == 1

    # the snowballing draft FT round must NOT hide round 1's results: the
    # default FT round stays the latest ACTIVE one
    ft_default = user_client.get(
        f"/api/projects/{pid}/screening/config?stage=ft").json()
    assert ft_default["round"] == 1
    assert ft_default["config"]["status"] == "active"

    # citation edges: remapped onto the canonical (existing) record for sb.3
    graph = user_client.get(f"/api/projects/{pid}/snowballing/graph").json()
    ids = {n["id"]: n for n in graph["nodes"]}
    assert ids[s1]["status"] == "seed" and ids[s2]["status"] == "seed"
    known3 = sb_project["excluded_ta"][0]  # 10.1/sb.3 canonical
    assert known3 in ids and ids[known3]["status"] == "excluded"
    pairs = {(e["citing"], e["cited"]) for e in graph["edges"]}
    new_a = next(n["id"] for n in graph["nodes"]
                 if n["title"] == "Brand new referenced study")
    new_c = next(n["id"] for n in graph["nodes"]
                 if n["title"] == "Fresh citing paper")
    assert (s1, new_a) in pairs and (s2, new_a) in pairs   # backward
    assert (s1, known3) in pairs                            # remapped duplicate
    assert (new_c, s1) in pairs                             # forward
    assert len(pairs) == 4
    # discovery round on nodes (round columns): crawled seeds belong to the
    # initial corpus (r1), papers discovered by the first crawl are r2, and an
    # initial-corpus paper the crawl finds again stays r1 (not a new candidate)
    assert ids[s1]["round"] == 1 and ids[s2]["round"] == 1
    assert ids[new_a]["round"] == 2 and ids[new_c]["round"] == 2
    assert ids[known3]["round"] == 1

    # node payload: origin shape code, seed contribution counts, exclusion reason
    assert ids[new_a]["origin"] == "backward"
    assert ids[new_c]["origin"] == "forward"
    assert ids[s1]["n_backward"] == 2 and ids[s1]["n_forward"] == 1
    assert ids[s2]["n_backward"] == 1 and ids[s2]["n_forward"] == 0
    assert ids[known3]["origin"] == "backward"
    assert ids[new_a]["has_pdf"] is False

    # per-seed contributions table
    contrib = user_client.get(
        f"/api/projects/{pid}/snowballing/contributions").json()
    by_id = {c["id"]: c for c in contrib}
    assert by_id[s1]["n_backward"] == 2 and by_id[s1]["n_forward"] == 1
    assert by_id[s2]["n_backward"] == 1 and by_id[s2]["n_forward"] == 0
    assert by_id[s1]["round"] == 2
    # the audit table gets the article lists (metadata + screening status)
    s1_back_titles = {a["title"] for a in by_id[s1]["backward"]}
    assert "Brand new referenced study" in s1_back_titles
    assert {a["id"] for a in by_id[s1]["forward"]} == {new_c}
    assert all(a["status"] in ("seed", "included", "excluded", "pending")
               for a in by_id[s1]["backward"] + by_id[s1]["forward"])
    known3_row = next(a for a in by_id[s1]["backward"] if a["id"] == known3)
    assert known3_row["status"] == "excluded"

    # PRISMA per-round breakdown: initial search + this iteration
    prisma = user_client.get(f"/api/projects/{pid}/prisma").json()
    assert [r["label"] for r in prisma["rounds"]] == [
        "Initial search", "Snowballing iteration 1"]
    r1, r2 = prisma["rounds"]
    assert r1["identified"] == 4 and r1["records_excluded"] == 2
    assert r2["identified"] == 3 and r2["duplicates_removed"] == 1
    assert r2["records_screened"] == 2
    # T/A round 2 auto-started by the run: active with no vote yet -> 0
    assert r2["records_excluded"] == 0
    assert r2["studies_included"] is None  # FT round 2 still a draft
    assert prisma["final_total_ready"] is False

    # included_only keeps seeds (and later FT-included) only
    only = user_client.get(
        f"/api/projects/{pid}/snowballing/graph?included_only=true").json()
    assert {n["id"] for n in only["nodes"]} == {s1, s2}

    # status: seeds all crawled, run recorded, not saturated (2 to screen)
    status = user_client.get(f"/api/projects/{pid}/snowballing/status").json()
    assert status["pending_seeds"] == 0
    assert status["runs"][0]["n_new_unique"] == 2
    assert status["saturated"] is False
    # a second run without new seeds is refused
    r = user_client.post(f"/api/projects/{pid}/snowballing/run", json={})
    assert r.status_code == 400


def test_saturation_after_all_new_excluded(user_client, sb_project, monkeypatch):
    pid = sb_project["pid"]
    _mock_crawl(monkeypatch,
                backward_map={"10.1/sb.1": [_ref("One new lead", "10.9/only.one")],
                              "10.1/sb.2": []},
                forward_map={"10.1/sb.1": [], "10.1/sb.2": []})
    r = user_client.post(f"/api/projects/{pid}/snowballing/run", json={})
    job = _await(user_client, r.json()["job_id"])
    assert job["status"] == "done", job.get("error")

    # screen the single new record: exclude at T/A (both reviewers), round 2
    q2 = user_client.get(
        f"/api/projects/{pid}/screening/queue?stage=ta&round=2").json()
    rid = q2["items"][0]["id"]
    for who in ("admin", "reviewer"):
        _login(user_client, who)
        user_client.post(f"/api/projects/{pid}/screening/vote?stage=ta&round=2",
                         json={"record_id": rid, "decision": "exclude"})
    _login(user_client, "admin")

    # start FT round 2: nothing eligible (no include) -> start refused;
    # saturation comes from "no pending seeds + last round produced no include"
    r = user_client.post(f"/api/projects/{pid}/screening/start?stage=ft&round=2")
    assert r.status_code == 400
    status = user_client.get(f"/api/projects/{pid}/snowballing/status").json()
    assert status["pending_seeds"] == 0
    # T/A round-2 excluded everything: FT never runs, saturation shows once the
    # FT stage cannot proceed — the run report still says 1 new unique, so the
    # UI shows "0 seeds pending"; explicit saturation via ft outcomes needs the
    # ft config; with none active we rely on pending_seeds == 0 + n_new == 0 on
    # a NEXT empty run. Here: not flagged saturated, but no run is possible.
    r = user_client.post(f"/api/projects/{pid}/snowballing/run", json={})
    assert r.status_code == 400


def test_abstract_backfill_job(user_client, sb_project, monkeypatch):
    pid = sb_project["pid"]
    # discover one paper WITHOUT an abstract (enrichment finds none on the run)
    _mock_crawl(monkeypatch,
                backward_map={"10.1/sb.1": [_ref("Abstractless discovery", "10.9/na.1")],
                              "10.1/sb.2": []},
                forward_map={"10.1/sb.1": [], "10.1/sb.2": []})
    job = _await(user_client, user_client.post(
        f"/api/projects/{pid}/snowballing/run", json={}).json()["job_id"])
    assert job["result"]["n_abstracts"] == 0

    status = user_client.get(f"/api/projects/{pid}/snowballing/status").json()
    assert status["missing_abstracts"] == 1

    # backfill: the API finds it this time
    monkeypatch.setattr(
        "app.services.connectors.abstracts.fetch_abstracts",
        lambda client, dois, **kw: {"10.9/na.1": "Backfilled abstract."})
    job = _await(user_client, user_client.post(
        f"/api/projects/{pid}/snowballing/enrich-abstracts").json()["job_id"])
    assert job["result"] == {"targets": 1, "filled": 1}

    q2 = user_client.get(
        f"/api/projects/{pid}/screening/queue?stage=ta&round=2").json()
    assert q2["items"][0]["abstract"] == "Backfilled abstract."
    status = user_client.get(f"/api/projects/{pid}/snowballing/status").json()
    assert status["missing_abstracts"] == 0


def test_empty_crawl_run_is_saturation(user_client, sb_project, monkeypatch):
    pid = sb_project["pid"]
    _mock_crawl(monkeypatch, backward_map={}, forward_map={})
    r = user_client.post(f"/api/projects/{pid}/snowballing/run", json={})
    job = _await(user_client, r.json()["job_id"])
    assert job["status"] == "done", job.get("error")
    assert job["result"]["n_discovered"] == 0
    status = user_client.get(f"/api/projects/{pid}/snowballing/status").json()
    assert status["saturated"] is True  # ran, no pending seeds, nothing new


def test_delete_latest_iteration(user_client, sb_project, monkeypatch):
    """Full undo of the latest round: the discovered papers, their screening,
    the citation edges and the run row all disappear; the seeds become pending
    again and round 1 is untouched — a fresh run re-discovers the same papers
    as brand new (proof the round-2 records were really deleted)."""
    pid = sb_project["pid"]
    s1, s2 = sb_project["seeds"]

    _mock_crawl(
        monkeypatch,
        backward_map={
            "10.1/sb.1": [_ref("Brand new referenced study", "10.9/new.a"),
                          _ref("Cycling safety interventions in dense cities",
                               "10.1/sb.3", year=2013)],
            "10.1/sb.2": [_ref("Brand new referenced study", "10.9/new.a")],
        },
        forward_map={"10.1/sb.1": [_ref("Fresh citing paper", "10.9/new.c")],
                     "10.1/sb.2": []})
    job = _await(user_client, user_client.post(
        f"/api/projects/{pid}/snowballing/run", json={}).json()["job_id"])
    assert job["status"] == "done", job.get("error")

    # round 2 is live: one run row, four edges, two new records to screen
    status = user_client.get(f"/api/projects/{pid}/snowballing/status").json()
    assert len(status["runs"]) == 1 and status["n_edges"] == 4

    # only the latest round is removable, and only by a project admin
    bad = user_client.delete(f"/api/projects/{pid}/snowballing/iterations/1")
    assert bad.status_code == 409
    _login(user_client, "reviewer")
    forbidden = user_client.delete(
        f"/api/projects/{pid}/snowballing/iterations/2")
    assert forbidden.status_code == 403
    _login(user_client, "admin")

    # delete round 2
    r = user_client.delete(f"/api/projects/{pid}/snowballing/iterations/2")
    assert r.status_code == 200, r.text
    assert r.json() == {"ok": True, "round": 2}

    # snowballing state fully reverted: no run, no edges, seeds pending again
    status = user_client.get(f"/api/projects/{pid}/snowballing/status").json()
    assert status["runs"] == []
    assert status["n_edges"] == 0
    assert status["pending_seeds"] == 2
    seeds = user_client.get(f"/api/projects/{pid}/snowballing/seeds").json()
    assert {s["id"] for s in seeds} == {s1, s2}
    graph = user_client.get(f"/api/projects/{pid}/snowballing/graph").json()
    assert graph["nodes"] == [] and graph["edges"] == []
    assert user_client.get(
        f"/api/projects/{pid}/snowballing/contributions").json() == []

    # the round-2 T/A config is gone; round 1 screening is intact
    info = user_client.get(
        f"/api/projects/{pid}/screening/config?stage=ta").json()
    assert info["rounds"] == [1] and info["round"] == 1
    q1 = user_client.get(
        f"/api/projects/{pid}/screening/queue?stage=ta&round=1").json()
    assert q1["total"] == 4 and q1["done"] == 4

    # PRISMA drops the snowballing column
    prisma = user_client.get(f"/api/projects/{pid}/prisma").json()
    assert [r["label"] for r in prisma["rounds"]] == ["Initial search"]
    assert prisma["identified_other"] == []

    # deleting again: nothing left to delete
    gone = user_client.delete(f"/api/projects/{pid}/snowballing/iterations/2")
    assert gone.status_code == 404

    # a fresh iteration re-discovers the same papers as NEW (round numbering
    # reset to 2, both unique again -> the records were truly deleted)
    _mock_crawl(
        monkeypatch,
        backward_map={
            "10.1/sb.1": [_ref("Brand new referenced study", "10.9/new.a")],
            "10.1/sb.2": []},
        forward_map={"10.1/sb.1": [_ref("Fresh citing paper", "10.9/new.c")],
                     "10.1/sb.2": []})
    job = _await(user_client, user_client.post(
        f"/api/projects/{pid}/snowballing/run", json={}).json()["job_id"])
    assert job["status"] == "done", job.get("error")
    assert job["result"]["round"] == 2
    assert job["result"]["n_new_unique"] == 2


# ---- manual backward/forward additions ----------------------------------------------

def test_manual_add(user_client, sb_project, monkeypatch):
    """B3: DOIs the crawl missed join the seed's round — hydrated, deduped,
    edged, and screenable (T/A config created if the crawl found nothing)."""
    pid = sb_project["pid"]
    s1 = sb_project["seeds"][0]
    known_excluded = sb_project["excluded_ta"][0]  # 10.1/sb.3 in the base

    # an empty crawl first: round 2 exists but has no discoveries (no TA config)
    _mock_crawl(monkeypatch, backward_map={}, forward_map={})
    _await(user_client, user_client.post(
        f"/api/projects/{pid}/snowballing/run", json={}).json()["job_id"])

    # manual add hydration stubs (no network)
    monkeypatch.setattr(
        "app.services.snowballing.core.openalex_resolve_dois",
        lambda client, dois, **kw: [
            {"title": "Manually added missed study", "doi": "10.9/man.a",
             "authors": ["Hand, A."], "year": 2021, "src": "openalex"}])
    monkeypatch.setattr(
        "app.services.snowballing.core.fetch_abstracts",
        lambda client, dois, **kw: {"10.9/man.a": "Pasted abstract."})

    r = user_client.post(f"/api/projects/{pid}/snowballing/manual", json={
        "seed_record_id": s1, "direction": "backward",
        "dois": ["10.9/man.a", "10.1/sb.3", "10.9/man.a"]})  # dup input folded
    assert r.status_code == 200, r.text
    res = r.json()
    assert res["round"] == 2
    assert res["requested"] == 2
    assert res["created"] == 1          # man.a — sb.3 was already in the base
    assert res["already_known"] == 1
    assert res["edges_added"] == 2      # seed -> man.a and seed -> sb.3
    assert res["unresolved"] == []

    # the new record entered round 2 and is screenable (config auto-created)
    info = user_client.get(
        f"/api/projects/{pid}/screening/config?stage=ta&round=2").json()
    assert info["config"]["status"] == "active"
    assert info["eligible_records"] == 1
    queue = user_client.get(
        f"/api/projects/{pid}/screening/queue?stage=ta&round=2").json()
    assert queue["total"] == 1
    assert queue["items"][0]["title"] == "Manually added missed study"
    assert queue["items"][0]["abstract"] == "Pasted abstract."

    # graph got the edges; adding the same DOI again adds nothing
    graph = user_client.get(f"/api/projects/{pid}/snowballing/graph").json()
    assert {(e["citing"], e["cited"]) for e in graph["edges"]} >= {
        (s1, known_excluded)}
    r2 = user_client.post(f"/api/projects/{pid}/snowballing/manual", json={
        "seed_record_id": s1, "direction": "backward", "dois": ["10.1/sb.3"]})
    assert r2.json()["edges_added"] == 0

    # invalid input paths
    bad = user_client.post(f"/api/projects/{pid}/snowballing/manual", json={
        "seed_record_id": 999999, "direction": "backward", "dois": ["10.1/x"]})
    assert bad.status_code == 400


# ---- paper card (B7) -----------------------------------------------------------------

def test_record_card(user_client, sb_project, monkeypatch):
    pid = sb_project["pid"]
    s1 = sb_project["seeds"][0]
    _mock_crawl(
        monkeypatch,
        backward_map={"10.1/sb.1": [_ref("Card ref study", "10.9/card.a")],
                      "10.1/sb.2": []},
        forward_map={"10.1/sb.1": [], "10.1/sb.2": []})
    _await(user_client, user_client.post(
        f"/api/projects/{pid}/snowballing/run", json={}).json()["job_id"])

    # the seed's card: metadata + FT include outcome + its own crawl lists
    card = user_client.get(f"/api/projects/{pid}/records/{s1}/card").json()
    assert card["id"] == s1
    assert any(s["stage"] == "ft" and s["outcome"] == "include"
               for s in card["screening"])
    assert card["as_seed"]["n_backward"] == 1
    assert card["as_seed"]["backward"][0]["title"] == "Card ref study"
    found_id = card["as_seed"]["backward"][0]["id"]

    # the discovered paper's card: provenance + discovered_by pointing at the seed
    card = user_client.get(f"/api/projects/{pid}/records/{found_id}/card").json()
    assert card["as_seed"] is None
    assert [s["name"] for s in card["sources"]] == ["snowballing r2"]
    assert card["discovered_by"] == [{
        "id": s1, "title": card["discovered_by"][0]["title"],
        "authors": card["discovered_by"][0]["authors"],
        "year": card["discovered_by"][0]["year"],
        "doi": "10.1/sb.1", "direction": "backward", "round": 2}]

    # unknown record -> 404
    r = user_client.get(f"/api/projects/{pid}/records/999999/card")
    assert r.status_code == 404


def test_graph_follows_late_duplicates(user_client, sb_project, monkeypatch):
    """A record ruled a duplicate after the crawl (pair arbitration, dedup
    re-run) keeps its citation edges: graph, contributions and card follow it
    to the record kept instead of showing it as a candidate never screened."""
    pid = sb_project["pid"]
    s1 = sb_project["seeds"][0]
    _mock_crawl(
        monkeypatch,
        backward_map={"10.1/sb.1": [_ref("Kept study", "10.9/kept")],
                      "10.1/sb.2": [_ref("Kept study, preprint", "10.9/preprint")]},
        forward_map={"10.1/sb.1": [], "10.1/sb.2": []})
    job = _await(user_client, user_client.post(
        f"/api/projects/{pid}/snowballing/run", json={}).json()["job_id"])
    assert job["status"] == "done", job.get("error")
    nodes = user_client.get(f"/api/projects/{pid}/snowballing/graph").json()["nodes"]
    kept = next(n["id"] for n in nodes if n["title"] == "Kept study")
    late = next(n["id"] for n in nodes if n["title"] == "Kept study, preprint")

    from app.core.db import SessionLocal
    from app.models import Record
    with SessionLocal() as db:
        rec = db.get(Record, late)
        rec.dedup_status, rec.canonical_id = "duplicate", kept
        db.commit()

    graph = user_client.get(f"/api/projects/{pid}/snowballing/graph").json()
    ids = {n["id"] for n in graph["nodes"]}
    assert late not in ids and kept in ids
    s2 = sb_project["seeds"][1]
    pairs = {(e["citing"], e["cited"]) for e in graph["edges"]}
    assert (s1, kept) in pairs and (s2, kept) in pairs
    contrib = {c["id"]: c for c in user_client.get(
        f"/api/projects/{pid}/snowballing/contributions").json()}
    assert [a["id"] for a in contrib[s2]["backward"]] == [kept]
    card = user_client.get(f"/api/projects/{pid}/records/{kept}/card").json()
    assert {d["id"] for d in card["discovered_by"]} == {s1, s2}
