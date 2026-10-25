"""Weighted lots, rotating pairs, named arbiters, preview,
validated start, allocation export, late lots."""
import csv
import io
from collections import Counter

import pytest

from app.services.screening.lots import (
    allowed_pairs, effective_weights, plan_lots, plan_pairs, weights_error,
)
from tests.test_screening import (  # noqa: F401 — fixtures
    LATE_RIS, _login, _run_dedup, project, team,
)

FIVE = [1, 2, 3, 4, 5]
WEIGHTS = {"1": 30, "2": 25, "3": 20, "4": 15, "5": 10}


def _counts(plan):
    counts = Counter()
    for lot in plan:
        for u in lot["user_ids"]:
            counts[u] += len(lot["record_ids"])
    return counts


# ---- planner ------------------------------------------------------------------------

def test_weighted_shares_within_one_lot():
    """5 reviewers at 30/25/20/15/10 %, 1000 records, lots of 100: every
    reviewer's assignments land within one lot of their target."""
    plan = plan_lots(list(range(1, 1001)), FIVE, WEIGHTS, 100)
    assert len(plan) == 10
    assert [lot["index"] for lot in plan] == list(range(1, 11))
    counts = _counts(plan)
    for u in FIVE:
        target = WEIGHTS[str(u)] / 100 * 2000
        assert abs(counts[u] - target) <= 100, (u, counts[u], target)
    # every record is screened exactly twice
    assert sum(counts.values()) == 2000
    for lot in plan:
        assert len(set(lot["user_ids"])) == 2


def test_weighted_shares_with_an_uneven_corpus():
    plan = plan_lots(list(range(1, 998)), FIVE, WEIGHTS, 100)
    assert len(plan) == 10 and len(plan[-1]["record_ids"]) == 97
    counts = _counts(plan)
    for u in FIVE:
        assert abs(counts[u] - WEIGHTS[str(u)] / 100 * 2 * 997) <= 100


def test_every_pair_is_served_before_any_repeats():
    """Equal shares: 5 reviewers = 10 pairs; the first 10 lots use 10
    distinct pairs, and 20 lots use every pair exactly twice."""
    pairs = plan_pairs([100] * 20, FIVE, None, None)
    first = [tuple(sorted(p)) for p in pairs[:10]]
    assert len(set(first)) == 10
    assert Counter(tuple(sorted(p)) for p in pairs) == {
        p: 2 for p in allowed_pairs(FIVE, None)}
    # four reviewers, 6 pairs, 12 lots -> twice each, first six distinct
    pairs = plan_pairs([50] * 12, [1, 2, 3, 4], None, None)
    assert len({tuple(sorted(p)) for p in pairs[:6]}) == 6
    assert set(Counter(tuple(sorted(p)) for p in pairs).values()) == {2}


def test_arbiters_are_never_paired_together():
    plan = plan_lots(list(range(1, 2001)), FIVE, WEIGHTS, 100, arbiter_ids=[1, 2])
    for lot in plan:
        assert set(lot["user_ids"]) != {1, 2}
    assert (1, 2) not in allowed_pairs(FIVE, [1, 2])
    assert len(allowed_pairs(FIVE, [1, 2])) == 9
    # the shares still hold (arbiter 1 keeps 30 % without ever meeting 2)
    counts = _counts(plan)
    for u in FIVE:
        assert abs(counts[u] - WEIGHTS[str(u)] / 100 * 4000) <= 100
    # two arbiters who are the only reviewers: no pair at all
    assert allowed_pairs([1, 2], [1, 2]) == []
    with pytest.raises(ValueError):
        plan_pairs([10], [1, 2], None, [1, 2])


def test_late_lots_continue_on_the_remaining_quotas():
    plan = plan_lots(list(range(1, 1001)), FIVE, WEIGHTS, 100)
    assigned = _counts(plan)
    served = {tuple(sorted(lot["user_ids"])): lot["index"] for lot in plan}
    late = plan_lots(list(range(1001, 1301)), FIVE, WEIGHTS, 100,
                     first_index=11, total_records=1300, assigned=assigned,
                     served=served)
    assert [lot["index"] for lot in late] == [11, 12, 13]
    total = assigned + _counts(late)
    for u in FIVE:
        assert abs(total[u] - WEIGHTS[str(u)] / 100 * 2600) <= 100


def test_weights_helpers():
    assert effective_weights([1, 2], None) == {1: 50, 2: 50}
    assert effective_weights([1, 2, 3], {"1": 60, "2": 40}) == {1: 60, 2: 40, 3: 0}
    assert weights_error([1, 2], {"1": 60, "2": 30}) is not None
    assert weights_error([1, 2], {"1": 60, "2": 40}) is None
    assert weights_error([1, 2], None) is None


