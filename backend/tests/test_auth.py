def test_register_login_me(client):
    r = client.post("/api/auth/register", json={
        "email": "alice@example.com", "password": "password123",
        "display_name": "Alice",
    })
    assert r.status_code == 200
    assert r.json()["is_admin"] is True  # first account is app admin

    r = client.get("/api/auth/me")
    assert r.status_code == 200
    assert r.json()["email"] == "alice@example.com"

    client.post("/api/auth/logout")
    client.cookies.clear()
    assert client.get("/api/auth/me").status_code == 401

    r = client.post("/api/auth/login", json={
        "email": "alice@example.com", "password": "password123"})
    assert r.status_code == 200
    assert client.get("/api/auth/me").status_code == 200


def test_second_user_is_not_admin(client):
    client.post("/api/auth/register", json={
        "email": "a@example.com", "password": "password123", "display_name": "A"})
    client.cookies.clear()
    r = client.post("/api/auth/register", json={
        "email": "b@example.com", "password": "password123", "display_name": "B"})
    assert r.json()["is_admin"] is False


def test_wrong_password(client):
    client.post("/api/auth/register", json={
        "email": "a@example.com", "password": "password123", "display_name": "A"})
    r = client.post("/api/auth/login", json={
        "email": "a@example.com", "password": "wrongpass1"})
    assert r.status_code == 401


def test_login_lockout_after_repeated_failures(client):
    client.post("/api/auth/register", json={
        "email": "a@example.com", "password": "password123", "display_name": "A"})
    client.cookies.clear()
    # 3 wrong attempts -> the 4th is refused with 429 even if the password
    # were now correct (L2: online brute-force cooldown)
    for _ in range(3):
        r = client.post("/api/auth/login", json={
            "email": "a@example.com", "password": "wrongpass1"})
        assert r.status_code == 401
    r = client.post("/api/auth/login", json={
        "email": "a@example.com", "password": "password123"})
    assert r.status_code == 429
    assert "Retry-After" in r.headers


def test_duplicate_email(client):
    payload = {"email": "a@example.com", "password": "password123",
               "display_name": "A"}
    client.post("/api/auth/register", json=payload)
    assert client.post("/api/auth/register", json=payload).status_code == 409


def test_tokens_of_accounts_older_than_the_session_salt_stay_valid(client):
    """Accounts created before users.session_salt existed have none, and the
    tokens already issued to them carry none: those sessions survive the
    upgrade."""
    from app.core.db import SessionLocal
    from app.core.security import create_access_token
    from app.models import User

    user = client.post("/api/auth/register", json={
        "email": "legacy@example.com", "password": "password123",
        "display_name": "L"}).json()
    with SessionLocal() as db:
        row = db.get(User, user["id"])
        assert row.session_salt  # every new account gets one
        row.session_salt = None
        db.commit()
    client.cookies.clear()
    client.cookies.set("litubik_token", create_access_token(user["id"], 0))
    assert client.get("/api/auth/me").json()["email"] == "legacy@example.com"
