import time

import pytest

from app.services.dedup import first_author_key, normalize_title

# Calibrated fixture (token_sort_ratio on normalized titles):
#  A4 vs A1 -> 99.0  auto-merge (same first author, year +-1)
#  D2 vs D1 -> 95.7  but no authors -> uncertain (manual arbitration)
#  B2 vs B1 -> 89.5  uncertainty window -> manual arbitration
#  E2 vs E1 -> ~97   but years 2010 vs 2020 -> NOT a duplicate
MAIN_RIS = """TY  - JOUR
TI  - Gamification of driving behaviour: a systematic review
AU  - Dupont, Jean
PY  - 2020
DO  - 10.1/dup.a
ER  -
TY  - JOUR
TI  - Totally different rendering of the same paper title
AU  - Dupont, Jean
PY  - 2020
DO  - 10.1/dup.a
ER  -
TY  - JOUR
TI  - GAMIFICATION OF DRIVING BEHAVIOUR - A Systematic Review!
AU  - Dupont, J.
PY  - 2020
ER  -
TY  - JOUR
TI  - Gamification of driving behavior: a systematic review
AU  - Dupont, J.
PY  - 2021
AB  - An abstract only present on the duplicate.
ER  -
TY  - JOUR
TI  - Gamified feedback and driver speed: a simulator study
AU  - Martin, Paul
PY  - 2019
ER  -
TY  - JOUR
TI  - Gamified feedback and driving speed: simulator studies
AU  - Martin, P.
PY  - 2019
ER  -
TY  - JOUR
TI  - Serious games for road safety
AU  - Chen, Wei
PY  - 2022
ER  -
TY  - JOUR
TI  - Effects of gamified feedback on driver speed
PY  - 2018
ER  -
TY  - JOUR
TI  - Effects of gamified feedbacks on driver speeding
PY  - 2018
ER  -
TY  - JOUR
TI  - Cycling infrastructure and helmet use in urban areas
AU  - Smith, Anna
PY  - 2010
ER  -
TY  - JOUR
TI  - Cycling infrastructure and helmet usage in urban areas
AU  - Smith, Anna
PY  - 2020
ER  -
"""


def test_normalize_title():
    assert normalize_title("GAMIFICATION of Driving — a review!") == \
        normalize_title("gamification of driving:  a review")
    assert normalize_title(None) == ""


def test_first_author_key():
    assert first_author_key(["Dupont, Jean", "X"]) == "dupont"
    assert first_author_key(["Jean Dupont"]) == "dupont"
    assert first_author_key(["Dupont J"]) == "j"  # no comma: last token
    assert first_author_key([]) == ""


@pytest.fixture
def project(user_client):
    return user_client.post("/api/projects", json={"name": "M4 demo"}).json()


def _import(client, pid, ris, source="pubmed"):
    return client.post(
        f"/api/projects/{pid}/imports/upload",
        files={"file": (f"{source}.ris", ris.encode(), "text/plain")},
        data={"source_name": source, "source_type": "database"},
    )


def _run_dedup(client, pid):
    job_id = client.post(f"/api/projects/{pid}/dedup/run").json()["job_id"]
    for _ in range(200):
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in ("done", "failed"):
            return job
        time.sleep(0.05)
    return job


RICHER_RIS = """TY  - JOUR
TI  - Telehealth adoption drivers in rural areas
AU  - Ng, Amy
PY  - 2022
DO  - 10.1/rich.1
AB  - Short.
ER  -
TY  - JOUR
TI  - Telehealth adoption drivers in rural areas
AU  - Ng, Amy
PY  - 2022
DO  - 10.1/rich.1
AB  - A much longer and more complete abstract with background, methods, results and conclusions.
ER  -
"""


def test_canonical_keeps_fullest_abstract(user_client, project):
    """The canonical id never swaps, but its content keeps the richest
    version per field — here the duplicate's fuller abstract wins."""
    pid = project["id"]
    _import(user_client, pid, RICHER_RIS)
    job = _run_dedup(user_client, pid)
    assert job["status"] == "done"
    items = user_client.get(f"/api/projects/{pid}/records",
                            params={"q": "Telehealth",
                                    "dedup": "unique"}).json()["items"]
    assert len(items) == 1
    assert "much longer and more complete" in items[0]["abstract"]


