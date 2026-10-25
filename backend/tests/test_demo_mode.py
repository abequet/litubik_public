"""M6 demo instance: account tiers via the allowlist, sandbox restrictions
(optional retrieval extension, project/import caps), /api/instance. Everything
here must be inert on a normal instance — the last test checks exactly that.

Visitors enter through the one-click guest session (POST /api/auth/guest);
e-mail registration on a demo instance is for the allowlist only. The guest
session, the AI budget and the legal pages have their own tests in
test_demo_public.py."""
import pytest

from app.core.config import get_settings

RIS_ONE = """TY  - JOUR
TI  - Demo paper
AU  - Doe, J.
PY  - 2020
DO  - 10.5/demo.1
ER  -
"""


@pytest.fixture
def demo(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "demo_mode", True)
    monkeypatch.setattr(settings, "trusted_emails", "")
    # the test client's host is "testserver": open the guest entry on it
    monkeypatch.setattr(settings, "demo_guest_hosts", "*")
    from app.core.ratelimit import guest_daily, guest_hourly
    guest_daily.clear()
    guest_hourly.clear()
    return settings


def _register(client, email, name="U"):
    return client.post("/api/auth/register", json={
        "email": email, "password": "password123", "display_name": name})


def _guest(client):
    """Open a guest session (the visitor's way in) on this client."""
    r = client.post("/api/auth/guest", json={"accept_terms": True})
    assert r.status_code == 200, r.text
    return r


def _login(client, email):
    return client.post("/api/auth/login", json={
        "email": email, "password": "password123"})


# ---- instance profile ---------------------------------------------------------

def test_instance_endpoint(client, demo):
    r = client.get("/api/instance")  # public, no auth
    assert r.status_code == 200
    body = r.json()
    assert body["demo"] is True and body["reset_hour"] == 4
    assert body["guest_entry"] is True
    assert body["legal"] == ["notice", "terms", "privacy"]
    # the endpoint also carries the AGPLv3 §13 source offer
    assert body["license"] == "AGPL-3.0-or-later"
    assert body["source_url"].startswith("http")
    assert body["version"]


def test_instance_endpoint_normal(client):
    body = client.get("/api/instance").json()
    assert body["demo"] is False and body["guest_entry"] is False
    assert body["legal"] == []  # a desktop install publishes no legal page


# ---- registration tiers -------------------------------------------------------

def test_register_tiers(client, demo):
    # first account = superadmin, trusted regardless of the allowlist
    r = _register(client, "admin@example.com", "Admin")
    assert r.json()["is_admin"] is True and r.json()["is_trusted"] is True

    # allowlist one email
    r = client.post("/api/admin/trusted-emails", json={"email": "Full@Lab.fr"})
    assert r.status_code == 200 and r.json()["email"] == "full@lab.fr"

    # a random e-mail cannot register on a demo: visitors use a guest session
    r = _register(client, "visitor@example.com", "Visitor")
    assert r.status_code == 403 and "guest session" in r.json()["detail"]
    r = _guest(client)
    assert r.json()["is_trusted"] is False and r.json()["is_guest"] is True

    # allowlisted email -> full account
    r = _register(client, "full@lab.fr", "Colleague")
    assert r.json()["is_trusted"] is True


def _sandbox_account(email):
    """An e-mail sandbox account, as visitors had before the guest session."""
    from app.core.db import SessionLocal
    from app.core.security import hash_password
    from app.models import User
    with SessionLocal() as db:
        db.add(User(email=email, password_hash=hash_password("password123"),
                    display_name="Late", is_trusted=False))
        db.commit()


def test_add_trusted_promotes_existing_account(client, demo):
    _register(client, "admin@example.com", "Admin")
    _sandbox_account("late@example.com")
    _login(client, "late@example.com")
    assert client.get("/api/auth/me").json()["is_trusted"] is False
    client.post("/api/auth/login", json={
        "email": "admin@example.com", "password": "password123"})
    r = client.post("/api/admin/trusted-emails", json={"email": "late@example.com"})
    assert r.json()["registered"] is True
    client.post("/api/auth/login", json={
        "email": "late@example.com", "password": "password123"})
    assert client.get("/api/auth/me").json()["is_trusted"] is True


def test_allowlist_admin_only(client, demo):
    _register(client, "admin@example.com", "Admin")
    _guest(client)
    assert client.get("/api/admin/trusted-emails").status_code == 403
    assert client.post("/api/admin/trusted-emails",
                       json={"email": "me@too.fr"}).status_code == 403


