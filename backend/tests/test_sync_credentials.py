"""Sync phase 3: shared API keys — keywrap, share/revoke cycle through
contribution packages and snapshots, wrong/missing passphrase, zero plaintext
in any exchanged artifact."""
import json

import pytest

from app.core.crypto import decrypt_secret, encrypt_secret
from app.core.db import SessionLocal
from app.core.security import hash_password
from app.models import (
    DatabaseCredential, LLMCredential, Project, ProjectMember, User,
)
from app.services.connectors.keys import resolve_db_key
from app.services.sync.contributions import (
    build_contributions, import_contributions,
)
from app.services.sync.keywrap import (
    WrongPassphrase, decrypt_blob, encrypt_blob,
)
from app.services.sync.snapshot import build_snapshot, import_snapshot

PHRASE = "phrase-commune-123"
SCOPUS_KEY = "SCOPUS-SECRET-abcdef123456"
LLM_KEY = "sk-ant-SECRET-9876543210"


def _seed(db):
    alice = User(email="alice@a.org", password_hash=hash_password("password1"),
                 display_name="Alice", is_admin=True)
    bob = User(email="bob@b.org", password_hash=hash_password("password2"),
               display_name="Bob")
    db.add_all([alice, bob])
    db.flush()
    p = Project(name="P", sync_passphrase_encrypted=encrypt_secret(PHRASE))
    db.add(p)
    db.flush()
    db.add_all([ProjectMember(project_id=p.id, user_id=alice.id, role="admin"),
                ProjectMember(project_id=p.id, user_id=bob.id,
                              role="reviewer")])
    db.add(DatabaseCredential(project_id=p.id, provider="scopus",
                              api_key_encrypted=encrypt_secret(SCOPUS_KEY),
                              owner_user_id=bob.id, shared=True))
    db.add(LLMCredential(project_id=p.id, provider="anthropic",
                         api_key_encrypted=encrypt_secret(LLM_KEY),
                         default_model="claude-x", owner_user_id=bob.id,
                         shared=True))
    db.commit()
    return p, alice, bob


def _wipe_bob_keys(db, project_id):
    for model in (DatabaseCredential, LLMCredential):
        db.query(model).filter_by(project_id=project_id).delete(
            synchronize_session=False)
    db.commit()


def test_keywrap_round_trip_and_wrong_phrase():
    blob = encrypt_blob({"secret": "value-123"}, PHRASE)
    assert "value-123" not in json.dumps(blob)
    assert decrypt_blob(blob, PHRASE) == {"secret": "value-123"}
    with pytest.raises(WrongPassphrase):
        decrypt_blob(blob, "not-the-phrase")


def test_share_revoke_cycle_via_packages():
    with SessionLocal() as db:
        p, alice, bob = _seed(db)

        package = build_contributions(db, p, bob)[0]
        raw = json.dumps(package)
        assert SCOPUS_KEY not in raw and LLM_KEY not in raw  # never cleartext
        assert package["credentials_enc"] is not None

        # the receiving instance has none of bob's keys
        _wipe_bob_keys(db, p.id)
        report = import_contributions(db, package, alice)
        assert report["credentials"]["applied"] == 2

        # acceptance criterion: counts/search resolution now works with the key
        assert resolve_db_key(db, p.id, "scopus") == SCOPUS_KEY
        llm = db.query(LLMCredential).filter_by(project_id=p.id).one()
        assert decrypt_secret(llm.api_key_encrypted) == LLM_KEY
        assert llm.owner_user_id == bob.id and llm.shared

        # bob revokes his scopus key on HIS side -> builds a package without it
        scopus = db.query(DatabaseCredential).filter_by(project_id=p.id).one()
        scopus.shared = False
        db.commit()
        package2 = build_contributions(db, p, bob)[0]
        # (same-instance test: restore the RECEIVER's state before importing)
        scopus.shared = True
        db.commit()
        report2 = import_contributions(db, package2, alice)
        assert report2["credentials"]["removed"] == 1
        assert resolve_db_key(db, p.id, "scopus") is None
        assert db.query(LLMCredential).filter_by(project_id=p.id).count() == 1

        # revoking the LAST shared key still propagates (empty full-set blob)
        llm = db.query(LLMCredential).filter_by(project_id=p.id).one()
        llm.shared = False
        db.commit()
        package3 = build_contributions(db, p, bob)[0]
        assert package3["credentials_enc"] is not None
        llm.shared = True
        db.commit()
        report3 = import_contributions(db, package3, alice)
        assert report3["credentials"]["removed"] == 1
        assert db.query(LLMCredential).filter_by(
            project_id=p.id, shared=True).count() == 0


def test_wrong_and_missing_passphrase():
    with SessionLocal() as db:
        p, alice, bob = _seed(db)
        package = build_contributions(db, p, bob)[0]

        # receiving side has a different phrase -> keys ignored with a warning
        p.sync_passphrase_encrypted = encrypt_secret("une-autre-phrase-999")
        db.commit()
        _wipe_bob_keys(db, p.id)
        report = import_contributions(db, package, alice)
        assert report["credentials"]["applied"] == 0
        assert any("Phrase" in w for w in report["warnings"])
        # ...but the rest of the package still imported fine (no exception)

        # exporting without a passphrase: keys cannot travel, note is logged
        p.sync_passphrase_encrypted = None
        db.add(DatabaseCredential(project_id=p.id, provider="scopus",
                                  api_key_encrypted=encrypt_secret(SCOPUS_KEY),
                                  owner_user_id=bob.id, shared=True))
        db.commit()
        package2 = build_contributions(db, p, bob)[0]
        assert package2["credentials_enc"] is None


