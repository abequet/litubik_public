"""Where the project's review framing reaches the AI, and where it must not.

The shipped instruction blocks speak PICO; the framing is appended after them
so a project can be re-framed without rewriting (or diverging from) any prompt
the user may have overridden. It is injected only where the framework actually
changes the answer — never in the per-record screening prompts, which judge
coded I*/E* criteria and are the highest-volume calls in the app.
"""
import pytest

from app.services.llm.base import LLMResult


class FakeProvider:
    name = "anthropic"
    model = "claude-fake"
    last_system = ""

    def generate(self, messages, system=None, max_tokens=4096):
        FakeProvider.last_system = system or ""
        return LLMResult(text="{}", tokens_input=10, tokens_output=5)

    def generate_json(self, messages, json_schema, system=None, max_tokens=4096):
        FakeProvider.last_system = system or ""
        return LLMResult(text="{}", data={
            "research_question": "Q?",
            "concepts": [{"name": "Sample", "keywords": ["ambulance"]}],
            "keywords": ["ambulance", "paramedic"],
            "columns": [{"name": "Country", "col_type": "text"}],
        }, tokens_input=10, tokens_output=5)


@pytest.fixture
def fake_llm(monkeypatch):
    provider = FakeProvider()
    FakeProvider.last_system = ""
    monkeypatch.setattr("app.services.llm.credentials.get_provider",
                        lambda *a, **kw: provider)
    return provider


@pytest.fixture
def spider_project(user_client):
    """A project framed as a best fit framework synthesis on SPIDER, with a
    validated protocol so the AI features have their context pack."""
    pid = user_client.post("/api/projects", json={"name": "Review"}).json()["id"]
    r = user_client.put(f"/api/projects/{pid}", json={
        "review_type": "best_fit", "question_framework": "spider"})
    assert r.status_code == 200, r.text
    user_client.post(f"/api/projects/{pid}/protocols/upload",
                     files={"file": ("p.md", b"# P\n\nProtocol text", "text/markdown")})
    prot = user_client.get(f"/api/projects/{pid}/protocols").json()[0]
    user_client.put(f"/api/projects/{pid}/protocols/{prot['id']}", json={
        "protocol_md": "# P\n\n## Criteria",
        "criteria": [{"code": "I1", "type": "include", "label": "topic",
                      "description": "on topic"}]})
    user_client.post(f"/api/projects/{pid}/protocols/{prot['id']}/validate")
    user_client.put("/api/llm/credentials", json={
        "provider": "anthropic", "api_key": "sk-ant-fake-key-123"})
    return pid


def test_the_project_stores_and_returns_its_framing(user_client):
    pid = user_client.post("/api/projects", json={"name": "P"}).json()["id"]
    # a fresh project is a plain systematic review on PICOS
    listed = user_client.get("/api/projects").json()[0]
    assert (listed["review_type"], listed["question_framework"]) == \
        ("systematic", "picos")

    r = user_client.put(f"/api/projects/{pid}", json={
        "review_type": "best_fit", "question_framework": "spider"})
    assert r.json()["question_framework"] == "spider"
    assert user_client.get("/api/projects").json()[0]["review_type"] == "best_fit"


def test_an_unknown_framing_is_rejected(user_client):
    pid = user_client.post("/api/projects", json={"name": "P"}).json()["id"]
    assert user_client.put(f"/api/projects/{pid}",
                           json={"review_type": "nawak"}).status_code == 400
    assert user_client.put(f"/api/projects/{pid}",
                           json={"question_framework": "nawak"}).status_code == 400


def test_concepts_propose_is_told_the_framing(user_client, spider_project, fake_llm):
    r = user_client.post(f"/api/projects/{spider_project}/concepts/propose")
    assert r.status_code == 200, r.text
    system = FakeProvider.last_system
    assert "SPIDER" in system
    assert "Phenomenon of interest" in system
    assert "Carroll & Booth, 2013" in system


