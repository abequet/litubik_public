"""Key-activated database connectors (Scopus, IEEE): key storage, dynamic
api/manual method, and count/fetch dispatch (mocked — no live API calls)."""
import time

import pytest

from app.services.connectors import fetch as fetchmod
from app.services.connectors.keys import resolve_db_key
from app.services.equations import counts as counters


@pytest.fixture
def project(user_client):
    return user_client.post("/api/projects", json={"name": "keys demo"}).json()


@pytest.fixture
def equation(user_client, project):
    pid = project["id"]
    cid = user_client.post(f"/api/projects/{pid}/concepts",
                           json={"name": "Intervention",
                                 "keywords": ["gamification"]}).json()["id"]
    return user_client.post(f"/api/projects/{pid}/equations", json={
        "label": "v1", "concept_ids": [cid],
        "params": {"year_from": 2015, "year_to": 2024}}).json()


def _await(client, job_id):
    for _ in range(100):
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in ("done", "failed"):
            return job
        time.sleep(0.05)
    raise AssertionError("job never finished")


# ---- key management -----------------------------------------------------------

def test_key_management_and_permissions(user_client):
    # initially nothing configured
    keys = {k["provider"]: k for k in user_client.get("/api/database-credentials").json()}
    assert keys["scopus"]["configured"] is False and keys["ieee"]["configured"] is False

    # app admin can store a key (write-only: only a hint comes back)
    r = user_client.put("/api/database-credentials",
                        json={"provider": "scopus", "api_key": "secret-scopus-key"})
    assert r.status_code == 200 and r.json()["configured"] is True
    assert "secret" not in r.json()["key_hint"]
    keys = {k["provider"]: k for k in user_client.get("/api/database-credentials").json()}
    assert keys["scopus"]["configured"] is True

    # a non-app-admin cannot manage keys
    user_client.post("/api/auth/register", json={
        "email": "plain@example.com", "password": "password123",
        "display_name": "Plain"})
    r = user_client.put("/api/database-credentials",
                        json={"provider": "ieee", "api_key": "secret-ieee-key"})
    assert r.status_code == 403
    user_client.post("/api/auth/login", json={
        "email": "admin@example.com", "password": "password123"})

    assert user_client.delete("/api/database-credentials/scopus").status_code == 200
    keys = {k["provider"]: k for k in user_client.get("/api/database-credentials").json()}
    assert keys["scopus"]["configured"] is False


def test_key_resolution_project_overrides_global(user_client, project):
    """resolve_db_key prefers a project-scoped key over the global one."""
    from app.core.crypto import encrypt_secret
    from app.core.db import SessionLocal
    from app.models import DatabaseCredential
    pid = project["id"]
    with SessionLocal() as db:
        db.add(DatabaseCredential(project_id=None, provider="scopus",
                                  api_key_encrypted=encrypt_secret("GLOBAL")))
        db.add(DatabaseCredential(project_id=pid, provider="scopus",
                                  api_key_encrypted=encrypt_secret("PROJECT")))
        db.commit()
        assert resolve_db_key(db, pid, "scopus") == "PROJECT"
        assert resolve_db_key(db, None, "scopus") == "GLOBAL"
        assert resolve_db_key(db, pid, "ieee") is None


# ---- dynamic api/manual method ------------------------------------------------

def test_databases_method_flips_with_key(user_client, project):
    pid = project["id"]
    dbs = {d["id"]: d for d in
           user_client.get(f"/api/projects/{pid}/equations/databases").json()["databases"]}
    assert dbs["scopus"]["count"] == "manual"  # no key yet
    assert dbs["scopus"]["key_required"] is True

    user_client.put("/api/database-credentials",
                    json={"provider": "scopus", "api_key": "secret-scopus-key"})
    dbs = {d["id"]: d for d in
           user_client.get(f"/api/projects/{pid}/equations/databases").json()["databases"]}
    assert dbs["scopus"]["count"] == "api"
    assert dbs["ieee"]["count"] == "manual"  # ieee still keyless


# ---- counts & fetch dispatch (mocked) -----------------------------------------

def test_scopus_count_requires_key_then_runs(user_client, project, equation, monkeypatch):
    pid, eqid = project["id"], equation["id"]
    # without a key the counts endpoint rejects scopus
    r = user_client.post(f"/api/projects/{pid}/equations/{eqid}/counts",
                         json={"databases": ["scopus"]})
    assert r.status_code == 400

    user_client.put("/api/database-credentials",
                    json={"provider": "scopus", "api_key": "secret-scopus-key"})
    seen = {}

    def fake_scopus(query, params, key):
        seen["query"], seen["key"] = query, key
        return 314

    monkeypatch.setitem(counters.KEYED_COUNTERS, "scopus", fake_scopus)
    r = user_client.post(f"/api/projects/{pid}/equations/{eqid}/counts",
                         json={"databases": ["scopus"]})
    assert r.status_code == 200, r.text
    job = _await(user_client, r.json()["job_id"])
    assert job["status"] == "done"
    assert job["result"]["results"]["scopus"] == {"count": 314}
    assert seen["key"] == "secret-scopus-key"
    assert "TITLE-ABS" in seen["query"]  # the translated Scopus query was used
    eq = user_client.get(f"/api/projects/{pid}/equations").json()[0]
    scopus_count = next(c for c in eq["counts"] if c["database_name"] == "scopus")
    assert scopus_count["count"] == 314 and scopus_count["method"] == "api"


def test_scopus_fetch_with_key(user_client, project, equation, monkeypatch):
    pid, eqid = project["id"], equation["id"]
    # no key -> fetch refused
    r = user_client.post(f"/api/projects/{pid}/search/fetch",
                         json={"equation_id": eqid, "database": "scopus"})
    assert r.status_code == 400

    user_client.put("/api/database-credentials",
                    json={"provider": "scopus", "api_key": "secret-scopus-key"})

    def fake_fetch(query, params, cap, progress, key):
        progress(2, 2)
        return [
            {"doi": "10.1/a", "title": "Scopus paper A", "authors": ["Doe, J"],
             "year": 2020, "journal": "J", "abstract": "", "raw": ""},
            {"doi": "10.1/b", "title": "Scopus paper B", "authors": ["Roe, K"],
             "year": 2021, "journal": "J", "abstract": "", "raw": ""},
        ]

    monkeypatch.setitem(fetchmod.KEYED_FETCHERS, "scopus", fake_fetch)
    r = user_client.post(f"/api/projects/{pid}/search/fetch",
                         json={"equation_id": eqid, "database": "scopus", "cap": 100})
    assert r.status_code == 200, r.text
    job = _await(user_client, r.json()["job_id"])
    assert job["status"] == "done", job.get("error")
    assert job["result"]["n_records"] == 2
    records = user_client.get(f"/api/projects/{pid}/records").json()
    assert records["total"] == 2
    assert {r["source_name"] for r in records["items"]} == {"scopus"}


def test_key_test_endpoint(user_client, monkeypatch):
    user_client.put("/api/database-credentials",
                    json={"provider": "ieee", "api_key": "secret-ieee-key"})
    monkeypatch.setitem(counters.KEYED_COUNTERS, "ieee", lambda q, p, key: 42)
    r = user_client.post("/api/database-credentials/ieee/test")
    assert r.status_code == 200 and r.json()["ok"] is True
    assert "42" in r.json()["detail"]
