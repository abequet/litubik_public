"""A demo instance open to the public: the one-click guest session, the AI
budget of the visitors, what a visitor may not reach (institutional access,
stored keys, sync…), the legal pages — and, as important, that none of it
changes anything for the trusted accounts of the same instance."""
import pytest

from app.core.config import get_settings
from app.services.llm.base import LLMError, LLMResult

GUEST_HOST = "demo.litubik.example"


@pytest.fixture
def demo(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "demo_mode", True)
    monkeypatch.setattr(settings, "trusted_emails", "")
    monkeypatch.setattr(settings, "demo_guest_hosts", "*")
    monkeypatch.setattr(settings, "contact_email", "operator@lab.example")
    from app.core.ratelimit import guest_daily, guest_hourly
    guest_daily.clear()
    guest_hourly.clear()
    return settings


@pytest.fixture
def no_seed(monkeypatch):
    """Guests without the 60-reference example project (faster)."""
    monkeypatch.setattr("app.services.demo_seed.seed_for_new_demo_account",
                        lambda db, user_id: None)


def _register(client, email, name="U"):
    return client.post("/api/auth/register", json={
        "email": email, "password": "password123", "display_name": name})


def _login(client, email):
    return client.post("/api/auth/login", json={
        "email": email, "password": "password123"})


def _guest(client):
    r = client.post("/api/auth/guest", json={"accept_terms": True})
    assert r.status_code == 200, r.text
    return r.json()


def _fake_llm(monkeypatch, calls: list, tokens=(1000, 1000)):
    """Every opened provider answers with `tokens` (input, output) and logs
    (provider, model) in `calls`."""
    class Fake:
        api_key = ""
        answered_model = None

        def __init__(self, provider, model):
            self.name, self.model = provider, model

        def generate(self, messages, system=None, max_tokens=4096):
            calls.append((self.name, self.model))
            return LLMResult(text="ok", tokens_input=tokens[0],
                             tokens_output=tokens[1])

    monkeypatch.setattr(
        "app.services.llm.credentials.get_provider",
        lambda provider, api_key, model=None, base_url=None, effort=None:
        Fake(provider, model))


def _setup_ai(client):
    """Superadmin with an app-wide AI key, then a guest with a project."""
    _register(client, "admin@example.com", "Admin")
    client.put("/api/llm/credentials", json={
        "provider": "anthropic", "api_key": "sk-ant-global-key-123"})
    guest = _guest(client)
    pid = client.post("/api/projects", json={"name": "sandbox"}).json()["id"]
    return guest["id"], pid


def _ask(project_id, user_id, feature="screening_ta_suggest", max_tokens=100):
    from app.core.db import SessionLocal
    from app.services.llm.credentials import open_provider_chain
    with SessionLocal() as db:
        chain = open_provider_chain(db, project_id, feature=feature,
                                    user_id=user_id)
        return chain.generate([{"role": "user", "content": "hello"}],
                              max_tokens=max_tokens)


# ---- the guest entry ----------------------------------------------------------

def test_guest_host_matching(demo, monkeypatch):
    from app.core.demo import guest_entry_for_host
    monkeypatch.setattr(demo, "demo_guest_hosts", "demo.*")
    assert guest_entry_for_host("demo.litubik.org") is True
    assert guest_entry_for_host("DEMO.litubik.org:443") is True
    assert guest_entry_for_host("litubik.org") is False
    assert guest_entry_for_host("www.litubik.org") is False
    assert guest_entry_for_host(None) is False
    monkeypatch.setattr(demo, "demo_mode", False)
    assert guest_entry_for_host("demo.litubik.org") is False


def test_guest_only_on_guest_hosts(client, demo, monkeypatch, no_seed):
    monkeypatch.setattr(demo, "demo_guest_hosts", "demo.*")
    _register(client, "admin@example.com", "Admin")
    client.cookies.clear()
    body = {"accept_terms": True}
    # the ordinary name of the instance: ordinary sign-in, no guest entry
    assert client.get("/api/instance").json()["guest_entry"] is False
    assert client.post("/api/auth/guest", json=body).status_code == 404
    # the demo name opens it
    headers = {"host": GUEST_HOST}
    assert client.get("/api/instance", headers=headers).json()["guest_entry"] is True
    r = client.post("/api/auth/guest", json=body, headers=headers)
    assert r.status_code == 200
    assert r.json()["is_guest"] is True and r.json()["is_trusted"] is False
    assert r.json()["email"].endswith("@guest.invalid")


