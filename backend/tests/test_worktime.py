"""Reviewer work time (roadmap chantier 14): heartbeat folding, estimate from
activity timestamps, admin-only report, own total, sync of the sessions."""
from datetime import datetime, timedelta, timezone

import pytest

from app.core.db import SessionLocal
from app.models import Project, User, Vote, WorkSession
from app.services.worktime.estimate import Act, estimate_sessions
from app.services.worktime.sessions import (
    GAP_S, HEARTBEAT_S, record_heartbeat, session_seconds,
)

T0 = datetime(2026, 10, 1, 9, 0, tzinfo=timezone.utc)  # in the past: sessions are closed


# ---- sessions from heartbeats -------------------------------------------------

def test_heartbeats_fold_into_sessions(user_client):
    project = user_client.post("/api/projects", json={"name": "W"}).json()
    me = user_client.get("/api/auth/me").json()
    with SessionLocal() as db:
        s1 = record_heartbeat(db, project["id"], me["id"], "ta", now=T0)
        s2 = record_heartbeat(db, project["id"], me["id"], "ta",
                              now=T0 + timedelta(seconds=30))
        s3 = record_heartbeat(db, project["id"], me["id"], "ta",
                              now=T0 + timedelta(seconds=60))
        assert s1.id == s2.id == s3.id
        assert s3.n_heartbeats == 3
        assert session_seconds(s3) == 60 + HEARTBEAT_S
        # another stage is another session, even in the same minute
        other = record_heartbeat(db, project["id"], me["id"], "extraction",
                                 now=T0 + timedelta(seconds=60))
        assert other.id != s1.id
        # a beat after the gap opens a new session
        s4 = record_heartbeat(db, project["id"], me["id"], "ta",
                              now=T0 + timedelta(seconds=60 + GAP_S + 1))
        assert s4.id != s1.id
        assert session_seconds(s4) == HEARTBEAT_S
        db.commit()
        assert db.query(WorkSession).filter_by(project_id=project["id"]).count() == 3


def test_unknown_stage_rejected(user_client):
    project = user_client.post("/api/projects", json={"name": "W"}).json()
    r = user_client.post(f"/api/projects/{project['id']}/worktime/heartbeat",
                         json={"stage": "lunch"})
    assert r.status_code == 422


# ---- estimate from activity ---------------------------------------------------

def test_estimate_sessions_gap_cap_and_median():
    # five votes a minute apart, a 7-minute read, then a 30-minute break and
    # two more votes: two sessions, the long read capped at 5 min
    times = [T0 + timedelta(minutes=m) for m in (0, 1, 2, 3, 4, 11)]
    times += [T0 + timedelta(minutes=m) for m in (41, 42)]
    acts = [Act(1, "ta", t, on_record=True) for t in times]
    sessions = estimate_sessions(acts, gap_s=600, cap_s=300)
    assert len(sessions) == 2
    first, second = sessions
    assert first["n_acts"] == 6
    # 4 × 60 s + min(420, 300) + last act = median of the credits (60 s)
    assert first["seconds"] == 4 * 60 + 300 + 60
    assert second["n_acts"] == 2
    assert second["seconds"] == 60 + 60
    assert sorted(first["record_times"]) == [60, 60, 60, 60, 60, 300]


def test_estimate_single_act_and_separate_stages():
    acts = [Act(1, "ta", T0, on_record=True), Act(1, "dedup", T0)]
    sessions = estimate_sessions(acts)
    assert {s["stage"] for s in sessions} == {"ta", "dedup"}
    assert all(s["seconds"] == 60 for s in sessions)


# ---- API: roles ---------------------------------------------------------------

@pytest.fixture
def team_project(user_client):
    user_client.post("/api/auth/register", json={
        "email": "rev@example.com", "password": "password123",
        "display_name": "Reviewer"})
    rev = user_client.get("/api/auth/me").json()
    user_client.post("/api/auth/login", json={
        "email": "admin@example.com", "password": "password123"})
    project = user_client.post("/api/projects", json={"name": "W"}).json()
    user_client.post(f"/api/projects/{project['id']}/members",
                     json={"email": "rev@example.com", "role": "reviewer"})
    return project, rev


def _as(client, email):
    client.post("/api/auth/login", json={"email": email, "password": "password123"})


def test_reviewer_beats_sees_own_total_not_report(user_client, team_project):
    project, rev = team_project
    pid = project["id"]
    _as(user_client, "rev@example.com")
    r = user_client.post(f"/api/projects/{pid}/worktime/heartbeat", json={"stage": "ft"})
    assert r.status_code == 200, r.text
    assert r.json()["session_seconds"] == HEARTBEAT_S
    mine = user_client.get(f"/api/projects/{pid}/worktime/me").json()
    assert mine["total_seconds"] == HEARTBEAT_S
    assert mine["by_stage"]["ft"] == HEARTBEAT_S
    assert user_client.get(f"/api/projects/{pid}/worktime/report").status_code == 403
    assert user_client.get(f"/api/projects/{pid}/worktime/export.csv").status_code == 403

    _as(user_client, "admin@example.com")
    report = user_client.get(f"/api/projects/{pid}/worktime/report").json()
    assert report["source"] == "measured"
    row = next(x for x in report["reviewers"] if x["user_id"] == rev["id"])
    assert row["role"] == "reviewer"
    assert row["by_stage"]["ft"]["seconds"] == HEARTBEAT_S
    assert row["total_seconds"] == HEARTBEAT_S
    assert report["weeks"] and str(rev["id"]) in report["weeks"][0]["by_user"]
    # the admin's own total is what they see on the members panel
    assert user_client.get(f"/api/projects/{pid}/worktime/me").json()["total_seconds"] == 0

    csv_text = user_client.get(f"/api/projects/{pid}/worktime/export.csv").text
    assert "reviewer,stage,day,seconds" in csv_text
    assert "Reviewer,ft," in csv_text

    assert user_client.get(f"/api/projects/{pid}/worktime/report?source=guess").status_code == 422


