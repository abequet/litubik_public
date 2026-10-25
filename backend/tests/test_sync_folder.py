"""Sync phase 4: shared-folder transport — outbound push with change
detection, inbound import with seq cursor, publish, folder state, guards."""
import json

from app.core.crypto import encrypt_secret
from app.core.db import SessionLocal
from app.core.security import hash_password
from app.models import (
    Assignment, Import, Project, ProjectInvitation, ProjectMember, Record,
    ScreeningConfig, Source, SyncEvent, User, Vote,
)
from app.models.accounts import utcnow
from app.services.sync import signing
from app.services.sync.folder import (
    folder_state, publish_snapshot_to_folder, scan_project,
)

FOLDER_PASSPHRASE = "shared-folder-passphrase-123"


def _seed(db, folder: str):
    from pathlib import Path
    Path(folder).mkdir(parents=True, exist_ok=True)
    alice = User(email="alice@a.org", password_hash=hash_password("password1"),
                 display_name="Alice", is_admin=True)
    db.add(alice)
    db.flush()
    p = Project(name="P", sync_dir=folder)
    db.add(p)
    db.flush()
    db.add(ProjectMember(project_id=p.id, user_id=alice.id, role="admin"))
    src = Source(project_id=p.id, type="database", name="PubMed")
    db.add(src)
    db.flush()
    imp = Import(project_id=p.id, source_id=src.id)
    db.add(imp)
    db.flush()
    r1 = Record(project_id=p.id, import_id=imp.id, title="R1",
                dedup_status="unique")
    db.add(r1)
    db.flush()
    cfg = ScreeningConfig(project_id=p.id, stage="ta", round=1,
                          reviewer_ids=[alice.id], status="active",
                          started_at=utcnow())
    db.add(cfg)
    db.flush()
    db.add(Assignment(config_id=cfg.id, record_id=r1.id, user_id=alice.id))
    db.add(Vote(project_id=p.id, record_id=r1.id, stage="ta", round=1,
                voter_user_id=alice.id, decision="include"))
    db.commit()
    return p, alice, r1, cfg


def test_outbound_push_with_change_detection(tmp_path):
    folder = tmp_path / "share"
    with SessionLocal() as db:
        p, alice, r1, cfg = _seed(db, str(folder))

        summary = scan_project(db, p, actor=alice)
        assert summary["pushed"] == [{"author": "alice@a.org", "seq": 1}]
        assert (folder / "contributions" / "alice@a.org" / "1.json").exists()
        # coordinator wrote the folder manifest
        manifest = json.loads(
            (folder / "litubik-manifest.json").read_text(encoding="utf-8"))
        assert manifest["project_uuid"] == p.uuid

        # nothing changed -> nothing pushed
        summary = scan_project(db, p, actor=alice)
        assert summary["pushed"] == []

        # a new vote -> a new package
        vote = db.query(Vote).filter_by(voter_user_id=alice.id).one()
        vote.decision = "exclude"
        db.commit()
        summary = scan_project(db, p, actor=alice)
        assert summary["pushed"] == [{"author": "alice@a.org", "seq": 2}]
        assert (folder / "contributions" / "alice@a.org" / "2.json").exists()


def _signed_package(p, r1, seq, decision):
    package = {
        "format": "litubik-contributions", "format_version": 1,
        "project_uuid": p.uuid, "project_name": p.name,
        "author": {"email": "bob@remote.org", "display_name": "Bob",
                   "instance_id": "bob-inst"},
        "seq": seq, "based_on_snapshot_version": 0,
        "exported_at": utcnow().isoformat(),
        "votes": [{"record": r1.uuid, "stage": "ta", "round": 1,
                   "email": "bob@remote.org", "is_ai": False,
                   "decision": decision, "reasons": [],
                   "justification": "", "criteria_eval": {},
                   "confidence": None, "generated_by": None,
                   "created_at": utcnow().isoformat(),
                   "updated_at": utcnow().isoformat()}],
        "jbi": [], "extraction_values": [], "annotations": [],
        "skips": [], "credentials_enc": None,
    }
    # H3: a folder package is only imported if signed with the project
    # passphrase (the same secret bob's remote instance shares out-of-band)
    signing.sign_dict(p, package)
    return package


