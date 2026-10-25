"""Anonymous reviewers: while an anonymous round runs, nobody — the admins
included — sees who voted what nor who is paired with whom; the names come
back once the round is complete. Plus the blind leaks closed with it
(notes, PDF annotations, reviewer-mode triage votes)."""
from tests.test_screening import _login, _setup, project, team  # noqa: F401


def _ids(client, pid, stage="ta"):
    queue = client.get(f"/api/projects/{pid}/screening/queue?stage={stage}").json()
    return [i["id"] for i in queue["items"]]


def _vote(client, pid, who, record_id, decision, stage="ta", note=""):
    _login(client, who)
    r = client.post(f"/api/projects/{pid}/screening/vote?stage={stage}",
                    json={"record_id": record_id, "decision": decision,
                          "justification": note})
    assert r.status_code == 200, r.text
    return r.json()


def test_anonymous_round_hides_names_until_complete(user_client, team, project):
    pid = project["id"]
    _setup(user_client, pid, team, anonymous=True)
    info = user_client.get(f"/api/projects/{pid}/screening/config").json()
    assert info["config"]["anonymous"] is True
    assert info["names_hidden"] is True
    ids = _ids(user_client, pid)

    # one conflict, one unanimous record: four other assignments still open
    _vote(user_client, pid, "admin", ids[0], "include", note="admin says yes")
    _vote(user_client, pid, "reviewer", ids[0], "exclude", note="rev says no")
    _vote(user_client, pid, "admin", ids[1], "include")
    _vote(user_client, pid, "reviewer", ids[1], "include")

    # the admin — the arbiter — sees pseudonyms, and their own vote flagged
    _login(user_client, "admin")
    conflicts = user_client.get(f"/api/projects/{pid}/screening/conflicts").json()
    assert len(conflicts) == 1
    votes = conflicts[0]["votes"]
    assert {v["reviewer"] for v in votes} == {"Reviewer 1", "Reviewer 2"}
    assert sorted(v["mine"] for v in votes) == [False, True]
    mine = next(v for v in votes if v["mine"])
    assert mine["decision"] == "include"
    # no real name anywhere in the payload
    assert "Admin" not in str(conflicts) and "Reviewer\"" not in str(conflicts)

    # the same pseudonym for everyone: the reviewer sees the same labels
    _login(user_client, "reviewer")
    rev_conflicts = user_client.get(
        f"/api/projects/{pid}/screening/conflicts").json()
    rev_mine = next(v for v in rev_conflicts[0]["votes"] if v["mine"])
    assert rev_mine["decision"] == "exclude"
    assert rev_mine["reviewer"] != mine["reviewer"]
    by_label = {v["reviewer"]: v["decision"] for v in votes}
    assert {v["reviewer"]: v["decision"] for v in rev_conflicts[0]["votes"]} == by_label

    # stats: pseudonyms, opaque ids that cannot be matched on the roster
    stats = user_client.get(f"/api/projects/{pid}/screening/stats").json()
    assert stats["names_hidden"] is True
    names = {r["display_name"] for r in stats["per_reviewer"]}
    assert names == {"Reviewer 1", "Reviewer 2"}
    assert all(r["user_id"] < 0 for r in stats["per_reviewer"])
    matrix = stats["agreement"]["matrix"]
    assert {matrix["rows_name"], matrix["cols_name"]} == names
    assert matrix["rows_user_id"] < 0 and matrix["cols_user_id"] < 0
    pair = stats["agreement"]["pairs"][0]
    assert pair["rows_user_id"] < 0 and pair["rows_name"] in names

    # resolving the conflict keeps the names hidden: other records are open
    r = user_client.post(
        f"/api/projects/{pid}/screening/conflicts/{conflicts[0]['id']}/resolve",
        json={"decision": "include", "note": "settled"})
    assert r.status_code == 200
    resolved = user_client.get(
        f"/api/projects/{pid}/screening/conflicts?status=resolved").json()
    assert resolved[0]["resolved_by"] in names

    # PRISMA reviewer activity is withheld, notes carry pseudonyms
    prisma = user_client.get(f"/api/projects/{pid}/prisma/reviewers").json()
    assert prisma["withheld"] is True and prisma["reviewers"] == []
    notes = user_client.get(f"/api/projects/{pid}/notes").json()
    assert {n["author"] for n in notes} <= names | {"Reviewer ?"}
    assert "Admin" not in str(notes)

    # the option is frozen: the config is locked once the round runs
    _login(user_client, "admin")
    r = user_client.put(f"/api/projects/{pid}/screening/config", json={
        "stage": "ta", "allocation": "all", "anonymous": False,
        "reviewer_ids": [team["admin"]["id"], team["reviewer"]["id"]]})
    assert r.status_code == 400

    # finish the round: every record voted, no open conflict -> names return
    for rid in ids[2:]:
        _vote(user_client, pid, "admin", rid, "exclude")
        _vote(user_client, pid, "reviewer", rid, "exclude")
    _login(user_client, "reviewer")
    info = user_client.get(f"/api/projects/{pid}/screening/config").json()
    assert info["names_hidden"] is False
    stats = user_client.get(f"/api/projects/{pid}/screening/stats").json()
    assert {r["display_name"] for r in stats["per_reviewer"]} == {"Admin", "Reviewer"}
    assert all(r["user_id"] > 0 for r in stats["per_reviewer"])
    resolved = user_client.get(
        f"/api/projects/{pid}/screening/conflicts?status=resolved").json()
    assert {v["reviewer"] for v in resolved[0]["votes"]} == {"Admin", "Reviewer"}
    assert resolved[0]["resolved_by"] == "Reviewer"
    prisma = user_client.get(f"/api/projects/{pid}/prisma/reviewers").json()
    assert prisma["withheld"] is False and len(prisma["reviewers"]) == 2


