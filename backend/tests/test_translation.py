from types import SimpleNamespace

import pytest

from tests.test_fulltext import project_with_records  # noqa: F401 — fixture

SPANISH = ("Este estudio evalúa el efecto de los juegos serios sobre el "
           "aprendizaje de los estudiantes de enfermería en un ensayo "
           "controlado con 120 participantes durante dos semestres.")


@pytest.fixture
def fake_llm(monkeypatch):
    calls = []

    class FakeProvider:
        name, model = "anthropic", "claude-test"

        def generate_json(self, messages, json_schema, system=None,
                          max_tokens=4096):
            calls.append({"system": system, "prompt": messages[0]["content"]})
            return SimpleNamespace(
                text="", tokens_input=10, tokens_output=10,
                data={"source_language": "es", "same_language": False,
                      "title": "Titre traduit", "abstract": "Résumé traduit."})

    monkeypatch.setattr("app.services.translation.open_provider_chain",
                        lambda *a, **kw: FakeProvider())
    return calls


def _first_record(client, pid):
    return client.get(f"/api/projects/{pid}/records").json()["items"][0]["id"]


def test_language_heuristic():
    from app.services.translation import already_in
    english = ("The aim of this study was to assess the effect of serious "
               "games on the learning of nursing students in a trial that "
               "was conducted with 120 participants.")
    french = ("Cette étude évalue l'effet des jeux sérieux sur l'apprentissage "
              "des étudiants en soins infirmiers dans un essai contrôlé mené "
              "avec 120 participants pendant deux semestres.")
    assert already_in(english, "en") and not already_in(english, "fr")
    assert already_in(french, "fr") and not already_in(french, "en")
    # neither target language, or too short to tell: the model decides
    assert not already_in(SPANISH, "en") and not already_in(SPANISH, "fr")
    assert not already_in("Serious games", "en")


def test_translate_caches_and_follows_abstract_edits(
        user_client, project_with_records, fake_llm):  # noqa: F811
    pid = project_with_records["id"]
    rid = _first_record(user_client, pid)
    user_client.put(f"/api/projects/{pid}/records/{rid}/abstract",
                    json={"abstract": SPANISH})

    r = user_client.post(f"/api/projects/{pid}/records/{rid}/translate",
                         json={"lang": "fr"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["abstract"] == "Résumé traduit."
    assert (body["source_language"], body["same_language"]) == ("es", False)
    assert body["model"] == "claude-test"
    assert "French" in fake_llm[0]["system"] and SPANISH in fake_llm[0]["prompt"]

    # second request: the team's cached entry, no new AI call
    user_client.post(f"/api/projects/{pid}/records/{rid}/translate",
                     json={"lang": "fr"})
    assert len(fake_llm) == 1
    # the abstract itself is untouched, and the queue carries the translation
    from app.core.db import SessionLocal
    from app.models import Record
    from app.services.translation import valid_translations
    with SessionLocal() as db:
        record = db.get(Record, rid)
        assert record.abstract == SPANISH
        assert valid_translations(record)["fr"]["title"] == "Titre traduit"

    # editing the abstract orphans the translation: it is redone on request
    user_client.put(f"/api/projects/{pid}/records/{rid}/abstract",
                    json={"abstract": SPANISH + " Texto añadido."})
    with SessionLocal() as db:
        assert valid_translations(db.get(Record, rid)) == {}
    user_client.post(f"/api/projects/{pid}/records/{rid}/translate",
                     json={"lang": "fr"})
    assert len(fake_llm) == 2


def test_text_already_in_target_language_costs_no_call(
        user_client, project_with_records, fake_llm):  # noqa: F811
    pid = project_with_records["id"]
    rid = _first_record(user_client, pid)
    user_client.put(f"/api/projects/{pid}/records/{rid}/abstract", json={
        "abstract": "The aim of this study was to assess the effect of "
                    "serious games on the learning of nursing students in a "
                    "trial that was conducted with 120 participants."})
    body = user_client.post(f"/api/projects/{pid}/records/{rid}/translate",
                            json={"lang": "en"}).json()
    assert body["same_language"] is True and body["abstract"] == ""
    assert fake_llm == []


def test_translate_needs_membership_key_and_known_language(
        user_client, project_with_records):  # noqa: F811
    from fastapi.testclient import TestClient

    from app.main import app
    pid = project_with_records["id"]
    rid = _first_record(user_client, pid)
    url = f"/api/projects/{pid}/records/{rid}/translate"
    assert user_client.post(url, json={"lang": "de"}).status_code == 422
    user_client.put(f"/api/projects/{pid}/records/{rid}/abstract",
                    json={"abstract": SPANISH})
    # no AI key configured on this instance
    r = user_client.post(url, json={"lang": "fr"})
    assert r.status_code == 400 and "API key" in r.json()["detail"]

    other = TestClient(app)
    other.post("/api/auth/register", json={
        "email": "stranger@example.com", "password": "password123",
        "display_name": "Stranger"})
    assert other.post(url, json={"lang": "fr"}).status_code in (403, 404)