def test_keyword_suggestion_is_told_the_framing(user_client, spider_project,
                                                fake_llm):
    cid = user_client.post(f"/api/projects/{spider_project}/concepts",
                           json={"name": "Sample"}).json()["id"]
    r = user_client.post(
        f"/api/projects/{spider_project}/concepts/{cid}/suggest")
    assert r.status_code == 200, r.text
    assert "SPIDER" in FakeProvider.last_system


def test_extraction_column_suggestion_is_told_the_framing(
        user_client, spider_project, fake_llm):
    r = user_client.post(
        f"/api/projects/{spider_project}/extraction/columns/suggest")
    assert r.status_code == 200, r.text
    assert "SPIDER" in FakeProvider.last_system


def test_the_template_endpoint_follows_the_review_type(user_client,
                                                       spider_project):
    """No body = the template of the project's review type. For a plain
    systematic review that is the historical evidence table, so callers that
    never passed one keep their behaviour."""
    r = user_client.post(
        f"/api/projects/{spider_project}/extraction/columns/template")
    assert r.status_code == 200, r.text
    assert r.json()["template"] == "best_fit"
    names = {c["name"] for c in user_client.get(
        f"/api/projects/{spider_project}/extraction/columns").json()}
    assert "A priori framework theme(s)" in names
    assert "New (emergent) theme" in names
    assert "Comparator" not in names  # this review has no comparator


def test_a_template_can_be_picked_explicitly(user_client):
    pid = user_client.post("/api/projects", json={"name": "P"}).json()["id"]
    listed = user_client.get(
        f"/api/projects/{pid}/extraction/columns/templates").json()
    assert {t["key"] for t in listed} >= {"evidence_pico", "best_fit"}
    assert [t["key"] for t in listed if t["is_default"]] == ["evidence_pico"]

    r = user_client.post(f"/api/projects/{pid}/extraction/columns/template",
                         json={"template": "evidence_qualitative"})
    assert r.json()["template"] == "evidence_qualitative"
    names = {c["name"] for c in user_client.get(
        f"/api/projects/{pid}/extraction/columns").json()}
    assert "Phenomenon of interest" in names

    assert user_client.post(
        f"/api/projects/{pid}/extraction/columns/template",
        json={"template": "nawak"}).status_code == 400


def test_the_dossier_carries_the_framing_to_the_methods_draft(user_client,
                                                              spider_project):
    from app.core.db import SessionLocal
    from app.services.reporting import audit

    with SessionLocal() as db:
        dossier = audit.review_dossier(db, spider_project)
    assert dossier["framing"]["review_type"] == "best_fit"
    assert dossier["framing"]["question_framework"] == "SPIDER"
    assert "Carroll" in dossier["framing"]["synthesis_method"]
    assert "Popay" not in dossier["framing"]["synthesis_method"]
    # the honest note travels with the numbers, so the draft cannot claim the
    # software did the framework coding
    assert dossier["framing"]["tooling_note"]
    # PRISMA still applies to the selection of a best fit framework synthesis
    assert dossier["reporting_guidelines"] == "PRISMA 2020"
    assert "systematic review pipeline" not in dossier["tool"]["description"]


def test_the_methods_prompt_no_longer_hard_codes_a_synthesis_method():
    """It once cited `framing.synthesis_method` verbatim — a method typical of
    the review *type*, not a record of what the team did. The synthesis stage
    replaced that with a declaration, so the prompt now branches on whether one
    exists and marks a gap when it does not."""
    from app.services.llm.prompts import default_text
    text = default_text("reporting_methods")
    assert "Popay" not in text
    assert "`synthesis` block" in text
    # the distinction that keeps a default from being attributed to the authors
    assert "`declared` false" in text
    assert "do not attribute it to the authors" in text
    assert "tooling_note" in text


def test_the_shipped_prompts_no_longer_speak_pico():
    """The framing block is appended *after* the instruction text, so the
    instruction text must not contradict it."""
    from app.services.llm.prompts import PROMPTS
    for spec in PROMPTS.values():
        assert "PICO" not in spec.text, spec.key
