"""Sync phase 2: contribution packages — merge rules, conflict detection,
idempotence, quarantine, membership guard, journal, API round-trip."""
from datetime import timedelta

import pytest

from app.core.db import SessionLocal
from app.core.security import hash_password
from app.models import (
    Assignment, Conflict, PdfAnnotation, Project, ProjectInvitation,
    ProjectMember, Record, RecordTag, ScreeningConfig, SyncEvent, Tag, Ticket,
    TicketComment, User, Vote,
)
from app.models.accounts import utcnow
from app.services.sync.common import SnapshotError
from app.services.sync.contributions import (
    build_contributions, import_contributions,
)


def _reexport(db, package):
    """A second export re-signs the package (M5). Tests that simulate one by
    editing the previous payload must do the same, or the author signature
    correctly reads as tampered."""
    from app.core.instance import get_signing_key
    from app.services.sync import signing
    package.pop("author_signature", None)
    signing.sign_author(get_signing_key(db), package)
    return package

def _seed(db):
    """Coordinator-side project: alice (admin) voted include on r1; bob is a
    member whose votes will arrive by package."""
    alice = User(email="alice@a.org", password_hash=hash_password("password1"),
                 display_name="Alice", is_admin=True)
    bob = User(email="bob@b.org", password_hash=hash_password("password2"),
               display_name="Bob")
    db.add_all([alice, bob])
    db.flush()
    p = Project(name="P")
    db.add(p)
    db.flush()
    db.add_all([ProjectMember(project_id=p.id, user_id=alice.id, role="admin"),
                ProjectMember(project_id=p.id, user_id=bob.id,
                              role="reviewer")])
    from app.models import Import, Source
    src = Source(project_id=p.id, type="database", name="PubMed")
    db.add(src)
    db.flush()
    imp = Import(project_id=p.id, source_id=src.id)
    db.add(imp)
    db.flush()
    r1 = Record(project_id=p.id, import_id=imp.id, title="R1",
                dedup_status="unique")
    r2 = Record(project_id=p.id, import_id=imp.id, title="R2",
                dedup_status="unique")
    db.add_all([r1, r2])
    db.flush()
    cfg = ScreeningConfig(project_id=p.id, stage="ta", round=1,
                          reviewer_ids=[alice.id, bob.id], status="active",
                          started_at=utcnow())
    db.add(cfg)
    db.flush()
    for user in (alice, bob):
        for record in (r1, r2):
            db.add(Assignment(config_id=cfg.id, record_id=record.id,
                              user_id=user.id))
    db.add(Vote(project_id=p.id, record_id=r1.id, stage="ta", round=1,
                voter_user_id=alice.id, decision="include"))
    db.commit()
    return p, alice, bob, r1, r2, cfg


def _bob_package(db, p, r1, r2, cfg, seq=1, based_on=None):
    """Hand-built package, as bob's satellite would produce it."""
    return {
        "format": "litubik-contributions", "format_version": 1,
        "project_uuid": p.uuid, "project_name": p.name,
        "author": {"email": "bob@b.org", "display_name": "Bob",
                   "instance_id": "instance-bob"},
        "seq": seq,
        "based_on_snapshot_version": (p.snapshot_version if based_on is None
                                      else based_on),
        "exported_at": utcnow().isoformat(),
        "votes": [
            {"record": r1.uuid, "stage": "ta", "round": 1,
             "email": "bob@b.org", "is_ai": False, "decision": "exclude",
             "reasons": ["E1"], "justification": "off topic",
             "criteria_eval": {}, "confidence": None, "generated_by": None,
             "created_at": utcnow().isoformat(),
             "updated_at": utcnow().isoformat()},
            {"record": r1.uuid, "stage": "ta", "round": 1, "email": None,
             "is_ai": True, "decision": "exclude", "reasons": [],
             "justification": "ai says no", "criteria_eval": {},
             "confidence": 0.8, "generated_by": "bob@b.org",
             "created_at": utcnow().isoformat(),
             "updated_at": utcnow().isoformat()},
        ],
        "jbi": [],
        "extraction_values": [],
        "annotations": [
            {"record": r1.uuid, "page": 1,
             "rects": [{"x": 0.1, "y": 0.1, "w": 0.2, "h": 0.1}],
             "quote": "methods", "note": "check", "color": "yellow",
             "created_at": utcnow().isoformat(),
             "updated_at": utcnow().isoformat()},
        ],
        "skips": [
            {"config": cfg.uuid, "record": r2.uuid,
             "skipped_at": utcnow().isoformat()},
        ],
        # bob looked at the batch suggestion on r1 before voting
        "ai_reveals": [
            {"record": r1.uuid, "stage": "ta", "round": 1,
             "revealed_at": utcnow().isoformat()},
        ],
    }


