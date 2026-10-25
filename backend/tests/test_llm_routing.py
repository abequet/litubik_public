"""Per-task AI routing: tier defaults, stored routes (global / project),
permissions, and the request options the Anthropic provider sends."""
from types import SimpleNamespace

import pytest

from app.services.llm.base import LLMError, LLMResult


def _open(monkeypatch, opened: list):
    """Replace get_provider by a recorder of (provider, model, effort)."""
    class Fake:
        def __init__(self, provider, model, effort):
            self.name, self.model, self.effort = provider, model, effort

        def generate(self, messages, system=None, max_tokens=4096):
            return LLMResult(text="ok")

    def fake_get_provider(provider, api_key, model=None, base_url=None, effort=None):
        opened.append((provider, model, effort))
        return Fake(provider, model, effort)

    monkeypatch.setattr("app.services.llm.credentials.get_provider", fake_get_provider)


def test_every_prompt_key_belongs_to_a_task():
    from app.services.llm.prompts import _SPECS
    from app.services.llm.tasks import task_for_feature
    missing = [s.key for s in _SPECS if task_for_feature(s.key) is None]
    assert missing == []


def test_tier_default_picks_bulk_or_reasoning_model(user_client, monkeypatch):
    from app.core.db import SessionLocal
    from app.services.llm.credentials import open_provider_chain, resolve_model

    user_client.put("/api/llm/credentials", json={
        "provider": "anthropic", "api_key": "sk-ant-fake-key-123"})
    opened: list = []
    _open(monkeypatch, opened)
    with SessionLocal() as db:
        open_provider_chain(db, None, feature="screening_ta_suggest").generate([])
        open_provider_chain(db, None, feature="protocol_extract").generate([])
        assert resolve_model(db, None, feature="title_triage") == (
            "anthropic", "claude-sonnet-5-5")
        assert resolve_model(db, None, feature="results_narrative") == (
            "anthropic", "claude-opus-5-5")
    assert opened == [("anthropic", "claude-sonnet-5-5", "medium"),
                      ("anthropic", "claude-opus-5-5", "medium")]


def test_local_provider_keeps_its_default_model(user_client, monkeypatch):
    """No tier table for a self-hosted server: the credential's model is used."""
    from app.core.db import SessionLocal
    from app.services.llm.credentials import resolve_model

    user_client.put("/api/llm/credentials", json={
        "provider": "local", "api_key": "", "default_model": "qwen3:8b"})
    with SessionLocal() as db:
        assert resolve_model(db, None, feature="protocol_extract") == ("local", "qwen3:8b")


def test_stored_route_overrides_and_project_beats_global(user_client, monkeypatch):
    from app.core.db import SessionLocal
    from app.services.llm.credentials import open_provider_chain

    user_client.put("/api/llm/credentials", json={
        "provider": "anthropic", "api_key": "sk-ant-fake-key-123"})
    user_client.put("/api/llm/credentials", json={
        "provider": "openai", "api_key": "sk-openai-fake-key"})
    pid = user_client.post("/api/projects", json={"name": "Routed"}).json()["id"]

    r = user_client.put("/api/llm/routes", json={
        "task": "screening_ta", "provider": "openai", "model": "gpt-5-mini",
        "effort": "low"})
    assert r.status_code == 200
    opened: list = []
    _open(monkeypatch, opened)
    with SessionLocal() as db:
        chain = open_provider_chain(db, pid, feature="screening_ta_suggest")
        chain.generate([])
    # route's provider first (its model + effort), the other key behind it on
    # its own tier model, same effort
    assert opened == [("openai", "gpt-5-mini", "low"),
                      ("anthropic", "claude-sonnet-5-5", "low")]

    r = user_client.put("/api/llm/routes", json={
        "task": "screening_ta", "provider": "anthropic",
        "model": "claude-haiku-5-5", "effort": "high", "project_id": pid})
    assert r.status_code == 200
    opened.clear()
    with SessionLocal() as db:
        open_provider_chain(db, pid, feature="screening_ta_suggest").generate([])
    assert opened[0] == ("anthropic", "claude-haiku-5-5", "high")

    rows = {x["task"]: x for x in
            user_client.get(f"/api/llm/routes?project_id={pid}").json()["routes"]}
    assert rows["screening_ta"]["route"] == {
        "provider": "anthropic", "model": "claude-haiku-5-5", "effort": "high"}
    assert rows["screening_ta"]["effective"]["source"] == "project"
    assert rows["protocol"]["route"] is None
    assert rows["protocol"]["effective"] == {
        "source": "default", "provider": "anthropic", "model": "claude-opus-5-5",
        "effort": "medium", "provider_missing": False}

    # deleting the project row falls back to the global one
    user_client.delete(f"/api/llm/routes/screening_ta?project_id={pid}")
    rows = {x["task"]: x for x in
            user_client.get(f"/api/llm/routes?project_id={pid}").json()["routes"]}
    assert rows["screening_ta"]["effective"]["source"] == "global"
    assert rows["screening_ta"]["effective"]["model"] == "gpt-5-mini"