# ---- API ---------------------------------------------------------------------------

@pytest.fixture
def trio(user_client, team, project):
    """A third member, so the round has 3 reviewers (3 pairs)."""
    user_client.post("/api/auth/register", json={
        "email": "third@example.com", "password": "password123",
        "display_name": "Third"})
    third = user_client.get("/api/auth/me").json()
    _login(user_client, "admin")
    user_client.post(f"/api/projects/{project['id']}/members",
                     json={"email": "third@example.com", "role": "reviewer"})
    return [team["admin"]["id"], team["reviewer"]["id"], third["id"]]


def _config(client, pid, reviewers, **overrides):
    payload = {"stage": "ta", "allocation": "lots", "lot_size": 2,
               "conflict_resolution": "consensus", "ai_enabled": False,
               "reviewer_ids": reviewers,
               "weights": {str(reviewers[0]): 50, str(reviewers[1]): 30,
                           str(reviewers[2]): 20},
               **overrides}
    return client.put(f"/api/projects/{pid}/screening/config", json=payload)


def test_preview_edit_start_export_and_late_lot(user_client, team, project, trio):
    pid = project["id"]
    a, b, c = trio
    r = _config(user_client, pid, trio, arbiter_ids=[a, b])
    assert r.status_code == 200, r.text
    cfg = r.json()
    assert cfg["allocation"] == "lots" and cfg["lot_size"] == 2
    assert cfg["arbiter_ids"] == [a, b]
    assert cfg["weights"] == {str(a): 50.0, str(b): 30.0, str(c): 20.0}

    # preview: 6 records / lots of 2 = 3 lots, the two arbiters never together
    r = user_client.post(f"/api/projects/{pid}/screening/lots/preview")
    assert r.status_code == 200, r.text
    preview = r.json()
    assert preview["n_records"] == 6 and len(preview["lots"]) == 3
    assert [l["index"] for l in preview["lots"]] == [1, 2, 3]
    assert all(l["size"] == 2 for l in preview["lots"])
    for lot in preview["lots"]:
        assert set(lot["user_ids"]) != {a, b}
    assert sorted(map(tuple, preview["pairs"])) == sorted([(a, c), (b, c)])
    shares = {s["user_id"]: s for s in preview["shares"]}
    assert shares[a]["target_pct"] == 50 and shares[c]["assigned"] == 6

    # the admin edits lot 2 to (b, c) with a deadline, then starts with it
    lots = preview["lots"]
    lots[1]["user_ids"] = [b, c]
    lots[1]["due_at"] = "2026-11-30T00:00:00Z"
    r = user_client.post(f"/api/projects/{pid}/screening/start",
                         json={"lots": lots})
    assert r.status_code == 200, r.text
    assert r.json()["lots"] == 3 and r.json()["assignments"] == 12

    stats = user_client.get(f"/api/projects/{pid}/screening/stats").json()
    assert stats["allocation"] == "lots"
    assert [l["index"] for l in stats["lots"]] == [1, 2, 3]
    assert stats["lots"][1]["user_ids"] == [b, c]
    assert stats["lots"][1]["due_at"].startswith("2026-11-30")
    assert all(l["status"] == "open" for l in stats["lots"])
    effective = {s["user_id"]: s["effective_pct"] for s in stats["shares"]}
    assert sum(effective.values()) == pytest.approx(100)

    # the export: one line per lot, names of the pair, deadline, status
    r = user_client.get(f"/api/projects/{pid}/screening/allocation.csv")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    rows = list(csv.reader(io.StringIO(r.content.decode("utf-8-sig"))))
    assert rows[0] == ["Lot", "Size", "Reviewer A", "Reviewer B", "Due", "Status"]
    assert len(rows) == 4
    assert rows[2][:4] == ["2", "2", "Reviewer", "Third"]
    assert rows[2][4] == "2026-11-30" and rows[2][5] == "open"

    # lot 1 closes once both of its reviewers voted on its two records
    lot1 = stats["lots"][0]
    for uid in lot1["user_ids"]:
        who = {a: "admin", b: "reviewer"}.get(uid)
        if who is None:
            user_client.post("/api/auth/login", json={
                "email": "third@example.com", "password": "password123"})
        else:
            _login(user_client, who)
        queue = user_client.get(f"/api/projects/{pid}/screening/queue?limit=50").json()
        # lot order: the first records of the queue belong to lot 1
        for item in queue["items"][:2]:
            r = user_client.post(f"/api/projects/{pid}/screening/vote",
                                 json={"record_id": item["id"], "decision": "include"})
            assert r.status_code == 200, r.text
    _login(user_client, "admin")
    stats = user_client.get(f"/api/projects/{pid}/screening/stats").json()
    assert stats["lots"][0]["status"] == "closed"
    assert all(d["done"] == 2 for d in stats["lots"][0]["done"])
    assert stats["lots"][1]["status"] == "open"

    # late records (a later import) form a new lot, numbered after the others
    user_client.post(
        f"/api/projects/{pid}/imports/upload",
        files={"file": ("late.ris", LATE_RIS.encode(), "text/plain")},
        data={"source_name": "wos", "source_type": "database"})
    _run_dedup(user_client, pid)
    stats = user_client.get(f"/api/projects/{pid}/screening/stats").json()
    assert [l["index"] for l in stats["lots"]] == [1, 2, 3, 4]
    assert stats["lots"][3]["size"] == 2 and stats["lots"][3]["status"] == "open"
    assert set(stats["lots"][3]["user_ids"]) != {a, b}
    assert stats["assignments_total"] == 16
    rows = list(csv.reader(io.StringIO(user_client.get(
        f"/api/projects/{pid}/screening/allocation.csv").content.decode("utf-8-sig"))))
    assert len(rows) == 5

    # reset wipes the lots with the assignments
    user_client.post(f"/api/projects/{pid}/screening/reset")
    stats = user_client.get(f"/api/projects/{pid}/screening/stats").json()
    assert stats["lots"] == []


