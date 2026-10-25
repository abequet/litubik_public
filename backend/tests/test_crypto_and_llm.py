import pytest

from app.core.crypto import decrypt_secret, encrypt_secret
from app.services.llm.base import LLMError, _extract_json
from app.services.llm.registry import get_provider


def test_encrypt_decrypt_roundtrip():
    secret = "sk-ant-test-1234567890"
    encrypted = encrypt_secret(secret)
    assert encrypted != secret
    assert decrypt_secret(encrypted) == secret


def test_decrypt_garbage_returns_none():
    assert decrypt_secret("not-a-token") is None


def test_extract_json_plain():
    assert _extract_json('{"a": 1}') == {"a": 1}


def test_extract_json_fenced():
    assert _extract_json('```json\n{"a": [1, 2]}\n```') == {"a": [1, 2]}


def test_extract_json_invalid():
    with pytest.raises(LLMError):
        _extract_json("not json at all")


def test_get_provider_every_registered():
    from app.services.llm.registry import PROVIDERS
    for name in PROVIDERS:
        provider = get_provider(name, api_key="k")
        assert provider.model  # default model filled in
        assert provider.name == name


def test_get_provider_unknown():
    with pytest.raises(LLMError):
        get_provider("nope", api_key="k")


def test_local_provider_defaults():
    """A self-hosted server needs no key and gets Ollama's endpoint unless
    told otherwise; Mistral and local servers take `max_tokens`, OpenAI the
    newer `max_completion_tokens`."""
    from app.services.llm import providers

    local = get_provider("local", api_key="", model="qwen3:8b")
    assert local.api_key == "none"  # placeholder the SDK accepts
    assert local.base_url == "http://localhost:11434/v1"
    assert local.token_param == "max_tokens"
    custom = get_provider("local", api_key="", base_url="http://gpu-box:8000/v1")
    assert custom.base_url == "http://gpu-box:8000/v1"
    assert get_provider("mistral", api_key="k").token_param == "max_tokens"
    assert get_provider("mistral", api_key="k").base_url == "https://api.mistral.ai/v1"
    assert providers.OpenAICompatibleProvider(api_key="k", model="gpt-5").token_param         == "max_completion_tokens"


def test_local_calls_are_free():
    from app.services.llm import pricing
    assert pricing.cost_usd("local", "llama3.1:8b", 1_000_000, 1_000_000) == 0.0
    breakdown = pricing.cost_breakdown("local", "llama3.1:8b", 5000, 500)
    assert breakdown["free"] is True and breakdown["cost_label"] == "$0.00"
    assert pricing.cost_breakdown("mistral", "mistral-small-latest", 5000, 500)["free"] is False


def test_openai_compatible_sends_the_right_token_param(monkeypatch):
    """Ollama drops unknown fields silently (an unbounded answer, no error),
    so the cap must be sent under the name each server knows."""
    from types import SimpleNamespace

    import openai

    from app.services.llm import providers

    providers._EFFORT_MEMO.clear()
    seen: list[dict] = []

    def create(**kwargs):
        seen.append(kwargs)
        return SimpleNamespace(
            usage=SimpleNamespace(prompt_tokens=3, completion_tokens=1),
            choices=[SimpleNamespace(finish_reason="stop",
                                     message=SimpleNamespace(content="ok"))])

    class FakeClient:
        def __init__(self, api_key=None, base_url=None):
            self.chat = SimpleNamespace(completions=SimpleNamespace(create=create))

    monkeypatch.setattr(openai, "OpenAI", FakeClient)
    providers.LocalProvider(api_key="", model="qwen3:8b").generate(
        [{"role": "user", "content": "hi"}], max_tokens=77)
    providers.OpenAICompatibleProvider(api_key="k", model="gpt-4.1").generate(
        [{"role": "user", "content": "hi"}], max_tokens=88)
    assert seen[0]["max_tokens"] == 77 and "max_completion_tokens" not in seen[0]
    assert seen[1]["max_completion_tokens"] == 88 and "max_tokens" not in seen[1]


