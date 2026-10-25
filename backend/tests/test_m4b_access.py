"""M4b — access onboarding: institution→proxy resolution, ephemeral
browser-held credentials in full-text retrieval, project-scoped database keys."""
import time

import pytest

RIS = """TY  - JOUR
TI  - Access paper one
AU  - Doe, J.
PY  - 2020
DO  - 10.5/m4b.1
AB  - Abstract.
ER  -
"""


@pytest.fixture
def project(user_client):
    project = user_client.post("/api/projects", json={"name": "M4b demo"}).json()
    pid = project["id"]
    user_client.post(f"/api/projects/{pid}/imports/upload",
                     files={"file": ("s.ris", RIS.encode(), "text/plain")},
                     data={"source_name": "pubmed", "source_type": "database"})
    job = user_client.post(f"/api/projects/{pid}/dedup/run").json()["job_id"]
    for _ in range(100):
        if user_client.get(f"/api/jobs/{job}").json()["status"] in ("done", "failed"):
            break
        time.sleep(0.05)
    return project


def _await(client, job_id):
    for _ in range(200):
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in ("done", "failed"):
            return job
        time.sleep(0.05)
    raise AssertionError("job never finished")


# ---- institution → proxy resolution ------------------------------------------

def test_proxy_search_requires_auth(client):
    assert client.get("/api/institution-proxies?q=cnrs").status_code == 401


def test_proxy_search(user_client):
    # accent/case-insensitive multi-word match against the bundled database
    hits = user_client.get("/api/institution-proxies?q=bibcnrs ins2i").json()
    assert any("INS2I" in h["name"] for h in hits)
    assert all("$@" in h["url"] or h["url"].startswith("http") for h in hits)
    # empty query returns nothing (typeahead only)
    assert user_client.get("/api/institution-proxies?q=").json() == []
    assert user_client.get("/api/institution-proxies?q=zz-no-such-place").json() == []


def test_proxy_search_reports_a_missing_directory(user_client, monkeypatch):
    """A data file absent from the installation must not look like 'your
    institution is not listed' — that is what made the field seem dead."""
    from app.api import institution_proxies as mod
    monkeypatch.setattr(mod, "_load_db", lambda: [])
    r = user_client.get("/api/institution-proxies?q=harvard")
    assert r.status_code == 503 and "proxy directory" in r.json()["detail"]
    # an empty query still answers normally (nothing typed yet)
    assert user_client.get("/api/institution-proxies?q=").json() == []


def test_proxy_search_tolerates_punctuation_and_domains(user_client):
    """People type their institution the way they know it: hyphenated, as a
    domain, or as the acronym of a longer official name."""
    def names(q):
        return [h["name"] for h in
                user_client.get(f"/api/institution-proxies?q={q}").json()]

    assert any("Gustave Eiffel" in n for n in names("univ-eiffel"))   # proxy host
    assert any("Gustave Eiffel" in n for n in names("universite gustave eiffel"))
    assert any("Lyon" in n for n in names("ucly"))                    # host again
    assert names("harvard")[0] == "Harvard University"                # best first


# ---- ephemeral credentials in retrieval --------------------------------------

def test_retrieve_with_ephemeral_institutions_never_persists_password(
        user_client, project, monkeypatch):
    pid = project["id"]
    seen = {}

    def fake_process_doi(doi, email, institutions=None,
                         use_extensions=True):
        seen["institutions"] = institutions
        return ({"source": None, "filename": None, "title": "T", "oa_url": ""},
                None)

    monkeypatch.setattr("app.services.fulltext.downloader.process_doi",
                        fake_process_doi)

    r = user_client.post(f"/api/projects/{pid}/fulltext/retrieve", json={
        "institutions": [{"name": "My Uni",
                          "ezproxy_url": "https://proxy.myuni.edu/login?url=$@",
                          "username": "me", "password": "hunter2secret"}]})
    assert r.status_code == 200
    job = _await(user_client, r.json()["job_id"])
    assert job["status"] == "done", job.get("error")

    # the job actually used the ephemeral credentials...
    assert seen["institutions"] and seen["institutions"][0]["name"] == "My Uni"
    assert seen["institutions"][0]["password"] == "hunter2secret"

    # ...but nothing sensitive was persisted anywhere in the DB
    from app.core.db import SessionLocal
    from app.models import FulltextConfig, Job
    with SessionLocal() as db:
        stored = db.get(Job, job["id"]).params
        assert "hunter2secret" not in str(stored)
        assert "institutions" not in stored  # only the one-time token travels
        assert stored.get("institutions_token")
        assert db.query(FulltextConfig).filter_by(project_id=pid).first() is None

    # the token is single-use: consumed by the job
    from app.services.fulltext.ephemeral import pop_institutions
    assert pop_institutions(stored["institutions_token"]) == []