def test_route_to_provider_without_key_falls_back_to_tier(user_client, monkeypatch):
    from app.core.db import SessionLocal
    from app.services.llm.credentials import open_provider_chain

    user_client.put("/api/llm/credentials", json={
        "provider": "anthropic", "api_key": "sk-ant-fake-key-123"})
    user_client.put("/api/llm/routes", json={
        "task": "triage", "provider": "gemini", "model": "gemini-2.5-flash"})
    opened: list = []
    _open(monkeypatch, opened)
    with SessionLocal() as db:
        open_provider_chain(db, None, feature="title_triage").generate([])
    assert opened == [("anthropic", "claude-sonnet-5-5", "medium")]
    rows = {x["task"]: x for x in user_client.get("/api/llm/routes").json()["routes"]}
    assert rows["triage"]["effective"]["provider_missing"] is True


def test_route_validation(user_client):
    assert user_client.put("/api/llm/routes", json={
        "task": "nope", "provider": "anthropic", "model": "x"}).status_code == 422
    assert user_client.put("/api/llm/routes", json={
        "task": "triage", "provider": "anthropic", "model": "x",
        "effort": "max"}).status_code == 422


def test_reviewers_route_only_when_the_project_allows(user_client):
    pid = user_client.post("/api/projects", json={"name": "Perms"}).json()["id"]
    user_client.post(f"/api/projects/{pid}/members",
                     json={"email": "rev@example.com", "role": "reviewer"})
    # registering logs the new (non-admin) user in
    user_client.post("/api/auth/register", json={
        "email": "rev@example.com", "password": "password123",
        "display_name": "Rev"})
    body = {"task": "triage", "provider": "anthropic",
            "model": "claude-haiku-5-5", "project_id": pid}
    assert user_client.put("/api/llm/routes", json=body).status_code == 403
    # global routing is never a reviewer's
    assert user_client.put("/api/llm/routes", json={
        **body, "project_id": None}).status_code == 403
    # a reviewer may still read the project's routing
    assert user_client.get(f"/api/llm/routes?project_id={pid}").status_code == 200

    # back as the admin: open the setting
    user_client.post("/api/auth/login", json={
        "email": "admin@example.com", "password": "password123"})
    r = user_client.put(f"/api/projects/{pid}", json={"llm_reviewers_can_route": True})
    assert r.status_code == 200 and r.json()["llm_reviewers_can_route"] is True

    user_client.post("/api/auth/login", json={
        "email": "rev@example.com", "password": "password123"})
    assert user_client.put("/api/llm/routes", json=body).status_code == 200
    assert user_client.delete(
        f"/api/llm/routes/triage?project_id={pid}").status_code == 200


# --- Anthropic request options ---------------------------------------------

