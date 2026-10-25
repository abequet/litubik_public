"""Reporting: the AI-use journal, the audit dossier, and the two
generated write-ups (Methods paragraph, DAISY-style AI disclosure).

The provider is faked at the credentials layer, not at the feature layer, so
every call still goes through the logging chain — that is the point of the
journal and it must be exercised, not stubbed out.
"""
import time

import pytest

from app.services.llm.base import LLMResult

RIS = """TY  - JOUR
TI  - Gamified speed feedback for young drivers
AU  - Author, A.
PY  - 2021
DO  - 10.1/rep.1
AB  - Abstract of the study.
ER  -
"""


class FakeProvider:
    """Records what it was asked, so a test can assert on the prompt.

    Prose by default; a JSON object when the caller asked for a schema (the
    non-reporting features all go through generate_json)."""
    name = "anthropic"
    model = "claude-fake"
    last_system = ""

    def __init__(self, text="Generated text."):
        self.text = text
        self.json_text = '{"keywords": ["speed", "velocity"]}'

    def generate(self, messages, system=None, max_tokens=4096):
        FakeProvider.last_system = system or ""
        wants_json = bool(system) and "JSON Schema" in system
        return LLMResult(text=self.json_text if wants_json else self.text,
                         tokens_input=120, tokens_output=60)


def _await_job(client, job_id):
    for _ in range(100):
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in ("done", "failed"):
            return job
        time.sleep(0.05)
    raise AssertionError("job never finished")


@pytest.fixture
def fake_llm(monkeypatch):
    """Patch the provider factory: the credential ranking, the fallback chain
    and the usage logger all still run."""
    provider = FakeProvider()
    monkeypatch.setattr("app.services.llm.credentials.get_provider",
                        lambda *a, **kw: provider)
    return provider


@pytest.fixture
def project(user_client):
    """A project with a validated protocol and one imported record — enough
    for the Methods paragraph to have something to describe."""
    pid = user_client.post("/api/projects", json={"name": "M11 demo"}).json()["id"]
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
            {"code": "I1", "type": "include", "label": "adults",
             "description": ""},
            {"code": "E1", "type": "exclude", "label": "wrong population",
             "description": ""}]})
    user_client.post(f"/api/projects/{pid}/protocols/{prot['id']}/validate")
    user_client.put("/api/llm/credentials", json={
        "provider": "anthropic", "api_key": "sk-ant-fake-key-123"})
    return pid


# ---- the audit dossier --------------------------------------------------------------

def test_dossier_reads_the_pipeline(user_client, project):
    data = user_client.get(f"/api/projects/{project}/reporting/dossier").json()

    assert data["tool"]["name"] == "LitUbik" and data["tool"]["version"]
    assert data["protocol"]["validated"] is True
    assert data["protocol"]["n_include"] == 1
    assert data["protocol"]["n_exclude"] == 1
    assert data["dedup"]["n_records"] == 1 and data["dedup"]["n_unique"] == 1
    assert "rapidfuzz" in data["dedup"]["method"]
    assert [i["source"] for i in data["search"]["imports"]] == ["pubmed"]
    assert data["prisma"]["n_databases"] == 1


def test_dossier_of_an_empty_project(user_client):
    pid = user_client.post("/api/projects", json={"name": "empty"}).json()["id"]
    data = user_client.get(f"/api/projects/{pid}/reporting/dossier").json()
    assert data["protocol"] == {"imported": False}
    assert data["search"]["imports"] == []
    assert data["snowballing"]["n_iterations"] == 0


# ---- the AI-use journal -------------------------------------------------------------

def test_journal_records_every_call_and_aggregates_per_day(
        user_client, project, fake_llm):
    base = f"/api/projects/{project}/reporting"
    assert user_client.get(f"{base}/ai-usage").json()["any_ai_used"] is False

    user_client.post(f"{base}/methods/generate", json={"lang": "en"})
    user_client.post(f"{base}/methods/generate", json={"lang": "en"})

    data = user_client.get(f"{base}/ai-usage").json()
    assert data["any_ai_used"] is True
    assert [u["feature"] for u in data["usage"]] == ["reporting_methods"]
    entry = data["usage"][0]
    # both calls folded into one (feature, model, author, day) bucket
    assert entry["n_calls"] == 2
    assert entry["tokens_in"] == 240 and entry["tokens_out"] == 120
    assert entry["models"] == [{"model": "anthropic:claude-fake", "n_calls": 2}]
    assert entry["users"] == ["Admin"]
    assert entry["activity"] == "reporting"
    assert data["totals"]["n_calls"] == 2


