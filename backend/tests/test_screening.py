import time

import pytest

from app.services.screening import cohen_kappa, fleiss_kappa

_TITLES = [
    "Gamified speed feedback for young drivers",
    "Serious games in nursing education outcomes",
    "Cycling safety interventions in dense cities",
    "Virtual reality exposure for driving anxiety",
    "Reward schedules and pedestrian attention",
    "Motivation design of fitness applications",
]
RIS = "".join(f"""TY  - JOUR
TI  - {title}
AU  - Author{i}, A.
PY  - 20{10 + i}
DO  - 10.1/screen.{i}
AB  - Abstract of study {i} on gamification and driving.
ER  -
""" for i, title in enumerate(_TITLES, start=1))


# ---- kappa hand-checked -------------------------------------------------------

def test_cohen_kappa_hand_value():
    pairs = ([("include", "include")] * 4 + [("exclude", "exclude")] * 3
             + [("include", "exclude")] + [("exclude", "include")] * 2)
    # po = 0.7, pe = 0.5 -> kappa = 0.4
    assert cohen_kappa(pairs) == pytest.approx(0.4)
    assert cohen_kappa([]) is None
    assert cohen_kappa([("include", "include")]) == 1.0  # pe == 1 edge


def test_fleiss_kappa_canonical_1971_example():
    # Fleiss (1971) / Wikipedia worked example: 10 subjects, 14 raters,
    # 5 categories -> kappa = 0.210
    rows = [
        [0, 0, 0, 0, 14],
        [0, 2, 6, 4, 2],
        [0, 0, 3, 5, 6],
        [0, 3, 9, 2, 0],
        [2, 2, 8, 1, 1],
        [7, 7, 0, 0, 0],
        [3, 2, 6, 3, 0],
        [2, 5, 3, 2, 2],
        [6, 5, 2, 1, 0],
        [0, 2, 2, 3, 7],
    ]
    assert fleiss_kappa(rows) == pytest.approx(0.210, abs=0.001)


def test_fleiss_kappa_prevalence_paradox():
    # 7 unanimous 'include' + 4 split records (the user's real-world case):
    # 64 % raw agreement but kappa is NEGATIVE because chance agreement is
    # huge when almost every vote is 'include'. Expected by design.
    rows = [[2, 0, 0]] * 7 + [[1, 1, 0]] * 4
    assert fleiss_kappa(rows) == pytest.approx(-0.222, abs=0.001)


def test_fleiss_kappa_hand_value():
    # 2 raters, 4 subjects: p_bar = 0.5, pe = 0.5 -> kappa = 0
    rows = [[2, 0, 0], [0, 2, 0], [1, 1, 0], [1, 1, 0]]
    assert fleiss_kappa(rows) == pytest.approx(0.0)
    # perfect agreement
    assert fleiss_kappa([[2, 0, 0], [2, 0, 0], [0, 2, 0]]) == pytest.approx(1.0)
    assert fleiss_kappa([]) is None
    assert fleiss_kappa([[1, 0, 0]]) is None  # single rater


# ---- fixtures -----------------------------------------------------------------

@pytest.fixture
def team(user_client):
    """Admin (logged in) + one reviewer; returns their ids."""
    me = user_client.get("/api/auth/me").json()
    user_client.post("/api/auth/register", json={
        "email": "rev@example.com", "password": "password123",
        "display_name": "Reviewer"})
    rev = user_client.get("/api/auth/me").json()
    user_client.post("/api/auth/login", json={
        "email": "admin@example.com", "password": "password123"})
    return {"admin": me, "reviewer": rev}


@pytest.fixture
def project(user_client, team):
    project = user_client.post("/api/projects", json={"name": "M5 demo"}).json()
    user_client.post(f"/api/projects/{project['id']}/members",
                     json={"email": "rev@example.com", "role": "reviewer"})
    # 6 unique records, deduplicated
    user_client.post(
        f"/api/projects/{project['id']}/imports/upload",
        files={"file": ("s.ris", RIS.encode(), "text/plain")},
        data={"source_name": "pubmed", "source_type": "database"})
    job_id = user_client.post(f"/api/projects/{project['id']}/dedup/run").json()["job_id"]
    for _ in range(100):
        job = user_client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in ("done", "failed"):
            break
        time.sleep(0.05)
    assert job["status"] == "done"
    return project


def _login(client, who):
    email = "admin@example.com" if who == "admin" else "rev@example.com"
    client.post("/api/auth/login", json={"email": email, "password": "password123"})


def _setup(client, pid, team, **overrides):
    payload = {"stage": "ta", "allocation": "all",
               "conflict_resolution": "consensus", "ai_enabled": False,
               "reviewer_ids": [team["admin"]["id"], team["reviewer"]["id"]],
               **overrides}
    r = client.put(f"/api/projects/{pid}/screening/config", json=payload)
    assert r.status_code == 200, r.text
    r = client.post(f"/api/projects/{pid}/screening/start")
    assert r.status_code == 200, r.text
    return r.json()


# ---- flow -----------------------------------------------------------------------

def test_screening_blind_flow_conflicts_stats(user_client, team, project):
    pid = project["id"]
    summary = _setup(user_client, pid, team)
    assert summary == {"records": 6, "reviewers": 2, "double_screened": 6}

    queue = user_client.get(f"/api/projects/{pid}/screening/queue").json()
    assert queue["total"] == 6 and queue["done"] == 0
    ids = [i["id"] for i in queue["items"]]
    # blind: the payload has no vote information at all
    assert all("votes" not in item and "decision" not in item
               for item in queue["items"])

    def vote(who, record_id, decision):
        _login(user_client, who)
        return user_client.post(f"/api/projects/{pid}/screening/vote",
                                json={"record_id": record_id, "decision": decision})

    # r0 unanimous include; r1 disagreement; r2 maybe -> conflict
    assert vote("admin", ids[0], "include").json()["outcome"] is None
    assert vote("reviewer", ids[0], "include").json()["outcome"] == "include"
    vote("admin", ids[1], "include")
    assert vote("reviewer", ids[1], "exclude").json()["outcome"] == "conflict"
    vote("admin", ids[2], "maybe")
    assert vote("reviewer", ids[2], "include").json()["outcome"] == "conflict"

    # voting is closed once complete
    _login(user_client, "admin")
    r = user_client.post(f"/api/projects/{pid}/screening/vote",
                         json={"record_id": ids[0], "decision": "exclude"})
    assert r.status_code == 400

    # reviewer's queue no longer offers the voted records
    _login(user_client, "reviewer")
    queue = user_client.get(f"/api/projects/{pid}/screening/queue").json()
    assert queue["done"] == 3 and len(queue["items"]) == 3

    conflicts = user_client.get(f"/api/projects/{pid}/screening/conflicts").json()
    assert len(conflicts) == 2
    assert all(len(c["votes"]) == 2 for c in conflicts)

    # consensus mode: the reviewer may resolve
    r = user_client.post(
        f"/api/projects/{pid}/screening/conflicts/{conflicts[0]['id']}/resolve",
        json={"decision": "include", "note": "agreed on call"})
    assert r.status_code == 200

    stats = user_client.get(f"/api/projects/{pid}/screening/stats").json()
    assert stats["votes_done"] == 6
    assert stats["included"] == 2      # unanimous + resolved conflict
    assert stats["conflicts_open"] == 1
    assert stats["conflicts_resolved"] == 1
    agreement = stats["agreement"]
    assert agreement["method"] == "cohen"
    assert agreement["n_records"] == 3
    # T/A counts "maybe" as "include" in the statistic: the pairs (inc,inc),
    # (inc,exc), (maybe,inc) become (inc,inc), (inc,exc), (inc,inc)
    # -> po=2/3, pe=1*2/3 + 0*1/3 = 2/3, kappa=0
    assert agreement["maybe_as_include"] is True
    assert agreement["kappa"] == pytest.approx(0.0, abs=1e-9)
    assert agreement["percent"] == pytest.approx(2 / 3)
    # cross matrix: rows = admin, cols = reviewer — the three votes kept apart
    matrix = agreement["matrix"]
    assert matrix["rows_name"] == "Admin" and matrix["cols_name"] == "Reviewer"
    assert matrix["cells"]["include"]["include"] == 1
    assert matrix["cells"]["include"]["exclude"] == 1
    assert matrix["cells"]["maybe"]["include"] == 1
    # the same cross-tab, per named pair of reviewers (one pair here)
    assert len(agreement["pairs"]) == 1
    pair = agreement["pairs"][0]
    assert (pair["rows_name"], pair["cols_name"]) == ("Admin", "Reviewer")
    assert pair["cells"] == matrix["cells"]
    assert pair["n_records"] == 3
    assert pair["kappa"] == pytest.approx(0.0, abs=1e-9)
    assert pair["percent"] == pytest.approx(2 / 3)

    # PRISMA picks up the outcomes
    prisma = user_client.get(f"/api/projects/{pid}/prisma").json()
    assert prisma["reports_sought"] == 2
    assert prisma["records_excluded"] == 0


def test_vote_can_change_until_complete(user_client, team, project):
    pid = project["id"]
    _setup(user_client, pid, team)
    ids = [i["id"] for i in
           user_client.get(f"/api/projects/{pid}/screening/queue").json()["items"]]
    user_client.post(f"/api/projects/{pid}/screening/vote",
                     json={"record_id": ids[0], "decision": "include"})
    r = user_client.post(f"/api/projects/{pid}/screening/vote",
                         json={"record_id": ids[0], "decision": "exclude"})
    assert r.status_code == 200
    _login(user_client, "reviewer")
    r = user_client.post(f"/api/projects/{pid}/screening/vote",
                         json={"record_id": ids[0], "decision": "exclude"})
    assert r.json()["outcome"] == "exclude"