def _fake_anthropic(monkeypatch, calls: list, reject=lambda kw: None,
                    stop_reason="end_turn", model="claude-sonnet-5-5"):
    import anthropic

    class Bad(anthropic.BadRequestError):
        def __init__(self, msg):  # the SDK signature needs a response; skip it
            self._msg = msg

        def __str__(self):
            return self._msg

    def create(**kwargs):
        calls.append(kwargs)
        msg = reject(kwargs)
        if msg:
            raise Bad(msg)
        return SimpleNamespace(
            stop_reason=stop_reason, model=model,
            stop_details=SimpleNamespace(explanation="policy"),
            content=[SimpleNamespace(type="text", text="ok")],
            usage=SimpleNamespace(input_tokens=5, output_tokens=1))

    class FakeClient:
        def __init__(self, api_key=None):
            self.beta = SimpleNamespace(messages=SimpleNamespace(create=create))

    monkeypatch.setattr(anthropic, "Anthropic", FakeClient)
    monkeypatch.setattr("app.services.llm.providers._ANTHROPIC_OPTS", {})


def test_anthropic_sends_effort_fallbacks_and_output_floor(monkeypatch):
    from app.services.llm.providers import AnthropicProvider
    calls: list = []
    _fake_anthropic(monkeypatch, calls)
    p = AnthropicProvider(api_key="k", model="claude-sonnet-5-5", effort="medium")
    result = p.generate([{"role": "user", "content": "hi"}], system="s", max_tokens=1500)
    assert result.text == "ok"
    kw = calls[0]
    assert kw["output_config"] == {"effort": "medium"}
    assert kw["fallbacks"] == "default"
    assert kw["betas"] == ["server-side-fallback-2026-07-01"]
    assert kw["max_tokens"] == 8192  # thinking is counted in the cap
    assert kw["system"] == "s"
    assert p.answered_model == "claude-sonnet-5-5"


def test_anthropic_drops_options_an_old_model_rejects(monkeypatch):
    from app.services.llm.providers import AnthropicProvider
    calls: list = []

    def reject(kw):
        if "output_config" in kw:
            return "Error code: 400 - output_config.effort is not supported on this model"
        if "fallbacks" in kw:
            return "Error code: 400 - unknown beta server-side-fallback"
        return None

    _fake_anthropic(monkeypatch, calls, reject=reject)
    p = AnthropicProvider(api_key="k", model="claude-sonnet-4-5", effort="medium")
    assert p.generate([{"role": "user", "content": "hi"}]).text == "ok"
    assert len(calls) == 3
    assert "output_config" not in calls[-1] and "fallbacks" not in calls[-1]
    # remembered: the next call goes straight to the accepted shape
    p.generate([{"role": "user", "content": "hi"}])
    assert len(calls) == 4 and "output_config" not in calls[-1]


def test_anthropic_refusal_is_an_error_naming_the_fix(monkeypatch):
    from app.services.llm.providers import AnthropicProvider
    _fake_anthropic(monkeypatch, [], stop_reason="refusal")
    p = AnthropicProvider(api_key="k", model="claude-sonnet-5-5")
    with pytest.raises(LLMError, match="declined"):
        p.generate([{"role": "user", "content": "hi"}])


def test_anthropic_reports_the_model_that_answered(monkeypatch):
    """A server-side fallback answers with another model: the usage journal
    must record that one, while the provider keeps routing to its own."""
    from app.services.llm.providers import AnthropicProvider
    from app.services.llm.usage import UsageLogger
    _fake_anthropic(monkeypatch, [], model="claude-opus-4-8")
    recorded: list = []
    monkeypatch.setattr("app.services.llm.usage.record_usage",
                        lambda *a, **k: recorded.append(a))
    p = AnthropicProvider(api_key="k", model="claude-sonnet-5-5")
    logged = UsageLogger(p, "title_triage", None, None)
    logged.generate([{"role": "user", "content": "hi"}])
    assert logged.model == "claude-opus-4-8"
    assert p.model == "claude-sonnet-5-5"
    assert recorded[0][3] == "claude-opus-4-8"