def test_guest_needs_demo_mode_terms_and_a_set_up_instance(client, demo, no_seed,
                                                          monkeypatch):
    # an instance without accounts: the first one must be the superadmin
    assert client.post("/api/auth/guest",
                       json={"accept_terms": True}).status_code == 503
    _register(client, "admin@example.com", "Admin")
    assert client.post("/api/auth/guest", json={}).status_code == 422
    monkeypatch.setattr(demo, "demo_mode", False)
    assert client.post("/api/auth/guest",
                       json={"accept_terms": True}).status_code == 404


def test_guest_session_is_a_sandbox_with_the_example(client, demo):
    _register(client, "admin@example.com", "Admin")
    guest = _guest(client)
    me = client.get("/api/auth/me").json()
    assert me["id"] == guest["id"] and me["is_guest"] is True
    projects = client.get("/api/projects").json()
    assert len(projects) == 1 and "Example review" in projects[0]["name"]


def test_guest_rate_limit_per_address(client, demo, no_seed):
    _register(client, "admin@example.com", "Admin")
    for _ in range(5):
        _guest(client)
    r = client.post("/api/auth/guest", json={"accept_terms": True})
    assert r.status_code == 429


def test_live_guest_cap(client, demo, no_seed, monkeypatch):
    monkeypatch.setattr("app.core.demo.DEMO_MAX_LIVE_GUESTS", 1)
    _register(client, "admin@example.com", "Admin")
    _guest(client)
    r = client.post("/api/auth/guest", json={"accept_terms": True})
    assert r.status_code == 503 and "full" in r.json()["detail"]


def test_guest_ends_session_and_data(client, demo):
    _register(client, "admin@example.com", "Admin")
    guest = _guest(client)
    pid = client.get("/api/projects").json()[0]["id"]
    assert client.delete("/api/auth/guest").status_code == 200
    assert client.get("/api/auth/me").status_code == 401
    from app.core.db import SessionLocal
    from app.models import Project, User
    with SessionLocal() as db:
        assert db.get(User, guest["id"]) is None
        assert db.get(Project, pid) is None
    # a trusted account cannot delete itself through this door
    _login(client, "admin@example.com")
    assert client.delete("/api/auth/guest").status_code == 403


def test_nightly_purge_spares_the_last_hour(client, demo, no_seed):
    _register(client, "admin@example.com", "Admin")
    guest = _guest(client)
    from app.core.db import SessionLocal
    from app.models import User
    from app.services.demo_reset import run_demo_reset
    with SessionLocal() as db:
        assert run_demo_reset(db)["users"] == 0  # just arrived: kept
        assert db.get(User, guest["id"]) is not None
        assert run_demo_reset(db, grace=False)["users"] == 1
        assert db.get(User, guest["id"]) is None


# ---- e-mail registration on a demo instance -----------------------------------

def test_demo_registration_is_for_the_allowlist(client, demo, monkeypatch):
    # LITUBIK_ALLOW_REGISTRATION does not reopen a demo instance
    monkeypatch.setattr(demo, "allow_registration", True)
    _register(client, "admin@example.com", "Admin")
    assert _register(client, "stranger@example.com").status_code == 403
    client.post("/api/admin/trusted-emails", json={"email": "friend@lab.fr"})
    assert _register(client, "friend@lab.fr").status_code == 200


def test_first_account_must_be_listed_when_a_list_is_provisioned(client, demo,
                                                                 monkeypatch):
    monkeypatch.setattr(demo, "trusted_emails", "owner@lab.fr")
    from app.core.db import SessionLocal
    from app.core.demo import seed_trusted_emails
    with SessionLocal() as db:
        seed_trusted_emails(db)
    assert _register(client, "first-comer@example.com").status_code == 403
    r = _register(client, "owner@lab.fr", "Owner")
    assert r.status_code == 200 and r.json()["is_admin"] is True


# ---- the AI budget ------------------------------------------------------------

def test_guest_runs_on_the_global_key_in_the_bulk_tier(client, demo, monkeypatch):
    calls: list = []
    _fake_llm(monkeypatch, calls)
    guest_id, pid = _setup_ai(client)
    _ask(pid, guest_id, feature="protocol_extract")  # a "reasoning" task
    assert calls == [("anthropic", "claude-sonnet-5-5")]  # bulk model anyway
    from app.core.db import SessionLocal
    from app.models import User
    from app.services.llm.demo_budget import month_spent
    with SessionLocal() as db:
        spent = db.get(User, guest_id).demo_ai_spent_usd
        assert spent > 0
        assert month_spent(db)[0] == pytest.approx(spent)
    status = client.get("/api/demo/ai-budget").json()
    assert status["applies"] is True
    assert status["user_left_usd"] == pytest.approx(2.0 - spent, abs=1e-4)