def test_local_credential_api_needs_no_key(user_client):
    """A local server is stored with its URL and without a key; a hosted
    provider still refuses an empty key."""
    r = user_client.put("/api/llm/credentials", json={
        "provider": "local", "api_key": "", "default_model": "qwen3:8b",
        "base_url": "http://gpu-box:8000/v1/"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["base_url"] == "http://gpu-box:8000/v1"  # trailing slash dropped
    assert body["default_model"] == "qwen3:8b"

    # editing the URL later keeps working without re-sending a key
    r = user_client.put("/api/llm/credentials", json={
        "provider": "local", "api_key": "", "default_model": "qwen3:8b",
        "base_url": "http://localhost:1234/v1"})
    assert r.status_code == 200 and r.json()["base_url"] == "http://localhost:1234/v1"

    r = user_client.put("/api/llm/credentials", json={
        "provider": "local", "api_key": "", "base_url": "gpu-box:8000"})
    assert r.status_code == 422  # not http(s)://

    r = user_client.put("/api/llm/credentials", json={
        "provider": "openai", "api_key": ""})
    assert r.status_code == 422
    r = user_client.put("/api/llm/credentials", json={
        "provider": "nope", "api_key": "whatever-123"})
    assert r.status_code == 422

    info = user_client.get("/api/llm/providers").json()
    assert info["meta"]["local"]["needs_key"] is False
    assert info["meta"]["local"]["needs_url"] is True
    assert info["meta"]["openai"]["needs_key"] is True


def test_project_no_fallback_opens_only_the_top_key(user_client, monkeypatch):
    """llm_no_fallback: the project's best-ranked key is the only one opened —
    a team on a local model is never silently moved to a cloud key."""
    from app.core.db import SessionLocal
    from app.services.llm.base import LLMResult
    from app.services.llm.credentials import open_provider_chain

    pid = user_client.post("/api/projects", json={"name": "Local only"}).json()["id"]
    user_client.put("/api/llm/credentials", json={
        "provider": "local", "api_key": "", "project_id": pid})
    user_client.put("/api/llm/credentials", json={
        "provider": "anthropic", "api_key": "sk-ant-fake-key-123"})  # global

    class Broke:
        model = "qwen3:8b"
        name = "local"

        def generate(self, messages, system=None, max_tokens=4096):
            raise LLMError("connection refused")

    class Works:
        model = "claude"
        name = "anthropic"

        def generate(self, messages, system=None, max_tokens=4096):
            return LLMResult(text="ok")

    fakes = {"local": Broke(), "anthropic": Works()}
    monkeypatch.setattr("app.services.llm.credentials.get_provider",
                        lambda provider, api_key, model=None, **kw: fakes[provider])

    with SessionLocal() as db:  # default: the global key takes over
        assert open_provider_chain(db, project_id=pid).generate([]).text == "ok"

    r = user_client.put(f"/api/projects/{pid}", json={"llm_no_fallback": True})
    assert r.status_code == 200 and r.json()["llm_no_fallback"] is True

    with SessionLocal() as db:  # now the local failure surfaces as such
        with pytest.raises(LLMError, match="connection refused"):
            open_provider_chain(db, project_id=pid).generate([])


def test_credentials_api(user_client):
    r = user_client.put("/api/llm/credentials", json={
        "provider": "anthropic", "api_key": "sk-ant-fake-key-123"})
    assert r.status_code == 200
    body = r.json()
    assert body["default_model"] == "claude-sonnet-5-5"
    assert "sk-ant" not in str(body)  # key is never returned

    creds = user_client.get("/api/llm/credentials").json()
    assert len(creds) == 1

    # upsert same provider replaces, not duplicates
    user_client.put("/api/llm/credentials", json={
        "provider": "anthropic", "api_key": "sk-ant-other-key-456",
        "default_model": "claude-opus-4-8"})
    creds = user_client.get("/api/llm/credentials").json()
    assert len(creds) == 1
    assert creds[0]["default_model"] == "claude-opus-4-8"

    # changing only the model (no re-entering the key) via the model endpoint
    cid = creds[0]["id"]
    r = user_client.post(f"/api/llm/credentials/{cid}/model",
                         json={"default_model": "claude-haiku-4-5"})
    assert r.status_code == 200 and r.json()["default_model"] == "claude-haiku-4-5"
    creds = user_client.get("/api/llm/credentials").json()
    assert creds[0]["default_model"] == "claude-haiku-4-5"


def test_provider_fallback_chain(user_client, monkeypatch):
    """When a key errors (no credit, outage), the next stored key takes over
    in registry order; JSON parsing still happens on the successful answer."""
    from app.core.db import SessionLocal
    from app.services.llm.base import LLMResult
    from app.services.llm.credentials import open_provider_chain

    for provider in ("anthropic", "gemini"):
        user_client.put("/api/llm/credentials", json={
            "provider": provider, "api_key": f"{provider}-fake-key-123"})

    class Broke:
        model = "claude-broke"
        name = "anthropic"

        def generate(self, messages, system=None, max_tokens=4096):
            raise LLMError("credit balance is too low")

    class Works:
        model = "gemini-works"
        name = "gemini"

        def generate(self, messages, system=None, max_tokens=4096):
            return LLMResult(text='{"ok": true}')

    fakes = {"anthropic": Broke(), "gemini": Works()}
    monkeypatch.setattr("app.services.llm.credentials.get_provider",
                        lambda provider, api_key, model=None, **kw: fakes[provider])

    with SessionLocal() as db:
        chain = open_provider_chain(db, project_id=None)
        result = chain.generate_json([{"role": "user", "content": "hi"}],
                                     json_schema={"type": "object"})
        assert result.data == {"ok": True}
        assert chain.name == "gemini" and chain.model == "gemini-works"

        # every key failing -> aggregated error
        fakes["gemini"] = Broke()
        chain = open_provider_chain(db, project_id=None)
        with pytest.raises(LLMError, match="Every configured AI key failed"):
            chain.generate([{"role": "user", "content": "hi"}])


def test_default_credential_selection(user_client):
    """B2: with several stored keys, the one marked default wins resolution."""
    from app.core.db import SessionLocal
    from app.services.llm.credentials import resolve_credential

    a = user_client.put("/api/llm/credentials", json={
        "provider": "anthropic", "api_key": "sk-ant-fake-1"}).json()
    g = user_client.put("/api/llm/credentials", json={
        "provider": "gemini", "api_key": "gm-fake-2"}).json()
    assert a["is_default"] is False and g["is_default"] is False

    with SessionLocal() as db:  # no default yet -> registry order (anthropic)
        assert resolve_credential(db, project_id=None).provider == "anthropic"

    r = user_client.post(f"/api/llm/credentials/{g['id']}/default")
    assert r.status_code == 200
    creds = {c["provider"]: c for c in
             user_client.get("/api/llm/credentials").json()}
    assert creds["gemini"]["is_default"] is True
    assert creds["anthropic"]["is_default"] is False

    with SessionLocal() as db:  # the chosen default now wins
        assert resolve_credential(db, project_id=None).provider == "gemini"

    # switching the default clears the previous one (one per scope)
    user_client.post(f"/api/llm/credentials/{creds['anthropic']['id']}/default")
    creds = {c["provider"]: c for c in
             user_client.get("/api/llm/credentials").json()}
    assert creds["anthropic"]["is_default"] is True
    assert creds["gemini"]["is_default"] is False


def _fake_openai(monkeypatch, refuse: set[str], tried: list):
    """Stand in for openai.OpenAI: records the reasoning_effort of each request
    and rejects the values in `refuse` the way the API does (400 naming the
    parameter)."""
    from types import SimpleNamespace

    import openai

    class Rejected(openai.OpenAIError):
        def __init__(self, value):
            self.value = value

        def __str__(self):
            return ("Error code: 400 - {'error': {'message': \"Unsupported value: "
                    f"'reasoning_effort' does not support '{self.value}' with this "
                    "model. Supported values are: 'none', 'low', 'medium', 'high', "
                    "and 'xhigh'.\", 'param': 'reasoning_effort'}}")

    def create(**kwargs):
        effort = kwargs.get("reasoning_effort")
        tried.append(effort)
        if effort in refuse:
            raise Rejected(effort)
        return SimpleNamespace(
            usage=SimpleNamespace(prompt_tokens=3, completion_tokens=1),
            choices=[SimpleNamespace(finish_reason="stop",
                                     message=SimpleNamespace(content="ok"))])

    class FakeClient:
        def __init__(self, api_key=None, base_url=None):
            self.chat = SimpleNamespace(completions=SimpleNamespace(create=create))

    monkeypatch.setattr(openai, "OpenAI", FakeClient)


def test_openai_reasoning_effort_probes_supported_value(monkeypatch):
    """Newer GPT-5.x models refuse 'minimal' and want 'none'. The rejected word
    must not sink the call, and the working one is remembered so the next call
    goes straight through."""
    from app.services.llm import providers

    providers._EFFORT_MEMO.clear()
    tried: list = []
    _fake_openai(monkeypatch, refuse={"minimal"}, tried=tried)

    provider = providers.OpenAICompatibleProvider(api_key="k", model="gpt-5.6-terra")
    assert provider.test_connection().text == "ok"
    assert tried == ["minimal", "none"]

    tried.clear()
    providers.OpenAICompatibleProvider(api_key="k", model="gpt-5.6-terra").generate(
        [{"role": "user", "content": "hi"}])
    assert tried == ["none"]  # memorised, no second probe


def test_openai_reasoning_effort_dropped_when_unsupported(monkeypatch):
    """A model that takes no reasoning_effort at all still answers: the ladder
    ends by sending no parameter."""
    from app.services.llm import providers

    providers._EFFORT_MEMO.clear()
    tried: list = []
    _fake_openai(monkeypatch, refuse={"minimal", "none", "low"}, tried=tried)

    provider = providers.OpenAICompatibleProvider(api_key="k", model="gpt-5-oddball")
    assert provider.test_connection().text == "ok"
    assert tried[-1] is None


def test_openai_other_errors_are_not_retried(monkeypatch):
    """An error that is not about reasoning_effort (bad key, no credit) surfaces
    at once instead of being probed against every effort value."""
    import openai

    from app.services.llm import providers

    providers._EFFORT_MEMO.clear()
    calls = []

    def create(**kwargs):
        calls.append(kwargs.get("reasoning_effort"))
        raise openai.OpenAIError("Error code: 401 - invalid api key")

    class FakeClient:
        def __init__(self, api_key=None, base_url=None):
            from types import SimpleNamespace
            self.chat = SimpleNamespace(completions=SimpleNamespace(create=create))

    monkeypatch.setattr(openai, "OpenAI", FakeClient)
    with pytest.raises(LLMError, match="401"):
        providers.OpenAICompatibleProvider(
            api_key="k", model="gpt-5").test_connection()
    assert len(calls) == 1


def test_pricing_cost_and_fallback():
    """Cost math is linear in tokens; unknown models fall back per provider,
    and a tiny cost never rounds down to $0.00 in the label."""
    from app.services.llm import pricing

    # known model: 1M in + 1M out at claude-opus-4-8 rates ($5 + $25)
    assert pricing.cost_usd("anthropic", "claude-opus-4-8",
                            1_000_000, 1_000_000) == 30.0
    # unknown model -> provider fallback (anthropic 4/20)
    assert pricing.cost_usd("anthropic", "mystery-model",
                            1_000_000, 0) == 4.0
    # unknown provider -> generic default, never crashes
    assert pricing.cost_usd("", "", 1000, 1000) > 0
    # a sub-cent cost keeps 4 decimals instead of collapsing to $0.00
    small = pricing.cost_usd("anthropic", "claude-haiku-4-5", 500, 200)
    assert pricing.format_usd(small).startswith("$0.00")
    assert pricing.format_usd(0) == "$0.00"

    breakdown = pricing.cost_breakdown("openai", "gpt-5", 2000, 500)
    assert breakdown["tokens_in"] == 2000 and breakdown["cost_usd"] > 0
    assert breakdown["cost_label"].startswith("$")


def test_generate_json_names_the_output_cap_when_the_answer_is_cut_off():
    """A reply stopped at max_tokens is reported as such, not as bad JSON."""
    import pytest
    from dataclasses import dataclass
    from app.services.llm.base import LLMError, LLMProvider, LLMResult

    @dataclass
    class CutOff(LLMProvider):
        def generate(self, messages, system=None, max_tokens=4096):
            return LLMResult(text='{"title": "Stress, charge et', tokens_output=max_tokens,
                             truncated=True)

    @dataclass
    class Garbled(LLMProvider):
        def generate(self, messages, system=None, max_tokens=4096):
            return LLMResult(text='{"title": "Stress, charge et', truncated=False)

    with pytest.raises(LLMError, match="cut off at the output cap"):
        CutOff(api_key="k", model="m").generate_json(
            [{"role": "user", "content": "x"}], json_schema={"type": "object"},
            max_tokens=100)
    with pytest.raises(LLMError, match="did not return valid JSON"):
        Garbled(api_key="k", model="m").generate_json(
            [{"role": "user", "content": "x"}], json_schema={"type": "object"})
