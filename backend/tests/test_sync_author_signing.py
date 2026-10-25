"""M5: a contribution package is bound to the installation that produced it.

The project passphrase is shared by every member, so the HMAC on a package only
proves membership. These tests cover the forgery it cannot stop, and the
trust-on-first-use binding that does.
"""
import os

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app.core.crypto import encrypt_secret
from app.core.db import SessionLocal
from app.core.security import hash_password
from app.models import (
    Assignment, Import, Project, ProjectMember, Record, ScreeningConfig, Source,
    User, Vote,
)
from app.models.accounts import utcnow
from app.services.sync import signing
from app.services.sync.common import SnapshotError
from app.services.sync.contributions import build_contributions, import_contributions


def _seed(db):
    """alice = coordinator admin, bob and carol = reviewers on the same project."""
    users = {}
    for name, admin in (("alice", True), ("bob", False), ("carol", False)):
        u = User(email=f"{name}@x.org", password_hash=hash_password("password1"),
                 display_name=name.title(), is_admin=admin)
        db.add(u)
        users[name] = u
    db.flush()
    # a real project passphrase: without one there is no HMAC at all, and the
    # forgery test below would prove nothing about what the HMAC fails to stop
    p = Project(name="P",
                sync_passphrase_encrypted=encrypt_secret("shared-team-phrase"))
    db.add(p)
    db.flush()
    db.add(ProjectMember(project_id=p.id, user_id=users["alice"].id, role="admin"))
    for name in ("bob", "carol"):
        db.add(ProjectMember(project_id=p.id, user_id=users[name].id,
                             role="reviewer"))
    src = Source(project_id=p.id, type="database", name="PubMed")
    db.add(src)
    db.flush()
    imp = Import(project_id=p.id, source_id=src.id)
    db.add(imp)
    db.flush()
    rec = Record(project_id=p.id, import_id=imp.id, title="R1",
                 dedup_status="unique")
    db.add(rec)
    db.flush()
    cfg = ScreeningConfig(project_id=p.id, stage="ta", round=1,
                          reviewer_ids=[u.id for u in users.values()],
                          status="active", started_at=utcnow())
    db.add(cfg)
    db.flush()
    for u in users.values():
        db.add(Assignment(config_id=cfg.id, record_id=rec.id, user_id=u.id))
    db.commit()
    return p, users, rec


def _package_from(db, project, author, record, decision="include"):
    """Build a real contribution package carrying one vote by `author`.

    The vote is removed afterwards so the helper can be called again — an
    earlier import may already have created that exact row on this instance.
    """
    vote = (db.query(Vote)
            .filter_by(record_id=record.id, stage="ta", round=1,
                       voter_user_id=author.id, is_ai=False).first())
    if vote is None:
        vote = Vote(project_id=project.id, record_id=record.id, stage="ta",
                    round=1, voter_user_id=author.id, decision=decision)
        db.add(vote)
    else:
        vote.decision = decision
    db.commit()
    payload, _name = build_contributions(db, project, author)
    db.delete(vote)
    db.commit()
    return payload


def test_package_carries_an_author_signature():
    with SessionLocal() as db:
        project, users, rec = _seed(db)
        payload = _package_from(db, project, users["bob"], rec)
    verdict, pubkey = signing.verify_author(payload)
    assert verdict is True and len(pubkey) == 64


def test_first_package_binds_the_author_key():
    with SessionLocal() as db:
        project, users, rec = _seed(db)
        payload = _package_from(db, project, users["bob"], rec)
        import_contributions(db, payload, importer=users["alice"])
        member = (db.query(ProjectMember)
                  .filter_by(project_id=project.id, user_id=users["bob"].id)
                  .first())
        assert member.sync_pubkey == payload["author_signature"]["pubkey"]


def test_forged_package_from_another_installation_is_refused():
    """The attack M5 is about: carol holds the project passphrase, so she can
    produce a package that declares bob as its author and passes the HMAC. Once
    bob's own installation is known, hers must not be accepted for him."""
    with SessionLocal() as db:
        project, users, rec = _seed(db)
        genuine = _package_from(db, project, users["bob"], rec, "include")
        import_contributions(db, genuine, importer=users["alice"])

        # carol re-signs a package attributed to bob with HER instance key
        forged = _package_from(db, project, users["bob"], rec, "exclude")
        carol_key = Ed25519PrivateKey.from_private_bytes(os.urandom(32))
        forged.pop("author_signature", None)
        signing.sign_author(carol_key, forged)
        signing.sign_dict(project, forged)          # project HMAC still valid
        assert signing.verify_dict(project, forged) is True
        assert signing.verify_author(forged)[0] is True   # internally consistent

        with pytest.raises(SnapshotError, match="autre installation"):
            import_contributions(db, forged, importer=users["alice"])


def test_tampered_author_signature_is_refused():
    with SessionLocal() as db:
        project, users, rec = _seed(db)
        payload = _package_from(db, project, users["bob"], rec)
        payload["votes"][0]["decision"] = "exclude"   # edited after export
        with pytest.raises(SnapshotError, match="Signature d'auteur invalide"):
            import_contributions(db, payload, importer=users["alice"])


def test_same_installation_imports_again_cleanly():
    with SessionLocal() as db:
        project, users, rec = _seed(db)
        first = _package_from(db, project, users["bob"], rec, "include")
        import_contributions(db, first, importer=users["alice"])
        second = _package_from(db, project, users["bob"], rec, "exclude")
        out = import_contributions(db, second, importer=users["alice"])
        assert not any("autre installation" in w for w in out.get("warnings", []))


def test_unsigned_legacy_package_is_merged_with_a_warning():
    with SessionLocal() as db:
        project, users, rec = _seed(db)
        payload = _package_from(db, project, users["bob"], rec)
        payload.pop("author_signature")
        out = import_contributions(db, payload, importer=users["alice"])
        assert any("authenticité" in w for w in out.get("warnings", []))
