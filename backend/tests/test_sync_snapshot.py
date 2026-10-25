"""Sync phase 1: snapshot export/import round-trip, update merge, satellite
lock, schema guard, shadow-account claim."""
import json
import zipfile
from datetime import timedelta

import pytest

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.core.security import hash_password
from app.models import (
    Assignment, CitationEdge, Concept, Conflict, CustomDatabase, Equation,
    EquationCount,
    ExtractionColumn, ExtractionConfig, ExtractionValue, FullText, GoldenRef,
    Import, JbiAppraisal, PdfAnnotation, Project, ProjectMember, Protocol,
    Record, RecordTag, ResultsSynthesis, ScreeningConfig, ScreeningLot,
    SnowballRun, Source, Tag, User, Vote,
)
from app.models.accounts import utcnow
from app.services.sync.serialize import serialize_project
from app.services.sync.snapshot import (
    SnapshotError, build_snapshot, import_snapshot, read_manifest,
)


def _deep_sort(obj):
    if isinstance(obj, dict):
        return {k: _deep_sort(v) for k, v in obj.items()}
    if isinstance(obj, list):
        items = [_deep_sort(x) for x in obj]
        return sorted(items, key=lambda x: json.dumps(x, sort_keys=True,
                                                      default=str))
    return obj


def _build_demo(db) -> int:
    """Small but complete project graph: 3 users (carla will be deleted to
    simulate a remote-only member), records, votes incl. AI, conflict,
    extraction, JBI, annotation, tags, snowballing, fulltext with a real file,
    and a database the project declared itself."""
    alice = User(email="alice@a.org", password_hash=hash_password("password1"),
                 display_name="Alice", is_admin=True)
    bob = User(email="bob@b.org", password_hash=hash_password("password2"),
               display_name="Bob")
    carla = User(email="carla@c.org", password_hash=hash_password("password3"),
                 display_name="Carla")
    db.add_all([alice, bob, carla])
    db.flush()

    p = Project(name="Demo SLR", description="d", research_question="rq",
                highlights={"green": ["robot"], "red": ["rat"]})
    db.add(p)
    db.flush()
    db.add_all([ProjectMember(project_id=p.id, user_id=alice.id, role="admin"),
                ProjectMember(project_id=p.id, user_id=bob.id,
                              role="reviewer"),
                ProjectMember(project_id=p.id, user_id=carla.id,
                              role="reviewer")])

    db.add(Protocol(project_id=p.id, version=1, protocol_md="# proto",
                    criteria=[{"code": "I1", "type": "include",
                               "label": "topic", "description": ""}],
                    validated_at=utcnow()))
    db.add(Concept(project_id=p.id, name="C1", keywords=["a", "b"]))
    db.add(CustomDatabase(project_id=p.id, db_id="cairn-info", label="Cairn.info",
                          syntax="generic", instructions="Recherche avancée.",
                          url="https://www.cairn.info"))
    eq = Equation(project_id=p.id, label="broad", structure={"x": 1},
                  translations={"PubMed": "a AND b"}, status="frozen",
                  frozen_at=utcnow())
    db.add(eq)
    db.flush()
    db.add(EquationCount(equation_id=eq.id, database_name="PubMed", count=42))
    db.add(GoldenRef(project_id=p.id, doi="10.1/x", title="Golden"))

    src = Source(project_id=p.id, type="database", name="PubMed")
    db.add(src)
    db.flush()
    imp = Import(project_id=p.id, source_id=src.id, equation_id=eq.id,
                 filename="pubmed.ris", n_records=3, imported_by=alice.id)
    db.add(imp)
    db.flush()

    r1 = Record(project_id=p.id, import_id=imp.id, doi="10.1/r1",
                title="R1", abstract="abs1", dedup_status="unique",
                authors=["X", "Y"], year=2024)
    r2 = Record(project_id=p.id, import_id=imp.id, doi="10.1/r2",
                title="R2", dedup_status="unique", year=2023)
    r3 = Record(project_id=p.id, import_id=imp.id, title="R1 dup",
                dedup_status="duplicate")
    db.add_all([r1, r2, r3])
    db.flush()
    r3.canonical_id = r1.id
    db.add(CitationEdge(project_id=p.id, citing_record_id=r2.id,
                        cited_record_id=r1.id, direction="backward", round=2))
    db.add(SnowballRun(project_id=p.id, round=2, seed_record_ids=[r1.id],
                       n_seeds=1, n_new_records=1))

    cfg = ScreeningConfig(project_id=p.id, stage="ta", round=1,
                          reviewer_ids=[alice.id, bob.id, carla.id],
                          status="active", started_at=utcnow(),
                          ai_enabled=True, ai_reveal="after_vote",
                          # R2a lot settings travel too (keyed by e-mail)
                          weights={str(alice.id): 40, str(bob.id): 30,
                                   str(carla.id): 30},
                          lot_size=50, arbiter_ids=[alice.id])
    db.add(cfg)
    db.flush()
    lot = ScreeningLot(config_id=cfg.id, index=1, user_ids=[alice.id, bob.id],
                       due_at=utcnow() + timedelta(days=30))
    db.add(lot)
    db.flush()
    for user in (alice, bob, carla):
        for record in (r1, r2):
            db.add(Assignment(config_id=cfg.id, record_id=record.id,
                              user_id=user.id,
                              lot_id=lot.id if user is not carla else None,
                              skipped_at=utcnow() if user is bob
                              and record is r2 else None))
    db.add(Vote(project_id=p.id, record_id=r1.id, stage="ta", round=1,
                voter_user_id=alice.id, decision="include"))
    db.add(Vote(project_id=p.id, record_id=r1.id, stage="ta", round=1,
                voter_user_id=bob.id, decision="exclude", reasons=["E1"],
                justification="off topic"))
    db.add(Vote(project_id=p.id, record_id=r1.id, stage="ta", round=1,
                voter_user_id=carla.id, decision="include"))
    db.add(Vote(project_id=p.id, record_id=r1.id, stage="ta", round=1,
                voter_user_id=None, is_ai=True, decision="include",
                confidence=0.9, generated_by="bob@b.org"))
    # carla looked at the AI suggestion before voting — travels like a vote
    from app.models import AiReveal
    db.add(AiReveal(project_id=p.id, record_id=r1.id, stage="ta", round=1,
                    user_id=carla.id))
    db.add(Conflict(project_id=p.id, record_id=r1.id, stage="ta", round=1,
                    status="resolved", resolution="include",
                    resolution_note="discussed", resolved_by=alice.id,
                    resolved_at=utcnow()))

    ft = FullText(record_id=r1.id, status="retrieved", filename="r1.pdf",
                  via="unpaywall", size_kb=10)
    db.add(ft)
    db.flush()
    pdf_dir = get_settings().storage_dir / str(p.id) / "pdfs"
    pdf_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = pdf_dir / f"{r1.id}.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 fake")
    ft.file_path = str(pdf_path)

    col = ExtractionColumn(project_id=p.id, name="Population",
                           col_type="text")
    db.add(col)
    db.flush()
    xcfg = ExtractionConfig(project_id=p.id, n_extractors=1,
                            extractor_ids=[bob.id], status="active")
    db.add(xcfg)
    from app.models import ExtractionStudy
    study = ExtractionStudy(record_id=r1.id, label="Study 1", position=0,
                            study_design="rct", design_origin="human")
    db.add(study)
    db.flush()
    db.add(ExtractionValue(record_id=r1.id, study_id=study.id, column_id=col.id,
                           user_id=bob.id, value={"v": "n=30"}, validated=True))
    db.add(JbiAppraisal(record_id=r1.id, study_id=study.id, user_id=bob.id,
                        design="rct", answers={"q1": {"answer": "yes"}},
                        overall="include"))
    db.add(PdfAnnotation(project_id=p.id, record_id=r1.id, user_id=bob.id,
                         page=1, rects=[{"x": 0.1, "y": 0.2, "w": 0.3,
                                         "h": 0.05}], quote="methods",
                         note="check"))

    tag = Tag(project_id=p.id, name="intro-material", created_by=carla.id)
    db.add(tag)
    db.flush()
    db.add(RecordTag(tag_id=tag.id, record_id=r2.id, created_by=carla.id))
    db.add(ResultsSynthesis(project_id=p.id, content_md="## synthesis",
                            provider="anthropic", model="m",
                            generated_by=alice.id))
    db.commit()
    return p.id