def test_journal_covers_a_pipeline_feature_not_only_reporting(
        user_client, project, fake_llm):
    """A keyword suggestion leaves no trace of its own once the reviewer edits
    the list — the journal is the only record that it happened."""
    pid = project
    user_client.post(f"/api/projects/{pid}/concepts",
                     json={"name": "driving", "keywords": ["driving"]})
    cid = user_client.get(f"/api/projects/{pid}/concepts").json()[0]["id"]
    r = user_client.post(f"/api/projects/{pid}/concepts/{cid}/suggest")
    assert r.status_code == 200

    usage = user_client.get(f"/api/projects/{pid}/reporting/ai-usage").json()
    features = {u["feature"]: u for u in usage["usage"]}
    assert features["concepts_suggest"]["n_calls"] == 1
    assert features["concepts_suggest"]["activity"] == "search"
    # the pre-filled form picks it up as search-strategy support
    search = next(a for a in usage["form"]["activities"] if a["key"] == "search")
    assert search["level"] == "low" and search["n_calls"] == 1


def test_form_is_prefilled_from_the_journal(user_client, project, fake_llm):
    base = f"/api/projects/{project}/reporting"
    form = user_client.get(f"{base}/ai-usage").json()["form"]

    assert [a["key"] for a in form["activities"]] == [
        "protocol", "search", "screening", "appraisal", "extraction",
        "synthesis", "reporting"]
    # nothing used yet -> everything at 'none', and the scope is stated
    assert {a["level"] for a in form["activities"]} == {"none"}
    assert "not cover the writing of the manuscript" in form["scope_note"]
    assert form["safeguards"] == ""   # author-declared, never guessed


def test_journal_gap_is_flagged_not_hidden(user_client, project):
    """AI that ran before the journal existed leaves outputs but no journal rows: the app must
    say so instead of letting the statement claim no AI was used."""
    from app.core.db import SessionLocal
    from app.models import Record, Vote

    with SessionLocal() as db:
        record = db.query(Record).filter_by(project_id=project).first()
        db.add(Vote(project_id=project, record_id=record.id, stage="ta",
                    round=1, voter_user_id=None, is_ai=True,
                    decision="exclude"))
        db.commit()

    data = user_client.get(f"/api/projects/{project}/reporting/ai-usage").json()
    assert data["any_ai_used"] is False          # journal is empty…
    assert data["journal"]["incomplete"] is True  # …but AI output exists


# ---- generation ---------------------------------------------------------------------

def test_methods_generation_is_grounded_in_the_dossier(
        user_client, project, fake_llm):
    base = f"/api/projects/{project}/reporting"
    assert user_client.get(f"{base}/sections").json()["methods"] is None

    est = user_client.get(f"{base}/methods/estimate").json()["cost"]
    assert est["estimated"] is True and est["tokens_in"] > 0

    out = user_client.post(f"{base}/methods/generate", json={"lang": "fr"}).json()
    assert out["content_md"] == "Generated text."
    assert out["lang"] == "fr"
    assert out["cost"]["tokens_in"] == 120
    assert out["generated_by_name"] == "Admin"

    system = FakeProvider.last_system
    assert "Methods section" in system
    assert "in French" in system            # the language selector reaches it
    assert "\"name\":\"LitUbik\"" in system  # the audit trail is the input
    assert "pubmed" in system

    stored = user_client.get(f"{base}/sections").json()["methods"]
    assert stored["content_md"] == "Generated text."