def test_inbound_import_with_cursor(tmp_path):
    folder = tmp_path / "share"
    with SessionLocal() as db:
        p, alice, r1, cfg = _seed(db, str(folder))
        # bob is a remote member known only by invitation
        db.add(ProjectInvitation(project_id=p.id, email="bob@remote.org",
                                 role="reviewer"))
        cfg.reviewer_ids = [alice.id]
        # H3: folder sync now requires an authenticating passphrase
        p.sync_passphrase_encrypted = encrypt_secret(FOLDER_PASSPHRASE)
        db.commit()

        target = folder / "contributions" / "bob@remote.org" / "1.json"
        target.parent.mkdir(parents=True)
        target.write_text(json.dumps(_signed_package(p, r1, 1, "exclude")),
                          encoding="utf-8")

        summary = scan_project(db, p, actor=alice)
        assert summary["imported"][0]["author"] == "bob@remote.org"
        bob = db.query(User).filter_by(email="bob@remote.org").one()
        assert db.query(Vote).filter_by(voter_user_id=bob.id).count() == 1

        # cursor: same file is not imported twice
        summary = scan_project(db, p, actor=alice)
        assert summary["imported"] == []

        # background scan (no actor) falls back to the local admin
        target2 = folder / "contributions" / "bob@remote.org" / "2.json"
        target2.write_text(json.dumps(_signed_package(p, r1, 2, "include")),
                           encoding="utf-8")
        summary = scan_project(db, p, actor=None)
        assert summary["imported"][0]["seq"] == 2

        # H3: an UNSIGNED / forged package dropped into the folder is refused
        # (folder write access must not let anyone forge votes)
        forged = _signed_package(p, r1, 3, "include")
        forged.pop("signature")
        target3 = folder / "contributions" / "bob@remote.org" / "3.json"
        target3.write_text(json.dumps(forged), encoding="utf-8")
        summary = scan_project(db, p, actor=alice)
        assert summary["imported"] == []
        assert any("non authentifié" in w for w in summary["warnings"])

        # a foreign folder is refused
        manifest_path = folder / "litubik-manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["project_uuid"] = "someone-else"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        summary = scan_project(db, p, actor=alice)
        assert any("autre projet" in w for w in summary["warnings"])


def test_publish_and_folder_state(tmp_path):
    folder = tmp_path / "share"
    with SessionLocal() as db:
        p, alice, r1, cfg = _seed(db, str(folder))
        result = publish_snapshot_to_folder(db, p, alice, include_pdfs=False)
        assert result["version"] == 1
        assert (folder / "snapshots" / "v1.zip").exists()

        state = folder_state(db, p)
        assert state["ok"] and state["latest_snapshot_version"] == 1
        assert not state["update_available"]

        # satellite view: a newer folder snapshot flags an available update
        p.sync_role = "satellite"
        p.snapshot_version = 0
        db.commit()
        state = folder_state(db, p)
        assert state["update_available"]

        # auto-publish mirrors the last export when the folder lags
        p.sync_role = "coordinator"
        p.snapshot_version = 1
        p.sync_auto_publish = True
        db.commit()
        (folder / "snapshots" / "v1.zip").unlink()
        summary = scan_project(db, p, actor=alice)
        assert summary["published"] == 1
        assert (folder / "snapshots" / "v1.zip").exists()


def test_join_folder_one_step_bootstrap(user_client, tmp_path):
    """A co-reviewer points at the shared folder: the latest snapshot there is
    imported AND the project gets linked to the folder in one step."""
    import time
    folder = tmp_path / "share"
    with SessionLocal() as db:
        p, alice, r1, cfg = _seed(db, str(folder))
        publish_snapshot_to_folder(db, p, alice, include_pdfs=False)
        project_uuid = p.uuid
        db.delete(p)  # simulate the co-reviewer's instance
        db.commit()

    # empty folder guard
    r = user_client.post("/api/sync/join-folder",
                         json={"path": str(tmp_path / "wrong")})
    assert r.status_code == 400

    r = user_client.post("/api/sync/join-folder", json={"path": str(folder)})
    assert r.status_code == 200, r.text
    job_id = r.json()["job_id"]
    for _ in range(100):
        job = user_client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in ("done", "failed"):
            break
        time.sleep(0.2)
    assert job["status"] == "done", job.get("error")
    assert job["result"]["folder_linked"] == str(folder)

    with SessionLocal() as db:
        project = db.query(Project).filter_by(uuid=project_uuid).one()
        assert project.sync_role == "satellite"
        assert project.sync_dir == str(folder)
        # the snapshot zip stays in place for the other co-reviewers
        assert (folder / "snapshots" / "v1.zip").exists()


def test_folder_api(user_client, tmp_path):
    project_id = user_client.post("/api/projects",
                                  json={"name": "P"}).json()["id"]
    folder = tmp_path / "share-api"
    r = user_client.post(f"/api/projects/{project_id}/sync/folder",
                         json={"path": str(folder), "auto_publish": False})
    assert r.status_code == 200, r.text
    assert folder.is_dir()

    state = user_client.get(
        f"/api/projects/{project_id}/sync/folder").json()
    assert state["configured"] and state["ok"]

    r = user_client.post(f"/api/projects/{project_id}/sync/folder/scan")
    assert r.status_code == 200
    # the admin's (empty) contribution set was pushed on first scan
    with SessionLocal() as db:
        assert (db.query(SyncEvent)
                .filter_by(project_id=project_id, direction="export",
                           kind="contributions").count() == 1)

    # unlink
    r = user_client.post(f"/api/projects/{project_id}/sync/folder",
                         json={"path": "", "auto_publish": False})
    assert r.status_code == 200
    assert user_client.get(
        f"/api/projects/{project_id}/sync/folder").json()["configured"] is False