def _wipe_project_and_carla(db, project_id: int):
    """Simulate a second instance: the project and carla's account are gone."""
    project = db.get(Project, project_id)
    db.delete(project)
    carla = db.query(User).filter_by(email="carla@c.org").first()
    if carla:
        db.delete(carla)
    db.commit()


def _export(db, project_id: int) -> tuple:
    project = db.get(Project, project_id)
    alice = db.query(User).filter_by(email="alice@a.org").one()
    snap_before = serialize_project(db, project)
    path = build_snapshot(db, project, include_pdfs=True, exporter=alice)
    return snap_before, path


def test_round_trip_is_identical():
    with SessionLocal() as db:
        pid = _build_demo(db)
        snap_before, path = _export(db, pid)
        _wipe_project_and_carla(db, pid)

    with SessionLocal() as db:
        bob = db.query(User).filter_by(email="bob@b.org").one()
        report = import_snapshot(db, path, bob)
        assert report["mode"] == "create"
        assert report["shadow_users"] == ["carla@c.org"]
        assert report["pdfs_missing"] == 0
        assert report["quarantined_count"] == 0

        project = db.get(Project, report["project_id"])
        assert project.sync_role == "satellite"
        assert project.coordinator_email == "alice@a.org"
        assert project.uuid == snap_before["project"]["uuid"]

        # carla exists again as a non-loggable shadow with her display name
        carla = db.query(User).filter_by(email="carla@c.org").one()
        assert carla.password_hash == ""
        assert carla.display_name == "Carla"

        # the acceptance criterion: re-serializing the imported project gives
        # exactly the state that was exported
        snap_after = serialize_project(db, project)
        assert _deep_sort(snap_after) == _deep_sort(snap_before)

        # the PDF travelled and is linked to the new record id
        ft = (db.query(FullText).join(Record)
              .filter(Record.project_id == project.id).one())
        assert ft.status == "retrieved"
        assert ft.file_path and open(ft.file_path, "rb").read().startswith(
            b"%PDF")