def test_env_seed(client, demo, monkeypatch):
    # a repeated email (same address twice, and a case variant) must NOT crash
    # on the UNIQUE constraint — the autoflush=False session made the naive
    # version insert duplicates
    monkeypatch.setattr(
        demo, "trusted_emails",
        "seeded@lab.fr, ALSO@LAB.FR ,, bad-entry, seeded@lab.fr, SEEDED@lab.fr")
    from app.core.db import SessionLocal
    from app.core.demo import seed_trusted_emails
    with SessionLocal() as db:
        assert seed_trusted_emails(db) == 2  # deduped to seeded@ + also@
        assert seed_trusted_emails(db) == 0  # idempotent on a second boot
    r = _register(client, "seeded@lab.fr", "Seeded")
    assert r.json()["is_trusted"] is True


def test_invite_by_trusted_account_allowlists(client, demo):
    # a trusted project admin adds a member -> the email is allowlisted with
    # source="invite" and the awaiting account is trusted right away (so the
    # daily reset never purges it or its votes)
    _register(client, "admin@example.com", "Admin")
    pid = client.post("/api/projects", json={"name": "real review"}).json()["id"]
    r = client.post(f"/api/projects/{pid}/members",
                    json={"email": "colleague@lab.fr", "role": "reviewer"})
    assert r.status_code == 200 and r.json()["status"] == "awaiting"

    entries = client.get("/api/admin/trusted-emails").json()
    by_email = {e["email"]: e for e in entries}
    assert by_email["colleague@lab.fr"]["source"] == "invite"

    # surviving the purge, then registering as a full account
    client.post("/api/admin/demo-reset")
    r = _register(client, "colleague@lab.fr", "Colleague")
    assert r.json()["is_trusted"] is True
    projects = client.get("/api/projects").json()
    assert [p["id"] for p in projects] == [pid]  # membership kept, no demo seed


def test_sandbox_account_adds_no_member(client, demo):
    # a visitor cannot add anyone: an invitation would store a third party's
    # e-mail on a public instance (and used to open a way to register)
    _register(client, "admin@example.com", "Admin")
    _guest(client)
    pid = client.get("/api/projects").json()[0]["id"]  # seeded sandbox project
    r = client.post(f"/api/projects/{pid}/members",
                    json={"email": "friend@example.com", "role": "reviewer"})
    assert r.status_code == 403

    _login(client, "admin@example.com")
    emails = [e["email"] for e in client.get("/api/admin/trusted-emails").json()]
    assert "friend@example.com" not in emails
    from app.core.db import SessionLocal
    from app.models import User
    with SessionLocal() as db:
        assert db.query(User).filter_by(email="friend@example.com").first() is None


# ---- sandbox restrictions -----------------------------------------------------

def test_demo_project_cap(client, demo):
    _register(client, "admin@example.com", "Admin")
    _guest(client)
    # the seeded example project counts towards the cap of 3
    already = len(client.get("/api/projects").json())
    for i in range(3 - already):
        assert client.post("/api/projects",
                           json={"name": f"p{i}"}).status_code == 200
    r = client.post("/api/projects", json={"name": "p3"})
    assert r.status_code == 403 and "limited" in r.json()["detail"]
    # trusted accounts are not capped
    client.post("/api/auth/login", json={
        "email": "admin@example.com", "password": "password123"})
    for i in range(4):
        assert client.post("/api/projects",
                           json={"name": f"a{i}"}).status_code == 200


def test_demo_import_cap(client, demo, monkeypatch):
    monkeypatch.setattr("app.core.demo.DEMO_MAX_IMPORT_RECORDS", 1)
    _register(client, "admin@example.com", "Admin")
    _guest(client)
    pid = client.post("/api/projects", json={"name": "sandbox"}).json()["id"]
    two = RIS_ONE + RIS_ONE.replace("Demo paper", "Second paper")
    r = client.post(f"/api/projects/{pid}/imports/upload",
                    files={"file": ("s.ris", two.encode(), "text/plain")},
                    data={"source_name": "pubmed", "source_type": "database"})
    assert r.status_code == 413 and "at most 1" in r.json()["detail"]
    # a single record passes
    r = client.post(f"/api/projects/{pid}/imports/upload",
                    files={"file": ("s.ris", RIS_ONE.encode(), "text/plain")},
                    data={"source_name": "pubmed", "source_type": "database"})
    assert r.status_code == 200


