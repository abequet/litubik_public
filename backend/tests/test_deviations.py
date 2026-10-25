"""Protocol deviations: what the tables betray, and what the team declares.

The rule the whole module serves is that a detected signal is a *question*, not
a verdict. Amending a protocol is legitimate; what a reader needs is the
amendment and its reason, and only the team has the reason. So nothing is ever
promoted to a deviation automatically, and an answered signal stops being
offered.
"""
import pytest

from tests.test_extraction import ext_project, team, _login, _await_job  # noqa: F401


def _api(pid):
    return f"/api/projects/{pid}/reporting/deviations"


@pytest.fixture
def with_signal(user_client, ext_project):
    """A project whose eligibility criteria were reworded after screening had
    already begun — the signal the register exists to catch."""
    pid = ext_project["pid"]
    first = user_client.get(f"/api/projects/{pid}/protocols").json()[0]
    user_client.post(f"/api/projects/{pid}/protocols/upload",
                     files={"file": ("p2.md", b"# P2", "text/markdown")})
    v2 = [p for p in user_client.get(f"/api/projects/{pid}/protocols").json()
          if p["id"] != first["id"]][0]
    user_client.put(f"/api/projects/{pid}/protocols/{v2['id']}", json={
        "protocol_md": "# P2", "criteria": [
            {"code": "E1", "type": "exclude", "label": "wrong population",
             "description": "reworded after the fact"}]})
    user_client.post(f"/api/projects/{pid}/protocols/{v2['id']}/validate")
    return pid


def test_a_clean_project_raises_no_signal(user_client):
    """Nothing happened out of order, so nothing is flagged — the register
    must not manufacture concerns."""
    pid = user_client.post("/api/projects", json={"name": "P"}).json()["id"]
    data = user_client.get(_api(pid)).json()
    assert data["signals"] == []
    assert data["deviations"] == []
    assert data["n_undeclared_signals"] == 0


def test_criteria_changed_after_screening_started_is_detected(user_client,
                                                              ext_project):
    """The strongest signal there is: records were judged against one set of
    criteria and the review would report another."""
    pid = ext_project["pid"]
    protocols = user_client.get(f"/api/projects/{pid}/protocols").json()
    first = protocols[0]

    # a second version, validated now — after the fixture's screening votes
    user_client.post(f"/api/projects/{pid}/protocols/upload",
                     files={"file": ("p2.md", b"# P2", "text/markdown")})
    v2 = [p for p in user_client.get(f"/api/projects/{pid}/protocols").json()
          if p["id"] != first["id"]][0]
    user_client.put(f"/api/projects/{pid}/protocols/{v2['id']}", json={
        "protocol_md": "# P2", "criteria": [
            {"code": "E1", "type": "exclude", "label": "wrong population",
             "description": "reworded after the fact"},
            {"code": "E2", "type": "exclude", "label": "wrong setting",
             "description": "added mid-screening"}]})
    user_client.post(f"/api/projects/{pid}/protocols/{v2['id']}/validate")

    signals = user_client.get(_api(pid)).json()["signals"]
    criteria = [s for s in signals if s["signal"].startswith("criteria_changed")]
    assert len(criteria) == 1
    assert criteria[0]["stage"] == "protocol"
    assert "after screening had begun" in criteria[0]["summary"]


def test_answering_a_signal_stops_it_being_offered_again(user_client,
                                                         with_signal):
    pid = with_signal
    signals = user_client.get(_api(pid)).json()["signals"]
    assert signals
    signal = signals[0]

    data = user_client.post(_api(pid), json={
        "stage": signal["stage"], "signal": signal["signal"],
        "summary": signal["summary"],
        "rationale": "A reviewer found the wording ambiguous.",
        "occurred_at": signal["occurred_at"]}).json()
    assert signal["signal"] not in [s["signal"] for s in data["signals"]]
    declared = [d for d in data["deviations"] if d["signal"] == signal["signal"]]
    assert len(declared) == 1
    assert declared[0]["kind"] == "detected"
    assert declared[0]["rationale"].startswith("A reviewer")


def test_dismissing_a_signal_is_recorded_not_forgotten(user_client,
                                                       with_signal):
    """"We looked at this and it was not a deviation" is itself a finding —
    losing it would mean re-litigating the same signal at the next reading."""
    pid = with_signal
    signal = user_client.get(_api(pid)).json()["signals"][0]
    data = user_client.post(f"{_api(pid)}/dismiss", json={
        "signal": signal["signal"], "summary": signal["summary"],
        "note": "A typo fix, not a change of meaning."}).json()
    assert signal["signal"] not in [s["signal"] for s in data["signals"]]
    row = next(d for d in data["deviations"] if d["signal"] == signal["signal"])
    assert row["dismissed"] is True
    assert "typo fix" in row["dismiss_note"]


