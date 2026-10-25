"""The databases a review searches (Project.databases) and the AI drafts of a
raw equation's other syntaxes: auto-draft job, flags, validation, reports."""
import time

import pytest

from app.services.equations import drafting
from app.services.equations.jobs import equation_draft_all_handler

PUBMED = '("emergency driving"[tiab] OR "ambulance driver*"[tiab]) AND stress[tiab]'


def _await(client, job_id, timeout=30):
    t0 = time.time()
    while time.time() - t0 < timeout:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in ("done", "failed"):
            return job
        time.sleep(0.05)
    raise AssertionError("job never finished")


@pytest.fixture
def project(user_client):
    return user_client.post("/api/projects", json={"name": "drafts"}).json()


@pytest.fixture
def llm(user_client, monkeypatch):
    """A fake provider: the translation is the source wrapped in the target
    label, with one comment line. Calls are counted."""
    calls = []

    class Translator:
        name = "anthropic"
        model = "claude-fake"

        def generate(self, messages, system=None, max_tokens=4096):
            from app.services.llm.base import LLMResult
            prompt = messages[0]["content"]
            target = prompt.split("Target database: ")[1].split(" (")[0]
            calls.append(target)
            return LLMResult(text=f"TRANSLATED[{target}]: {PUBMED}\n# field tags adapted",
                             tokens_input=300, tokens_output=120)

    user_client.put("/api/llm/credentials", json={
        "provider": "anthropic", "api_key": "sk-ant-fake-key-123"})
    monkeypatch.setattr("app.services.equations.drafting.open_provider_chain",
                        lambda *a, **kw: Translator())
    return calls


# ---- the databases a review searches ----------------------------------------------

def test_project_database_selection(user_client, project):
    pid = project["id"]
    base = f"/api/projects/{pid}"
    everything = user_client.get(f"{base}/equations/databases").json()["databases"]
    assert len(everything) > 15
    # the settings listing shows all, flagged selected
    listing = user_client.get(f"/api/database-credentials/databases?project_id={pid}&all=true").json()
    assert all(d["selected"] for d in listing)

    r = user_client.put(base, json={"databases": ["pubmed", "scopus", "ebsco", "nope"]})
    assert r.status_code == 400
    r = user_client.put(base, json={"databases": ["pubmed", "scopus", "ebsco", "pubmed"]})
    assert r.status_code == 200, r.text
    assert r.json()["databases"] == ["pubmed", "scopus", "ebsco"]

    # every list the review works from follows the selection…
    ids = [d["id"] for d in user_client.get(f"{base}/equations/databases").json()["databases"]]
    assert ids == ["pubmed", "scopus", "ebsco"]
    listing = user_client.get(f"/api/database-credentials/databases?project_id={pid}&all=true").json()
    assert {d["id"] for d in listing if d["selected"]} == {"pubmed", "scopus", "ebsco"}
    assert len(listing) == len(everything)
    assert user_client.get(f"{base}/equations/recall/databases").json()["api"] == ["pubmed"]
    # …a declared database always counts
    user_client.post(f"{base}/custom-databases", json={"label": "Cairn", "syntax": "generic"})
    ids = [d["id"] for d in user_client.get(f"{base}/equations/databases").json()["databases"]]
    assert ids == ["pubmed", "scopus", "ebsco", "cairn"]
    # a raw equation cannot be typed for a database the review does not search
    r = user_client.post(f"{base}/equations", json={
        "label": "x", "mode": "raw", "translations": {"wos": "TS=(x)"}})
    assert r.status_code == 400
    # null = back to everything
    r = user_client.put(base, json={"databases": None})
    assert r.json()["databases"] is None
    assert len(user_client.get(f"{base}/equations/databases").json()["databases"]) == len(everything) + 1


# ---- auto-draft ------------------------------------------------------------------------