def test_per_account_cap(client, demo, monkeypatch):
    calls: list = []
    _fake_llm(monkeypatch, calls)
    monkeypatch.setattr(demo, "demo_ai_user_cap_usd", 0.02)
    guest_id, pid = _setup_ai(client)
    _ask(pid, guest_id)  # $0.012 at Sonnet rates
    _ask(pid, guest_id)  # $0.024: crosses the cap with this call
    with pytest.raises(LLMError, match="used up"):
        _ask(pid, guest_id)
    assert len(calls) == 2


def test_monthly_cap_across_visitors_and_purge(client, demo, monkeypatch):
    calls: list = []
    _fake_llm(monkeypatch, calls)
    monkeypatch.setattr(demo, "demo_ai_monthly_cap_usd", 0.02)
    guest_id, pid = _setup_ai(client)
    _ask(pid, guest_id)
    _ask(pid, guest_id)
    # the purge removes the visitor, not the month's spending
    from app.core.db import SessionLocal
    from app.services.demo_reset import run_demo_reset
    from app.services.llm.demo_budget import month_spent
    _login(client, "admin@example.com")
    with SessionLocal() as db:
        before = month_spent(db)[0]
        run_demo_reset(db, grace=False)
        assert month_spent(db)[0] == pytest.approx(before)
    second = _guest(client)
    pid2 = client.post("/api/projects", json={"name": "s2"}).json()["id"]
    with pytest.raises(LLMError, match="used up"):
        _ask(pid2, second["id"])
    # the superadmin starts the month again
    _login(client, "admin@example.com")
    status = client.get("/api/demo/ai-budget").json()
    assert status["applies"] is False and status["month_calls"] == 2
    assert status["live_visitors"] == 1
    assert client.post("/api/admin/demo-ai-budget/reset").status_code == 200
    _ask(pid2, second["id"])


def test_worst_case_is_refused_before_the_call(client, demo, monkeypatch):
    calls: list = []
    _fake_llm(monkeypatch, calls)
    guest_id, pid = _setup_ai(client)
    with pytest.raises(LLMError, match="could cost up to"):
        _ask(pid, guest_id, max_tokens=1_000_000)  # $15 of answer at most
    assert calls == []


def test_month_rollover(client, demo):
    from app.core.db import SessionLocal
    from app.models import DemoAiBudget
    from app.services.llm.demo_budget import month_spent
    with SessionLocal() as db:
        db.add(DemoAiBudget(period="2000-01", spent_usd=9.99, n_calls=3))
        db.commit()
        assert month_spent(db) == (0.0, 0)
        assert month_spent(db, "2000-01") == (9.99, 3)


def test_ai_off_for_visitors_when_a_cap_is_zero(client, demo, monkeypatch):
    calls: list = []
    _fake_llm(monkeypatch, calls)
    monkeypatch.setattr(demo, "demo_ai_monthly_cap_usd", 0)
    guest_id, pid = _setup_ai(client)
    with pytest.raises(LLMError, match="not available"):
        _ask(pid, guest_id)


def test_guest_cannot_pick_a_key(client, demo, monkeypatch):
    _fake_llm(monkeypatch, [])
    guest_id, pid = _setup_ai(client)
    from app.core.db import SessionLocal
    from app.models import LLMCredential
    from app.services.llm.credentials import open_provider_chain
    with SessionLocal() as db:
        key_id = db.query(LLMCredential).first().id
        with pytest.raises(LLMError):
            open_provider_chain(db, pid, credential_id=key_id)


def test_explicit_key_must_be_in_scope(user_client, monkeypatch):
    # every instance: a project cannot borrow another project's key by its id
    _fake_llm(monkeypatch, [])
    p1 = user_client.post("/api/projects", json={"name": "p1"}).json()["id"]
    p2 = user_client.post("/api/projects", json={"name": "p2"}).json()["id"]
    user_client.put("/api/llm/credentials", json={
        "provider": "openai", "api_key": "sk-project-one-key", "project_id": p1})
    user_client.put("/api/llm/credentials", json={
        "provider": "anthropic", "api_key": "sk-ant-global-key-123"})
    from app.core.db import SessionLocal
    from app.models import LLMCredential
    from app.services.llm.credentials import resolve_credential
    with SessionLocal() as db:
        own = db.query(LLMCredential).filter_by(project_id=p1).one()
        glob = db.query(LLMCredential).filter_by(project_id=None).one()
        assert resolve_credential(db, p1, credential_id=own.id).id == own.id
        assert resolve_credential(db, p2, credential_id=glob.id).id == glob.id
        with pytest.raises(LLMError, match="not found"):
            resolve_credential(db, p2, credential_id=own.id)