def test_lots_validation(user_client, team, project, trio):
    pid = project["id"]
    a, b, c = trio
    # shares must add up to 100
    r = _config(user_client, pid, trio, weights={str(a): 50, str(b): 30, str(c): 10})
    assert r.status_code == 400 and "100" in r.json()["detail"]
    # no weights = equal shares
    r = _config(user_client, pid, trio, weights=None)
    assert r.status_code == 200 and r.json()["weights"] is None
    preview = user_client.post(f"/api/projects/{pid}/screening/lots/preview").json()
    assert all(s["target_pct"] == pytest.approx(33.33, abs=0.01)
               for s in preview["shares"])
    # a validated plan whose pair is the two arbiters is refused
    _config(user_client, pid, trio, weights=None, arbiter_ids=[a, b])
    preview = user_client.post(f"/api/projects/{pid}/screening/lots/preview").json()
    bad = preview["lots"]
    bad[0]["user_ids"] = [a, b]
    r = user_client.post(f"/api/projects/{pid}/screening/start", json={"lots": bad})
    assert r.status_code == 400 and "arbiters" in r.json()["detail"]
    # ... as is a lot with one reviewer, or a stale plan
    bad[0]["user_ids"] = [a, a]
    r = user_client.post(f"/api/projects/{pid}/screening/start", json={"lots": bad})
    assert r.status_code == 400
    r = user_client.post(f"/api/projects/{pid}/screening/start",
                         json={"lots": preview["lots"][:2]})
    assert r.status_code == 400 and "preview" in r.json()["detail"]
    # the two arbiters cannot be the only two reviewers
    r = _config(user_client, pid, trio, reviewer_ids=[a, b], weights=None,
                arbiter_ids=[a, b])
    assert r.status_code == 200
    r = user_client.post(f"/api/projects/{pid}/screening/lots/preview")
    assert r.status_code == 400
    # without an edited plan the start applies the automatic one
    _config(user_client, pid, trio, weights=None)
    r = user_client.post(f"/api/projects/{pid}/screening/start")
    assert r.status_code == 200 and r.json()["lots"] == 3
    # the export is for members only when the round is in lots
    _login(user_client, "reviewer")
    assert user_client.get(f"/api/projects/{pid}/screening/allocation.csv").status_code == 200
    assert user_client.post(f"/api/projects/{pid}/screening/lots/preview").status_code == 403


def test_snowballing_round_copies_the_lot_settings(user_client, team, project, trio):
    from app.core.db import SessionLocal
    from app.services.snowballing.jobs import _copy_config
    pid = project["id"]
    a, b, c = trio
    _config(user_client, pid, trio, arbiter_ids=[a])
    with SessionLocal() as db:
        cfg = _copy_config(db, pid, "ta", 2)
        assert cfg.allocation == "lots" and cfg.lot_size == 2
        assert cfg.arbiter_ids == [a]
        assert cfg.weights == {str(a): 50.0, str(b): 30.0, str(c): 20.0}
        db.rollback()