def test_arbiter_mode_restricts_resolution(user_client, team, project):
    pid = project["id"]
    _setup(user_client, pid, team, conflict_resolution="arbiter")
    ids = [i["id"] for i in
           user_client.get(f"/api/projects/{pid}/screening/queue").json()["items"]]
    user_client.post(f"/api/projects/{pid}/screening/vote",
                     json={"record_id": ids[0], "decision": "include"})
    _login(user_client, "reviewer")
    user_client.post(f"/api/projects/{pid}/screening/vote",
                     json={"record_id": ids[0], "decision": "exclude"})
    conflicts = user_client.get(f"/api/projects/{pid}/screening/conflicts").json()
    r = user_client.post(
        f"/api/projects/{pid}/screening/conflicts/{conflicts[0]['id']}/resolve",
        json={"decision": "include"})
    assert r.status_code == 403  # reviewer cannot arbiter
    _login(user_client, "admin")
    r = user_client.post(
        f"/api/projects/{pid}/screening/conflicts/{conflicts[0]['id']}/resolve",
        json={"decision": "include"})
    assert r.status_code == 200


def test_named_arbiter_resolves_even_without_admin_role(user_client, team,
                                                        project):
    """An arbiter named for the round settles its conflicts, admin or not —
    and then only the named arbiters do."""
    pid = project["id"]
    _setup(user_client, pid, team, conflict_resolution="arbiter",
           arbiter_ids=[team["reviewer"]["id"]])
    ids = [i["id"] for i in
           user_client.get(f"/api/projects/{pid}/screening/queue").json()["items"]]
    user_client.post(f"/api/projects/{pid}/screening/vote",
                     json={"record_id": ids[0], "decision": "include"})
    _login(user_client, "reviewer")
    user_client.post(f"/api/projects/{pid}/screening/vote",
                     json={"record_id": ids[0], "decision": "exclude"})
    conflict = user_client.get(f"/api/projects/{pid}/screening/conflicts").json()[0]
    _login(user_client, "admin")
    r = user_client.post(
        f"/api/projects/{pid}/screening/conflicts/{conflict['id']}/resolve",
        json={"decision": "include"})
    assert r.status_code == 403  # an arbiter is named: the admin is not one
    _login(user_client, "reviewer")
    r = user_client.post(
        f"/api/projects/{pid}/screening/conflicts/{conflict['id']}/resolve",
        json={"decision": "exclude"})
    assert r.status_code == 200, r.text


def test_conflict_resolution_can_be_undone(user_client, team, project):
    """A misclick on Include/Exclude is reversible: reopening puts the
    conflict back in "to resolve" with the votes intact."""
    pid = project["id"]
    _setup(user_client, pid, team)
    ids = [i["id"] for i in
           user_client.get(f"/api/projects/{pid}/screening/queue").json()["items"]]
    user_client.post(f"/api/projects/{pid}/screening/vote",
                     json={"record_id": ids[0], "decision": "include"})
    _login(user_client, "reviewer")
    user_client.post(f"/api/projects/{pid}/screening/vote",
                     json={"record_id": ids[0], "decision": "exclude"})
    base = f"/api/projects/{pid}/screening/conflicts"
    cid = user_client.get(base).json()[0]["id"]

    # nothing to undo while it is still open
    assert user_client.post(f"{base}/{cid}/reopen").status_code == 400

    user_client.post(f"{base}/{cid}/resolve",
                     json={"decision": "exclude", "note": "oops"})
    stats = user_client.get(f"/api/projects/{pid}/screening/stats").json()
    assert stats["excluded"] == 1 and stats["conflicts_open"] == 0

    r = user_client.post(f"{base}/{cid}/reopen")
    assert r.status_code == 200, r.text
    reopened = user_client.get(base).json()
    assert [c["id"] for c in reopened] == [cid]
    assert reopened[0]["status"] == "open" and reopened[0]["resolution"] == ""
    assert reopened[0]["resolution_note"] == "" and reopened[0]["resolved_by"] is None
    assert len(reopened[0]["votes"]) == 2          # the votes are untouched
    stats = user_client.get(f"/api/projects/{pid}/screening/stats").json()
    assert stats["excluded"] == 0 and stats["conflicts_open"] == 1
    assert stats["conflicts_resolved"] == 0

    # and it can be settled again, the other way
    r = user_client.post(f"{base}/{cid}/resolve", json={"decision": "include"})
    assert r.status_code == 200
    stats = user_client.get(f"/api/projects/{pid}/screening/stats").json()
    assert stats["included"] == 1


def test_undo_follows_the_resolution_rights(user_client, team, project):
    """Whoever may not resolve may not reopen either (arbiter mode)."""
    pid = project["id"]
    _setup(user_client, pid, team, conflict_resolution="arbiter")
    ids = [i["id"] for i in
           user_client.get(f"/api/projects/{pid}/screening/queue").json()["items"]]
    user_client.post(f"/api/projects/{pid}/screening/vote",
                     json={"record_id": ids[0], "decision": "include"})
    _login(user_client, "reviewer")
    user_client.post(f"/api/projects/{pid}/screening/vote",
                     json={"record_id": ids[0], "decision": "exclude"})
    base = f"/api/projects/{pid}/screening/conflicts"
    cid = user_client.get(base).json()[0]["id"]
    _login(user_client, "admin")
    user_client.post(f"{base}/{cid}/resolve", json={"decision": "include"})
    _login(user_client, "reviewer")
    assert user_client.post(f"{base}/{cid}/reopen").status_code == 403
    _login(user_client, "admin")
    assert user_client.post(f"{base}/{cid}/reopen").status_code == 200


def test_undo_takes_the_record_back_out_of_full_text(user_client, team, project):
    """A title/abstract inclusion sends the record to full-text screening:
    undoing it removes it from the full-text queues — unless full-text votes
    already exist, in which case the decision stays."""
    pid = project["id"]
    _setup(user_client, pid, team)
    ids = [i["id"] for i in
           user_client.get(f"/api/projects/{pid}/screening/queue").json()["items"]]

    def vote(who, record_id, decision, stage="ta"):
        _login(user_client, who)
        return user_client.post(
            f"/api/projects/{pid}/screening/vote?stage={stage}",
            json={"record_id": record_id, "decision": decision})

    vote("admin", ids[0], "include"); vote("reviewer", ids[0], "include")
    vote("admin", ids[1], "include"); vote("reviewer", ids[1], "exclude")
    _login(user_client, "admin")
    user_client.put(f"/api/projects/{pid}/screening/config", json={
        "stage": "ft", "allocation": "all", "conflict_resolution": "consensus",
        "reviewer_ids": [team["admin"]["id"], team["reviewer"]["id"]]})
    r = user_client.post(f"/api/projects/{pid}/screening/start?stage=ft")
    assert r.status_code == 200, r.text

    base = f"/api/projects/{pid}/screening/conflicts"
    ft_queue = f"/api/projects/{pid}/screening/queue?stage=ft"
    cid = user_client.get(base).json()[0]["id"]
    assert user_client.get(ft_queue).json()["total"] == 1

    user_client.post(f"{base}/{cid}/resolve", json={"decision": "include"})
    assert user_client.get(ft_queue).json()["total"] == 2   # joined full text
    assert user_client.post(f"{base}/{cid}/reopen").status_code == 200
    assert user_client.get(ft_queue).json()["total"] == 1   # and left it again

    user_client.post(f"{base}/{cid}/resolve", json={"decision": "include"})
    assert user_client.get(ft_queue).json()["total"] == 2
    assert vote("admin", ids[1], "include", stage="ft").status_code == 200
    r = user_client.post(f"{base}/{cid}/reopen")
    assert r.status_code == 400
    assert "full-text votes" in r.json()["detail"]


def test_agreement_pairs_with_three_reviewers(user_client, team, project):
    """Beyond two reviewers the folded matrix no longer says who voted what:
    the stats carry one named cross-tab per pair instead."""
    pid = project["id"]
    user_client.post("/api/auth/register", json={
        "email": "third@example.com", "password": "password123",
        "display_name": "Third"})
    third = user_client.get("/api/auth/me").json()
    _login(user_client, "admin")
    user_client.post(f"/api/projects/{pid}/members",
                     json={"email": "third@example.com", "role": "reviewer"})
    _setup(user_client, pid, team, reviewer_ids=[
        team["admin"]["id"], team["reviewer"]["id"], third["id"]])
    ids = [i["id"] for i in
           user_client.get(f"/api/projects/{pid}/screening/queue").json()["items"]]
    logins = {"admin": "admin@example.com", "reviewer": "rev@example.com",
              "third": "third@example.com"}
    votes = {"admin": ["include", "exclude"], "reviewer": ["include", "include"],
             "third": ["exclude", "exclude"]}
    for who, decisions in votes.items():
        user_client.post("/api/auth/login", json={
            "email": logins[who], "password": "password123"})
        for rid, decision in zip(ids, decisions):
            user_client.post(f"/api/projects/{pid}/screening/vote",
                             json={"record_id": rid, "decision": decision})
    _login(user_client, "admin")
    agreement = user_client.get(
        f"/api/projects/{pid}/screening/stats").json()["agreement"]
    assert agreement["method"] == "fleiss"
    pairs = {(p["rows_name"], p["cols_name"]): p for p in agreement["pairs"]}
    assert set(pairs) == {("Admin", "Reviewer"), ("Admin", "Third"),
                          ("Reviewer", "Third")}
    assert all(p["n_records"] == 2 for p in pairs.values())
    assert pairs[("Admin", "Reviewer")]["cells"]["include"]["include"] == 1
    assert pairs[("Admin", "Reviewer")]["cells"]["exclude"]["include"] == 1
    assert pairs[("Admin", "Third")]["percent"] == pytest.approx(0.5)
    assert pairs[("Reviewer", "Third")]["percent"] == 0