def test_demo_retrieve_skips_the_extension(client, demo):
    _register(client, "admin@example.com", "Admin")
    _guest(client)
    pid = client.post("/api/projects", json={"name": "sandbox"}).json()["id"]
    job_id = client.post(f"/api/projects/{pid}/fulltext/retrieve",
                         json={}).json()["job_id"]
    from app.core.db import SessionLocal
    from app.models import Job
    with SessionLocal() as db:
        params = db.get(Job, job_id).params
        assert params["use_extensions"] is False
        assert params["sandbox"] is True
        assert params["fallback_email"] == ""  # never the visitor's address

    # the flag really keeps the optional extension out of the cascade: with it off,
    # the only sources tried are the declared/open ones
    from app.services.fulltext import doibatch
    captured = []
    orig = doibatch._run_tier_parallel

    def spy(tasks):
        captured.append([label for label, _ in tasks])
        return None, None

    doibatch._run_tier_parallel = spy
    try:
        doibatch.fetch_crossref, orig_cr = (
            lambda doi: {"first_author": "A", "year": 2020, "title": "T"},
            doibatch.fetch_crossref)
        doibatch.process_doi("10.5/x", email="", use_extensions=False)
    finally:
        doibatch._run_tier_parallel = orig
        doibatch.fetch_crossref = orig_cr
    flat = {label for tier in captured for label in tier}
    assert flat <= {"europepmc", "publisher_oa", "playwright", "institution"}


# ---- the seeded example project -----------------------------------------------

def test_demo_registration_seeds_example_project(client, demo):
    _register(client, "admin@example.com", "Admin")
    _guest(client)

    projects = client.get("/api/projects").json()
    assert len(projects) == 1
    assert "Example review" in projects[0]["name"]
    assert projects[0]["my_role"] == "admin"
    pid = projects[0]["id"]

    # corpus imported and deduplicated
    records = client.get(f"/api/projects/{pid}/records").json()
    assert records["total"] >= 55

    # dual T/A screening started, partly voted, with open conflicts
    config = client.get(f"/api/projects/{pid}/screening/config").json()
    assert config["config"]["status"] == "active"
    assert len(config["config"]["reviewer_ids"]) == 2
    stats = client.get(f"/api/projects/{pid}/screening/stats").json()
    assert stats["votes_done"] > 20  # both reviewers voted on ~70% of records

    # full-text round exists with a few justified exclusions feeding PRISMA
    prisma = client.get(f"/api/projects/{pid}/prisma").json()
    assert prisma["records_screened"] > 0

    # the visitor can screen the remaining records (assignments exist)
    queue = client.get(f"/api/projects/{pid}/screening/queue").json()
    assert isinstance(queue, (list, dict))

    # a second visitor gets their OWN copy, not a membership of the first
    _guest(client)
    projects2 = client.get("/api/projects").json()
    assert len(projects2) == 1 and projects2[0]["id"] != pid


def test_trusted_registration_gets_no_seed(client, demo):
    _register(client, "admin@example.com", "Admin")
    client.post("/api/admin/trusted-emails", json={"email": "full@lab.fr"})
    _register(client, "full@lab.fr", "Colleague")
    assert client.get("/api/projects").json() == []


# ---- global API keys: database keys reserved, AI key through the budget ---------

def test_global_keys_and_sandbox_projects(client, demo):
    _register(client, "admin@example.com", "Admin")
    # superadmin stores app-wide keys (AI + database)
    client.put("/api/llm/credentials", json={
        "provider": "anthropic", "api_key": "sk-global-ai-key"})
    client.put("/api/database-credentials",
               json={"provider": "scopus", "api_key": "global-scopus-key"})
    admin_pid = client.post("/api/projects", json={"name": "trusted"}).json()["id"]

    _guest(client)
    sandbox_pid = client.get("/api/projects").json()[0]["id"]

    from app.core.db import SessionLocal
    from app.services.connectors.keys import resolve_db_key
    from app.services.llm.credentials import resolve_credential
    with SessionLocal() as db:
        # trusted project: global keys apply
        assert resolve_db_key(db, admin_pid, "scopus") == "global-scopus-key"
        assert resolve_credential(db, admin_pid).provider == "anthropic"
        # visitor sandbox: no global database key; the global AI key, within
        # the demo budget (test_demo_public.py)
        assert resolve_db_key(db, sandbox_pid, "scopus") is None
        assert resolve_credential(db, sandbox_pid).project_id is None

    # ...and the settings UI does not pretend the app-wide key applies
    keys = {k["provider"]: k for k in client.get(
        f"/api/database-credentials?project_id={sandbox_pid}").json()}
    assert keys["scopus"]["global_configured"] is False

    # ...and a visitor stores no key of their own on a public instance
    r = client.put("/api/database-credentials", json={
        "provider": "scopus", "api_key": "visitor-own-key",
        "project_id": sandbox_pid})
    assert r.status_code == 403
    r = client.put("/api/llm/credentials", json={
        "provider": "openai", "api_key": "sk-visitor-own-key",
        "project_id": sandbox_pid})
    assert r.status_code == 403
    with SessionLocal() as db:
        assert resolve_db_key(db, sandbox_pid, "scopus") is None