def test_methods_needs_something_to_describe(user_client, fake_llm):
    pid = user_client.post("/api/projects", json={"name": "empty"}).json()["id"]
    user_client.put("/api/llm/credentials", json={
        "provider": "anthropic", "api_key": "sk-ant-fake-key-123"})
    r = user_client.post(f"/api/projects/{pid}/reporting/methods/generate",
                         json={"lang": "en"})
    assert r.status_code == 400
    assert "import your search results" in r.json()["detail"].lower()
    # …and the estimate stays silent rather than pricing an impossible call
    assert user_client.get(
        f"/api/projects/{pid}/reporting/methods/estimate").json()["cost"] is None


def test_disclosure_uses_the_authors_corrected_form(user_client, project,
                                                    fake_llm):
    base = f"/api/projects/{project}/reporting"
    form = user_client.get(f"{base}/ai-usage").json()["form"]
    # the author disagrees with the pre-filled answer and says so
    screening = next(a for a in form["activities"] if a["key"] == "screening")
    screening["level"] = "medium"
    screening["note"] = "used on the ambiguous abstracts only"
    form["safeguards"] = "training opt-out enabled"

    out = user_client.post(f"{base}/ai_disclosure/generate",
                           json={"lang": "en", "form": form}).json()

    system = FakeProvider.last_system
    assert "used on the ambiguous abstracts only" in system
    assert "training opt-out enabled" in system
    assert "disclosure statement" in system
    # the form is stored with the statement: it is what the text was written from
    assert out["form"]["safeguards"] == "training opt-out enabled"
    assert user_client.get(f"{base}/sections").json()["ai_disclosure"]["form"][
        "activities"][2]["level"] == "medium"


def test_disclosure_without_any_ai_use(user_client, project, fake_llm):
    """A review that used no AI still owes a statement saying so."""
    base = f"/api/projects/{project}/reporting"
    out = user_client.post(f"{base}/ai_disclosure/generate",
                           json={"lang": "en"}).json()
    assert out["content_md"] == "Generated text."
    assert "\"any_ai_used\":false" in FakeProvider.last_system.replace(" ", "")


def test_edited_version_survives_regeneration(user_client, project, fake_llm):
    base = f"/api/projects/{project}/reporting"
    user_client.post(f"{base}/methods/generate", json={"lang": "en"})
    user_client.put(f"{base}/methods", json={"edited_md": "My own wording."})

    fake_llm.text = "Regenerated text."
    out = user_client.post(f"{base}/methods/generate", json={"lang": "en"}).json()
    assert out["content_md"] == "Regenerated text."
    assert out["edited_md"] == "My own wording."


def test_unknown_section_kind_is_404(user_client, project):
    r = user_client.post(f"/api/projects/{project}/reporting/whatever/generate",
                         json={"lang": "en"})
    assert r.status_code == 404


def test_reporting_stage_completes_the_pipeline(user_client, project, fake_llm):
    base = f"/api/projects/{project}/reporting"
    assert "reporting" not in user_client.get(
        f"/api/projects/{project}/progress").json()["done"]

    user_client.post(f"{base}/methods/generate", json={"lang": "en"})
    assert "reporting" not in user_client.get(
        f"/api/projects/{project}/progress").json()["done"]

    user_client.post(f"{base}/ai_disclosure/generate", json={"lang": "en"})
    assert "reporting" in user_client.get(
        f"/api/projects/{project}/progress").json()["done"]


def test_generation_needs_a_key(user_client):
    """No credential configured: the app must refuse before reaching a
    provider, not fail on an authentication error."""
    pid = user_client.post("/api/projects", json={"name": "keyless"}).json()["id"]
    user_client.post(f"/api/projects/{pid}/imports/upload",
                     files={"file": ("s.ris", RIS.encode(), "text/plain")},
                     data={"source_name": "pubmed", "source_type": "database"})
    r = user_client.post(f"/api/projects/{pid}/reporting/methods/generate",
                         json={"lang": "en"})
    assert r.status_code == 400
    assert "API key" in r.json()["detail"]