def test_allocations(user_client, team, project):
    pid = project["id"]
    # dual with 2 reviewers: 2 votes per record, balanced
    summary = _setup(user_client, pid, team, allocation="dual")
    assert summary["double_screened"] == 6
    q_admin = user_client.get(f"/api/projects/{pid}/screening/queue").json()
    assert q_admin["total"] == 6  # 2 reviewers, 12 assignments -> 6 each
    user_client.post(f"/api/projects/{pid}/screening/reset")

    # single with 50% overlap: 6 + 3 assignments
    summary = _setup(user_client, pid, team, allocation="single_overlap",
                     overlap_pct=50)
    assert summary["double_screened"] == 3
    stats = user_client.get(f"/api/projects/{pid}/screening/stats").json()
    total_assigned = sum(e["assigned"] for e in stats["per_reviewer"])
    assert total_assigned == 9

    # config is locked while active
    r = user_client.put(f"/api/projects/{pid}/screening/config", json={
        "stage": "ta", "allocation": "all",
        "reviewer_ids": [team["admin"]["id"]]})
    assert r.status_code == 400


def test_dual_requires_two_reviewers(user_client, team, project):
    pid = project["id"]
    r = user_client.put(f"/api/projects/{pid}/screening/config", json={
        "stage": "ta", "allocation": "dual",
        "reviewer_ids": [team["admin"]["id"]]})
    assert r.status_code == 200
    r = user_client.post(f"/api/projects/{pid}/screening/start")
    assert r.status_code == 400


def test_my_votes_history(user_client, team, project):
    pid = project["id"]
    _setup(user_client, pid, team)
    ids = [i["id"] for i in
           user_client.get(f"/api/projects/{pid}/screening/queue?limit=10").json()["items"]]

    user_client.post(f"/api/projects/{pid}/screening/vote", json={
        "record_id": ids[0], "decision": "include", "justification": "solid RCT"})
    user_client.post(f"/api/projects/{pid}/screening/vote", json={
        "record_id": ids[1], "decision": "exclude"})
    # complete ids[0] so it locks
    _login(user_client, "reviewer")
    user_client.post(f"/api/projects/{pid}/screening/vote", json={
        "record_id": ids[0], "decision": "include"})
    _login(user_client, "admin")

    history = user_client.get(f"/api/projects/{pid}/screening/my-votes").json()
    assert [h["record"]["id"] for h in history] == [ids[1], ids[0]]  # recent first
    assert history[1]["note"] == "solid RCT"
    assert history[1]["locked"] is True    # completed (unanimous)
    assert history[0]["locked"] is False   # still waiting for the other vote

    # T15: the notes view aggregates the vote justifications
    notes = user_client.get(f"/api/projects/{pid}/notes").json()
    assert [n["note"] for n in notes] == ["solid RCT"]
    assert notes[0]["kind"] == "vote" and notes[0]["stage"] == "ta"
    assert notes[0]["record_id"] == ids[0]
    csv_body = user_client.get(
        f"/api/projects/{pid}/notes/export.csv").content.decode("utf-8-sig")
    assert "solid RCT" in csv_body

    # only MY votes appear (blind preserved)
    _login(user_client, "reviewer")
    history = user_client.get(f"/api/projects/{pid}/screening/my-votes").json()
    assert len(history) == 1


def test_manual_abstract_paste(user_client, team, project):
    pid = project["id"]
    records = user_client.get(f"/api/projects/{pid}/records").json()["items"]
    rid = records[0]["id"]
    r = user_client.put(f"/api/projects/{pid}/records/{rid}/abstract",
                        json={"abstract": "Pasted abstract text."})
    assert r.status_code == 200
    records = user_client.get(f"/api/projects/{pid}/records").json()["items"]
    assert any(x["abstract"] == "Pasted abstract text." for x in records)

    # T21: edits are traced — original kept once, author & time recorded
    from app.core.db import SessionLocal
    from app.models import Record as RecordModel
    user_client.put(f"/api/projects/{pid}/records/{rid}/abstract",
                    json={"abstract": "Edited abstract text."})
    with SessionLocal() as db:
        rec = db.get(RecordModel, rid)
        assert rec.abstract == "Edited abstract text."
        # first edit snapshotted whatever the record held before
        assert rec.abstract_original is not None
        assert rec.abstract_edited_by is not None
        assert rec.abstract_edited_at is not None


def test_highlight_word_lists(user_client, team, project):
    """T14: per-project green/red highlight lists, cleaned & deduplicated."""
    pid = project["id"]
    r = user_client.get(f"/api/projects/{pid}/highlights")
    assert r.json() == {"green": [], "red": []}
    r = user_client.put(f"/api/projects/{pid}/highlights", json={
        "green": ["  simulator ", "RCT", "rct", ""],
        "red": ["animal model"]})
    assert r.json() == {"green": ["simulator", "RCT"],
                        "red": ["animal model"]}
    assert user_client.get(f"/api/projects/{pid}/highlights").json() == {
        "green": ["simulator", "RCT"], "red": ["animal model"]}


def test_invitation_flow(user_client, team, project):
    pid = project["id"]
    # adding an unknown email creates an awaiting-registration member
    r = user_client.post(f"/api/projects/{pid}/members",
                         json={"email": "future@example.com", "role": "reviewer"})
    assert r.status_code == 200
    assert r.json()["status"] == "awaiting"
    members = user_client.get(f"/api/projects/{pid}/members").json()
    awaiting = [m for m in members if m["status"] == "awaiting"]
    assert [m["email"] for m in awaiting] == ["future@example.com"]

    # the invitee registers -> claims the account (with their display name)
    user_client.post("/api/auth/register", json={
        "email": "future@example.com", "password": "password123",
        "display_name": "Future"})
    _login(user_client, "admin")
    members = user_client.get(f"/api/projects/{pid}/members").json()
    assert not any(m["status"] == "awaiting" for m in members)
    future = next(m for m in members if m["email"] == "future@example.com")
    assert future["role"] == "reviewer" and future["user_id"] is not None
    assert future["display_name"] == "Future"

    # awaiting members can be removed like any member
    r = user_client.post(f"/api/projects/{pid}/members",
                         json={"email": "gone@example.com", "role": "admin"})
    r = user_client.delete(
        f"/api/projects/{pid}/members/{r.json()['user_id']}")
    assert r.status_code == 200
    members = user_client.get(f"/api/projects/{pid}/members").json()
    assert not any(m["email"] == "gone@example.com" for m in members)


def test_ai_inconsistency_warning(user_client, team, project, monkeypatch):
    pid = project["id"]
    user_client.post(f"/api/projects/{pid}/protocols/upload",
                     files={"file": ("p.md", b"# P\n\nText", "text/markdown")})
    protocol = user_client.get(f"/api/projects/{pid}/protocols").json()[0]
    user_client.put(f"/api/projects/{pid}/protocols/{protocol['id']}", json={
        "protocol_md": "# P", "criteria": [
            {"code": "E3", "type": "exclude", "label": "review", "description": ""}]})
    user_client.post(f"/api/projects/{pid}/protocols/{protocol['id']}/validate")
    user_client.put("/api/llm/credentials", json={
        "provider": "anthropic", "api_key": "sk-ant-fake-key-123"})

    class Contradictory:
        model = "claude-fake"

        def generate_json(self, messages, json_schema, system=None, max_tokens=4096):
            from app.services.llm.base import LLMResult
            assert "MUST follow mechanically" in system  # hardened prompt
            return LLMResult(text="{}", data={
                "decision": "include", "confidence": 0.92,
                "criteria": [{"code": "E3", "assessment": "met"}],
                "justification": "This is a review, should likely be excluded."})

    monkeypatch.setattr("app.services.screening.ai.open_provider_chain",
                        lambda *a, **kw: Contradictory())
    _setup(user_client, pid, team, ai_enabled=True)
    ids = [i["id"] for i in
           user_client.get(f"/api/projects/{pid}/screening/queue").json()["items"]]
    r = user_client.post(f"/api/projects/{pid}/screening/records/{ids[0]}/suggest")
    assert r.status_code == 200
    assert "Inconsistent output" in r.json()["warning"]
    assert "E3" in r.json()["warning"]


def _suggest_provider(monkeypatch, decision="exclude"):
    """Fake provider for the title/abstract on-click suggestion engine."""
    class Fake:
        model = "claude-fake"
        name = "anthropic"

        def generate_json(self, messages, json_schema, system=None,
                          max_tokens=4096):
            from app.services.llm.base import LLMResult
            return LLMResult(text="{}", data={
                "analysis": "assessed", "decision": decision, "confidence": 0.9,
                "criteria": [], "justification": "batch suggestion"})

    monkeypatch.setattr("app.services.screening.ai.open_provider_chain",
                        lambda *a, **kw: Fake())