# ---- the daily selective reset -------------------------------------------------

def test_demo_reset_is_selective(client, demo):
    _register(client, "admin@example.com", "Admin")
    client.post("/api/admin/trusted-emails", json={"email": "full@lab.fr"})
    _register(client, "full@lab.fr", "Colleague")
    trusted_pid = client.post("/api/projects", json={"name": "keep me"}).json()["id"]
    _guest(client)
    _guest(client)
    guest_cookie = client.cookies.get("litubik_token")

    client.post("/api/auth/login", json={
        "email": "admin@example.com", "password": "password123"})
    r = client.post("/api/admin/demo-reset")
    assert r.status_code == 200
    # 2 sandbox accounts, each with its seeded example project
    assert r.json() == {"users": 2, "projects": 2}

    # visitors are gone (their session no longer opens), trusted people and
    # their data survive
    client.cookies.clear()
    client.cookies.set("litubik_token", guest_cookie)
    assert client.get("/api/auth/me").status_code == 401
    client.cookies.clear()
    assert client.post("/api/auth/login", json={
        "email": "full@lab.fr", "password": "password123"}).status_code == 200
    assert [p["id"] for p in client.get("/api/projects").json()] == [trusted_pid]

    # the shared demo co-reviewer account survives too (trusted)
    from app.core.db import SessionLocal
    from app.models import User
    from app.services.demo_seed import CO_REVIEWER_EMAIL
    with SessionLocal() as db:
        assert db.query(User).filter_by(email=CO_REVIEWER_EMAIL).first() is not None

    # a purge marks today as done: the scheduler will not fire again
    from app.services.demo_reset import reset_due
    assert reset_due() is False


def test_reset_due_logic(demo, monkeypatch):
    from datetime import datetime, timezone

    from app.core.config import get_settings
    from app.services import demo_reset

    marker = get_settings().data_dir / "demo_last_reset"
    if marker.exists():
        marker.unlink()
    at = lambda h: datetime(2026, 7, 20, h, 30, tzinfo=timezone.utc)  # noqa: E731
    assert demo_reset.reset_due(at(3)) is False   # before the reset hour (4)
    assert demo_reset.reset_due(at(5)) is True    # due
    marker.write_text("2026-07-20", encoding="utf-8")
    assert demo_reset.reset_due(at(5)) is False   # already done today
    marker.write_text("2026-07-19", encoding="utf-8")
    assert demo_reset.reset_due(at(5)) is True    # yesterday's marker
    monkeypatch.setattr(demo, "demo_reset_hour", -1)
    assert demo_reset.reset_due(at(5)) is False   # disabled
    marker.unlink()


def test_reset_endpoint_guards(client, demo, monkeypatch):
    _register(client, "admin@example.com", "Admin")
    _guest(client)
    assert client.post("/api/admin/demo-reset").status_code == 403  # not admin
    client.post("/api/auth/login", json={
        "email": "admin@example.com", "password": "password123"})
    monkeypatch.setattr(demo, "demo_mode", False)
    assert client.post("/api/admin/demo-reset").status_code == 400  # not a demo


# ---- normal instance stays untouched ------------------------------------------

def test_normal_instance_all_trusted(client):
    r = _register(client, "admin@example.com", "Admin")
    assert r.json()["is_trusted"] is True
    r = _register(client, "anyone@example.com", "Anyone")
    assert r.json()["is_trusted"] is True
    # no cap either
    for i in range(4):
        assert client.post("/api/projects",
                           json={"name": f"p{i}"}).status_code == 200
