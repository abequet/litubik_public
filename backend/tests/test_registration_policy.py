"""H1 — restricted registration.

LITUBIK_ALLOW_REGISTRATION=false is not a blanket 403: the first account of a
fresh instance, an allowlisted email, someone a project admin already added to a
team, and an open project invitation all still get through. Everyone else is
turned away, so a public instance cannot be taken over by whoever registers
first.
"""
import pytest

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.models import ProjectInvitation, TrustedEmail


@pytest.fixture
def restricted(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "allow_registration", False)
    return settings


def _register(client, email, name="U"):
    return client.post("/api/auth/register", json={
        "email": email, "password": "password123", "display_name": name})


# ---- the four ways in --------------------------------------------------------

def test_first_account_bootstraps(client, restricted):
    """A fresh instance must stay usable: the first account is let in, and it is
    the app admin."""
    r = _register(client, "founder@example.com")
    assert r.status_code == 200
    assert r.json()["is_admin"] is True


def test_allowlisted_email(client, restricted):
    _register(client, "founder@example.com")
    client.cookies.clear()
    with SessionLocal() as db:
        db.add(TrustedEmail(email="invited@example.com"))
        db.commit()
    r = _register(client, "invited@example.com")
    assert r.status_code == 200
    assert r.json()["is_admin"] is False


def test_member_added_by_a_project_admin(user_client, restricted):
    """The case the whole feature exists for: an admin adds a reviewer to their
    team, and that reviewer can then create their account."""
    pid = user_client.post("/api/projects", json={"name": "P"}).json()["id"]
    assert user_client.post(
        f"/api/projects/{pid}/members",
        json={"email": "rev@example.com", "role": "reviewer"}).status_code in (200, 201)
    user_client.cookies.clear()
    r = _register(user_client, "rev@example.com", name="Rev")
    assert r.status_code == 200
    # the membership created before registration is still attached
    projects = user_client.get("/api/projects").json()
    assert [p["id"] for p in projects] == [pid]


def test_open_project_invitation(user_client, restricted):
    pid = user_client.post("/api/projects", json={"name": "P"}).json()["id"]
    with SessionLocal() as db:
        db.add(ProjectInvitation(project_id=pid, email="guest@example.com",
                                 role="reviewer"))
        db.commit()
    user_client.cookies.clear()
    assert _register(user_client, "guest@example.com").status_code == 200


# ---- and the way out ---------------------------------------------------------

def test_unknown_email_is_refused(user_client, restricted):
    r = _register(user_client, "stranger@example.com")
    assert r.status_code == 403
    assert "restricted" in r.json()["detail"].lower()


def test_refusal_does_not_create_the_account(user_client, restricted):
    _register(user_client, "stranger@example.com")
    # not a half-created shadow account: logging in must fail on credentials
    user_client.cookies.clear()
    r = user_client.post("/api/auth/login", json={
        "email": "stranger@example.com", "password": "password123"})
    assert r.status_code == 401


def test_already_registered_still_conflicts(user_client, restricted):
    """409 (email taken) must win over 403 — a stranger probing the endpoint
    learns nothing new, and a legitimate retry gets the accurate error."""
    assert _register(user_client, "admin@example.com").status_code == 409


# ---- non-regression ----------------------------------------------------------

def test_free_signup_when_enabled(user_client):
    """Default-off is a policy, not a wall: LITUBIK_ALLOW_REGISTRATION=true
    restores open signup (this is what conftest sets for the rest of the suite)."""
    assert get_settings().allow_registration is True
    assert _register(user_client, "anyone@example.com").status_code == 200
