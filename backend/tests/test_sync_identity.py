"""Sync phase 0: cross-instance identity — uuid defaults, sync fields on
projects, instance id stability, vote updated_at/provenance."""
from app.core.db import SessionLocal
from app.core.instance import get_instance_id
from app.models import Import, Project, Record, Source, User, Vote


def _seed(db):
    """User + project + source + import + record (FK chain for votes)."""
    user = User(email="a@example.com", password_hash="x", display_name="A")
    project = Project(name="P")
    db.add_all([user, project])
    db.flush()
    source = Source(project_id=project.id, type="database", name="PubMed")
    db.add(source)
    db.flush()
    imp = Import(project_id=project.id, source_id=source.id)
    db.add(imp)
    db.flush()
    record = Record(project_id=project.id, import_id=imp.id, title="T")
    db.add(record)
    db.commit()
    return user, project, record


def test_project_uuid_and_sync_defaults(user_client):
    user_client.post("/api/projects", json={"name": "P1"})
    user_client.post("/api/projects", json={"name": "P2"})
    with SessionLocal() as db:
        p1, p2 = db.query(Project).order_by(Project.id).all()
        assert len(p1.uuid) == 36
        assert p1.uuid != p2.uuid
        assert p1.sync_role == "coordinator"
        assert p1.coordinator_email == ""
        assert p1.coordinator_instance_id is None
        assert p1.snapshot_version == 0


def test_structural_rows_get_distinct_uuids():
    with SessionLocal() as db:
        _, project, record = _seed(db)
        other = Record(project_id=project.id, import_id=record.import_id,
                       title="T2")
        db.add(other)
        db.commit()
        assert len(record.uuid) == 36
        assert len(project.uuid) == 36
        assert record.uuid != other.uuid


def test_instance_id_stable_across_sessions():
    with SessionLocal() as db:
        first = get_instance_id(db)
    with SessionLocal() as db:
        again = get_instance_id(db)
    assert len(first) == 36
    assert again == first


def test_vote_updated_at_and_ai_provenance():
    with SessionLocal() as db:
        user, project, record = _seed(db)
        vote = Vote(project_id=project.id, record_id=record.id, stage="ta",
                    round=1, voter_user_id=user.id, decision="include")
        db.add(vote)
        db.commit()
        db.refresh(vote)
        assert vote.updated_at is not None
        assert vote.generated_by is None  # set by the sync import (phase 2)
        first = vote.updated_at

        vote.decision = "exclude"
        db.commit()
        db.refresh(vote)
        assert vote.updated_at > first  # onupdate feeds the "newest wins" rule