def test_import_merges_and_detects_conflict():
    with SessionLocal() as db:
        p, alice, bob, r1, r2, cfg = _seed(db)
        package = _bob_package(db, p, r1, r2, cfg)
        report = import_contributions(db, package, alice)

        assert report["votes"] == {"new": 1, "updated": 0, "unchanged": 0}
        assert report["ai_votes"] == {"added": 1, "skipped": 0}
        assert report["ai_reveals"] == {"added": 1, "skipped": 0}
        assert report["annotations"] == 1
        assert report["skips"] == 1
        # alice include vs bob exclude on r1 -> a conflict opened
        assert report["conflicts_created"] == 1
        conflict = db.query(Conflict).filter_by(project_id=p.id,
                                                record_id=r1.id).one()
        assert conflict.status == "open"

        vote = (db.query(Vote)
                .filter_by(record_id=r1.id, voter_user_id=bob.id,
                           is_ai=False).one())
        assert vote.decision == "exclude"
        assert vote.imported_from == "bob@b.org #1"
        skip = (db.query(Assignment)
                .filter_by(config_id=cfg.id, record_id=r2.id,
                           user_id=bob.id).one())
        assert skip.skipped_at is not None

        # double import: strict no-op
        report2 = import_contributions(db, package, alice)
        assert report2["votes"] == {"new": 0, "updated": 0, "unchanged": 1}
        assert report2["ai_votes"] == {"added": 0, "skipped": 1}
        assert report2["ai_reveals"] == {"added": 0, "skipped": 1}
        assert report2["conflicts_created"] == 0
        assert db.query(Vote).filter_by(record_id=r1.id).count() == 3

        # journal has both imports
        events = db.query(SyncEvent).filter_by(project_id=p.id,
                                               direction="import").all()
        assert len(events) == 2
        assert events[0].author_email == "bob@b.org"


def test_newer_local_vote_wins_over_older_package():
    with SessionLocal() as db:
        p, alice, bob, r1, r2, cfg = _seed(db)
        package = _bob_package(db, p, r1, r2, cfg)
        import_contributions(db, package, alice)

        # bob's vote evolves ON THIS instance (e.g. re-imported newer package
        # earlier); an OLD package must not roll it back
        vote = (db.query(Vote)
                .filter_by(record_id=r1.id, voter_user_id=bob.id,
                           is_ai=False).one())
        vote.decision = "include"
        vote.updated_at = utcnow() + timedelta(minutes=10)
        db.commit()

        report = import_contributions(db, package, alice)
        assert report["votes"] == {"new": 0, "updated": 0, "unchanged": 1}
        db.refresh(vote)
        assert vote.decision == "include"

        # while a NEWER package wins
        package["votes"][0]["decision"] = "maybe"
        package["votes"][0]["updated_at"] = (
            utcnow() + timedelta(minutes=20)).isoformat()
        package["seq"] = 2
        report = import_contributions(db, _reexport(db, package), alice)
        assert report["votes"]["updated"] == 1
        db.refresh(vote)
        assert vote.decision == "maybe"
        assert vote.imported_from == "bob@b.org #2"