def test_pipeline_progress_survives_the_round_trip():
    """Field bug: after importing a snapshot taken at the full-text stage, the
    satellite's pipeline menu showed T/A screening as still current."""
    from app.models.accounts import utcnow as _utcnow
    from app.services.progress import project_progress

    with SessionLocal() as db:
        pid = _build_demo(db)
        # complete the T/A round: the demo leaves r2 unvoted — everyone
        # includes it, so outcomes = {r1: resolved include, r2: unanimous}
        r2 = db.query(Record).filter_by(project_id=pid, title="R2").one()
        for email in ("alice@a.org", "bob@b.org", "carla@c.org"):
            user = db.query(User).filter_by(email=email).one()
            db.add(Vote(project_id=pid, record_id=r2.id, stage="ta", round=1,
                        voter_user_id=user.id, decision="include"))
        # the coordinator is now at the FT stage
        alice = db.query(User).filter_by(email="alice@a.org").one()
        bob = db.query(User).filter_by(email="bob@b.org").one()
        ft_cfg = ScreeningConfig(project_id=pid, stage="ft", round=1,
                                 reviewer_ids=[alice.id, bob.id],
                                 status="active", started_at=_utcnow())
        db.add(ft_cfg)
        db.commit()

        before = project_progress(db, pid)
        assert "screening" in before["done"], before
        _, path = _export(db, pid)
        _wipe_project_and_carla(db, pid)

    with SessionLocal() as db:
        bob = db.query(User).filter_by(email="bob@b.org").one()
        report = import_snapshot(db, path, bob)
        after = project_progress(db, report["project_id"])
        assert after["current"] == before["current"], (before, after)
        assert after["done"] == before["done"]
        assert after["rounds"] == before["rounds"]