def test_dossier_carries_what_the_methods_template_needs(user_client, project):
    """The Methods section reports criteria as a Criterion/Description table,
    quotes each database query verbatim as it was run, and gives the conflict
    count of every screening phase — so the dossier must carry all three."""
    from app.core.db import SessionLocal
    from app.models import Conflict, Equation, Record, ScreeningConfig

    with SessionLocal() as db:
        db.add(Equation(
            project_id=project, label="broad", status="frozen",
            structure={"concepts": [{"name": "driving",
                                     "keywords": ["driving", "driver"]}]},
            # a reviewer hand-edited the PubMed query: that is what ran
            translations={"auto": {"pubmed": "AUTO QUERY",
                                   "openalex": "OA QUERY"},
                          "overrides": {"pubmed": "EDITED QUERY"}}))
        cfg = ScreeningConfig(project_id=project, stage="ta", round=1,
                              reviewer_ids=[1], status="active")
        db.add(cfg)
        record = db.query(Record).filter_by(project_id=project).first()
        db.add(Conflict(project_id=project, record_id=record.id, stage="ta",
                        round=1, status="resolved", resolution="exclude"))
        db.commit()

    data = user_client.get(f"/api/projects/{project}/reporting/dossier").json()

    criterion = data["protocol"]["criteria"][0]
    assert criterion["code"] == "I1" and "description" in criterion

    equation = data["search"]["equations"][0]
    assert equation["queries_per_database"] == {"pubmed": "EDITED QUERY",
                                                "openalex": "OA QUERY"}
    assert equation["hand_edited_queries"] == ["pubmed"]

    phase = data["screening"]["ta"][0]
    assert phase["conflicts"] == {"resolved": 1, "still_open": 0}
    assert phase["n_excluded_by_validated_ai_triage"] == 0


def test_french_methods_get_the_terminology_not_a_literal_translation(
        user_client, project, fake_llm):
    user_client.post(f"/api/projects/{project}/reporting/methods/generate",
                     json={"lang": "fr"})
    system = FakeProvider.last_system
    assert "in French" in system
    assert "[À COMPLÉTER" in system              # localized gap marker
    assert "snowballing arrière/avant" in system  # glossary travels with it


def test_methods_prompt_forbids_inventing_and_asks_for_gaps(
        user_client, project, fake_llm):
    user_client.post(f"/api/projects/{project}/reporting/methods/generate",
                     json={"lang": "en"})
    system = FakeProvider.last_system
    assert "[TO COMPLETE:" in system
    assert "Landis & Koch" in system     # every kappa carries its band
    assert "verbatim" in system          # equations quoted as run
    assert "PRISMA 2020" in system


def test_a_budget_exhausted_call_is_retried_with_a_wider_one(
        user_client, project, monkeypatch):
    """A reasoning model can burn the whole output budget on hidden reasoning
    and return nothing. The user cannot raise max_tokens from the interface, so
    the retry has to happen here."""
    from app.services.llm.base import LLMError

    class BudgetHungryProvider:
        name = "openai"
        model = "gpt-fake"

        def __init__(self):
            self.budgets = []

        def generate(self, messages, system=None, max_tokens=4096):
            self.budgets.append(max_tokens)
            if len(self.budgets) == 1:
                raise LLMError("Model returned no text (finish_reason=length, "
                               "8000 completion tokens used)")
            return LLMResult(text="Methods.", tokens_input=100,
                             tokens_output=2000)

    provider = BudgetHungryProvider()
    monkeypatch.setattr("app.services.llm.credentials.get_provider",
                        lambda *a, **kw: provider)

    out = user_client.post(
        f"/api/projects/{project}/reporting/methods/generate",
        json={"lang": "en"}).json()
    assert out["content_md"] == "Methods."
    assert provider.budgets == [8000, 16000]


def test_a_real_failure_is_not_retried(user_client, project, monkeypatch):
    """Only the output cap earns a second (billable) attempt — an invalid key
    must surface immediately."""
    from app.services.llm.base import LLMError

    calls = []

    class BrokenProvider:
        name = "openai"
        model = "gpt-fake"

        def generate(self, messages, system=None, max_tokens=4096):
            calls.append(max_tokens)
            raise LLMError("authentication_error: invalid api key")

    monkeypatch.setattr("app.services.llm.credentials.get_provider",
                        lambda *a, **kw: BrokenProvider())
    r = user_client.post(f"/api/projects/{project}/reporting/methods/generate",
                         json={"lang": "en"})
    assert r.status_code == 400
    assert len(calls) == 1