def test_refusal_is_still_journaled(monkeypatch):
    """A refused call is billed: the journal counts it with its tokens."""
    from app.services.llm.providers import AnthropicProvider
    from app.services.llm.usage import UsageLogger
    _fake_anthropic(monkeypatch, [], stop_reason="refusal")
    recorded: list = []
    monkeypatch.setattr("app.services.llm.usage.record_usage",
                        lambda *a, **k: recorded.append(a))
    logged = UsageLogger(AnthropicProvider(api_key="k", model="claude-sonnet-5-5"),
                         "title_triage", 7, 3)
    with pytest.raises(LLMError, match="declined"):
        logged.generate([{"role": "user", "content": "hi"}])
    assert recorded == [(7, "title_triage", "anthropic", "claude-sonnet-5-5",
                         3, 5, 1)]


def test_failover_journals_the_billed_failure_and_the_answer(monkeypatch):
    """The first key returns an empty answer (billed), the second answers:
    both calls land in the journal, each under its own provider and model."""
    from app.services.llm.base import BilledAttempt
    from app.services.llm.credentials import FallbackProvider
    from app.services.llm.usage import UsageLogger

    class Empty:
        name, model, answered_model = "openai", "gpt-5", None

        def generate(self, messages, system=None, max_tokens=4096):
            raise LLMError("Model returned no text",
                           billed=[BilledAttempt("openai", "gpt-5", 40, 30)])

    class Down:
        name, model, answered_model = "gemini", "gemini-2.5-pro", None

        def generate(self, messages, system=None, max_tokens=4096):
            raise LLMError("503 unavailable")  # never reached the model

    class Ok:
        name, model, answered_model = "mistral", "mistral-large-latest", None

        def generate(self, messages, system=None, max_tokens=4096):
            return LLMResult(text="ok", tokens_input=12, tokens_output=2)

    recorded: list = []
    monkeypatch.setattr("app.services.llm.usage.record_usage",
                        lambda *a, **k: recorded.append(a))
    chain = FallbackProvider([("openai", Empty()), ("gemini", Down()),
                              ("mistral", Ok())])
    UsageLogger(chain, "title_triage", 1, None).generate(
        [{"role": "user", "content": "hi"}])
    assert recorded == [
        (1, "title_triage", "openai", "gpt-5", None, 40, 30),
        (1, "title_triage", "mistral", "mistral-large-latest", None, 12, 2)]

    # every key fails: the billed attempt is still counted
    recorded.clear()
    chain = FallbackProvider([("openai", Empty()), ("gemini", Down())])
    with pytest.raises(LLMError, match="Every configured AI key failed"):
        UsageLogger(chain, "title_triage", 1, None).generate(
            [{"role": "user", "content": "hi"}])
    assert recorded == [(1, "title_triage", "openai", "gpt-5", None, 40, 30)]


def test_openai_route_effort_goes_first(monkeypatch):
    from app.services.llm.providers import OpenAICompatibleProvider
    import openai
    tried: list = []

    def create(**kwargs):
        tried.append(kwargs.get("reasoning_effort"))
        return SimpleNamespace(
            usage=SimpleNamespace(prompt_tokens=3, completion_tokens=1),
            choices=[SimpleNamespace(finish_reason="stop",
                                     message=SimpleNamespace(content="ok"))])

    class FakeClient:
        def __init__(self, api_key=None, base_url=None):
            self.chat = SimpleNamespace(completions=SimpleNamespace(create=create))

    monkeypatch.setattr(openai, "OpenAI", FakeClient)
    monkeypatch.setattr("app.services.llm.providers._EFFORT_MEMO", {})
    p = OpenAICompatibleProvider(api_key="k", model="gpt-5", effort="medium")
    p.generate([{"role": "user", "content": "hi"}])
    assert tried == ["medium"]