def test_a_team_can_declare_a_change_no_table_could_see(user_client,
                                                        ext_project):
    pid = ext_project["pid"]
    data = user_client.post(_api(pid), json={
        "stage": "synthesis",
        "summary": "Outcomes were regrouped by setting rather than by age.",
        "rationale": "Too few studies reported age bands to group on them."}).json()
    row = next(d for d in data["deviations"] if d["stage"] == "synthesis")
    assert row["kind"] == "declared"
    assert row["signal"] is None
    assert row["stage_label"] == "Synthesis"


def test_an_unknown_stage_is_rejected(user_client, ext_project):
    r = user_client.post(_api(ext_project["pid"]),
                         json={"stage": "nawak", "summary": "x"})
    assert r.status_code == 400


def test_a_deviation_can_be_edited_and_removed(user_client, ext_project):
    pid = ext_project["pid"]
    data = user_client.post(_api(pid), json={
        "stage": "search", "summary": "Added a database", "rationale": ""}).json()
    row = next(d for d in data["deviations"] if d["stage"] == "search")
    data = user_client.put(f"{_api(pid)}/{row['id']}", json={
        "stage": "search", "summary": "Added TRID mid-search",
        "rationale": "Transport coverage was thin."}).json()
    updated = next(d for d in data["deviations"] if d["id"] == row["id"])
    assert updated["rationale"] == "Transport coverage was thin."
    data = user_client.delete(f"{_api(pid)}/{row['id']}").json()
    assert row["id"] not in [d["id"] for d in data["deviations"]]


# -- what the manuscript reads ------------------------------------------------

def test_only_declared_deviations_reach_the_dossier(user_client, with_signal):
    """A signal nobody answered is a question for the team, not a fact about
    the review — the Methods draft must not report it as an amendment."""
    from app.core.db import SessionLocal
    from app.services.reporting.audit import review_dossier
    pid = with_signal

    with SessionLocal() as db:
        block = review_dossier(db, pid)["deviations"]
    assert block["n_declared"] == 0
    assert block["n_detected_unanswered"] >= 1
    assert block["deviations"] == []

    user_client.post(_api(pid), json={
        "stage": "screening", "summary": "Switched to dual screening",
        "rationale": "Agreement was too low in the pilot."})
    with SessionLocal() as db:
        block = review_dossier(db, pid)["deviations"]
    assert block["n_declared"] == 1
    assert block["deviations"][0]["why"].startswith("Agreement")


def test_an_answered_signal_reaches_the_dossier(user_client, with_signal):
    """A detected change the team explains is an amendment like any other:
    the Methods draft lists it (it used to vanish from both lists)."""
    from app.core.db import SessionLocal
    from app.services.reporting.audit import review_dossier
    pid = with_signal
    signal = user_client.get(_api(pid)).json()["signals"][0]
    user_client.post(_api(pid), json={
        "stage": signal["stage"], "signal": signal["signal"],
        "summary": signal["summary"],
        "rationale": "A reviewer found the wording ambiguous.",
        "occurred_at": signal["occurred_at"]})
    with SessionLocal() as db:
        block = review_dossier(db, pid)["deviations"]
    assert block["n_declared"] == 1
    assert block["deviations"][0]["why"].startswith("A reviewer")


def test_a_dismissed_signal_is_not_reported_as_an_amendment(user_client,
                                                            with_signal):
    from app.core.db import SessionLocal
    from app.services.reporting.audit import review_dossier
    pid = with_signal
    signal = user_client.get(_api(pid)).json()["signals"][0]
    user_client.post(f"{_api(pid)}/dismiss",
                     json={"signal": signal["signal"], "note": "not a change"})
    with SessionLocal() as db:
        block = review_dossier(db, pid)["deviations"]
    assert block["n_declared"] == 0


def test_the_register_travels_in_a_snapshot(user_client, ext_project):
    from app.core.db import SessionLocal
    from app.models import Project
    from app.services.sync.serialize import serialize_project
    pid = ext_project["pid"]
    user_client.post(_api(pid), json={
        "stage": "protocol", "summary": "Widened the year window",
        "rationale": "Too few records before 2015."})
    with SessionLocal() as db:
        data = serialize_project(db, db.get(Project, pid))
    rows = data["protocol_deviations"]
    assert len(rows) == 1
    assert rows[0]["rationale"].startswith("Too few")
