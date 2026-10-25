"""AI prompt transparency (M2): registry listing, override, reset, resolution,
and the scope rules (member reads, project admin writes)."""
from app.core.db import SessionLocal
from app.services.llm.prompts import PROMPTS, resolve_prompt


def _project(client) -> int:
    return client.post("/api/projects",
                       json={"name": "P", "description": ""}).json()["id"]


def test_list_prompts_exposes_all_features(user_client):
    pid = _project(user_client)
    r = user_client.get(f"/api/projects/{pid}/prompts")
    assert r.status_code == 200
    rows = r.json()
    assert {row["key"] for row in rows} == set(PROMPTS)
    for row in rows:
        assert row["override_text"] is None
        assert row["effective_text"] == row["default_text"]


def test_override_and_reset(user_client):
    pid = _project(user_client)
    key = "screening_ta_suggest"
    r = user_client.put(f"/api/projects/{pid}/prompts/{key}",
                        json={"text": "Custom instructions."})
    assert r.status_code == 200
    assert r.json()["override_text"] == "Custom instructions."

    # the services resolve the override for this project, default elsewhere
    with SessionLocal() as db:
        assert resolve_prompt(db, pid, key) == "Custom instructions."
        assert resolve_prompt(db, pid + 999, key) == PROMPTS[key].text

    r = user_client.delete(f"/api/projects/{pid}/prompts/{key}")
    assert r.status_code == 200
    assert r.json()["override_text"] is None
    with SessionLocal() as db:
        assert resolve_prompt(db, pid, key) == PROMPTS[key].text


def test_unknown_feature_404(user_client):
    pid = _project(user_client)
    r = user_client.put(f"/api/projects/{pid}/prompts/nope",
                        json={"text": "x"})
    assert r.status_code == 404


def test_reviewer_reads_but_cannot_write(user_client, client):
    pid = _project(user_client)
    user_client.post(f"/api/projects/{pid}/members",
                     json={"email": "rev@example.com", "role": "reviewer"})
    # claim the awaiting account and switch the session to the reviewer
    client.post("/api/auth/register", json={
        "email": "rev@example.com", "password": "password123",
        "display_name": "Rev"})
    assert client.get(f"/api/projects/{pid}/prompts").status_code == 200
    r = client.put(f"/api/projects/{pid}/prompts/screening_ta_suggest",
                   json={"text": "hijack"})
    assert r.status_code == 403