def test_ai_batch_suggestion(user_client, team, project, monkeypatch):
    """Batch AI suggestion pre-computes the on-click suggestion for the caller's
    still-to-vote records; each becomes a cached is_ai vote surfaced under the
    article, and re-running has nothing left to do."""
    pid = project["id"]
    _validate_protocol(user_client, pid)
    user_client.put("/api/llm/credentials", json={
        "provider": "anthropic", "api_key": "sk-ant-fake-key-123"})
    _suggest_provider(monkeypatch, decision="exclude")
    _setup(user_client, pid, team, ai_enabled=True, ai_batch=True)

    ids = [i["id"] for i in user_client.get(
        f"/api/projects/{pid}/screening/queue?limit=50").json()["items"]]
    assert len(ids) == 6

    # nothing cached yet
    assert user_client.get(
        f"/api/projects/{pid}/screening/records/{ids[0]}/suggestion"
    ).json()["suggestion"] is None

    est = user_client.get(
        f"/api/projects/{pid}/screening/ai-batch/estimate").json()
    assert est["n_to_generate"] == 6 and est["already_suggested"] == 0

    r = user_client.post(f"/api/projects/{pid}/screening/ai-batch")
    assert r.status_code == 200, r.text
    assert r.json()["n"] == 6
    job = _await_job(user_client, r.json()["job_id"])
    assert job["result"]["generated"] == 6 and job["result"]["failed"] == 0

    # each record now carries a cached suggestion to show under the article
    sug = user_client.get(
        f"/api/projects/{pid}/screening/records/{ids[0]}/suggestion"
    ).json()["suggestion"]
    assert sug is not None and sug["decision"] == "exclude"

    # idempotent: re-running has nothing left to generate
    assert user_client.post(
        f"/api/projects/{pid}/screening/ai-batch").status_code == 400
    est = user_client.get(
        f"/api/projects/{pid}/screening/ai-batch/estimate").json()
    assert est["n_to_generate"] == 0 and est["already_suggested"] == 6


def test_ai_reveal_after_vote(user_client, team, project, monkeypatch):
    """ai_reveal=after_vote: the suggestion is withheld server-side until the
    requester's own vote. A batch-computed one can be revealed on purpose
    (recorded as an AiReveal); on-demand LLM calls wait for the vote."""
    pid = project["id"]
    _validate_protocol(user_client, pid)
    user_client.put("/api/llm/credentials", json={
        "provider": "anthropic", "api_key": "sk-ant-fake-key-123"})
    _suggest_provider(monkeypatch, decision="exclude")
    _setup(user_client, pid, team, ai_enabled=True, ai_batch=True,
           ai_reveal="after_vote")
    base = f"/api/projects/{pid}/screening"
    assert user_client.get(f"{base}/config").json()["config"]["ai_reveal"] == "after_vote"
    ids = [i["id"] for i in user_client.get(f"{base}/queue?limit=50").json()["items"]]

    # before any vote: no on-demand call, nothing to reveal yet
    r = user_client.post(f"{base}/records/{ids[0]}/suggest")
    assert r.status_code == 409 and "Vote first" in r.json()["detail"]
    s = user_client.get(f"{base}/records/{ids[0]}/suggestion").json()
    assert s == {"suggestion": None, "withheld": True, "available": False}
    assert user_client.post(f"{base}/records/{ids[0]}/reveal").status_code == 409

    # the admin pre-computes the batch (allocation=all: same records for both)
    r = user_client.post(f"{base}/ai-batch")
    assert r.status_code == 200, r.text
    _await_job(user_client, r.json()["job_id"])

    # still withheld, but now there is something to reveal
    s = user_client.get(f"{base}/records/{ids[0]}/suggestion").json()
    assert s["suggestion"] is None and s["withheld"] and s["available"]

    # the co-reviewer chooses to look before voting: recorded, then visible
    _login(user_client, "reviewer")
    r = user_client.post(f"{base}/records/{ids[0]}/reveal")
    assert r.status_code == 200, r.text
    assert r.json()["suggestion"]["decision"] == "exclude"
    assert r.json()["suggestion"]["revealed_early"] is True
    s = user_client.get(f"{base}/records/{ids[0]}/suggestion").json()
    assert s["suggestion"]["revealed_early"] is True
    # another record, voted blind: shown after the vote, flagged as such
    assert user_client.get(f"{base}/records/{ids[1]}/suggestion").json()["withheld"]
    user_client.post(f"{base}/vote", json={"record_id": ids[1], "decision": "include"})
    s = user_client.get(f"{base}/records/{ids[1]}/suggestion").json()
    assert s["suggestion"]["decision"] == "exclude"
    assert s["suggestion"]["revealed_early"] is False
    # on-demand regeneration is allowed once voted
    assert user_client.post(f"{base}/records/{ids[1]}/suggest").status_code == 200
    # voting after a reveal keeps the trace
    user_client.post(f"{base}/vote", json={"record_id": ids[0], "decision": "exclude"})

    # the reveal is per requester: the admin has not looked at ids[0]
    _login(user_client, "admin")
    assert user_client.get(f"{base}/records/{ids[0]}/suggestion").json()["withheld"]

    # reporting: the disclosure evidence and the Methods facts count it
    from app.core.db import SessionLocal
    from app.services.reporting.ai_audit import _screening_evidence
    from app.services.reporting.audit import _screening
    with SessionLocal() as db:
        ev = _screening_evidence(db, pid)["ta"]
        assert ev["n_revealed_before_vote"] == 1
        assert ev["reveal_modes"] == ["after_vote"]
        facts = _screening(db, pid)
        found = [v for v in _walk(facts) if isinstance(v, dict) and "reveal" in v]
        assert found and found[0]["reveal"] == "after_vote"
        assert found[0]["n_revealed_before_vote"] == 1

    # the mode can be switched while the round runs
    r = user_client.put(f"{base}/config/ai-reveal", json={"ai_reveal": "always"})
    assert r.status_code == 200
    assert user_client.get(f"{base}/records/{ids[0]}/suggestion").json()[
        "suggestion"]["decision"] == "exclude"


def _walk(value):
    """Every dict/list node of a nested structure (for locating a fact)."""
    yield value
    if isinstance(value, dict):
        for v in value.values():
            yield from _walk(v)
    elif isinstance(value, list):
        for v in value:
            yield from _walk(v)


def test_snowballing_round_copies_every_ai_setting(user_client, team, project):
    """The next round's config inherits triage, batch and reveal, not only
    ai_enabled (an omission the roadmap review caught)."""
    from app.core.db import SessionLocal
    from app.services.snowballing.jobs import _copy_config
    pid = project["id"]
    _setup(user_client, pid, team, ai_enabled=True, ai_batch=True,
           ai_triage="reviewers", ai_reveal="after_vote")
    with SessionLocal() as db:
        nxt = _copy_config(db, pid, "ta", 2)
        assert (nxt.ai_enabled, nxt.ai_batch, nxt.ai_triage, nxt.ai_reveal) \
            == (True, True, "reviewers", "after_vote")
        db.rollback()


def test_ai_batch_gating(user_client, team, project, monkeypatch):
    """Batch endpoints require ai_enabled + ai_batch; the admin flips ai_batch
    live via /config/ai-batch while the round runs."""
    pid = project["id"]
    _validate_protocol(user_client, pid)
    user_client.put("/api/llm/credentials", json={
        "provider": "anthropic", "api_key": "sk-ant-fake-key-123"})
    _setup(user_client, pid, team, ai_enabled=True, ai_batch=False)

    assert user_client.post(
        f"/api/projects/{pid}/screening/ai-batch").status_code == 400
    r = user_client.put(f"/api/projects/{pid}/screening/config/ai-batch",
                        json={"ai_batch": True})
    assert r.status_code == 200 and r.json()["ai_batch"] is True

    _suggest_provider(monkeypatch)
    assert user_client.post(
        f"/api/projects/{pid}/screening/ai-batch").status_code == 200


def _await_job(client, job_id, timeout=30):
    t0 = time.time()
    while time.time() - t0 < timeout:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in ("done", "failed"):
            assert job["status"] == "done", job.get("error")
            return job
        time.sleep(0.05)
    raise AssertionError("job never finished")


def _validate_protocol(client, pid):
    client.post(f"/api/projects/{pid}/protocols/upload",
                files={"file": ("p.md", b"# P\n\nGamification of driving.",
                                "text/markdown")})
    prot = client.get(f"/api/projects/{pid}/protocols").json()[0]
    client.put(f"/api/projects/{pid}/protocols/{prot['id']}", json={
        "protocol_md": "# P", "criteria": [
            {"code": "E1", "type": "exclude", "label": "off topic",
             "description": ""}]})
    client.post(f"/api/projects/{pid}/protocols/{prot['id']}/validate")


def _triage_provider(monkeypatch, exclude_ids, confidence=0.98):
    """Fake LLM proposing exclusion for the given record ids (from the batch)."""
    class Fake:
        model = "claude-fake"
        name = "anthropic"

        def generate_json(self, messages, json_schema, system=None,
                          max_tokens=4096):
            from app.services.llm.base import LLMResult
            import re
            ids_in_batch = {int(m) for m in
                            re.findall(r"\[(\d+)\]", messages[0]["content"])}
            picks = [rid for rid in exclude_ids if rid in ids_in_batch]
            return LLMResult(text="{}", data={"exclusions": [
                {"id": rid, "confidence": confidence, "reason": "off topic"}
                for rid in picks]})

    monkeypatch.setattr(
        "app.services.screening.triage.open_provider_chain",
        lambda *a, **kw: Fake())


def test_ai_title_triage_estimate(user_client, team, project):
    """The triage shows its size and an estimated cost before it runs."""
    pid = project["id"]
    _validate_protocol(user_client, pid)
    user_client.put("/api/llm/credentials", json={
        "provider": "anthropic", "api_key": "sk-ant-fake-key-123"})
    _setup(user_client, pid, team, ai_triage="admin")
    r = user_client.get(f"/api/projects/{pid}/screening/triage/estimate")
    assert r.status_code == 200, r.text
    est = r.json()
    assert est["candidates"] == 6 and est["n_batches"] == 1
    assert est["cost"]["estimated"] is True
    assert est["cost"]["tokens_out"] == 6 * 20
    assert est["cost"]["tokens_in"] > 0 and est["cost"]["cost_usd"] > 0


