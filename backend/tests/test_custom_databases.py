"""Databases a project declares by hand: CRUD, slugging, their query in the
equation translations, and their presence everywhere a database is listed."""
import pytest

RIS = """TY  - JOUR
TI  - A declared-source paper
AU  - Doe, J.
PY  - 2021
DO  - 10.5/custom.1
ER  -
"""


@pytest.fixture
def project(user_client):
    return user_client.post("/api/projects", json={"name": "custom db"}).json()


@pytest.fixture
def equation(user_client, project):
    pid = project["id"]
    cid = user_client.post(f"/api/projects/{pid}/concepts",
                           json={"name": "Intervention",
                                 "keywords": ["gamification", "serious game"]}
                           ).json()["id"]
    return user_client.post(f"/api/projects/{pid}/equations", json={
        "label": "v1", "concept_ids": [cid],
        "params": {"year_from": 2015, "year_to": 2024}}).json()


def test_declare_edit_and_remove(user_client, project):
    pid = project["id"]
    assert user_client.get(f"/api/projects/{pid}/custom-databases").json() == []

    r = user_client.post(f"/api/projects/{pid}/custom-databases", json={
        "label": "Cairn.info", "syntax": "generic",
        "url": "https://www.cairn.info", "instructions": "Recherche avancée."})
    assert r.status_code == 200
    entry = r.json()
    assert entry["db_id"] == "cairn-info" and entry["n_imports"] == 0

    # same name twice is refused; the slug never collides with a built-in id
    assert user_client.post(f"/api/projects/{pid}/custom-databases",
                            json={"label": "cairn.INFO"}).status_code == 400
    assert user_client.post(f"/api/projects/{pid}/custom-databases",
                            json={"label": "PubMed"}).json()["db_id"] == "pubmed-2"

    r = user_client.put(f"/api/projects/{pid}/custom-databases/{entry['id']}",
                        json={"label": "Cairn", "syntax": "wos", "url": "",
                              "instructions": ""})
    assert r.status_code == 200
    # renaming keeps the slug: imports already traced under it must still match
    assert r.json()["db_id"] == "cairn-info" and r.json()["syntax"] == "wos"

    assert user_client.delete(
        f"/api/projects/{pid}/custom-databases/{entry['id']}").status_code == 200
    assert [c["label"] for c in
            user_client.get(f"/api/projects/{pid}/custom-databases").json()] == ["PubMed"]


def test_bad_input_is_rejected(user_client, project):
    pid = project["id"]
    assert user_client.post(f"/api/projects/{pid}/custom-databases",
                            json={"label": "A"}).status_code == 422
    assert user_client.post(f"/api/projects/{pid}/custom-databases",
                            json={"label": "Portal", "url": "javascript:alert(1)"}
                            ).status_code == 400
    # an unknown syntax silently falls back on the generic boolean string
    r = user_client.post(f"/api/projects/{pid}/custom-databases",
                         json={"label": "Portal", "syntax": "nope"})
    assert r.json()["syntax"] == "generic"


def test_declared_database_gets_a_query_on_every_equation(
        user_client, project, equation):
    pid = project["id"]
    # declared after the equation exists → the translation is backfilled
    cdb = user_client.post(f"/api/projects/{pid}/custom-databases",
                           json={"label": "TRID", "syntax": "generic"}).json()
    eq = user_client.get(f"/api/projects/{pid}/equations").json()[0]
    query = eq["translations"]["auto"][cdb["db_id"]]
    assert '"serious game"' in query and " AND " not in query.split(")")[0]

    # switching syntax rewrites it in the borrowed language
    user_client.put(f"/api/projects/{pid}/custom-databases/{cdb['id']}",
                    json={"label": "TRID", "syntax": "scopus"})
    eq = user_client.get(f"/api/projects/{pid}/equations").json()[0]
    assert eq["translations"]["auto"][cdb["db_id"]].startswith("TITLE-ABS(")

    # an equation created afterwards has it from the start
    cid = user_client.post(f"/api/projects/{pid}/concepts",
                           json={"name": "Outcome", "keywords": ["engagement"]}
                           ).json()["id"]
    eq2 = user_client.post(f"/api/projects/{pid}/equations", json={
        "label": "v2", "concept_ids": [cid]}).json()
    assert cdb["db_id"] in eq2["translations"]["auto"]

    # removing the database drops its (now meaningless) translation
    user_client.delete(f"/api/projects/{pid}/custom-databases/{cdb['id']}")
    eq = user_client.get(f"/api/projects/{pid}/equations").json()[0]
    assert cdb["db_id"] not in eq["translations"]["auto"]


def test_declared_database_is_listed_and_usable(user_client, project, equation):
    pid = project["id"]
    cdb = user_client.post(f"/api/projects/{pid}/custom-databases", json={
        "label": "ERIC", "instructions": "ERIC advanced search."}).json()

    # Equations/Search page registry
    dbs = user_client.get(f"/api/projects/{pid}/equations/databases").json()["databases"]
    eric = next(d for d in dbs if d["id"] == cdb["db_id"])
    assert eric["count"] == "manual" and eric["custom"] is True
    assert eric["instructions"] == "ERIC advanced search."

    # settings listing (keyed + free + manual + declared)
    settings = user_client.get(
        f"/api/database-credentials/databases?project_id={pid}").json()
    modes = {d["id"]: d["mode"] for d in settings}
    assert modes["scopus"] == "api_key" and modes["pubmed"] == "api"
    assert modes["wos"] == "api_key" and modes["ebsco"] == "manual"  # WoS: Starter key (6b)
    assert modes[cdb["db_id"]] == "manual"

    # manual count + hand-written override + import, like any manual database
    assert user_client.post(
        f"/api/projects/{pid}/equations/{equation['id']}/counts/manual",
        json={"database": cdb["db_id"], "count": 42}).status_code == 200
    assert user_client.put(
        f"/api/projects/{pid}/equations/{equation['id']}/override",
        json={"database": cdb["db_id"], "query": "mine"}).status_code == 200
    r = user_client.post(f"/api/projects/{pid}/imports/upload",
                         files={"file": ("e.ris", RIS.encode(), "text/plain")},
                         data={"source_name": cdb["db_id"], "source_type": "database",
                               "equation_id": equation["id"]})
    assert r.status_code == 200 and r.json()["n_records"] == 1
    assert user_client.get(f"/api/projects/{pid}/custom-databases"
                           ).json()[0]["n_imports"] == 1

    # and it shows up in the PRISMA-S search report next to the built-ins
    user_client.post(f"/api/projects/{pid}/equations/{equation['id']}/freeze")
    report = user_client.get(f"/api/projects/{pid}/search-report").text
    assert "**ERIC**" in report and cdb["db_id"] in report


def test_only_project_admins_declare_databases(user_client, project):
    pid = project["id"]
    user_client.post(f"/api/projects/{pid}/members",
                     json={"email": "rev@example.com", "role": "reviewer"})
    user_client.post("/api/auth/register", json={
        "email": "rev@example.com", "password": "password123",
        "display_name": "Rev"})
    r = user_client.post(f"/api/projects/{pid}/custom-databases",
                         json={"label": "Private portal"})
    assert r.status_code == 403
    # …but a reviewer sees them
    assert user_client.get(f"/api/projects/{pid}/custom-databases").status_code == 200