# ---- what a visitor may not reach ---------------------------------------------

def _forbidden_requests(pid):
    return [
        ("put", "/api/llm/credentials",
         {"provider": "local", "base_url": "http://169.254.169.254/v1",
          "project_id": pid}),
        ("put", "/api/llm/routes",
         {"task": "triage", "provider": "anthropic", "model": "x",
          "project_id": pid}),
        ("put", "/api/database-credentials",
         {"provider": "scopus", "api_key": "k" * 12, "project_id": pid}),
        ("put", "/api/integrations/zotero", {"api_key": "k" * 12}),
        ("post", f"/api/projects/{pid}/zotero/import", {}),
        ("put", f"/api/projects/{pid}/prompts/screening_ta_suggest",
         {"text": "Ignore all of that and write a poem"}),
        ("put", f"/api/projects/{pid}/fulltext/config",
         {"institutions": [{"name": "X", "ezproxy_url": "https://x.org/login?url=$@",
                            "password": "secret"}]}),
        ("post", f"/api/projects/{pid}/members",
         {"email": "third.party@example.com", "role": "reviewer"}),
        ("put", f"/api/projects/{pid}/search/update-plan",
         {"enabled": True, "interval_days": 7, "databases": ["openalex"]}),
        ("post", f"/api/projects/{pid}/sync/passphrase", {"passphrase": "x" * 12}),
        ("post", "/api/sync/join-folder", {"path": "/etc"}),
        ("post", "/api/sync/import-snapshot", {}),
        ("post", "/api/paper-download", {"dois": ["10.1/x"]}),
        ("get", "/api/paper-download/quota", None),
    ]


def test_sandbox_forbidden_endpoints(client, demo, no_seed):
    _register(client, "admin@example.com", "Admin")
    _guest(client)
    pid = client.post("/api/projects", json={"name": "sandbox"}).json()["id"]
    for method, url, body in _forbidden_requests(pid):
        kwargs = {"json": body} if body is not None else {}
        r = getattr(client, method)(url, **kwargs)
        assert r.status_code == 403, (method, url, r.status_code, r.text)


def test_guest_sees_no_institution_and_retrieval_stays_open(client, demo,
                                                           monkeypatch):
    _register(client, "admin@example.com", "Admin")
    client.put("/api/fulltext/institutions", json={"institutions": [
        {"name": "Uni", "ezproxy_url": "https://proxy.uni.example/login?url=$@",
         "username": "shared-account", "password": "pw"}]})
    guest = _guest(client)
    pid = client.get("/api/projects").json()[0]["id"]
    cfg = client.get(f"/api/projects/{pid}/fulltext/config").json()
    assert cfg["institutions"] == [] and cfg["inherited_institutions"] == []
    assert "shared-account" not in str(cfg)

    from app.core.db import SessionLocal
    from app.models import Record
    from app.services.fulltext import jobs
    from app.services.fulltext.service import resolve_config
    with SessionLocal() as db:
        settings = resolve_config(db, pid, fallback_email="guest@x", sandbox=True)
        assert settings == {"email": "operator@lab.example", "institutions": []}
        rid = db.query(Record).filter_by(project_id=pid).first().id

    seen = []
    monkeypatch.setattr(jobs, "retrieve_one",
                        lambda db, p, record, settings: seen.append(settings) or
                        {"status": "not_found", "via": "", "filename": "",
                         "oa_url": "", "size_kb": None, "error": ""})
    jobs.fulltext_retrieve_handler(0, {
        "project_id": pid, "record_ids": [rid], "force": True,
        "fallback_email": "", "use_extensions": True,
        # even a run asked without the flag: the project decides
    }, lambda *a: None)
    assert seen and seen[0]["institutions"] == []
    assert seen[0]["use_extensions"] is False and seen[0]["sandbox"] is True
    assert seen[0]["email"] == "operator@lab.example"
    assert guest["email"] not in str(seen[0])

    # no institution reaches the pipeline, not even the legacy file
    captured = {}
    import app.services.fulltext.downloader as downloader
    monkeypatch.setattr(downloader, "process_doi",
                        lambda doi, **kw: captured.update(kw) or ({}, None))
    from app.services.fulltext.service import retrieve_one
    with SessionLocal() as db:
        record = db.get(Record, rid)
        record.doi = record.doi or "10.1/x"
        retrieve_one(db, pid, record, {**seen[0]})
    assert captured["institutions"] == [] and captured["use_extensions"] is False