def test_ai_title_triage_admin_mode(user_client, team, project, monkeypatch):
    """Admin mode: validated proposals globally exclude the records (audited),
    they leave every reviewer's queue and feed the excluded count/PRISMA."""
    pid = project["id"]
    _validate_protocol(user_client, pid)
    user_client.put("/api/llm/credentials", json={
        "provider": "anthropic", "api_key": "sk-ant-fake-key-123"})
    _setup(user_client, pid, team, ai_triage="admin")

    ids = [i["id"] for i in user_client.get(
        f"/api/projects/{pid}/screening/queue?limit=50").json()["items"]]
    assert len(ids) == 6
    _triage_provider(monkeypatch, exclude_ids=ids[:3])

    r = user_client.post(f"/api/projects/{pid}/screening/triage",
                         json={"threshold": 95})
    assert r.status_code == 200, r.text
    assert r.json()["candidates"] == 6
    job = _await_job(user_client, r.json()["job_id"])
    proposals = job["result"]["proposals"]
    assert {p["record_id"] for p in proposals} == set(ids[:3])
    assert all(p["confidence"] >= 0.95 for p in proposals)

    # validate only two of the three
    r = user_client.post(f"/api/projects/{pid}/screening/triage/apply",
                         json={"record_ids": ids[:2]})
    assert r.json() == {"applied": 2, "skipped": 0, "controls": 0,
                        "mode": "admin"}

    # excluded records left both reviewers' queues, no vote required
    for who in ("admin", "reviewer"):
        _login(user_client, who)
        q = user_client.get(
            f"/api/projects/{pid}/screening/queue?limit=50").json()
        assert q["total"] == 4
        assert set(ids[:2]).isdisjoint({i["id"] for i in q["items"]})
    _login(user_client, "admin")

    stats = user_client.get(f"/api/projects/{pid}/screening/stats").json()
    assert stats["auto_excluded"] == 2
    assert stats["excluded"] == 2
    assert stats["conflicts_open"] == 0  # triage rows are not conflicts
    # per reviewer: the triage took 2 of the 6 assigned records off the workload
    for entry in stats["per_reviewer"]:
        assert entry["assigned"] == 6 and entry["triage_excluded"] == 2
        assert entry["triage_votes"] == 0 and entry["done"] == 0

    # PRISMA (#12): automation exclusions get their own explicit tally
    prisma = user_client.get(f"/api/projects/{pid}/prisma").json()
    assert prisma["records_excluded"] == 2
    assert prisma["records_excluded_auto"] == 2
    assert prisma["via_databases"]["records_excluded_auto"] == 2
    assert prisma["rounds"][0]["records_excluded_auto"] == 2

    # #13: the audit history lists the validated AI exclusions with reasons
    hist = user_client.get(
        f"/api/projects/{pid}/screening/auto-excluded").json()
    assert {h["record_id"] for h in hist} == set(ids[:2])
    assert all(h["kind"] == "exclusion" for h in hist)
    assert all(h["validated_by"] for h in hist)
    assert all(h["reason"] for h in hist)  # recovered from the triage job
    conflicts = user_client.get(
        f"/api/projects/{pid}/screening/conflicts?status=resolved").json()
    assert conflicts == []  # audit rows never surface in the Conflicts tab

    # re-running proposes only the still-undecided records
    _triage_provider(monkeypatch, exclude_ids=ids[2:3])
    r = user_client.post(f"/api/projects/{pid}/screening/triage",
                         json={"threshold": 95})
    assert r.json()["candidates"] == 4


def test_ai_title_triage_latest_persists(user_client, team, project, monkeypatch):
    """The proposals persist: /triage/latest replays the last run without
    calling the AI again, and validated records drop out of the saved list."""
    pid = project["id"]
    _validate_protocol(user_client, pid)
    user_client.put("/api/llm/credentials", json={
        "provider": "anthropic", "api_key": "sk-ant-fake-key-123"})
    _setup(user_client, pid, team, ai_triage="admin")

    # nothing run yet -> no saved proposals
    assert user_client.get(
        f"/api/projects/{pid}/screening/triage/latest").json()["proposals"] is None

    ids = [i["id"] for i in user_client.get(
        f"/api/projects/{pid}/screening/queue?limit=50").json()["items"]]
    _triage_provider(monkeypatch, exclude_ids=ids[:3])
    _await_job(user_client, user_client.post(
        f"/api/projects/{pid}/screening/triage", json={"threshold": 95})
        .json()["job_id"])

    # replayed from storage, no re-run
    latest = user_client.get(
        f"/api/projects/{pid}/screening/triage/latest").json()
    assert {p["record_id"] for p in latest["proposals"]} == set(ids[:3])
    assert latest["threshold"] == 95

    # validating one removes it from the saved list
    user_client.post(f"/api/projects/{pid}/screening/triage/apply",
                     json={"record_ids": ids[:1]})
    latest = user_client.get(
        f"/api/projects/{pid}/screening/triage/latest").json()
    assert {p["record_id"] for p in latest["proposals"]} == set(ids[1:3])


def test_ai_title_triage_reviewer_mode(user_client, team, project, monkeypatch):
    """Reviewer mode: validated proposals cast MY exclude vote; the other
    reviewer still has to screen (double screening preserved)."""
    pid = project["id"]
    _validate_protocol(user_client, pid)
    user_client.put("/api/llm/credentials", json={
        "provider": "anthropic", "api_key": "sk-ant-fake-key-123"})
    _setup(user_client, pid, team, ai_triage="reviewers")

    ids = [i["id"] for i in user_client.get(
        f"/api/projects/{pid}/screening/queue?limit=50").json()["items"]]
    _triage_provider(monkeypatch, exclude_ids=ids[:2])
    job = _await_job(user_client, user_client.post(
        f"/api/projects/{pid}/screening/triage", json={"threshold": 95})
        .json()["job_id"])
    assert {p["record_id"] for p in job["result"]["proposals"]} == set(ids[:2])

    r = user_client.post(f"/api/projects/{pid}/screening/triage/apply",
                         json={"record_ids": ids[:2]})
    assert r.json()["applied"] == 2 and r.json()["mode"] == "reviewers"

    # my queue lost them; the record is NOT decided yet (needs the 2nd vote)
    q = user_client.get(f"/api/projects/{pid}/screening/queue?limit=50").json()
    assert set(ids[:2]).isdisjoint({i["id"] for i in q["items"]})
    stats = user_client.get(f"/api/projects/{pid}/screening/stats").json()
    assert stats["excluded"] == 0 and stats["auto_excluded"] == 0
    # per reviewer: those two votes are mine, and flagged as triage votes
    mine = next(e for e in stats["per_reviewer"]
                if e["user_id"] == team["admin"]["id"])
    other = next(e for e in stats["per_reviewer"]
                 if e["user_id"] == team["reviewer"]["id"])
    assert mine["done"] == 2 and mine["triage_votes"] == 2
    assert mine["triage_excluded"] == 0
    assert other["triage_votes"] == 0 and other["triage_excluded"] == 0

    # the other reviewer still sees them and completes the exclusion
    _login(user_client, "reviewer")
    q = user_client.get(f"/api/projects/{pid}/screening/queue?limit=50").json()
    assert set(ids[:2]).issubset({i["id"] for i in q["items"]})
    for rid in ids[:2]:
        user_client.post(f"/api/projects/{pid}/screening/vote",
                         json={"record_id": rid, "decision": "exclude"})
    _login(user_client, "admin")
    stats = user_client.get(f"/api/projects/{pid}/screening/stats").json()
    assert stats["excluded"] == 2


def test_ai_triage_permissions_and_gating(user_client, team, project, monkeypatch):
    pid = project["id"]
    _validate_protocol(user_client, pid)
    user_client.put("/api/llm/credentials", json={
        "provider": "anthropic", "api_key": "sk-ant-fake-key-123"})

    # off by default -> 400
    _setup(user_client, pid, team)
    assert user_client.post(f"/api/projects/{pid}/screening/triage",
                            json={"threshold": 95}).status_code == 400

    # admin mode: a plain reviewer cannot run it
    user_client.put(f"/api/projects/{pid}/screening/config/triage-mode",
                    json={"ai_triage": "admin"})
    _login(user_client, "reviewer")
    assert user_client.post(f"/api/projects/{pid}/screening/triage",
                            json={"threshold": 95}).status_code == 403
    _login(user_client, "admin")

    # apply only writes records that are genuine current candidates
    ids = [i["id"] for i in user_client.get(
        f"/api/projects/{pid}/screening/queue?limit=50").json()["items"]]
    user_client.post(f"/api/projects/{pid}/screening/vote",
                     json={"record_id": ids[0], "decision": "include"})
    r = user_client.post(f"/api/projects/{pid}/screening/triage/apply",
                         json={"record_ids": [ids[0]]})  # already voted
    assert r.json()["applied"] == 0 and r.json()["skipped"] == 1