def test_named_round_is_unchanged(user_client, team, project):
    pid = project["id"]
    _setup(user_client, pid, team)
    info = user_client.get(f"/api/projects/{pid}/screening/config").json()
    assert info["config"]["anonymous"] is False
    assert info["names_hidden"] is False
    ids = _ids(user_client, pid)
    _vote(user_client, pid, "admin", ids[0], "include")
    _vote(user_client, pid, "reviewer", ids[0], "exclude")
    conflicts = user_client.get(f"/api/projects/{pid}/screening/conflicts").json()
    assert {v["reviewer"] for v in conflicts[0]["votes"]} == {"Admin", "Reviewer"}
    stats = user_client.get(f"/api/projects/{pid}/screening/stats").json()
    assert stats["names_hidden"] is False
    assert all(r["user_id"] > 0 for r in stats["per_reviewer"])


def test_lead_is_hidden_from_co_reviewers_while_anonymous(user_client, team,
                                                          project):
    pid = project["id"]
    _setup(user_client, pid, team, allocation="lead", anonymous=True,
           lead_user_id=team["admin"]["id"])
    _login(user_client, "reviewer")
    info = user_client.get(f"/api/projects/{pid}/screening/config").json()
    assert info["config"]["lead_user_id"] is None
    stats = user_client.get(f"/api/projects/{pid}/screening/stats").json()
    assert stats["lead_user_id"] < 0
    assert all(s["user_id"] < 0 for s in stats["shares"])
    # the admin who picked the lead keeps it in the config
    _login(user_client, "admin")
    info = user_client.get(f"/api/projects/{pid}/screening/config").json()
    assert info["config"]["lead_user_id"] == team["admin"]["id"]


def test_notes_are_blind_until_the_record_is_complete(user_client, team, project):
    """Independent of anonymity: a justification is listed to a co-reviewer
    only once the record is complete — their own shows right away."""
    pid = project["id"]
    _setup(user_client, pid, team)
    ids = _ids(user_client, pid)
    _vote(user_client, pid, "admin", ids[0], "include", note="first look")
    # the reviewer has not voted on this record: nothing to see yet
    _login(user_client, "reviewer")
    assert user_client.get(f"/api/projects/{pid}/notes").json() == []
    # the admin sees their own note
    _login(user_client, "admin")
    notes = user_client.get(f"/api/projects/{pid}/notes").json()
    assert [n["note"] for n in notes] == ["first look"]
    # complete -> both see it, with the author's name (named round)
    _vote(user_client, pid, "reviewer", ids[0], "include")
    notes = user_client.get(f"/api/projects/{pid}/notes").json()
    assert notes[0]["author"] == "Admin"
    csv = user_client.get(f"/api/projects/{pid}/notes/export.csv").text
    assert "first look" in csv


def test_triage_audit_hides_open_reviewer_votes(user_client, team, project):
    """A reviewer-mode triage vote (an exclude vote tagged by the triage) is
    listed to others only once its record is complete."""
    pid = project["id"]
    _setup(user_client, pid, team)
    ids = _ids(user_client, pid)
    _vote(user_client, pid, "admin", ids[0], "exclude",
          note="AI title triage — validated")
    _login(user_client, "reviewer")
    assert user_client.get(f"/api/projects/{pid}/screening/auto-excluded").json() == []
    _login(user_client, "admin")
    rows = user_client.get(f"/api/projects/{pid}/screening/auto-excluded").json()
    assert len(rows) == 1 and rows[0]["validated_by"] == "Admin"
    _vote(user_client, pid, "reviewer", ids[0], "exclude")
    rows = user_client.get(f"/api/projects/{pid}/screening/auto-excluded").json()
    assert len(rows) == 1


def test_snowballing_copy_and_sync_carry_the_option(user_client, team, project):
    from app.core.db import SessionLocal
    from app.models import ScreeningConfig
    from app.services.snowballing.jobs import _copy_config
    from app.services.sync.serialize import serialize_project

    pid = project["id"]
    _setup(user_client, pid, team, allocation="lead", anonymous=True,
           lead_user_id=team["admin"]["id"])
    with SessionLocal() as db:
        nxt = _copy_config(db, pid, "ta", 2)
        assert nxt.anonymous is True
        assert nxt.lead_user_id == team["admin"]["id"]
        from app.models import Project
        snapshot = serialize_project(db, db.get(Project, pid))
        cfg = snapshot["screening_configs"][0]
        assert cfg["anonymous"] is True
        assert cfg["lead_email"] == "admin@example.com"
        db.rollback()
        assert db.query(ScreeningConfig).filter_by(project_id=pid).count() >= 1