def test_sandbox_upload_caps(client, demo, monkeypatch):
    monkeypatch.setattr("app.api.fulltext.DEMO_MAX_PDF_BYTES", 1000)
    _register(client, "admin@example.com", "Admin")
    _guest(client)
    pid = client.get("/api/projects").json()[0]["id"]  # the example review
    from app.core.db import SessionLocal
    from app.models import Record
    with SessionLocal() as db:
        rid = db.query(Record).filter_by(project_id=pid).first().id
    pdf = b"%PDF-1.4\n" + b"0" * 2000
    r = client.post(f"/api/projects/{pid}/fulltext/records/{rid}/upload",
                    files={"file": ("a.pdf", pdf, "application/pdf")})
    assert r.status_code == 413 and "demo" in r.json()["detail"]


def test_ticket_cap(client, demo, no_seed):
    _register(client, "admin@example.com", "Admin")
    _guest(client)
    body = {"title": "Nice", "body": "Works", "kind": "feedback"}
    for _ in range(5):
        assert client.post("/api/tickets", json=body).status_code == 200
    assert client.post("/api/tickets", json=body).status_code == 429


# ---- abuse limits ------------------------------------------------------------------

def test_proxy_trust_ignores_forged_addresses():
    """The image trusts only a proxy on a private network: an address the
    client writes at the front of X-Forwarded-For is never taken."""
    import asyncio
    import re
    from pathlib import Path

    from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

    dockerfile = (Path(__file__).resolve().parents[2] / "Dockerfile").read_text(
        encoding="utf-8")
    trusted = re.search(r"^ENV FORWARDED_ALLOW_IPS=(\S+)", dockerfile, re.M).group(1)
    assert trusted != "*"
    seen = {}

    async def app(scope, receive, send):
        seen["client"] = scope["client"]

    def client_of(peer, forwarded):
        scope = {"type": "http", "client": (peer, 1234), "scheme": "http",
                 "headers": [(b"x-forwarded-for", forwarded.encode())]}
        asyncio.run(ProxyHeadersMiddleware(app, trusted)(scope, None, None))
        return seen["client"][0]

    # the proxy (private address) appended the real client after a forged one
    assert client_of("100.64.0.7", "6.6.6.6, 203.0.113.9") == "203.0.113.9"
    assert client_of("10.1.2.3", "203.0.113.9") == "203.0.113.9"
    # a client reaching the server directly cannot claim another address
    assert client_of("198.51.100.4", "6.6.6.6") == "198.51.100.4"


def test_rate_key_groups_ipv6_by_64():
    from app.core.demo import rate_key
    assert rate_key("2001:db8:1:2::1") == rate_key("2001:db8:1:2:ffff::9")
    assert rate_key("2001:db8:1:2::1") == "2001:db8:1:2::/64"
    assert rate_key("2001:db8:1:3::1") != rate_key("2001:db8:1:2::1")
    assert rate_key("203.0.113.9") == "203.0.113.9"
    assert rate_key("::ffff:203.0.113.9") == "203.0.113.9"
    assert rate_key("testclient") == "testclient"


def test_guest_sessions_capped_for_the_whole_instance(client, demo, no_seed,
                                                     monkeypatch):
    from app.core.ratelimit import guest_global, guest_hourly
    monkeypatch.setattr(guest_hourly, "limit", 100)
    monkeypatch.setattr(guest_global, "limit", 2)
    _register(client, "admin@example.com", "Admin")
    _guest(client)
    _guest(client)
    r = client.post("/api/auth/guest", json={"accept_terms": True})
    assert r.status_code == 503 and "try again" in r.json()["detail"]


def test_one_job_at_a_time_per_visitor(client, demo, no_seed, monkeypatch):
    from fastapi import HTTPException

    from app.core.db import SessionLocal
    from app.core.demo import check_sandbox_job_quota
    from app.models import Job, User
    admin = _register(client, "admin@example.com", "Admin").json()
    guest = _guest(client)
    pid = client.post("/api/projects", json={"name": "sandbox"}).json()["id"]
    with SessionLocal() as db:
        db.add(Job(type="topics", status="running", created_by=guest["id"],
                   project_id=pid))
        db.commit()
    # through the API: the visitor's next task waits
    r = client.post(f"/api/projects/{pid}/fulltext/retrieve", json={})
    assert r.status_code == 429 and "one task" in r.json()["detail"]
    with SessionLocal() as db:
        # follow-ups their own task schedules are never refused
        check_sandbox_job_quota(db, guest["id"], "abstract_backfill")
        # a trusted account is never counted nor refused
        check_sandbox_job_quota(db, admin["id"], "fulltext_retrieve")
        # all visitors together: DEMO_MAX_SANDBOX_JOBS at once
        for i in range(3):
            other = User(email=f"g{i}@guest.invalid", password_hash="x",
                         display_name="G", is_trusted=False, is_guest=True)
            db.add(other)
            db.flush()
            db.add(Job(type="topics", status="queued", created_by=other.id))
        fresh = User(email="fresh@guest.invalid", password_hash="x",
                     display_name="F", is_trusted=False, is_guest=True)
        db.add(fresh)
        db.commit()
        with pytest.raises(HTTPException) as refused:
            check_sandbox_job_quota(db, fresh.id, "fulltext_retrieve")
        assert refused.value.status_code == 503
        check_sandbox_job_quota(db, admin["id"], "fulltext_retrieve")