def test_dedup_passes_and_arbitration(user_client, project):
    pid = project["id"]
    r = _import(user_client, pid, MAIN_RIS)
    assert r.json()["n_records"] == 11

    job = _run_dedup(user_client, pid)
    assert job["status"] == "done", job.get("error")
    assert job["result"]["auto_duplicates"] == 3   # doi, exact title, fuzzy 99
    assert job["result"]["new_uncertain"] == 2     # 95.7 no-authors + 89.5
    assert job["result"]["unique"] == 6            # incl. the year-blocked pair

    summary = user_client.get(f"/api/projects/{pid}/dedup/summary").json()
    assert summary["total"] == 11
    assert summary["duplicate"] == 3
    assert summary["uncertain"] == 2
    assert summary["unique"] == 6
    assert summary["pending"] == 0
    assert summary["pending_pairs"] == 2

    # canonical got enriched with the duplicate's abstract
    enriched = user_client.get(f"/api/projects/{pid}/records",
                               params={"q": "systematic review",
                                       "dedup": "unique"}).json()
    assert any("abstract only present on the duplicate" in i["abstract"]
               for i in enriched["items"])

    # dedup status filter on the records table
    dups = user_client.get(f"/api/projects/{pid}/records",
                           params={"dedup": "duplicate"}).json()
    assert dups["total"] == 3

    # arbitration queue, best score first
    pairs = user_client.get(f"/api/projects/{pid}/dedup/pairs").json()
    assert len(pairs) == 2
    assert pairs[0]["score"] >= pairs[1]["score"]
    assert pairs[0]["record"]["title"].startswith("Effects of gamified feedbacks")

    # resolve: merge the 95.7 pair, keep the 89.5 pair distinct
    r = user_client.post(f"/api/projects/{pid}/dedup/pairs/{pairs[0]['id']}/resolve",
                         json={"decision": "merge"})
    assert r.json()["remaining"] == 1
    r = user_client.post(f"/api/projects/{pid}/dedup/pairs/{pairs[1]['id']}/resolve",
                         json={"decision": "distinct"})
    assert r.json()["remaining"] == 0

    summary = user_client.get(f"/api/projects/{pid}/dedup/summary").json()
    assert summary["duplicate"] == 4
    assert summary["unique"] == 7
    assert summary["uncertain"] == 0

    # re-resolving is rejected
    r = user_client.post(f"/api/projects/{pid}/dedup/pairs/{pairs[1]['id']}/resolve",
                         json={"decision": "merge"})
    assert r.status_code == 400


def test_rerun_respects_resolutions_and_new_imports(user_client, project):
    pid = project["id"]
    _import(user_client, pid, MAIN_RIS)
    _run_dedup(user_client, pid)
    pairs = user_client.get(f"/api/projects/{pid}/dedup/pairs").json()
    for pair, decision in zip(pairs, ["merge", "distinct"]):
        user_client.post(f"/api/projects/{pid}/dedup/pairs/{pair['id']}/resolve",
                         json={"decision": decision})

    # re-run: nothing changes, "distinct" is not re-flagged
    job = _run_dedup(user_client, pid)
    assert job["result"]["new_uncertain"] == 0
    assert job["result"]["prior_duplicates"] == 4
    summary = user_client.get(f"/api/projects/{pid}/dedup/summary").json()
    assert summary["pending_pairs"] == 0
    assert summary["duplicate"] == 4 and summary["unique"] == 7

    # a new import (cross-database duplicate by DOI + one new record)
    second = """TY  - JOUR
TI  - The same gamification review, retitled by another database
AU  - Dupont, Jean
PY  - 2020
DO  - 10.1/dup.a
ER  -
TY  - JOUR
TI  - A brand new unrelated article about pedestrians
AU  - Novak, Petra
PY  - 2023
DO  - 10.1/new.1
ER  -
"""
    _import(user_client, pid, second, source="openalex")
    job = _run_dedup(user_client, pid)
    assert job["result"]["auto_duplicates"] == 1   # the cross-database DOI dup
    summary = user_client.get(f"/api/projects/{pid}/dedup/summary").json()
    assert summary["total"] == 13
    assert summary["duplicate"] == 5
    assert summary["unique"] == 8
    assert {s["source"]: s["n"] for s in summary["per_source"]} == \
        {"pubmed": 11, "openalex": 2}


def test_merged_duplicates_listing_and_prisma(user_client, project):
    pid = project["id"]
    _import(user_client, pid, MAIN_RIS)
    _run_dedup(user_client, pid)

    merged = user_client.get(f"/api/projects/{pid}/dedup/duplicates").json()
    assert len(merged) == 3
    reasons = sorted(m["reason"] for m in merged)
    assert reasons == ["doi", "fuzzy_title", "title_exact"]
    assert all(not m["manual"] for m in merged)
    fuzzy = next(m for m in merged if m["reason"] == "fuzzy_title")
    assert fuzzy["score"] and 92 <= fuzzy["score"] <= 100
    assert fuzzy["canonical"]["title"].startswith("Gamification of driving behaviour")

    # a manual merge shows up flagged as manual
    pairs = user_client.get(f"/api/projects/{pid}/dedup/pairs").json()
    user_client.post(f"/api/projects/{pid}/dedup/pairs/{pairs[0]['id']}/resolve",
                     json={"decision": "merge"})
    merged = user_client.get(f"/api/projects/{pid}/dedup/duplicates").json()
    assert len(merged) == 4
    assert sum(1 for m in merged if m["manual"]) == 1

    # PRISMA live counters
    prisma = user_client.get(f"/api/projects/{pid}/prisma").json()
    assert prisma["n_databases"] == 11
    assert prisma["duplicates_removed"] == 4
    assert prisma["records_screened"] == 6
    assert prisma["dedup_unresolved"] == 1   # the remaining uncertain pair
    assert prisma["records_excluded"] is None  # screening not implemented yet
    assert prisma["identified_databases"] == [{"source": "pubmed", "n": 11}]


def test_reviewer_cannot_run_or_resolve(user_client, project):
    pid = project["id"]
    _import(user_client, pid, MAIN_RIS)
    user_client.post("/api/auth/register", json={
        "email": "rev4@example.com", "password": "password123", "display_name": "R"})
    user_client.post("/api/auth/login", json={
        "email": "admin@example.com", "password": "password123"})
    user_client.post(f"/api/projects/{pid}/members",
                     json={"email": "rev4@example.com", "role": "reviewer"})
    user_client.post("/api/auth/login", json={
        "email": "rev4@example.com", "password": "password123"})
    assert user_client.post(f"/api/projects/{pid}/dedup/run").status_code == 403
    assert user_client.get(f"/api/projects/{pid}/dedup/summary").status_code == 200