def test_ai_triage_control_sample_admin_mode(user_client, team, project,
                                             monkeypatch):
    """Control sample: a share of every validated list is held back at random,
    stays in both queues unmarked, is never re-proposed, and the dashboard
    compares the humans' decision with the AI's once they ruled."""
    pid = project["id"]
    _validate_protocol(user_client, pid)
    user_client.put("/api/llm/credentials", json={
        "provider": "anthropic", "api_key": "sk-ant-fake-key-123"})
    _setup(user_client, pid, team, ai_triage="admin", triage_control_pct=50)
    config = user_client.get(f"/api/projects/{pid}/screening/config").json()
    assert config["config"]["triage_control_pct"] == 50

    ids = [i["id"] for i in user_client.get(
        f"/api/projects/{pid}/screening/queue?limit=50").json()["items"]]
    _triage_provider(monkeypatch, exclude_ids=ids[:4])
    job = _await_job(user_client, user_client.post(
        f"/api/projects/{pid}/screening/triage", json={"threshold": 95})
        .json()["job_id"])
    assert len(job["result"]["proposals"]) == 4

    r = user_client.post(f"/api/projects/{pid}/screening/triage/apply",
                         json={"record_ids": ids[:4]}).json()
    assert r["controls"] == 2 and r["applied"] == 2 and r["skipped"] == 0

    # the two controls are still in both queues, the two others left
    queues = {}
    for who in ("admin", "reviewer"):
        _login(user_client, who)
        queues[who] = {i["id"] for i in user_client.get(
            f"/api/projects/{pid}/screening/queue?limit=50").json()["items"]}
    _login(user_client, "admin")
    assert queues["admin"] == queues["reviewer"]
    controls = queues["admin"] & set(ids[:4])
    assert len(controls) == 2
    assert len(queues["admin"]) == 4  # 2 controls + 2 never proposed

    # blind-safe: pending controls are counted, never listed
    rep = user_client.get(f"/api/projects/{pid}/screening/triage-controls").json()
    assert rep["total"] == 2 and rep["pending"] == 2 and rep["rows"] == []
    stats = user_client.get(f"/api/projects/{pid}/screening/stats").json()
    assert stats["triage_controls"]["total"] == 2
    assert stats["auto_excluded"] == 2
    # a reviewer may not read it in admin mode
    _login(user_client, "reviewer")
    assert user_client.get(
        f"/api/projects/{pid}/screening/triage-controls").status_code == 403
    _login(user_client, "admin")

    # a second triage pass never proposes the controls again
    _triage_provider(monkeypatch, exclude_ids=ids)
    r = user_client.post(f"/api/projects/{pid}/screening/triage",
                         json={"threshold": 95})
    assert r.json()["candidates"] == 2
    latest = user_client.get(
        f"/api/projects/{pid}/screening/triage/latest").json()
    assert controls.isdisjoint({p["record_id"] for p in latest["proposals"]})

    # the humans rule: one control excluded by both, one included by both
    c1, c2 = sorted(controls)
    for who in ("admin", "reviewer"):
        _login(user_client, who)
        user_client.post(f"/api/projects/{pid}/screening/vote",
                         json={"record_id": c1, "decision": "exclude"})
        user_client.post(f"/api/projects/{pid}/screening/vote",
                         json={"record_id": c2, "decision": "include"})
    _login(user_client, "admin")
    rep = user_client.get(f"/api/projects/{pid}/screening/triage-controls").json()
    assert (rep["decided"], rep["confirmed"], rep["contradicted"]) == (2, 1, 1)
    assert rep["agreement_pct"] == 50
    by_id = {row["record_id"]: row for row in rep["rows"]}
    assert by_id[c1]["status"] == "confirmed" and by_id[c1]["human"] == "exclude"
    assert by_id[c2]["status"] == "contradicted" and by_id[c2]["human"] == "include"
    assert by_id[c1]["title"] and by_id[c1]["confidence"] >= 0.95
    assert by_id[c1]["reason"] == "off topic"

    # PRISMA: the control excluded by hand counts as a reviewer exclusion
    prisma = user_client.get(f"/api/projects/{pid}/prisma").json()
    assert prisma["records_excluded_auto"] == 2
    assert prisma["records_excluded"] == 3

    # reset wipes the controls with the votes
    user_client.post(f"/api/projects/{pid}/screening/reset")
    _setup(user_client, pid, team, ai_triage="admin", triage_control_pct=50)
    rep = user_client.get(f"/api/projects/{pid}/screening/triage-controls").json()
    assert rep["total"] == 0


def test_ai_triage_control_sample_reviewer_mode(user_client, team, project,
                                                monkeypatch):
    """Reviewers mode: the control casts no vote; the holder's own later vote
    is what gets compared, and only the holder (or an admin) can read it."""
    pid = project["id"]
    _validate_protocol(user_client, pid)
    user_client.put("/api/llm/credentials", json={
        "provider": "anthropic", "api_key": "sk-ant-fake-key-123"})
    _setup(user_client, pid, team, ai_triage="reviewers")
    # changeable while the round runs, with the mode
    r = user_client.put(f"/api/projects/{pid}/screening/config/triage-mode",
                        json={"ai_triage": "reviewers", "triage_control_pct": 50})
    assert r.json()["triage_control_pct"] == 50

    _login(user_client, "reviewer")
    ids = [i["id"] for i in user_client.get(
        f"/api/projects/{pid}/screening/queue?limit=50").json()["items"]]
    _triage_provider(monkeypatch, exclude_ids=ids[:2])
    _await_job(user_client, user_client.post(
        f"/api/projects/{pid}/screening/triage", json={"threshold": 95})
        .json()["job_id"])
    r = user_client.post(f"/api/projects/{pid}/screening/triage/apply",
                         json={"record_ids": ids[:2]}).json()
    assert r == {"applied": 1, "skipped": 0, "controls": 1, "mode": "reviewers"}
    stats = user_client.get(f"/api/projects/{pid}/screening/stats").json()
    assert stats["votes_done"] == 1  # the control cast nothing

    rep = user_client.get(f"/api/projects/{pid}/screening/triage-controls").json()
    assert rep["total"] == 1 and rep["pending"] == 1
    (control,) = {rid for rid in ids[:2]} - {
        row["record_id"] for row in user_client.get(
            f"/api/projects/{pid}/screening/auto-excluded").json()}
    user_client.post(f"/api/projects/{pid}/screening/vote",
                     json={"record_id": control, "decision": "maybe"})
    rep = user_client.get(f"/api/projects/{pid}/screening/triage-controls").json()
    assert rep["contradicted"] == 1 and rep["rows"][0]["human"] == "maybe"

    # the admin sees the whole round's sample too
    _login(user_client, "admin")
    rep = user_client.get(f"/api/projects/{pid}/screening/triage-controls").json()
    assert rep["total"] == 1 and rep["rows"][0]["held_by"]


def test_the_review_framing_is_not_injected_into_screening_prompts(
        user_client, team, project, monkeypatch):
    """Screening judges the protocol's coded I*/E* criteria, so the question
    framework tells it nothing — and this is the highest-volume AI call in the
    app (one per record). Paying for the framing block here would be pure
    tokens. If you are here because you added it, that is the trade-off."""
    pid = project["id"]
    user_client.put(f"/api/projects/{pid}",
                    json={"review_type": "best_fit",
                          "question_framework": "spider"})
    user_client.post(f"/api/projects/{pid}/protocols/upload",
                     files={"file": ("p.md", b"# P\n\nText", "text/markdown")})
    protocol = user_client.get(f"/api/projects/{pid}/protocols").json()[0]
    user_client.put(f"/api/projects/{pid}/protocols/{protocol['id']}", json={
        "protocol_md": "# P", "criteria": [
            {"code": "I1", "type": "include", "label": "topic",
             "description": "on topic"}]})
    user_client.post(f"/api/projects/{pid}/protocols/{protocol['id']}/validate")
    user_client.put("/api/llm/credentials", json={
        "provider": "anthropic", "api_key": "sk-ant-fake-key-123"})

    seen = {}

    class FakeProvider:
        model = "claude-fake"

        def generate_json(self, messages, json_schema, system=None,
                          max_tokens=4096):
            from app.services.llm.base import LLMResult
            seen["system"] = system or ""
            return LLMResult(text="{}", data={
                "decision": "include", "confidence": 0.9,
                "criteria": [{"code": "I1", "assessment": "met", "note": "ok"}],
                "justification": "On topic."})

    monkeypatch.setattr("app.services.screening.ai.open_provider_chain",
                        lambda *a, **kw: FakeProvider())
    _setup(user_client, pid, team, ai_enabled=True)
    ids = [i["id"] for i in
           user_client.get(f"/api/projects/{pid}/screening/queue").json()["items"]]
    r = user_client.post(f"/api/projects/{pid}/screening/records/{ids[0]}/suggest")
    assert r.status_code == 200, r.text
    assert "SPIDER" not in seen["system"]
    assert "Review framing" not in seen["system"]


def test_ai_suggestion_cached(user_client, team, project, monkeypatch):
    pid = project["id"]
    # validated protocol (context pack) + credential required
    user_client.post(f"/api/projects/{pid}/protocols/upload",
                     files={"file": ("p.md", b"# P\n\nProtocol text", "text/markdown")})
    protocol = user_client.get(f"/api/projects/{pid}/protocols").json()[0]
    user_client.put(f"/api/projects/{pid}/protocols/{protocol['id']}", json={
        "protocol_md": "# P\n\n## Criteria",
        "criteria": [{"code": "I1", "type": "include", "label": "topic",
                      "description": "on topic"}]})
    user_client.post(f"/api/projects/{pid}/protocols/{protocol['id']}/validate")
    user_client.put("/api/llm/credentials", json={
        "provider": "anthropic", "api_key": "sk-ant-fake-key-123"})

    calls = {"n": 0}

    class FakeProvider:
        model = "claude-fake"

        def generate_json(self, messages, json_schema, system=None, max_tokens=4096):
            from app.services.llm.base import LLMResult
            calls["n"] += 1
            assert "Review protocol (validated)" in system  # context pack injected
            # bibliographic metadata reaches the model (year for period criteria)
            assert "Publication year: 20" in messages[0]["content"]
            assert "Authors: " in messages[0]["content"]
            return LLMResult(text="{}", data={
                "decision": "include", "confidence": 0.85,
                "criteria": [{"code": "I1", "assessment": "met", "note": "ok"}],
                "justification": "Clearly on topic."})

    monkeypatch.setattr("app.services.screening.ai.open_provider_chain",
                        lambda *a, **kw: FakeProvider())
    _setup(user_client, pid, team, ai_enabled=True)
    ids = [i["id"] for i in
           user_client.get(f"/api/projects/{pid}/screening/queue").json()["items"]]

    r = user_client.post(f"/api/projects/{pid}/screening/records/{ids[0]}/suggest")
    assert r.status_code == 200, r.text
    assert r.json()["decision"] == "include"
    assert r.json()["criteria"][0]["code"] == "I1"
    # a fresh call reports its cost; the up-front estimate is available too
    assert "cost_usd" in r.json()["cost"] and r.json()["cost"]["estimated"] is False
    est = user_client.get(
        f"/api/projects/{pid}/screening/records/{ids[0]}/ai-estimate").json()
    assert est["cost"]["estimated"] is True and est["cost"]["cost_usd"] >= 0
    # second click (other reviewer): cached, no new LLM call (and no cost)
    _login(user_client, "reviewer")
    r = user_client.post(f"/api/projects/{pid}/screening/records/{ids[0]}/suggest")
    assert r.status_code == 200
    assert r.json()["cost"] is None  # cache hit — nothing was spent
    assert calls["n"] == 1

    # force=true discards the cache and calls the model again
    r = user_client.post(
        f"/api/projects/{pid}/screening/records/{ids[0]}/suggest?force=true")
    assert r.status_code == 200
    assert calls["n"] == 2

    # disabled AI is refused
    _login(user_client, "admin")
    user_client.post(f"/api/projects/{pid}/screening/reset")
    _setup(user_client, pid, team, ai_enabled=False)
    r = user_client.post(f"/api/projects/{pid}/screening/records/{ids[0]}/suggest")
    assert r.status_code == 400