def test_guest_retrieval_uses_no_browser(monkeypatch):
    from app.services.fulltext import doibatch
    captured = []
    monkeypatch.setattr(doibatch, "_run_tier_parallel",
                        lambda tasks: captured.append([n for n, _ in tasks])
                        or (None, None))
    monkeypatch.setattr(doibatch, "fetch_crossref",
                        lambda doi: {"first_author": "A", "year": 2020, "title": "T"})
    doibatch.process_doi("10.5/x", email="", use_extensions=False, browser=False)
    assert "playwright" not in {n for tier in captured for n in tier}
    captured.clear()
    doibatch.process_doi("10.5/x", email="", use_extensions=False)
    assert "playwright" in {n for tier in captured for n in tier}

    captured_kw = {}
    import app.services.fulltext.downloader as downloader
    monkeypatch.setattr(downloader, "process_doi",
                        lambda doi, **kw: captured_kw.update(kw) or ({}, None))
    from types import SimpleNamespace

    from app.services.fulltext.service import retrieve_one
    retrieve_one(None, 1, SimpleNamespace(doi="10.5/x", id=1),
                 {"sandbox": True, "use_extensions": False})
    assert captured_kw["browser"] is False and captured_kw["institutions"] == []


def test_daily_cap_shared_by_visitors(client, demo, monkeypatch):
    calls: list = []
    _fake_llm(monkeypatch, calls)
    monkeypatch.setattr(demo, "demo_ai_daily_cap_usd", 0.02)
    guest_id, pid = _setup_ai(client)
    _ask(pid, guest_id)
    _ask(pid, guest_id)
    with pytest.raises(LLMError, match="Today"):
        _ask(pid, guest_id)
    status = client.get("/api/demo/ai-budget").json()
    assert status["day_left_usd"] == 0 and status["user_left_usd"] > 0
    # the superadmin's reset frees today as well
    _login(client, "admin@example.com")
    client.post("/api/admin/demo-ai-budget/reset")
    _ask(pid, guest_id)


def test_request_size_limits(client, demo, monkeypatch):
    # anonymous: a sign-in never needs more than a few hundred bytes
    r = client.post("/api/auth/login", content=b"x" * (70 * 1024),
                    headers={"content-type": "application/json"})
    assert r.status_code == 413
    monkeypatch.setattr("app.core.demo.DEMO_MAX_REQUEST_BYTES", 1000)
    _register(client, "admin@example.com", "Admin")
    pid_admin = client.post("/api/projects", json={"name": "real"}).json()["id"]
    pdf = b"%PDF-1.4\n" + b"0" * 3000
    files = {"file": ("a.pdf", pdf, "application/pdf")}
    # a trusted account is not concerned (404: the record does not exist)
    r = client.post(f"/api/projects/{pid_admin}/fulltext/records/999/upload",
                    files=files)
    assert r.status_code == 404
    _guest(client)
    pid = client.get("/api/projects").json()[0]["id"]
    r = client.post(f"/api/projects/{pid}/fulltext/records/999/upload",
                    files=files)
    assert r.status_code == 413 and "too large" in r.json()["detail"]


def test_sandbox_project_reference_cap(client, demo, monkeypatch):
    monkeypatch.setattr("app.core.demo.DEMO_MAX_PROJECT_RECORDS", 1)
    _register(client, "admin@example.com", "Admin")
    admin_pid = client.post("/api/projects", json={"name": "real"}).json()["id"]
    ris = (b"TY  - JOUR\nTI  - Demo paper\nAU  - Doe, J.\nPY  - 2020\n"
           b"DO  - 10.5/demo.1\nER  -\n")
    upload = {"files": {"file": ("s.ris", ris, "text/plain")},
              "data": {"source_name": "pubmed", "source_type": "database"}}
    assert client.post(f"/api/projects/{admin_pid}/imports/upload",
                       **upload).status_code == 200  # trusted: no cap
    _guest(client)
    pid = client.get("/api/projects").json()[0]["id"]  # the example: 60 refs
    r = client.post(f"/api/projects/{pid}/imports/upload", **upload)
    assert r.status_code == 413 and "at most 1 references" in r.json()["detail"]
    from app.core.db import SessionLocal
    from app.core.demo import sandbox_records_room
    with SessionLocal() as db:
        assert sandbox_records_room(db, pid) == 0
        assert sandbox_records_room(db, admin_pid) is None


