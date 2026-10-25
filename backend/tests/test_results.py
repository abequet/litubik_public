"""M10 — results/synthesis: country normalization, consensus rule, live
aggregates endpoint, AI narrative persistence, long-format CSV export."""
import time
from types import SimpleNamespace

import pytest

from app.services.results.compute import consensus_cell
from app.services.results.countries import normalize_cell

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
DO  - 10.1/res.{i}
AB  - Abstract of study {i}.
ER  -
""" for i, title in enumerate(_TITLES, start=1))


def _login(client, who):
    email = "admin@example.com" if who == "admin" else "rev@example.com"
    client.post("/api/auth/login", json={"email": email, "password": "password123"})


def _await_job(client, job_id):
    for _ in range(100):
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in ("done", "failed"):
            return job
        time.sleep(0.05)
    raise AssertionError("job never finished")


# ---- country normalization (pure) --------------------------------------------------

@pytest.mark.parametrize("text,expected", [
    ("France", ["FRA"]),
    (" france ", ["FRA"]),
    ("États-Unis", ["USA"]),
    ("etats-unis", ["USA"]),
    ("Corée du Sud", ["KOR"]),
    ("UK", ["GBR"]),
    ("England", ["GBR"]),
    ("usa", ["USA"]),
    ("US", ["USA"]),
    ("Namibia", ["NAM"]),
    ("Iran (Islamic Republic of)", ["IRN"]),
    ("Côte d'Ivoire", ["CIV"]),
    ("Ivory Coast", ["CIV"]),
    ("Trinidad and Tobago", ["TTO"]),
    ("The Netherlands", ["NLD"]),
    ("Holland", ["NLD"]),
])
def test_normalize_single_country(text, expected):
    assert normalize_cell(text) == (expected, [])


@pytest.mark.parametrize("text,expected", [
    ("France / Germany", ["FRA", "DEU"]),
    ("USA, UK & Canada", ["USA", "GBR", "CAN"]),
    ("France et Allemagne", ["FRA", "DEU"]),
    ("France and Germany", ["FRA", "DEU"]),
    ("Bosnia and Herzegovina, France", ["BIH", "FRA"]),
    ("France, france", ["FRA"]),  # de-dup
])
def test_normalize_multi_country(text, expected):
    assert normalize_cell(text) == (expected, [])


def test_normalize_unmatched_and_none_tokens():
    assert normalize_cell("Bavaria") == ([], ["Bavaria"])
    assert normalize_cell("France; Atlantis") == (["FRA"], ["Atlantis"])
    # "not applicable" spellings are missing, never Namibia / unmatched noise
    for none_ish in ("", "N/A", "NA", "n.a.", "not reported", "Unknown", "-"):
        assert normalize_cell(none_ish) == ([], [])


# ---- consensus rule (pure) ----------------------------------------------------------

def _v(value, validated):
    return SimpleNamespace(value={"v": value}, validated=validated)


def test_consensus_cell():
    assert consensus_cell([]) == (None, "empty")
    assert consensus_cell([_v(None, True)]) == (None, "empty")
    assert consensus_cell([_v("France", False)]) == ("France", "ok")
    # validated beats unvalidated
    assert consensus_cell([_v("France", True),
                           _v("Belgium", False)]) == ("France", "ok")
    # two validated agreeing
    assert consensus_cell([_v(42, True), _v(42, True)]) == (42, "ok")
    # genuine disagreement -> excluded from aggregates
    assert consensus_cell([_v("field", True),
                           _v("lab", True)]) == (None, "conflict")
    # list values (multi) compare structurally
    assert consensus_cell([_v(["a", "b"], True),
                           _v(["a", "b"], True)]) == (["a", "b"], "ok")


# ---- seeded project -----------------------------------------------------------------

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
def res_project(user_client, team):
    """4 records through T/A + FT screening (3 FT-includes), then a small
    extraction table filled with consensus values, one conflict and one JBI."""
    pid = user_client.post("/api/projects", json={"name": "M10 demo"}).json()["id"]
    user_client.post(f"/api/projects/{pid}/members",
                     json={"email": "rev@example.com", "role": "reviewer"})
    user_client.post(f"/api/projects/{pid}/imports/upload",
                     files={"file": ("s.ris", RIS.encode(), "text/plain")},
                     data={"source_name": "pubmed", "source_type": "database"})
    _await_job(user_client, user_client.post(
        f"/api/projects/{pid}/dedup/run").json()["job_id"])
    user_client.post(f"/api/projects/{pid}/protocols/upload",
                     files={"file": ("p.md", b"# P\n\nText", "text/markdown")})
    prot = user_client.get(f"/api/projects/{pid}/protocols").json()[0]
    user_client.put(f"/api/projects/{pid}/protocols/{prot['id']}", json={
        "protocol_md": "# P", "criteria": [
            {"code": "E1", "type": "exclude", "label": "wrong population",
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
        for rid in ta_ids:
            user_client.post(f"/api/projects/{pid}/screening/vote",
                             json={"record_id": rid, "decision": "include"})
    _login(user_client, "admin")
    user_client.put(f"/api/projects/{pid}/screening/config", json={
        "stage": "ft", "allocation": "all", "conflict_resolution": "consensus",
        "reviewer_ids": reviewers})
    user_client.post(f"/api/projects/{pid}/screening/start?stage=ft")
    for who in ("admin", "reviewer"):
        _login(user_client, who)
        for idx, rid in enumerate(ta_ids):
            payload = {"record_id": rid, "decision": "include"}
            if idx == 3:
                payload = {"record_id": rid, "decision": "exclude",
                           "reasons": ["E1"]}
            user_client.post(f"/api/projects/{pid}/screening/vote?stage=ft",
                             json=payload)
    _login(user_client, "admin")

    # extraction table: Country (text) + Setting (choice) + Sample size (number)
    base = f"/api/projects/{pid}/extraction"
    for payload in ({"name": "Country", "col_type": "text"},
                    {"name": "Setting", "col_type": "choice",
                     "options": ["field", "lab"]},
                    {"name": "Sample size (N)", "col_type": "number"}):
        user_client.post(f"{base}/columns", json=payload)
    cols = {c["name"]: c["id"]
            for c in user_client.get(f"{base}/columns").json()}
    r1, r2, r3 = ta_ids[:3]
    for rid, country in ((r1, "France / Germany"), (r2, "États-Unis"),
                         (r3, "Atlantis")):
        user_client.put(f"{base}/values", json={
            "record_id": rid, "column_id": cols["Country"], "value": country})
    user_client.put(f"{base}/values", json={
        "record_id": r1, "column_id": cols["Setting"], "value": "field"})
    user_client.put(f"{base}/values", json={
        "record_id": r2, "column_id": cols["Setting"], "value": "lab"})
    user_client.put(f"{base}/values", json={
        "record_id": r1, "column_id": cols["Sample size (N)"], "value": "120"})
    user_client.put(f"{base}/values", json={
        "record_id": r2, "column_id": cols["Sample size (N)"], "value": "40"})
    # a genuine double-extraction conflict on r3's Setting
    user_client.put(f"{base}/values", json={
        "record_id": r3, "column_id": cols["Setting"], "value": "field"})
    _login(user_client, "reviewer")
    user_client.put(f"{base}/values", json={
        "record_id": r3, "column_id": cols["Setting"], "value": "lab"})
    _login(user_client, "admin")
    # one JBI appraisal on r1
    user_client.put(f"{base}/records/{r1}/design", json={"design": "rct"})
    user_client.put(f"{base}/records/{r1}/jbi", json={
        "answers": {"q1": {"answer": "yes", "comment": ""},
                    "q2": {"answer": "no", "comment": ""},
                    "q3": {"answer": "unclear", "comment": ""}},
        "overall": "include"})
    return {"pid": pid, "included": ta_ids[:3], "cols": cols}


def test_aggregates_endpoint(user_client, team, res_project):
    pid = res_project["pid"]
    data = user_client.get(f"/api/projects/{pid}/results").json()

    assert data["n_included"] == 3
    assert data["n_with_any_value"] == 3
    assert data["n_fully_validated"] == 3   # every stored cell is validated

    # years come straight from the RIS (2011..2013 for the included set)
    assert data["years"]["counts"] == [{"year": 2011, "n": 1},
                                       {"year": 2012, "n": 1},
                                       {"year": 2013, "n": 1}]
    assert data["years"]["unknown"] == 0

    # designs: one rct, two not qualified
    assert {(d["design"], d["n"]) for d in data["designs"]} == \
        {("rct", 1), (None, 2)}

    # countries: multi-country study counted once per country
    c = data["countries"]
    assert c["column_name"] == "Country"
    assert {(x["iso3"], x["n"]) for x in c["counts"]} == \
        {("FRA", 1), ("DEU", 1), ("USA", 1)}
    assert c["counts"][0]["name"] in ("France", "Germany", "United States")
    assert c["n_studies_with_country"] == 2
    assert c["n_multi_country"] == 1
    assert c["unmatched"] == [{"value": "Atlantis", "n": 1}]
    assert c["missing"] == 0

    # per-column blocks: text columns omitted, country column handled above
    by_name = {b["name"]: b for b in data["columns"]}
    assert set(by_name) == {"Setting", "Sample size (N)"}
    setting = by_name["Setting"]
    assert setting["distribution"] == [{"value": "field", "n": 1},
                                       {"value": "lab", "n": 1}]
    assert setting["n_conflicts"] == 1 and setting["n_missing"] == 0
    n_col = by_name["Sample size (N)"]
    assert n_col["values"] == [40, 120]
    assert n_col["stats"]["n"] == 2
    assert n_col["stats"]["median"] == 80
    assert n_col["n_missing"] == 1

    # JBI pooled answers
    assert data["jbi"]["n_appraised"] == 1
    study = data["jbi"]["per_study"][0]
    assert study["answers"] == {"yes": 1, "no": 1, "unclear": 1, "na": 0}
    assert study["pct_yes"] == pytest.approx(1 / 3, abs=1e-3)
    assert study["n_questions"] == 13
    assert data["jbi"]["by_design"] == [
        {"design": "rct", "n_studies": 1,
         "avg_pct_yes": study["pct_yes"]}]

    # per-study consensus rows (client-side cross-filtering)
    studies = {s["record_id"]: s for s in data["studies"]}
    assert set(studies) == set(res_project["included"])
    r1, r2, r3 = res_project["included"]
    setting_id = str(res_project["cols"]["Setting"])
    assert sorted(studies[r1]["countries"]) == ["DEU", "FRA"]
    assert studies[r1]["values"][setting_id] == {"v": "field", "s": "ok"}
    assert studies[r3]["values"][setting_id]["s"] == "conflict"
    assert studies[r3]["countries"] == []
    assert studies[r3]["countries_unmatched"] == ["Atlantis"]
    assert studies[r1]["year"] in (2011, 2012, 2013)


def test_aggregates_empty_project(user_client, team):
    pid = user_client.post("/api/projects", json={"name": "empty"}).json()["id"]
    data = user_client.get(f"/api/projects/{pid}/results").json()
    assert data["n_included"] == 0
    assert data["extraction_started"] is False
    assert data["countries"]["column_id"] is None
    assert data["columns"] == [] and data["jbi"]["per_study"] == []
    assert data["studies"] == []


def test_narrative_generate_and_persist(user_client, team, res_project,
                                        monkeypatch):
    pid = res_project["pid"]
    url = f"/api/projects/{pid}/results/narrative"

    # nothing yet; estimate is None without an API key
    assert user_client.get(url).json() == {"narrative": None}
    assert user_client.get(f"{url}/estimate").json() == {"cost": None}

    user_client.put("/api/llm/credentials", json={
        "provider": "anthropic", "api_key": "sk-ant-fake-key-123"})
    est = user_client.get(f"{url}/estimate").json()["cost"]
    assert est["estimated"] is True and est["tokens_in"] > 0

    class FakeProvider:
        name = "anthropic"
        model = "claude-fake"

        def __init__(self, text):
            self.text = text

        def generate(self, messages, system=None, max_tokens=4096):
            from app.services.llm.base import LLMResult
            assert "Results section" in system
            assert "Evidence table" in messages[0]["content"]
            return LLMResult(text=self.text, tokens_input=100,
                             tokens_output=50)

    monkeypatch.setattr("app.services.results.narrative.open_provider_chain",
                        lambda *a, **kw: FakeProvider("## Results\n\nDraft 1"))
    out = user_client.post(f"{url}/generate").json()["narrative"]
    assert out["content_md"] == "## Results\n\nDraft 1"
    assert out["cost"]["tokens_in"] == 100 and out["cost"]["estimated"] is False
    assert out["generated_by_name"] == "Admin"

    # persisted (visible on a plain GET) and the stage counts as done
    assert user_client.get(url).json()["narrative"]["content_md"] \
        == "## Results\n\nDraft 1"
    progress = user_client.get(f"/api/projects/{pid}/progress").json()
    assert "results" in progress["done"]

    # regenerate overwrites the single per-project row
    monkeypatch.setattr("app.services.results.narrative.open_provider_chain",
                        lambda *a, **kw: FakeProvider("## Results\n\nDraft 2"))
    user_client.post(f"{url}/generate")
    assert user_client.get(url).json()["narrative"]["content_md"] \
        == "## Results\n\nDraft 2"


def test_narrative_requires_included_studies(user_client, team, monkeypatch):
    pid = user_client.post("/api/projects", json={"name": "empty"}).json()["id"]
    r = user_client.post(f"/api/projects/{pid}/results/narrative/generate")
    assert r.status_code == 400
    assert "included" in r.json()["detail"]


def test_export_csv(user_client, team, res_project):
    pid = res_project["pid"]
    r = user_client.get(f"/api/projects/{pid}/results/export.csv")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    lines = r.text.lstrip("﻿").splitlines()
    assert lines[0] == "Section,Item,Detail,N"
    assert "summary,included studies,,3" in lines
    assert "studies per year,2011,,1" in lines
    assert "countries,France,FRA,1" in lines
    assert "countries (unrecognized),Atlantis,,1" in lines
    assert any(line.startswith("column: Sample size (N),median,80")
               for line in lines)