def test_update_preserves_newer_local_votes_and_reuses_pdfs():
    with SessionLocal() as db:
        pid = _build_demo(db)
        _, path = _export(db, pid)
        _wipe_project_and_carla(db, pid)

    with SessionLocal() as db:
        bob = db.query(User).filter_by(email="bob@b.org").one()
        report = import_snapshot(db, path, bob)
        new_pid = report["project_id"]

        # bob revises his vote locally after the import
        vote = (db.query(Vote)
                .filter_by(project_id=new_pid, voter_user_id=bob.id,
                           is_ai=False).one())
        vote.decision = "include"
        vote.justification = "changed my mind"
        vote.updated_at = utcnow() + timedelta(seconds=5)
        db.commit()

    # non-admin member cannot apply an update
    with SessionLocal() as db:
        bob = db.query(User).filter_by(email="bob@b.org").one()
        with pytest.raises(SnapshotError):
            import_snapshot(db, path, bob)

    with SessionLocal() as db:
        alice = db.query(User).filter_by(email="alice@a.org").one()
        report = import_snapshot(db, path, alice)
        assert report["mode"] == "update"
        assert report["kept_local"]["votes"] == 1

        bob = db.query(User).filter_by(email="bob@b.org").one()
        vote = (db.query(Vote)
                .filter_by(project_id=report["project_id"],
                           voter_user_id=bob.id, is_ai=False).one())
        assert vote.decision == "include"          # local newer version kept
        assert vote.justification == "changed my mind"

        # a satellite re-export without PDFs, applied as update, must keep the
        # stored file through the pdfs_old reuse path
        project = db.get(Project, report["project_id"])
        path2 = build_snapshot(db, project, include_pdfs=False, exporter=alice)
        report2 = import_snapshot(db, path2, alice)
        assert report2["mode"] == "update"
        assert report2["pdfs_missing"] == 0
        ft = (db.query(FullText).join(Record)
              .filter(Record.project_id == report2["project_id"]).one())
        assert ft.status == "retrieved"
        assert ft.file_path and open(ft.file_path, "rb").read().startswith(
            b"%PDF")


def test_satellite_lock_blocks_structural_allows_contributions(user_client):
    with SessionLocal() as db:
        pid = _build_demo(db)
        _, path = _export(db, pid)
        _wipe_project_and_carla(db, pid)
        bob = db.query(User).filter_by(email="bob@b.org").one()
        report = import_snapshot(db, path, bob)
        new_pid = report["project_id"]
        record_id = (db.query(Record)
                     .filter_by(project_id=new_pid, title="R1").one().id)

    client = user_client  # logged in as app admin (member added on import? no)
    # structural writes are locked on the satellite
    r = client.put(f"/api/projects/{new_pid}/highlights",
                   json={"green": ["x"], "red": []})
    assert r.status_code == 403
    r = client.post(f"/api/projects/{new_pid}/concepts",
                    json={"name": "nope"})
    assert r.status_code == 403
    # tags are NOT locked: they are per-reviewer contributions that ride the
    # contribution packages back to the coordinator
    r = client.post(f"/api/projects/{new_pid}/tags", json={"name": "t"})
    assert r.status_code == 200
    # per-user contributions still work (annotation on a record)
    r = client.post(
        f"/api/projects/{new_pid}/records/{record_id}/annotations",
        json={"page": 1, "rects": [{"x": 0.1, "y": 0.1, "w": 0.2, "h": 0.1}],
              "quote": "q", "note": "n", "color": "yellow"})
    assert r.status_code == 200, r.text
    # reads pass
    assert client.get(f"/api/projects/{new_pid}/sync").status_code == 200


