"""Public replication archive: what it leaves out, pseudonymisation, and that
re-importing it reproduces the review's numbers."""
import json
import time
import zipfile

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.models import FullText, Project, Record, User, Vote
from app.services.prisma.compute import prisma_counts
from app.services.sync.snapshot import (
    SnapshotError, build_snapshot, import_snapshot,
)

from tests.test_sync_snapshot import _build_demo, _wipe_project_and_carla

import pytest


def _public_export(db, pid, pseudonymize=False):
    project = db.get(Project, pid)
    # a raw database export on disk, as an import would have stored it
    raw = get_settings().storage_dir / str(pid) / "ris_raw"
    raw.mkdir(parents=True, exist_ok=True)
    (raw / "pubmed.ris").write_text("TY  - JOUR\nAB  - vendor abstract\nER  -\n")
    alice = db.query(User).filter_by(email="alice@a.org").one()
    version = project.snapshot_version
    path = build_snapshot(db, project, include_pdfs=True, exporter=alice,
                          public=True, pseudonymize=pseudonymize)
    assert project.snapshot_version == version  # publishing is not a new state
    return path


def test_public_archive_leaves_out_what_cannot_be_redistributed():
    with SessionLocal() as db:
        pid = _build_demo(db)
        path = _public_export(db, pid)

    assert path.name.endswith("_public.zip")
    with zipfile.ZipFile(path) as zf:
        names = zf.namelist()
        data = json.loads(zf.read("data.json"))
        manifest = json.loads(zf.read("manifest.json"))
    assert not [n for n in names if n.startswith("files/pdfs/")]
    assert not [n for n in names if n.startswith("files/ris_raw/")]
    assert "credentials.enc" not in names
    assert manifest["includes_pdfs"] is False
    assert manifest["public_replication"]["pseudonymized"] is False
    assert "signature" not in manifest

    records = {r["title"]: r for r in data["records"]}
    assert records["R1"]["abstract"] == "" and records["R1"]["raw_ris"] == ""
    assert records["R1"]["doi"] == "10.1/r1"  # metadata stays
    assert all(not r["translations"] for r in data["records"])
    assert [a["quote"] for a in data["pdf_annotations"]] == [""]
    assert data["pdf_annotations"][0]["note"] == "check"  # the team's own note
    # not pseudonymised: the reviewers are named
    assert {m["email"] for m in data["members"]} == {
        "alice@a.org", "bob@b.org", "carla@c.org"}


def test_public_archive_drops_operational_traces():
    """Work sessions, whose institutional access fetched a paper and why a
    retrieval failed, and an e-mail address a database left in an author
    field: none of it is needed to replicate the review."""
    from app.models import WorkSession
    with SessionLocal() as db:
        pid = _build_demo(db)
        alice = db.query(User).filter_by(email="alice@a.org").one()
        db.add(WorkSession(project_id=pid, user_id=alice.id, stage="title"))
        ft = (db.query(FullText).join(Record)
              .filter(Record.project_id == pid).first())
        ft.via = "institution (Université Exemple)"
        ft.error = "CAS login refused for jdoe"
        rec = db.query(Record).filter_by(project_id=pid, title="R1").one()
        rec.authors = ["De Col, A. (someone@mail.example)", "Smith, J."]
        db.commit()
        path = _public_export(db, pid)

    with zipfile.ZipFile(path) as zf:
        data = json.loads(zf.read("data.json"))
        manifest = json.loads(zf.read("manifest.json"))
        readme = zf.read("README.txt").decode()
    assert data["work_sessions"] == []
    assert [f["via"] for f in data["fulltexts"]] == ["institution"]
    assert [f["error"] for f in data["fulltexts"]] == [""]
    r1 = next(r for r in data["records"] if r["title"] == "R1")
    assert r1["authors"] == ["De Col, A.", "Smith, J."]
    assert "someone@mail.example" not in json.dumps(data)
    removed = manifest["public_replication"]["removed"]
    assert {"work_sessions", "retrieval_diagnostics",
            "emails_in_author_fields"} <= set(removed)
    assert "Pseudonymised: no" in readme and "work_sessions" in readme


def test_pseudonymized_archive_holds_no_address():
    with SessionLocal() as db:
        pid = _build_demo(db)
        path = _public_export(db, pid, pseudonymize=True)

    with zipfile.ZipFile(path) as zf:
        blob = zf.read("data.json").decode() + zf.read("manifest.json").decode()
        data = json.loads(zf.read("data.json"))
        manifest = json.loads(zf.read("manifest.json"))
    for real in ("alice@a.org", "bob@b.org", "carla@c.org", "Alice", "Carla"):
        assert real not in blob, real
    assert manifest["exporter"]["email"] == "reviewer-1@pseudonymized.invalid"
    assert [(m["email"], m["display_name"]) for m in data["members"]] == [
        ("reviewer-1@pseudonymized.invalid", "Reviewer 1"),
        ("reviewer-2@pseudonymized.invalid", "Reviewer 2"),
        ("reviewer-3@pseudonymized.invalid", "Reviewer 3")]
    cfg = data["screening_configs"][0]
    assert set(cfg["weights"]) == {f"reviewer-{i}@pseudonymized.invalid"
                                   for i in (1, 2, 3)}  # keys too
    ai_vote = next(v for v in data["votes"] if v["is_ai"])
    assert ai_vote["generated_by"] == "reviewer-2@pseudonymized.invalid"


def test_reimported_public_archive_reproduces_the_counts():
    with SessionLocal() as db:
        pid = _build_demo(db)
        before = prisma_counts(db, pid)
        n_votes = db.query(Vote).filter_by(project_id=pid).count()
        path = _public_export(db, pid, pseudonymize=True)
        _wipe_project_and_carla(db, pid)

    with SessionLocal() as db:
        bob = db.query(User).filter_by(email="bob@b.org").one()
        report = import_snapshot(db, path, bob, restore_own=True)
        new_pid = report["project_id"]
        assert prisma_counts(db, new_pid) == before
        assert db.query(Vote).filter_by(project_id=new_pid).count() == n_votes
        assert db.query(Record).filter_by(project_id=new_pid).count() == 3
        # the PDF did not travel: the report is to be fetched again
        assert report["pdfs_missing"] == 1
        ft = (db.query(FullText).join(Record)
              .filter(Record.project_id == new_pid).one())
        assert ft.status == "pending" and not ft.file_path


def test_pseudonymize_requires_public():
    with SessionLocal() as db:
        pid = _build_demo(db)
        project = db.get(Project, pid)
        alice = db.query(User).filter_by(email="alice@a.org").one()
        with pytest.raises(SnapshotError):
            build_snapshot(db, project, include_pdfs=False, exporter=alice,
                           pseudonymize=True)


def test_public_export_via_api(user_client):
    with SessionLocal() as db:
        pid = _build_demo(db)
    r = user_client.post(f"/api/projects/{pid}/sync/export-snapshot",
                         json={"pseudonymize": True})
    assert r.status_code == 400
    r = user_client.post(f"/api/projects/{pid}/sync/export-snapshot",
                         json={"public": True, "pseudonymize": True})
    assert r.status_code == 200, r.text
    job_id = r.json()["job_id"]
    for _ in range(100):
        job = user_client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in ("done", "failed"):
            break
        time.sleep(0.2)
    assert job["status"] == "done", job.get("error")
    assert job["result"]["filename"].endswith("_public.zip")
    r = user_client.get(f"/api/projects/{pid}/sync/snapshot-download",
                        params={"job_id": job_id})
    assert r.status_code == 200 and r.content[:2] == b"PK"