def test_guards_membership_project_and_quarantine():
    with SessionLocal() as db:
        p, alice, bob, r1, r2, cfg = _seed(db)
        package = _bob_package(db, p, r1, r2, cfg)

        # non-admin importer refused
        with pytest.raises(SnapshotError, match="admin"):
            import_contributions(db, package, bob)

        # unknown author (not member, not invited) refused
        stranger = dict(package, author={"email": "eve@evil.org",
                                         "display_name": "Eve",
                                         "instance_id": "x"})
        with pytest.raises(SnapshotError, match="pas membre"):
            import_contributions(db, stranger, alice)

        # invited-only author: invitation converts, shadow account created
        db.add(ProjectInvitation(project_id=p.id, email="carla@c.org",
                                 role="reviewer"))
        db.commit()
        invited = dict(package, author={"email": "carla@c.org",
                                        "display_name": "Carla",
                                        "instance_id": "y"})
        report = import_contributions(db, invited, alice)
        carla = db.query(User).filter_by(email="carla@c.org").one()
        assert carla.password_hash == ""
        assert db.query(ProjectMember).filter_by(
            project_id=p.id, user_id=carla.id).count() == 1
        assert report["votes"]["new"] == 1  # her copy of the r1 vote

        # unknown record uuid -> quarantined, stale based_on -> warning
        package["votes"][0]["record"] = "no-such-uuid"
        package["based_on_snapshot_version"] = -1
        report = import_contributions(db, package, alice)
        assert report["quarantined_count"] == 1
        assert any("v-1" in w or "quarantaine" in w for w in report["warnings"])

        # wrong project uuid -> unknown project
        package["project_uuid"] = "not-a-project"
        with pytest.raises(SnapshotError, match="inconnu"):
            import_contributions(db, package, alice)


def test_annotations_replace_by_author():
    with SessionLocal() as db:
        p, alice, bob, r1, r2, cfg = _seed(db)
        package = _bob_package(db, p, r1, r2, cfg)
        import_contributions(db, package, alice)
        assert db.query(PdfAnnotation).filter_by(project_id=p.id).count() == 1

        # bob deleted his annotation and added another one on r2
        package["annotations"] = [
            {"record": r2.uuid, "page": 2, "rects": [], "quote": "new",
             "note": "", "color": "green",
             "created_at": utcnow().isoformat(),
             "updated_at": utcnow().isoformat()},
        ]
        package["seq"] = 2
        import_contributions(db, _reexport(db, package), alice)
        annotations = db.query(PdfAnnotation).filter_by(project_id=p.id).all()
        assert len(annotations) == 1
        assert annotations[0].record_id == r2.id
        assert annotations[0].quote == "new"


def test_build_contributions_round_trip():
    with SessionLocal() as db:
        p, alice, bob, r1, r2, cfg = _seed(db)
        # bob works locally: vote + AI suggestion generated on his instance
        db.add(Vote(project_id=p.id, record_id=r1.id, stage="ta", round=1,
                    voter_user_id=bob.id, decision="exclude", reasons=["E2"]))
        db.add(Vote(project_id=p.id, record_id=r2.id, stage="ta", round=1,
                    voter_user_id=None, is_ai=True, decision="include",
                    generated_by="bob@b.org"))
        # noise that must NOT leave with bob's package:
        db.add(Vote(project_id=p.id, record_id=r2.id, stage="ta", round=1,
                    voter_user_id=alice.id, decision="include"))
        db.commit()

        data, filename = build_contributions(db, p, bob)
        assert data["seq"] == 1
        assert "bob" in filename
        assert len(data["votes"]) == 2  # his human vote + his AI vote only
        emails = {v["email"] for v in data["votes"]}
        assert "alice@a.org" not in emails

        # wipe bob's rows (as if the coordinator never had them), re-import
        db.query(Vote).filter(Vote.voter_user_id == bob.id).delete(
            synchronize_session=False)
        db.query(Vote).filter(Vote.is_ai.is_(True)).delete(
            synchronize_session=False)
        db.query(Conflict).filter_by(project_id=p.id).delete(
            synchronize_session=False)
        db.commit()

        report = import_contributions(db, data, alice)
        assert report["votes"]["new"] == 1
        assert report["ai_votes"]["added"] == 1
        assert report["conflicts_created"] == 1  # alice include vs bob exclude

        # export seq increments
        data2, _ = build_contributions(db, p, bob)
        assert data2["seq"] == 2