# ---- skip ("decide later") -------------------------------------------------------

def test_skip_decide_later(user_client, team, project):
    pid = project["id"]
    _setup(user_client, pid, team)
    queue = user_client.get(f"/api/projects/{pid}/screening/queue").json()
    first, second = queue["items"][0]["id"], queue["items"][1]["id"]
    assert queue.get("skipped", 0) == 0

    # skip the first record: it sinks to the back of MY queue
    r = user_client.post(f"/api/projects/{pid}/screening/skip",
                         json={"record_id": first})
    assert r.status_code == 200
    queue = user_client.get(f"/api/projects/{pid}/screening/queue?limit=10").json()
    assert queue["skipped"] == 1
    ids = [i["id"] for i in queue["items"]]
    assert ids[0] == second and ids[-1] == first
    assert queue["items"][-1]["skipped"] is True

    # vote everything else -> the skipped record comes around again
    for rid in ids[:-1]:
        user_client.post(f"/api/projects/{pid}/screening/vote",
                         json={"record_id": rid, "decision": "exclude"})
    queue = user_client.get(f"/api/projects/{pid}/screening/queue").json()
    assert [i["id"] for i in queue["items"]] == [first]
    # and voting on it is unchanged
    r = user_client.post(f"/api/projects/{pid}/screening/vote",
                         json={"record_id": first, "decision": "include"})
    assert r.status_code == 200

    # cannot skip a record that is not mine/assigned
    r = user_client.post(f"/api/projects/{pid}/screening/skip",
                         json={"record_id": 999999})
    assert r.status_code == 403


def test_undo_vote(user_client, team, project):
    pid = project["id"]
    _setup(user_client, pid, team)
    base = f"/api/projects/{pid}/screening"
    queue = user_client.get(f"{base}/queue").json()
    rid, other = queue["items"][0]["id"], queue["items"][1]["id"]

    # undo a first vote -> the record is back in my queue, unvoted
    user_client.post(f"{base}/vote", json={"record_id": rid, "decision": "include"})
    r = user_client.post(f"{base}/vote/undo", json={"record_id": rid})
    assert r.status_code == 200 and r.json()["outcome"] is None
    assert user_client.get(f"{base}/queue").json()["done"] == 0
    assert user_client.post(f"{base}/vote/undo",
                            json={"record_id": rid}).status_code == 400

    # undo a replacing vote -> the previous one comes back
    user_client.post(f"{base}/vote", json={"record_id": rid, "decision": "maybe",
                                           "justification": "unsure"})
    user_client.post(f"{base}/vote", json={"record_id": rid, "decision": "exclude"})
    user_client.post(f"{base}/vote/undo", json={
        "record_id": rid, "previous_decision": "maybe",
        "previous_justification": "unsure"})
    mine = {v["record"]["id"]: v for v in user_client.get(f"{base}/my-votes").json()}
    assert mine[rid]["decision"] == "maybe" and mine[rid]["note"] == "unsure"

    # the vote that opened a conflict: undoing it withdraws the conflict
    _login(user_client, "reviewer")
    user_client.post(f"{base}/vote", json={"record_id": other, "decision": "include"})
    _login(user_client, "admin")
    user_client.post(f"{base}/vote", json={"record_id": other, "decision": "exclude"})
    assert len(user_client.get(f"{base}/conflicts").json()) == 1
    r = user_client.post(f"{base}/vote/undo", json={"record_id": other})
    assert r.status_code == 200
    assert user_client.get(f"{base}/conflicts").json() == []

    # once the conflict is resolved, the vote stays
    user_client.post(f"{base}/vote", json={"record_id": other, "decision": "exclude"})
    cid = user_client.get(f"{base}/conflicts").json()[0]["id"]
    user_client.post(f"{base}/conflicts/{cid}/resolve", json={"decision": "exclude"})
    assert user_client.post(f"{base}/vote/undo",
                            json={"record_id": other}).status_code == 400


# ---- late-arriving records --------------------------------------------------------

LATE_RIS = """TY  - JOUR
TI  - Telematics feedback and adolescent driving style
AU  - Late, L.
PY  - 2024
DO  - 10.1/screen.late1
AB  - Late-imported study on gamified telematics.
ER  -
TY  - JOUR
TI  - Hazard perception training with game elements
AU  - Later, M.
PY  - 2024
DO  - 10.1/screen.late2
AB  - Another late-imported study.
ER  -
"""


def _run_dedup(client, pid):
    job_id = client.post(f"/api/projects/{pid}/dedup/run").json()["job_id"]
    for _ in range(100):
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in ("done", "failed"):
            break
        time.sleep(0.05)
    assert job["status"] == "done"


def test_late_import_joins_active_round(user_client, team, project):
    """Records imported AFTER /start must get assignments (sync_assignments),
    otherwise they sit in nobody's queue and the round can never complete."""
    pid = project["id"]
    _setup(user_client, pid, team)  # allocation=all, 2 reviewers, 6 records
    q = user_client.get(f"/api/projects/{pid}/screening/queue").json()
    assert q["total"] == 6

    user_client.post(
        f"/api/projects/{pid}/imports/upload",
        files={"file": ("late.ris", LATE_RIS.encode(), "text/plain")},
        data={"source_name": "wos", "source_type": "database"})
    _run_dedup(user_client, pid)

    # allocation=all: both reviewers find the late records in their queue
    for who in ("admin", "reviewer"):
        _login(user_client, who)
        queue = user_client.get(
            f"/api/projects/{pid}/screening/queue?limit=50").json()
        assert queue["total"] == 8
        for item in queue["items"]:
            user_client.post(f"/api/projects/{pid}/screening/vote",
                             json={"record_id": item["id"], "decision": "include"})

    # the round can now complete, late records included
    _login(user_client, "admin")
    stats = user_client.get(f"/api/projects/{pid}/screening/stats").json()
    assert stats["included"] == 8
    p = user_client.get(f"/api/projects/{pid}/progress").json()
    assert "screening" in p["done"]


# ---- pipeline progress -----------------------------------------------------------

def test_project_progress(user_client, team, project):
    pid = project["id"]
    # imports + dedup done, screening not started
    p = user_client.get(f"/api/projects/{pid}/progress").json()
    assert "search" in p["done"] and "dedup" in p["done"]
    assert p["current"] == "screening"
    assert p["rounds"] == {"ta": [], "ft": []}

    _setup(user_client, pid, team)
    p = user_client.get(f"/api/projects/{pid}/progress").json()
    assert p["current"] == "screening"
    ta = p["rounds"]["ta"]
    assert len(ta) == 1 and ta[0]["round"] == 1 and ta[0]["done"] is False

    # both reviewers vote everything -> screening done, current moves on
    for who in ("admin", "reviewer"):
        _login(user_client, who)
        queue = user_client.get(
            f"/api/projects/{pid}/screening/queue?limit=50").json()
        for item in queue["items"]:
            user_client.post(f"/api/projects/{pid}/screening/vote",
                             json={"record_id": item["id"], "decision": "include"})
    _login(user_client, "admin")
    p = user_client.get(f"/api/projects/{pid}/progress").json()
    assert "screening" in p["done"]
    assert p["rounds"]["ta"][0]["done"] is True
    assert p["current"] == "fulltext"


# ---- list view + keyword search (ticket #8) --------------------------------------

def test_list_view_search_and_status(user_client, team, project):
    pid = project["id"]
    _setup(user_client, pid, team)

    listing = user_client.get(f"/api/projects/{pid}/screening/list").json()
    assert listing["total"] == 6 and len(listing["items"]) == 6
    assert all(item["decision"] is None for item in listing["items"])
    # blind: my list never contains other reviewers'"'"' votes
    assert all("votes" not in item for item in listing["items"])
    # each card carries its tags, so the list needs no per-record request
    first = listing["items"][0]["id"]
    user_client.post(f"/api/projects/{pid}/tags/records/{first}",
                     json={"name": "Intro/Discussion"})
    tagged = user_client.get(f"/api/projects/{pid}/screening/list").json()
    assert {it["id"]: [t["name"] for t in it["tags"]]
            for it in tagged["items"]}[first] == ["Intro/Discussion"]

    # keyword search: AND of terms, case- and accent-insensitive, on
    # title/abstract/authors/journal
    hits = user_client.get(
        f"/api/projects/{pid}/screening/list?q=cycling&status=all").json()
    assert hits["total"] == 1
    assert "Cycling" in hits["items"][0]["title"]
    accents = user_client.get(
        f"/api/projects/{pid}/screening/list?q=s%C3%A9rious%20g%C3%A2mes&status=all").json()
    assert accents["total"] == 1  # "Serious games in nursing education"
    author = user_client.get(
        f"/api/projects/{pid}/screening/list?q=author3&status=all").json()
    assert author["total"] == 1
    assert user_client.get(
        f"/api/projects/{pid}/screening/list?q=nomatchxyz&status=all"
    ).json()["total"] == 0

    # voting from the list: the record moves to the voted filter with my vote
    record_id = hits["items"][0]["id"]
    r = user_client.post(f"/api/projects/{pid}/screening/vote",
                         json={"record_id": record_id, "decision": "include",
                               "justification": "from the list"})
    assert r.status_code == 200
    pending = user_client.get(f"/api/projects/{pid}/screening/list").json()
    assert pending["total"] == 5
    voted = user_client.get(
        f"/api/projects/{pid}/screening/list?status=voted").json()
    assert voted["total"] == 1
    assert voted["items"][0]["decision"] == "include"
    assert voted["items"][0]["note"] == "from the list"
    assert voted["items"][0]["locked"] is False  # 1 of 2 votes: still mine to change

    # pagination
    page = user_client.get(
        f"/api/projects/{pid}/screening/list?status=all&limit=2&offset=4").json()
    assert page["total"] == 6 and len(page["items"]) == 2