def test_refuses_newer_schema_and_coordinator_overwrite(tmp_path):
    with SessionLocal() as db:
        pid = _build_demo(db)
        project = db.get(Project, pid)
        alice = db.query(User).filter_by(email="alice@a.org").one()
        path = build_snapshot(db, project, include_pdfs=False, exporter=alice)

        # importing the archive onto its own coordinator project is refused
        with pytest.raises(SnapshotError, match="coordinateur"):
            import_snapshot(db, path, alice)

    # an archive claiming an unknown (newer) schema revision is refused
    bogus = tmp_path / "bogus.zip"
    with zipfile.ZipFile(path) as src, zipfile.ZipFile(bogus, "w") as dst:
        for name in src.namelist():
            payload = src.read(name)
            if name == "manifest.json":
                manifest = json.loads(payload)
                manifest["schema_revision"] = "ffffffffffff"
                payload = json.dumps(manifest)
            dst.writestr(name, payload)
    with pytest.raises(SnapshotError, match="récent"):
        read_manifest(bogus)


def test_restore_own_backup_on_coordinator():
    """restore_own: a coordinator project may be overwritten by its own backup;
    it stays coordinator and work done after the export is discarded (the
    archive is the reference — nothing is merged back)."""
    with SessionLocal() as db:
        pid = _build_demo(db)
        project = db.get(Project, pid)
        alice = db.query(User).filter_by(email="alice@a.org").one()
        path = build_snapshot(db, project, include_pdfs=True, exporter=alice)
        version = project.snapshot_version
        # work after the backup: a vote the restore must discard
        r2 = db.query(Record).filter_by(project_id=pid, title="R2").one()
        db.add(Vote(project_id=pid, record_id=r2.id, stage="ta", round=1,
                    voter_user_id=alice.id, decision="exclude"))
        db.commit()

        report = import_snapshot(db, path, alice, restore_own=True)
        assert report["mode"] == "update"
        assert report["restored"] is True
        project = db.get(Project, report["project_id"])
        assert project.sync_role == "coordinator"
        assert project.coordinator_email == ""
        assert project.snapshot_version == version
        post_export_votes = (
            db.query(Vote).join(Record, Record.id == Vote.record_id)
            .filter(Record.project_id == project.id, Record.title == "R2",
                    Vote.stage == "ta").count())
        assert post_export_votes == 0


def test_restore_own_create_yields_coordinator():
    """Restoring a backup on a fresh instance (project gone) must give back a
    project the owner administers — coordinator, not a locked satellite."""
    with SessionLocal() as db:
        pid = _build_demo(db)
        _, path = _export(db, pid)
        _wipe_project_and_carla(db, pid)

    with SessionLocal() as db:
        bob = db.query(User).filter_by(email="bob@b.org").one()
        report = import_snapshot(db, path, bob, restore_own=True)
        assert report["mode"] == "create"
        assert report["restored"] is True
        project = db.get(Project, report["project_id"])
        assert project.sync_role == "coordinator"
        assert project.coordinator_email == ""


