"""Review registration (PRISMA 2020 item 24a/24b).

The point under test throughout is the three-state distinction: a review that
is registered, one the team declared unregistered, and one nobody has answered
for. Collapsing the last two would make the Methods draft assert an absence the
team never claimed.
"""
from app.services import registration


def _project(user_client, **patch):
    pid = user_client.post("/api/projects", json={"name": "P"}).json()["id"]
    if patch:
        user_client.put(f"/api/projects/{pid}", json=patch)
    return pid


# -- the catalogue ------------------------------------------------------------

def test_catalogue_is_served_and_every_template_takes_an_id():
    for reg in registration.REGISTRIES.values():
        assert reg.label
        if reg.url_template:
            assert "{id}" in reg.url_template
            assert reg.id_hint, reg.key


def test_registries_endpoint_lists_the_catalogue(user_client):
    rows = user_client.get("/api/registries").json()
    assert {r["key"] for r in rows} == set(registration.REGISTRIES)
    prospero = next(r for r in rows if r["key"] == "prospero")
    assert prospero["has_url_template"] is True
    assert next(r for r in rows if r["key"] == "none")["has_url_template"] is False


# -- the three states ---------------------------------------------------------

def test_a_new_project_is_undeclared_not_unregistered(user_client):
    pid = _project(user_client)
    project = user_client.get("/api/projects").json()
    assert next(p for p in project if p["id"] == pid)["registry"] == ""


def test_audit_block_separates_undeclared_from_not_registered():
    class P:
        registry = ""
        registration_id = ""
        registration_url = ""
        registered_at = None
        protocol_url = ""

    assert registration.audit_block(P())["state"] == "undeclared"
    P.registry = "none"
    assert registration.audit_block(P())["state"] == "not_registered"
    P.registry = "prospero"
    P.registration_id = "CRD42024512345"
    block = registration.audit_block(P())
    assert block["state"] == "registered"
    assert block["identifier"] == "CRD42024512345"
    assert block["url"].endswith("CRD42024512345")


def test_audit_block_tolerates_a_missing_project():
    assert registration.audit_block(None)["state"] == "undeclared"


# -- the URL ------------------------------------------------------------------

def test_a_hand_entered_url_beats_the_template():
    """A register that moved its records must not be second-guessed."""
    url = registration.public_url("prospero", "CRD42024512345",
                                  "https://example.org/moved")
    assert url == "https://example.org/moved"


def test_no_url_without_an_identifier_and_none_for_a_template_less_register():
    assert registration.public_url("prospero", "  ", "") == ""
    assert registration.public_url("other", "REG-1", "") == ""
    assert registration.public_url("", "REG-1", "") == ""


def test_an_unknown_registry_key_degrades_instead_of_raising():
    # a snapshot written by a newer instance
    assert registration.registry("nawak") is None
    assert registration.public_url("nawak", "X", "") == ""
    block = registration.audit_block(type("P", (), {
        "registry": "nawak", "registration_id": "X", "registration_url": "",
        "registered_at": None, "protocol_url": ""})())
    assert block["state"] == "registered"
    assert block["registry_label"] == "nawak"


# -- the API ------------------------------------------------------------------

def test_registration_round_trips_through_the_project_endpoint(user_client):
    pid = _project(user_client, registry="prospero",
                   registration_id="CRD42024512345",
                   registered_at="2026-03-09T00:00:00Z",
                   protocol_url="https://osf.io/abcde/")
    project = next(p for p in user_client.get("/api/projects").json()
                   if p["id"] == pid)
    assert project["registry"] == "prospero"
    assert project["registration_id"] == "CRD42024512345"
    assert project["registered_at"].startswith("2026-03-09")
    assert project["protocol_url"] == "https://osf.io/abcde/"


def test_an_unknown_registry_is_rejected(user_client):
    pid = _project(user_client)
    r = user_client.put(f"/api/projects/{pid}", json={"registry": "nawak"})
    assert r.status_code == 400


def test_declaring_the_review_unregistered_clears_a_stale_identifier(user_client):
    """Otherwise the number of an abandoned registration would keep travelling
    into the Methods draft."""
    pid = _project(user_client, registry="prospero", registration_id="CRD1",
                   registered_at="2026-03-09T00:00:00Z")
    user_client.put(f"/api/projects/{pid}", json={"registry": "none"})
    project = next(p for p in user_client.get("/api/projects").json()
                   if p["id"] == pid)
    assert project["registration_id"] == ""
    assert project["registered_at"] is None


def test_the_date_can_be_cleared_but_is_left_alone_when_not_sent(user_client):
    pid = _project(user_client, registry="prospero", registration_id="CRD1",
                   registered_at="2026-03-09T00:00:00Z")
    user_client.put(f"/api/projects/{pid}", json={"registration_id": "CRD2"})
    project = next(p for p in user_client.get("/api/projects").json()
                   if p["id"] == pid)
    assert project["registered_at"].startswith("2026-03-09")

    user_client.put(f"/api/projects/{pid}", json={"registered_at": None})
    project = next(p for p in user_client.get("/api/projects").json()
                   if p["id"] == pid)
    assert project["registered_at"] is None


# -- the dossier the Methods draft reads --------------------------------------

def test_the_review_dossier_carries_the_registration_block(user_client):
    from app.core.db import SessionLocal
    from app.services.reporting.audit import review_dossier

    pid = _project(user_client, registry="osf", registration_id="ab3cd")
    with SessionLocal() as db:
        block = review_dossier(db, pid)["registration"]
    assert block["state"] == "registered"
    assert block["registry_label"] == "OSF Registries"
    assert block["url"] == "https://osf.io/ab3cd/"