def test_tickets_travel_with_contributions():
    with SessionLocal() as db:
        p, alice, bob, r1, r2, cfg = _seed(db)
        # bob files a project-linked ticket + an app-global one, with a thread
        t1 = Ticket(created_by=bob.id, project_id=p.id, title="PDF viewer bug",
                    body="page 2 blank", kind="bug", severity="major")
        t2 = Ticket(created_by=bob.id, project_id=None, title="Idea",
                    kind="feature")
        alice_ticket = Ticket(created_by=alice.id, project_id=p.id,
                              title="Alice's own")  # must NOT leave with bob
        db.add_all([t1, t2, alice_ticket])
        db.flush()
        db.add(TicketComment(ticket_id=t1.id, user_id=bob.id, body="details"))
        db.commit()

        package = build_contributions(db, p, bob)[0]
        assert {t["title"] for t in package["tickets"]} \
            == {"PDF viewer bug", "Idea"}

        # simulate the coordinator side: bob's tickets don't exist there
        db.query(TicketComment).delete(synchronize_session=False)
        db.query(Ticket).filter(Ticket.created_by == bob.id).delete(
            synchronize_session=False)
        db.commit()

        report = import_contributions(db, package, alice)
        assert report["tickets"]["new"] == 2
        assert report["ticket_comments"] == 1
        imported = (db.query(Ticket)
                    .filter(Ticket.created_by == bob.id).all())
        assert {t.title for t in imported} == {"PDF viewer bug", "Idea"}
        linked = next(t for t in imported if t.title == "PDF viewer bug")
        assert linked.project_id == p.id
        assert linked.imported_from == "bob@b.org #1"
        assert len(linked.comments) == 1

        # idempotent
        report = import_contributions(db, package, alice)
        assert report["tickets"] == {"new": 0, "updated": 0, "unchanged": 2}
        assert report["ticket_comments"] == 0

        # triage authority: the coordinator's status survives the author's
        # updates, but the author CAN close their own ticket
        linked.status = "in_progress"
        db.commit()
        for t in package["tickets"]:
            t["updated_at"] = (utcnow() + timedelta(minutes=5)).isoformat()
            t["body"] = "updated body"
        package["seq"] = 2
        report = import_contributions(db, _reexport(db, package), alice)
        assert report["tickets"]["updated"] == 2
        db.refresh(linked)
        assert linked.status == "in_progress"      # triage kept
        assert linked.body == "updated body"       # author fields updated

        next(t for t in package["tickets"]
             if t["title"] == "PDF viewer bug")["status"] = "closed"
        for t in package["tickets"]:
            t["updated_at"] = (utcnow() + timedelta(minutes=10)).isoformat()
        package["seq"] = 3
        import_contributions(db, _reexport(db, package), alice)
        db.refresh(linked)
        assert linked.status == "closed"           # author closing propagates


def test_tags_travel_with_contributions():
    """Field bug: satellites could not tag (403), and their tags had no way
    back to the coordinator. Tags now ride the contribution packages with
    replace-by-author semantics."""
    with SessionLocal() as db:
        p, alice, bob, r1, r2, cfg = _seed(db)
        # bob tags r1 with a tag he creates on his satellite
        tag = Tag(project_id=p.id, name="Intro/Discussion", created_by=bob.id)
        db.add(tag)
        db.flush()
        db.add(RecordTag(tag_id=tag.id, record_id=r1.id, created_by=bob.id))
        db.commit()

        package = build_contributions(db, p, bob)[0]
        assert package["tags"] == [dict(package["tags"][0])]  # 1 attachment
        assert package["tags"][0]["tag"] == "Intro/Discussion"

        # coordinator side: no such tag yet
        db.query(RecordTag).delete(synchronize_session=False)
        db.query(Tag).delete(synchronize_session=False)
        db.commit()

        report = import_contributions(db, package, alice)
        assert report["tags"]["attached"] == 1
        tag = db.query(Tag).filter_by(project_id=p.id).one()
        assert tag.name == "Intro/Discussion"
        assert db.query(RecordTag).filter_by(tag_id=tag.id,
                                             record_id=r1.id).count() == 1

        # idempotent
        report = import_contributions(db, package, alice)
        assert report["tags"] == {"attached": 0, "removed": 0, "unchanged": 1}

        # bob detaches on his side -> removal propagates (replace-by-author)
        package2 = _reexport(db, dict(package, tags=[], seq=2))
        report = import_contributions(db, package2, alice)
        assert report["tags"]["removed"] == 1
        assert db.query(RecordTag).count() == 0
        # alice's own attachments would be untouched: only bob's rows move