def test_snapshot_carries_shared_keys():
    with SessionLocal() as db:
        p, alice, bob = _seed(db)
        path = build_snapshot(db, p, include_pdfs=False, exporter=alice)
        assert SCOPUS_KEY.encode() not in path.read_bytes()

        project_uuid = p.uuid
        db.delete(p)  # simulate the other instance (creds cascade away)
        db.commit()

        # create mode: satellite has no passphrase yet -> keys ignored + hint
        report = import_snapshot(db, path, bob)
        assert report["credentials"]["applied"] == 0
        assert any("phrase" in w.lower() for w in report["warnings"])

        # enter the phrase, apply the snapshot again -> keys land
        satellite = db.query(Project).filter_by(uuid=project_uuid).one()
        satellite.sync_passphrase_encrypted = encrypt_secret(PHRASE)
        db.commit()
        report2 = import_snapshot(db, path, alice)
        assert report2["credentials"]["applied"] == 2
        assert resolve_db_key(db, satellite.id, "scopus") == SCOPUS_KEY


def test_adopt_global_llm_key(user_client):
    """A coordinator's app-wide LLM key can be attached to a project as a
    shared key in one click — after which it travels in snapshots."""
    project_id = user_client.post("/api/projects",
                                  json={"name": "P"}).json()["id"]
    user_client.put("/api/llm/credentials", json={
        "provider": "anthropic", "api_key": LLM_KEY, "project_id": None})

    r = user_client.get(
        f"/api/projects/{project_id}/sync/global-llm-providers")
    assert r.json() == ["anthropic"]

    r = user_client.post(
        f"/api/projects/{project_id}/sync/shared-keys/adopt-global",
        json={"provider": "anthropic"})
    assert r.status_code == 200, r.text
    assert r.json()["shared"] and r.json()["kind"] == "llm"

    with SessionLocal() as db:
        row = (db.query(LLMCredential)
               .filter_by(project_id=project_id, provider="anthropic").one())
        assert decrypt_secret(row.api_key_encrypted) == LLM_KEY
        assert row.shared
    # provider now attached -> no longer offered
    assert user_client.get(
        f"/api/projects/{project_id}/sync/global-llm-providers").json() == []


def test_shared_keys_api(user_client):
    project_id = user_client.post("/api/projects",
                                  json={"name": "P"}).json()["id"]
    r = user_client.post(f"/api/projects/{project_id}/sync/passphrase",
                         json={"passphrase": PHRASE})
    assert r.status_code == 200 and r.json()["has_passphrase"]
    r = user_client.post(f"/api/projects/{project_id}/sync/passphrase",
                         json={"passphrase": "short"})
    assert r.status_code == 400

    r = user_client.put(f"/api/projects/{project_id}/sync/database-keys",
                        json={"provider": "scopus", "api_key": SCOPUS_KEY})
    assert r.status_code == 200, r.text
    key = r.json()
    assert key["shared"] and key["is_mine"]

    keys = user_client.get(
        f"/api/projects/{project_id}/sync/shared-keys").json()
    assert len(keys) == 1 and keys[0]["provider"] == "scopus"

    r = user_client.post(
        f"/api/projects/{project_id}/sync/shared-keys/database/"
        f"{key['id']}/share", json={"shared": False})
    assert r.status_code == 200 and not r.json()["shared"]

    info = user_client.get(f"/api/projects/{project_id}/sync").json()
    assert info["has_passphrase"] and info["n_shared_keys"] == 0

    r = user_client.delete(
        f"/api/projects/{project_id}/sync/shared-keys/database/{key['id']}")
    assert r.status_code == 200
    assert user_client.get(
        f"/api/projects/{project_id}/sync/shared-keys").json() == []


def test_only_the_superadmin_adopts_a_global_key(user_client):
    """A shared key travels wrapped under a passphrase its project admin
    chooses: if any project admin could adopt the operator's global key, they
    could read it in clear from their own export."""
    user_client.put("/api/llm/credentials", json={
        "provider": "anthropic", "api_key": LLM_KEY, "project_id": None})
    user_client.post("/api/auth/register", json={
        "email": "coord@example.com", "password": "password123",
        "display_name": "C"})
    user_client.post("/api/auth/login", json={
        "email": "coord@example.com", "password": "password123"})
    project_id = user_client.post("/api/projects",
                                  json={"name": "Theirs"}).json()["id"]
    assert user_client.get(
        f"/api/projects/{project_id}/sync/global-llm-providers").json() == []
    r = user_client.post(
        f"/api/projects/{project_id}/sync/shared-keys/adopt-global",
        json={"provider": "anthropic"})
    assert r.status_code == 403
    with SessionLocal() as db:
        assert db.query(LLMCredential).filter_by(
            project_id=project_id).count() == 0