# ---- nothing changes for the trusted accounts of a demo instance ---------------

def test_trusted_account_keeps_everything(client, demo, monkeypatch):
    _register(client, "admin@example.com", "Admin")
    client.put("/api/llm/credentials", json={
        "provider": "anthropic", "api_key": "sk-ant-global-key-123"})
    client.put("/api/fulltext/institutions", json={"institutions": [
        {"name": "Uni", "ezproxy_url": "https://proxy.uni.example/login?url=$@",
         "username": "u", "password": "pw"}]})
    client.post("/api/admin/trusted-emails", json={"email": "colleague@lab.fr"})
    colleague = _register(client, "colleague@lab.fr", "Colleague").json()
    assert colleague["is_trusted"] is True and colleague["is_guest"] is False
    pid = client.post("/api/projects", json={"name": "real review"}).json()["id"]

    # institutions inherited and used, the extension on, their own address
    cfg = client.get(f"/api/projects/{pid}/fulltext/config").json()
    assert [i["name"] for i in cfg["inherited_institutions"]] == ["Uni"]
    job_id = client.post(f"/api/projects/{pid}/fulltext/retrieve",
                         json={}).json()["job_id"]
    from app.core.db import SessionLocal
    from app.models import Job
    from app.services.fulltext.service import resolve_config
    with SessionLocal() as db:
        params = db.get(Job, job_id).params
        assert params["use_extensions"] is True and params["sandbox"] is False
        assert params["fallback_email"] == "colleague@lab.fr"
        assert [i["name"] for i in resolve_config(db, pid)["institutions"]] == ["Uni"]

    # the AI chain carries no budget guard, and spends nothing from it
    calls: list = []
    _fake_llm(monkeypatch, calls)
    from app.services.llm.credentials import open_provider_chain
    from app.services.llm.demo_budget import DemoBudgetGuard, month_spent
    with SessionLocal() as db:
        chain = open_provider_chain(db, pid, feature="protocol_extract",
                                    user_id=colleague["id"])
        assert not isinstance(getattr(chain, "_inner", chain), DemoBudgetGuard)
        chain.generate([{"role": "user", "content": "x"}], max_tokens=1_000_000)
        assert month_spent(db) == (0.0, 0)
    assert calls == [("anthropic", "claude-opus-5-5")]  # their routing tier

    # and every door a visitor finds closed is open
    for method, url, body in _forbidden_requests(pid):
        if "paper-download" in url or "zotero/import" in url or "join-folder" in url:
            continue  # need a grant, a stored key or a real folder: not 403-gated
        kwargs = {"json": body} if body is not None else {}
        r = getattr(client, method)(url, **kwargs)
        assert r.status_code != 403 or "demo" not in r.text, (url, r.text)


# ---- legal pages ----------------------------------------------------------------

def test_legal_pages_public_on_a_demo(client, demo):
    _register(client, "admin@example.com", "Ada Operator")
    client.cookies.clear()
    r = client.get("/api/legal/en/terms")
    assert r.status_code == 200
    body = r.json()["body_md"]
    assert "Ada Operator" in body and "04:00 UTC" in body
    assert "2.00 USD" in body and "10.00 USD" in body
    notice = client.get("/api/legal/fr/notice").json()["body_md"]
    assert "contact@litubik.org" in notice
    assert "[à compléter]" in notice  # no known host outside Railway
    assert "{{" not in notice
    assert client.get("/api/legal/de/terms").status_code == 404
    assert client.get("/api/legal/en/cookies").status_code == 404


def test_legal_host_detected_on_railway(client, demo, monkeypatch):
    monkeypatch.setenv("RAILWAY_PROJECT_ID", "abc")
    _register(client, "admin@example.com", "Admin")
    notice = client.get("/api/legal/en/notice").json()["body_md"]
    assert "Railway Corporation" in notice and "San Francisco" in notice


def test_legal_pages_absent_on_a_normal_instance(client):
    assert client.get("/api/legal/en/terms").status_code == 404