def test_shadow_account_claim(client):
    with SessionLocal() as db:
        pid = _build_demo(db)
        _, path = _export(db, pid)
        _wipe_project_and_carla(db, pid)
        bob = db.query(User).filter_by(email="bob@b.org").one()
        import_snapshot(db, path, bob)

    # carla cannot log in on the shadow account
    r = client.post("/api/auth/login", json={"email": "carla@c.org",
                                             "password": "whatever123"})
    assert r.status_code == 401
    # registering with her email claims the shadow: memberships stay
    r = client.post("/api/auth/register", json={
        "email": "carla@c.org", "password": "newpassword1",
        "display_name": "Carla R."})
    assert r.status_code == 200, r.text
    with SessionLocal() as db:
        carla = db.query(User).filter_by(email="carla@c.org").one()
        assert carla.password_hash != ""
        assert db.query(ProjectMember).filter_by(user_id=carla.id).count() == 1
        assert db.query(Vote).filter_by(voter_user_id=carla.id).count() == 1


def test_export_import_via_api(user_client):
    import time
    with SessionLocal() as db:
        pid = _build_demo(db)

    # admin@example.com (app admin) exports through the API
    r = user_client.post(f"/api/projects/{pid}/sync/export-snapshot",
                         json={"include_pdfs": True})
    assert r.status_code == 200, r.text
    job_id = r.json()["job_id"]
    for _ in range(100):
        job = user_client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in ("done", "failed"):
            break
        time.sleep(0.2)
    assert job["status"] == "done", job.get("error")

    r = user_client.get(f"/api/projects/{pid}/sync/snapshot-download",
                        params={"job_id": job_id})
    assert r.status_code == 200
    assert r.content[:2] == b"PK"  # zip magic

    with SessionLocal() as db:
        _wipe_project_and_carla(db, pid)

    r = user_client.post("/api/sync/import-snapshot",
                         files={"file": ("snap.zip", r.content,
                                         "application/zip")})
    assert r.status_code == 200, r.text
    job_id = r.json()["job_id"]
    for _ in range(100):
        job = user_client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in ("done", "failed"):
            break
        time.sleep(0.2)
    assert job["status"] == "done", job.get("error")
    assert job["result"]["mode"] == "create"
    with SessionLocal() as db:
        project = db.get(Project, job["result"]["project_id"])
        assert project.sync_role == "satellite"
        assert db.query(Record).filter_by(project_id=project.id).count() == 3


def _tamper(path, edit):
    """Rewrite data.json inside a snapshot zip (a forged archive)."""
    with zipfile.ZipFile(path) as zf:
        members = {n: zf.read(n) for n in zf.namelist()}
    data = json.loads(members["data.json"])
    edit(data)
    members["data.json"] = json.dumps(data).encode()
    with zipfile.ZipFile(path, "w") as zf:
        for name, raw in members.items():
            zf.writestr(name, raw)


def test_a_forged_file_name_cannot_pull_a_server_file_into_an_export(tmp_path):
    """A create-mode import stores the archive's file names; the next export
    reads storage/<name>. A path there (absolute or ../) must not put a file
    from elsewhere on the server — secret.key, the database — into the zip."""
    secret = tmp_path / "secret.key"
    secret.write_bytes(b"TOP-SECRET-SENTINEL")
    with SessionLocal() as db:
        pid = _build_demo(db)
        _, path = _export(db, pid)
        _wipe_project_and_carla(db, pid)

    def forge(data):
        data["imports"][0]["filename"] = str(secret)
        data["protocols"][0]["source_filename"] = "../../../../secret.key"

    _tamper(path, forge)
    with SessionLocal() as db:
        bob = db.query(User).filter_by(email="bob@b.org").one()
        report = import_snapshot(db, path, bob)
        project = db.get(Project, report["project_id"])
        assert {i.filename for i in db.query(Import)
                .filter_by(project_id=project.id)} == {"secret.key"}
        # a name stored before this check existed is not trusted either
        db.query(Import).filter_by(project_id=project.id).update(
            {"filename": str(secret)})
        db.commit()
        out = build_snapshot(db, project, include_pdfs=True, exporter=bob)
    with zipfile.ZipFile(out) as zf:
        assert not any(b"TOP-SECRET-SENTINEL" in zf.read(n)
                       for n in zf.namelist())