def test_draft_all_job_fills_missing_databases(user_client, project, llm):
    pid = project["id"]
    base = f"/api/projects/{pid}/equations"
    user_client.put(f"/api/projects/{pid}", json={"databases": ["pubmed", "scopus", "ebsco", "trid"]})
    eq = user_client.post(base, json={"label": "Eq. 6", "mode": "raw",
                                      "translations": {"pubmed": PUBMED, "trid": "typed by hand"}}).json()

    est = user_client.get(f"{base}/draft-estimate?from_db=pubmed&chars=500").json()
    assert est["n_targets"] == 3 and est["available"] and est["cost_label"]
    est = user_client.get(f"{base}/draft-estimate?from_db=pubmed&equation_id={eq['id']}").json()
    assert est["targets"] == ["scopus", "ebsco"]  # trid is typed already

    r = user_client.post(f"{base}/{eq['id']}/translations/draft-all",
                         json={"from_db": "pubmed"})
    assert r.status_code == 200, r.text
    assert r.json()["targets"] == ["scopus", "ebsco"]
    job = _await(user_client, r.json()["job_id"])
    assert job["status"] == "done", job
    assert job["result"]["drafted"] == ["scopus", "ebsco"] and job["result"]["errors"] == {}
    assert llm == ["Scopus", "EBSCO"]

    eq = user_client.get(base).json()[0]
    overrides, drafts = eq["translations"]["overrides"], eq["translations"]["drafts"]
    assert overrides["scopus"].startswith("TRANSLATED[Scopus]:")
    assert overrides["trid"] == "typed by hand" and "trid" not in drafts
    assert drafts["scopus"]["validated"] is False
    assert drafts["scopus"]["model"] == "claude-fake" and drafts["scopus"]["from_db"] == "pubmed"
    assert drafts["ebsco"]["notes"] == ["field tags adapted"]

    # nothing left to draft: no job
    assert user_client.post(f"{base}/{eq['id']}/translations/draft-all",
                            json={"from_db": "pubmed"}).json()["job_id"] is None
    # the report and the audit say which queries are unreviewed AI drafts
    user_client.post(f"{base}/{eq['id']}/freeze")
    report = user_client.get(f"/api/projects/{pid}/search-report").text
    assert "**Scopus** — AI draft, NOT reviewed" in report
    from app.core.db import SessionLocal
    from app.services.reporting.audit import _search
    with SessionLocal() as db:
        search = _search(db, pid)
    assert search["equations"][0]["unreviewed_ai_queries"] == ["ebsco", "scopus"]
    assert search["equations"][0]["hand_edited_queries"] == ["pubmed", "trid"]


def test_validate_or_edit_a_draft(user_client, project, llm):
    pid = project["id"]
    base = f"/api/projects/{pid}/equations"
    user_client.put(f"/api/projects/{pid}", json={"databases": ["pubmed", "scopus", "ebsco"]})
    eq = user_client.post(base, json={"label": "raw", "mode": "raw",
                                      "translations": {"pubmed": PUBMED}}).json()
    equation_draft_all_handler(0, {"equation_id": eq["id"], "from_db": "pubmed",
                                   "databases": ["scopus", "ebsco"]}, lambda *a: None)
    # validating keeps the text and the provenance, marks who and when
    r = user_client.post(f"{base}/{eq['id']}/translations/validate", json={"database": "scopus"})
    assert r.status_code == 200, r.text
    scopus = r.json()["translations"]["drafts"]["scopus"]
    assert scopus["validated"] is True and scopus["validated_by"] and scopus["validated_at"]
    assert r.json()["translations"]["drafts"]["ebsco"]["validated"] is False
    assert user_client.post(f"{base}/{eq['id']}/translations/validate",
                            json={"database": "pubmed"}).status_code == 400
    # editing by hand drops the draft flag altogether
    r = user_client.put(f"{base}/{eq['id']}/override",
                        json={"database": "ebsco", "query": "TI stress AND AB driving"})
    assert "ebsco" not in r.json()["translations"]["drafts"]
    assert r.json()["translations"]["overrides"]["ebsco"] == "TI stress AND AB driving"
    # `unreviewed` mode redoes only the unvalidated drafts (none left here)
    assert drafting.targets(
        type("E", (), {"translations": r.json()["translations"]})(),
        {"pubmed": {}, "scopus": {}, "ebsco": {}}, "pubmed", "unreviewed") == []
    report = user_client.get(f"/api/projects/{pid}/search-report").text
    assert "NOT reviewed" not in report


def test_draft_all_refuses_without_source_or_when_frozen(user_client, project, llm):
    pid = project["id"]
    base = f"/api/projects/{pid}/equations"
    eq = user_client.post(base, json={"label": "raw", "mode": "raw",
                                      "translations": {"scopus": "TITLE(x)"}}).json()
    assert user_client.post(f"{base}/{eq['id']}/translations/draft-all",
                            json={"from_db": "pubmed"}).status_code == 400
    assert user_client.post(f"{base}/{eq['id']}/translations/draft-all",
                            json={"from_db": "nope"}).status_code == 400
    user_client.post(f"{base}/{eq['id']}/freeze")
    assert user_client.post(f"{base}/{eq['id']}/translations/draft-all",
                            json={"from_db": "scopus"}).status_code == 400