def test_legal_pages_admin_edit(client, demo):
    _register(client, "admin@example.com", "Admin")
    r = client.put("/api/admin/legal/settings", json={
        "operator_name": "A. Operator", "contact_email": "contact@x.example"})
    assert r.json()["effective"]["operator_name"] == "A. Operator"
    assert "contact@x.example" in client.get(
        "/api/legal/en/privacy").json()["body_md"]
    r = client.put("/api/admin/legal/en/terms", json={"body_md": "# Custom"})
    assert r.json()["custom"] is True
    assert client.get("/api/legal/en/terms").json()["body_md"] == "# Custom"
    overview = client.get("/api/admin/legal").json()
    assert {"slug": "terms", "lang": "en", "custom": True} in overview["pages"]
    client.delete("/api/admin/legal/en/terms")
    assert "Custom" not in client.get("/api/legal/en/terms").json()["body_md"]
    # visitors edit nothing
    _guest(client)
    assert client.put("/api/admin/legal/en/terms",
                      json={"body_md": "x"}).status_code == 403
    assert client.put("/api/admin/legal/settings", json={}).status_code == 403


def test_source_url_follows_the_deployment(monkeypatch):
    from app.core import version
    monkeypatch.delenv("LITUBIK_SOURCE_URL", raising=False)
    monkeypatch.delenv("RAILWAY_GIT_COMMIT_SHA", raising=False)
    assert version._source_url().endswith(f"/tree/v{version.__version__}")
    monkeypatch.setenv("RAILWAY_GIT_COMMIT_SHA", "abc123")
    assert version._source_url() == version.HOMEPAGE
    monkeypatch.setenv("LITUBIK_SOURCE_URL", "https://example.org/fork")
    assert version._source_url() == "https://example.org/fork"


def test_a_token_kept_from_a_deleted_guest_opens_no_other_account(client, demo,
                                                                  no_seed):
    """SQLite gives a deleted account's id to the next account created: a
    visitor who kept their cookie after ending their guest session must not be
    let into whoever takes that id next."""
    _register(client, "admin@example.com", "Admin")
    old = _guest(client)
    kept = client.cookies.get("litubik_token")
    assert client.delete("/api/auth/guest").status_code == 200
    client.cookies.clear()
    new = _guest(client)
    assert new["id"] == old["id"]  # the id was reused
    assert client.get("/api/auth/me").json()["id"] == new["id"]
    client.cookies.clear()
    client.cookies.set("litubik_token", kept)
    assert client.get("/api/auth/me").status_code == 401


def test_a_dead_session_cookie_gets_the_anonymous_size_limit(client, demo,
                                                             no_seed):
    """A deleted guest's cookie is still validly signed: it must not open the
    1 GiB limit of a real account to an anonymous sender."""
    _register(client, "admin@example.com", "Admin")
    _guest(client)
    kept = client.cookies.get("litubik_token")
    assert client.delete("/api/auth/guest").status_code == 200
    client.cookies.clear()
    client.cookies.set("litubik_token", kept)
    r = client.post("/api/projects", content=b"x" * (70 * 1024),
                    headers={"content-type": "application/json"})
    assert r.status_code == 413


def test_project_keys_cannot_reach_internal_endpoints_on_a_demo(client, demo):
    """A self-hosted LLM endpoint of a project key, on a hosted demo, must be a
    public address: localhost or the platform's private network would let a
    project admin make the server query its internal services. The app-wide
    keys stay the superadmin's to point anywhere."""
    from app.services.llm.credentials import endpoint_allowed
    _register(client, "admin@example.com", "Admin")
    client.post("/api/admin/trusted-emails", json={"email": "member@example.com"})
    r = client.put("/api/llm/credentials", json={
        "provider": "local", "api_key": "", "default_model": "m",
        "base_url": "http://localhost:11434/v1", "project_id": None})
    assert r.status_code == 200, r.text  # the superadmin's global key
    client.cookies.clear()
    _register(client, "member@example.com", "Member")
    pid = client.post("/api/projects", json={"name": "P"}).json()["id"]
    for url in ("http://localhost:11434/v1", "http://10.0.0.5:8000/v1",
                "http://100.64.0.7/v1"):
        r = client.put("/api/llm/credentials", json={
            "provider": "local", "api_key": "", "default_model": "m",
            "base_url": url, "project_id": pid})
        assert r.status_code == 400, url
        assert not endpoint_allowed(url, pid)
    assert endpoint_allowed("http://localhost:11434/v1", None)


def test_internal_endpoints_stay_allowed_off_demo(user_client):
    """Desktop and self-hosted instances: a local model is the point."""
    pid = user_client.post("/api/projects", json={"name": "P"}).json()["id"]
    r = user_client.put("/api/llm/credentials", json={
        "provider": "local", "api_key": "", "default_model": "m",
        "base_url": "http://localhost:11434/v1", "project_id": pid})
    assert r.status_code == 200, r.text
