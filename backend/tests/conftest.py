import os
import tempfile

# Must be set before any app import: config and engine are created at import time.
_tmpdir = tempfile.mkdtemp(prefix="litubik_test_")
os.environ["LITUBIK_DATA_DIR"] = _tmpdir
os.environ["LITUBIK_SECRET_KEY"] = "test-secret-key-not-for-production"
# H1 flipped the default to restricted registration. Most tests register extra
# accounts straight away to check *authorisation*, not signup policy, so the
# suite runs with free signup; test_registration_policy.py opts back into the
# restricted mode explicitly.
os.environ["LITUBIK_ALLOW_REGISTRATION"] = "true"
# the silent abstract backfill would call OpenAlex & co. after every upload a
# test makes; its own tests switch it back on and stub the fetch
os.environ["LITUBIK_ABSTRACT_BACKFILL"] = "false"

import pytest
from fastapi.testclient import TestClient

from app.core.db import Base, engine
from app.main import app


@pytest.fixture(autouse=True)
def fresh_db():
    from app.core.ratelimit import (guest_daily, guest_global, guest_hourly,
                                    login_throttle)
    # isolate the module-level rate limiters per test
    for limiter in (login_throttle, guest_daily, guest_global, guest_hourly):
        limiter.clear()
    Base.metadata.create_all(engine)
    yield
    Base.metadata.drop_all(engine)


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture
def user_client(client):
    """A TestClient logged in as a fresh (first == app admin) user."""
    client.post("/api/auth/register", json={
        "email": "admin@example.com", "password": "password123",
        "display_name": "Admin",
    })
    return client