def test_estimated_report_from_votes(user_client, team_project):
    project, rev = team_project
    pid = project["id"]
    with SessionLocal() as db:
        from app.models import Import, Record, Source
        src = Source(project_id=pid, type="database", name="PubMed")
        db.add(src)
        db.flush()
        imp = Import(project_id=pid, source_id=src.id)
        db.add(imp)
        db.flush()
        for i in range(4):
            rec = Record(project_id=pid, import_id=imp.id, title=f"R{i}",
                         dedup_status="unique")
            db.add(rec)
            db.flush()
            db.add(Vote(project_id=pid, record_id=rec.id, stage="ta", round=1,
                        voter_user_id=rev["id"], decision="include",
                        created_at=T0 + timedelta(seconds=45 * i),
                        updated_at=T0 + timedelta(seconds=45 * i)))
        db.commit()
    report = user_client.get(
        f"/api/projects/{pid}/worktime/report?source=estimated&gap=600&cap=300").json()
    row = next(x for x in report["reviewers"] if x["user_id"] == rev["id"])
    assert row["by_stage"]["ta"]["n_records"] == 4
    assert row["by_stage"]["ta"]["n_sessions"] == 1
    assert row["by_stage"]["ta"]["seconds"] == 3 * 45 + 45  # last act = median credit
    assert row["per_record"]["ta"] == 45
    # measured view of the same project: nothing was beaten, time-per-record
    # still comes from the votes
    measured = user_client.get(f"/api/projects/{pid}/worktime/report").json()
    mrow = next(x for x in measured["reviewers"] if x["user_id"] == rev["id"])
    assert mrow["by_stage"]["ta"]["seconds"] == 0
    assert mrow["per_record"]["ta"] == 45


# ---- sync ---------------------------------------------------------------------

def test_sessions_travel_in_contribution_packages(user_client, team_project):
    from app.services.sync.contributions import build_contributions, import_contributions
    project, rev = team_project
    pid = project["id"]
    with SessionLocal() as db:
        p = db.get(Project, pid)
        bob = db.get(User, rev["id"])
        closed = record_heartbeat(db, pid, bob.id, "ta", now=T0)
        record_heartbeat(db, pid, bob.id, "ta", now=T0 + timedelta(seconds=30))
        still_open = record_heartbeat(db, pid, bob.id, "extraction")  # now
        db.commit()
        closed_uuid, open_uuid = closed.uuid, still_open.uuid
        package, _name = build_contributions(db, p, bob)
        db.commit()
    sessions = package["work_sessions"]
    # only closed sessions travel: an open one would change the package every beat
    assert [s["uuid"] for s in sessions] == [closed_uuid]
    assert sessions[0]["stage"] == "ta" and sessions[0]["n_heartbeats"] == 2
    assert open_uuid not in {s["uuid"] for s in sessions}

    # import on a "coordinator" where the row does not exist yet: the package
    # is applied twice, the session is added once
    with SessionLocal() as db:
        db.query(WorkSession).filter_by(uuid=closed_uuid).delete()
        db.commit()
        p = db.get(Project, pid)
        alice = db.query(User).filter_by(email="admin@example.com").one()
        report = import_contributions(db, package, alice)
        assert report["work_sessions"] == {"added": 1, "skipped": 0}
        package["seq"] += 1
        from app.core.instance import get_signing_key
        from app.services.sync import signing
        package.pop("author_signature", None)
        signing.sign_author(get_signing_key(db), package)
        report2 = import_contributions(db, package, alice)
        assert report2["work_sessions"] == {"added": 0, "skipped": 1}
        row = db.query(WorkSession).filter_by(uuid=closed_uuid).one()
        assert row.user_id == rev["id"] and row.imported_from.startswith("rev@example.com")
        assert session_seconds(row) == 30 + HEARTBEAT_S


def test_sessions_in_snapshot_round_trip(user_client, team_project):
    from app.services.sync.serialize import serialize_project
    project, rev = team_project
    with SessionLocal() as db:
        p = db.get(Project, project["id"])
        record_heartbeat(db, p.id, rev["id"], "dedup", now=T0)
        db.commit()
        data = serialize_project(db, p)
    assert len(data["work_sessions"]) == 1
    s = data["work_sessions"][0]
    assert s["email"] == "rev@example.com" and s["stage"] == "dedup"
    assert s["started_at"].startswith("2026-10-01T09:00")