def test_satellite_can_tag(user_client):
    """The tags router is no longer satellite-locked."""
    with SessionLocal() as db:
        p, alice, bob, r1, r2, cfg = _seed(db)
        p.sync_role = "satellite"
        db.commit()
        pid, rid = p.id, r1.id
    # user_client = app admin (member via app-admin fallback)
    r = user_client.post(f"/api/projects/{pid}/tags/records/{rid}",
                         json={"name": "Intro/Discussion"})
    assert r.status_code == 200, r.text
    assert [t["name"] for t in r.json()] == ["Intro/Discussion"]


def test_contributions_via_api(user_client):
    with SessionLocal() as db:
        p, alice, bob, r1, r2, cfg = _seed(db)
        pid, bob_id = p.id, bob.id
        # admin@example.com (user_client) must be able to act on the project
        db.add(Vote(project_id=p.id, record_id=r1.id, stage="ta", round=1,
                    voter_user_id=bob.id, decision="exclude"))
        db.commit()

    # bob logs in and exports his contributions
    user_client.post("/api/auth/logout")
    user_client.cookies.clear()
    user_client.post("/api/auth/login", json={"email": "bob@b.org",
                                              "password": "password2"})
    r = user_client.post(f"/api/projects/{pid}/sync/export-contributions")
    assert r.status_code == 200, r.text
    assert "litubik-contrib.json" in r.headers.get("content-disposition", "")
    package_bytes = r.content

    # bob (reviewer) may not import; alice (project admin) may
    r = user_client.post(f"/api/projects/{pid}/sync/import-contributions",
                         files={"file": ("c.json", package_bytes,
                                         "application/json")})
    assert r.status_code == 403
    user_client.cookies.clear()
    user_client.post("/api/auth/login", json={"email": "alice@a.org",
                                              "password": "password1"})
    r = user_client.post(f"/api/projects/{pid}/sync/import-contributions",
                         files={"file": ("c.json", package_bytes,
                                         "application/json")})
    assert r.status_code == 200, r.text
    assert r.json()["votes"]["unchanged"] == 1  # self-import: no-op

    r = user_client.get(f"/api/projects/{pid}/sync/events")
    assert r.status_code == 200
    kinds = {(e["direction"], e["kind"]) for e in r.json()}
    assert ("export", "contributions") in kinds
    assert ("import", "contributions") in kinds


def test_ai_usage_journal_travels_with_contributions():
    """A satellite reviewer's AI calls must reach the coordinator: otherwise
    the project's disclosure statement would describe only the coordinator's
    own AI use and silently omit everyone else's."""
    from app.models import AiUsage

    with SessionLocal() as db:
        p, alice, bob, r1, r2, cfg = _seed(db)
        db.add(AiUsage(project_id=p.id, feature="screening_ta_suggest",
                       provider="anthropic", model="claude-x",
                       user_id=bob.id, day="2026-07-20", n_calls=12,
                       tokens_in=1000, tokens_out=400, cost_usd=0.02,
                       first_at=utcnow(), last_at=utcnow()))
        # alice's own bucket must not leave with bob's package
        db.add(AiUsage(project_id=p.id, feature="title_triage",
                       provider="anthropic", model="claude-x",
                       user_id=alice.id, day="2026-07-20", n_calls=3,
                       tokens_in=100, tokens_out=40, cost_usd=0.01,
                       first_at=utcnow(), last_at=utcnow()))
        db.commit()

        data, _ = build_contributions(db, p, bob)
        assert [u["feature"] for u in data["ai_usage"]] == ["screening_ta_suggest"]
        assert data["ai_usage"][0]["n_calls"] == 12

        db.query(AiUsage).filter_by(user_id=bob.id).delete(
            synchronize_session=False)
        db.commit()

        report = import_contributions(db, data, alice)
        assert report["ai_usage"] == 1
        rows = db.query(AiUsage).filter_by(project_id=p.id).all()
        assert {(r.feature, r.n_calls) for r in rows} == {
            ("screening_ta_suggest", 12), ("title_triage", 3)}

        # re-importing the same package must not double-count the calls
        import_contributions(db, data, alice)
        again = db.query(AiUsage).filter_by(project_id=p.id,
                                            feature="screening_ta_suggest").all()
        assert len(again) == 1 and again[0].n_calls == 12
