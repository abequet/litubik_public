"""Hardening checks that the public repository makes readable: H2 (cookie),
M1 (API explorer), M2 (response headers), M6 (satellite creation), E3/M9 (CSV
formula injection)."""
import csv
import io

import pytest

from app.core.config import get_settings


# ---- M1 / M2 -----------------------------------------------------------------

def test_api_schema_is_not_served(client):
    """The SPA catch-all answers unknown paths with index.html, so what matters
    is that no OpenAPI document is exposed — that is the map of the API."""
    for path in ("/docs", "/redoc", "/openapi.json"):
        body = client.get(path).text
        assert "swagger" not in body.lower(), path
        assert '"openapi"' not in body, path
    assert get_settings().api_docs is False


def test_security_headers_on_every_response(client):
    r = client.get("/api/health")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"
    assert "frame-ancestors 'none'" in r.headers["content-security-policy"]
    assert "object-src 'none'" in r.headers["content-security-policy"]
    # HSTS is meaningless over plain HTTP and harmful on a LAN
    assert "strict-transport-security" not in r.headers


def test_hsts_appears_behind_an_https_proxy(client):
    r = client.get("/api/health", headers={"X-Forwarded-Proto": "https"})
    assert "max-age=" in r.headers["strict-transport-security"]


# ---- H2 ----------------------------------------------------------------------

def test_session_cookie_is_secure_behind_an_https_proxy(client):
    r = client.post("/api/auth/register",
                    json={"email": "a@x.org", "password": "password123",
                          "display_name": "A"},
                    headers={"X-Forwarded-Proto": "https"})
    assert r.status_code == 200
    assert "Secure" in r.headers["set-cookie"]


def test_session_cookie_stays_usable_on_plain_http(client):
    r = client.post("/api/auth/register",
                    json={"email": "b@x.org", "password": "password123",
                          "display_name": "B"})
    assert r.status_code == 200
    assert "Secure" not in r.headers["set-cookie"]


# ---- E3 / M9 -----------------------------------------------------------------

@pytest.mark.parametrize("payload", ["=cmd|'/c calc'!A1", "+1+1", "-1+1",
                                     "@SUM(1)", "\tx", "\rx"])
def test_every_formula_metacharacter_is_neutralised(payload):
    from app.core.csvsafe import safe_row
    assert safe_row([payload]) == ["'" + payload]


def test_harmless_cells_are_left_alone():
    from app.core.csvsafe import safe_row
    assert safe_row(["Title", 2020, None, "a=b"]) == ["Title", 2020, None, "a=b"]


def test_reference_export_neutralises_a_crafted_title(user_client):
    """End to end: a reviewer types a formula as a paper title, a colleague
    opens the exported CSV in Excel."""
    import time
    payload = "=cmd|'/c calc'!A1"
    pid = user_client.post("/api/projects", json={"name": "P"}).json()["id"]
    ris = (f"TY  - JOUR\nTI  - {payload}\nAU  - Doe, J.\nPY  - 2020\n"
           "DO  - 10.5/inj.1\nER  -\n")
    user_client.post(f"/api/projects/{pid}/imports/upload",
                     files={"file": ("s.ris", ris.encode(), "text/plain")},
                     data={"source_name": "pubmed", "source_type": "database"})
    job_id = user_client.post(f"/api/projects/{pid}/dedup/run").json()["job_id"]
    for _ in range(100):
        if user_client.get(f"/api/jobs/{job_id}").json()["status"] in ("done", "failed"):
            break
        time.sleep(0.05)
    body = user_client.get(f"/api/projects/{pid}/export/references?fmt=csv").text
    rows = list(csv.reader(io.StringIO(body.lstrip("﻿"))))
    cells = [c for row in rows[1:] for c in row if payload in c]
    assert cells, f"the crafted title should appear in the export: {rows}"
    assert all(c.startswith("'") for c in cells), cells


# ---- M6 ----------------------------------------------------------------------

# M6 (create-mode snapshot import) is covered by tests/test_sync_snapshot.py,
# which exercises the real create path. It is deliberately not blocked: see the
# comment in services/sync/snapshot.py — the same "invite an arbitrary address"
# primitive already exists through projects.add_member, so the proportionate
# answer is to announce the pending accounts an archive will create, not to
# break the way a co-reviewer joins a review.