def test_retrieve_without_password_sends_no_institutions(user_client, project,
                                                         monkeypatch):
    pid = project["id"]
    seen = {}

    def fake_process_doi(doi, email, institutions=None,
                         use_extensions=True):
        seen["institutions"] = institutions
        return ({"source": None, "filename": None, "title": "T", "oa_url": ""},
                None)

    monkeypatch.setattr("app.services.fulltext.downloader.process_doi",
                        fake_process_doi)
    # missing password -> entry dropped, no token in params
    r = user_client.post(f"/api/projects/{pid}/fulltext/retrieve", json={
        "institutions": [{"name": "My Uni",
                          "ezproxy_url": "https://proxy.myuni.edu/login?url=$@",
                          "username": "me", "password": ""}]})
    job = _await(user_client, r.json()["job_id"])
    assert job["status"] == "done"
    assert not seen["institutions"]


# ---- project-scoped database keys --------------------------------------------

def test_project_scoped_database_keys(user_client, project):
    pid = project["id"]
    # project listing: nothing configured, no global fallback
    keys = {k["provider"]: k for k in user_client.get(
        f"/api/database-credentials?project_id={pid}").json()}
    assert keys["scopus"]["configured"] is False
    assert keys["scopus"]["global_configured"] is False
    assert keys["scopus"]["help_url"]

    # store a global key, then a project key
    user_client.put("/api/database-credentials",
                    json={"provider": "scopus", "api_key": "global-scopus-key"})
    keys = {k["provider"]: k for k in user_client.get(
        f"/api/database-credentials?project_id={pid}").json()}
    assert keys["scopus"]["configured"] is False  # project scope itself
    assert keys["scopus"]["global_configured"] is True

    r = user_client.put("/api/database-credentials", json={
        "provider": "scopus", "api_key": "project-scopus-key", "project_id": pid})
    assert r.status_code == 200 and r.json()["project_id"] == pid

    # the project key overrides the global one for that project
    from app.core.db import SessionLocal
    from app.services.connectors.keys import resolve_db_key
    with SessionLocal() as db:
        assert resolve_db_key(db, pid, "scopus") == "project-scopus-key"
        assert resolve_db_key(db, None, "scopus") == "global-scopus-key"

    # a reviewer of the project may see status but not manage keys
    user_client.post("/api/auth/register", json={
        "email": "rev-m4b@example.com", "password": "password123",
        "display_name": "Rev"})
    user_client.post("/api/auth/login", json={
        "email": "admin@example.com", "password": "password123"})
    user_client.post(f"/api/projects/{pid}/members",
                     json={"email": "rev-m4b@example.com", "role": "reviewer"})
    user_client.post("/api/auth/login", json={
        "email": "rev-m4b@example.com", "password": "password123"})
    assert user_client.get(
        f"/api/database-credentials?project_id={pid}").status_code == 200
    assert user_client.put("/api/database-credentials", json={
        "provider": "ieee", "api_key": "sneaky-key", "project_id": pid,
    }).status_code == 403
    assert user_client.delete(
        f"/api/database-credentials/scopus?project_id={pid}").status_code == 403

    # project admin (the creator) deletes the project key -> global applies again
    user_client.post("/api/auth/login", json={
        "email": "admin@example.com", "password": "password123"})
    assert user_client.delete(
        f"/api/database-credentials/scopus?project_id={pid}").status_code == 200
    with SessionLocal() as db:
        assert resolve_db_key(db, pid, "scopus") == "global-scopus-key"