def test_reviewer_summary_folds_the_whole_review(user_client, team, project):
    """The PRISMA page's per-reviewer block: votes summed over the rounds,
    conflict resolutions credited to who settled them, pooled kappa."""
    pid = project["id"]
    _setup(user_client, pid, team)
    ids = [i["id"] for i in
           user_client.get(f"/api/projects/{pid}/screening/queue").json()["items"]]

    def vote(who, record_id, decision):
        _login(user_client, who)
        return user_client.post(f"/api/projects/{pid}/screening/vote",
                                json={"record_id": record_id, "decision": decision})

    vote("admin", ids[0], "include"); vote("reviewer", ids[0], "include")
    vote("admin", ids[1], "include"); vote("reviewer", ids[1], "exclude")
    vote("admin", ids[2], "maybe");   vote("reviewer", ids[2], "include")
    vote("admin", ids[3], "exclude")
    _login(user_client, "reviewer")
    cid = user_client.get(f"/api/projects/{pid}/screening/conflicts").json()[0]["id"]
    user_client.post(f"/api/projects/{pid}/screening/conflicts/{cid}/resolve",
                     json={"decision": "include"})

    summary = user_client.get(f"/api/projects/{pid}/prisma/reviewers").json()
    by_name = {r["display_name"]: r for r in summary["reviewers"]}
    assert list(by_name) == ["Admin", "Reviewer"]
    admin, rev = by_name["Admin"], by_name["Reviewer"]
    assert admin["role"] == "admin" and rev["role"] == "reviewer"
    assert admin["ta"] == {"assigned": 6, "done": 4, "include": 2, "exclude": 1,
                           "maybe": 1, "triage_excluded": 0, "triage_votes": 0}
    assert rev["ta"]["done"] == 3 and rev["ta"]["include"] == 2
    assert rev["ft"]["done"] == 0  # no full-text round yet
    assert rev["conflicts_resolved"] == {"ta": 1, "ft": 0}
    assert admin["conflicts_resolved"] == {"ta": 0, "ft": 0}
    assert admin["dedup_decisions"] == 0 and admin["appraisals"] == 0
    assert admin["extraction"] == {"records": 0, "cells": 0}

    ta = summary["agreement"]["ta"]
    assert ta["n_rounds"] == 1 and ta["n_records"] == 3
    assert ta["maybe_as_include"] is True
    assert ta["percent"] == pytest.approx(2 / 3)
    [pair] = ta["pairs"]
    assert (pair["rows_name"], pair["cols_name"]) == ("Admin", "Reviewer")
    assert pair["kappa"] == pytest.approx(0.0, abs=1e-9)
    assert summary["agreement"]["ft"]["pairs"] == []
    assert summary["rounds"] == {"ta": [1], "ft": []}


# ---- lead reviewer: one screens everything, the others share ---------------------

def _third_member(user_client, team, pid):
    user_client.post("/api/auth/register", json={
        "email": "third@example.com", "password": "password123",
        "display_name": "Third"})
    third = user_client.get("/api/auth/me").json()
    _login(user_client, "admin")
    user_client.post(f"/api/projects/{pid}/members",
                     json={"email": "third@example.com", "role": "reviewer"})
    return third


def test_lead_allocation_equal_shares(user_client, team, project):
    """6 records, lead + 2 co-reviewers: the lead holds 6, each co-reviewer
    3, every record has exactly two assignments."""
    pid = project["id"]
    third = _third_member(user_client, team, pid)
    lead, a, b = team["admin"]["id"], team["reviewer"]["id"], third["id"]
    summary = _setup(user_client, pid, team, allocation="lead",
                     lead_user_id=lead, reviewer_ids=[lead, a, b])
    assert summary == {"records": 6, "reviewers": 3, "double_screened": 6}
    stats = user_client.get(f"/api/projects/{pid}/screening/stats").json()
    assigned = {e["user_id"]: e["assigned"] for e in stats["per_reviewer"]}
    assert assigned == {lead: 6, a: 3, b: 3}
    assert stats["lead_user_id"] == lead
    shares = {s["user_id"]: s for s in stats["shares"]}
    assert set(shares) == {a, b}
    assert shares[a]["effective_pct"] == 50.0
    assert user_client.get(f"/api/projects/{pid}/screening/queue").json()["total"] == 6
    # a lead/co-reviewer disagreement is an ordinary conflict
    ids = [i["id"] for i in
           user_client.get(f"/api/projects/{pid}/screening/queue").json()["items"]]
    user_client.post(f"/api/projects/{pid}/screening/vote",
                     json={"record_id": ids[0], "decision": "include"})
    _login(user_client, "reviewer")
    q = user_client.get(f"/api/projects/{pid}/screening/queue").json()
    assert q["total"] == 3
    if ids[0] in [i["id"] for i in q["items"]]:
        user_client.post(f"/api/projects/{pid}/screening/vote",
                         json={"record_id": ids[0], "decision": "exclude"})
    else:
        user_client.post("/api/auth/login", json={
            "email": "third@example.com", "password": "password123"})
        user_client.post(f"/api/projects/{pid}/screening/vote",
                         json={"record_id": ids[0], "decision": "exclude"})
    _login(user_client, "admin")
    stats = user_client.get(f"/api/projects/{pid}/screening/stats").json()
    assert stats["conflicts_open"] == 1


def test_lead_allocation_weighted_shares(user_client, team, project):
    pid = project["id"]
    third = _third_member(user_client, team, pid)
    lead, a, b = team["admin"]["id"], team["reviewer"]["id"], third["id"]
    # shares are over the co-reviewers only; a weight on the lead is dropped
    _setup(user_client, pid, team, allocation="lead", lead_user_id=lead,
           reviewer_ids=[lead, a, b],
           weights={str(lead): 40, str(a): 67, str(b): 33})
    stats = user_client.get(f"/api/projects/{pid}/screening/stats").json()
    assigned = {e["user_id"]: e["assigned"] for e in stats["per_reviewer"]}
    assert assigned == {lead: 6, a: 4, b: 2}
    shares = {s["user_id"]: s for s in stats["shares"]}
    assert shares[a]["target_pct"] == 67


def test_lead_allocation_guards(user_client, team, project):
    pid = project["id"]
    lead, a = team["admin"]["id"], team["reviewer"]["id"]
    base = f"/api/projects/{pid}/screening"
    # no lead picked
    r = user_client.put(f"{base}/config", json={
        "stage": "ta", "allocation": "lead", "reviewer_ids": [lead, a]})
    assert r.status_code == 200
    r = user_client.post(f"{base}/start")
    assert r.status_code == 400 and "lead reviewer" in r.json()["detail"]
    # lead alone
    r = user_client.put(f"{base}/config", json={
        "stage": "ta", "allocation": "lead", "lead_user_id": lead,
        "reviewer_ids": [lead]})
    assert r.status_code == 200
    assert user_client.post(f"{base}/start").status_code == 400
    # shares of the co-reviewers must add up to 100
    r = user_client.put(f"{base}/config", json={
        "stage": "ta", "allocation": "lead", "lead_user_id": lead,
        "reviewer_ids": [lead, a], "weights": {str(a): 60}})
    assert r.status_code == 400
    # lead + one co-reviewer: both screen everything
    _setup(user_client, pid, team, allocation="lead", lead_user_id=lead,
           reviewer_ids=[lead, a])
    stats = user_client.get(f"{base}/stats").json()
    assert {e["assigned"] for e in stats["per_reviewer"]} == {6}


def test_lead_allocation_late_records_keep_the_balance(user_client, team, project):
    pid = project["id"]
    third = _third_member(user_client, team, pid)
    lead, a, b = team["admin"]["id"], team["reviewer"]["id"], third["id"]
    _setup(user_client, pid, team, allocation="lead", lead_user_id=lead,
           reviewer_ids=[lead, a, b])
    late = "".join(f"""TY  - JOUR
TI  - Late study {i}
AU  - Late, L.
PY  - 2024
DO  - 10.1/late.{i}
ER  -
""" for i in range(4))
    user_client.post(
        f"/api/projects/{pid}/imports/upload",
        files={"file": ("late.ris", late.encode(), "text/plain")},
        data={"source_name": "wos", "source_type": "database"})
    _run_dedup(user_client, pid)
    user_client.get(f"/api/projects/{pid}/screening/queue")  # syncs
    stats = user_client.get(f"/api/projects/{pid}/screening/stats").json()
    assigned = {e["user_id"]: e["assigned"] for e in stats["per_reviewer"]}
    assert assigned == {lead: 10, a: 5, b: 5}
