"""Pre-filled reporting checklists, and the triage triggers.

CREST_Triage flags "self-declared compliance with standard rather than
analysis thereof". The whole point of this module is to answer that with facts,
so what is under test is that an item says what *happened* — including that
nothing happened — and never that the review is adequate.
"""
from tests.test_extraction import ext_project, team, _login, _await_job  # noqa: F401


def _api(pid):
    return f"/api/projects/{pid}/reporting/checklists"


def _rows(client, pid, key="prisma2020"):
    data = client.get(_api(pid)).json()
    block = next(c for c in data["checklists"] if c["key"] == key)
    return {r["number"]: r for r in block["rows"]}, data


# -- the catalogue ------------------------------------------------------------

def test_the_prisma_checklist_is_complete_and_uniquely_numbered():
    from app.services.reporting.checklists import prisma2020
    numbers = [i.number for i in prisma2020.ITEMS]
    assert len(numbers) == len(set(numbers))
    # the 2020 statement's own row count
    assert len(numbers) == 42
    assert numbers[0] == "1" and numbers[-1] == "27"
    for item in prisma2020.ITEMS:
        assert item.section and item.text


def test_swim_is_offered_only_to_the_reviews_it_covers(user_client, ext_project):
    """SWiM exists for reviews where meta-analysis was not possible for at
    least some outcomes; showing it to a review it does not cover teaches
    people that checklists are noise."""
    pid = ext_project["pid"]
    keys = [c["key"] for c in user_client.get(_api(pid)).json()["checklists"]]
    assert keys == ["prisma2020"]

    user_client.put(f"/api/projects/{pid}/synthesis/plan",
                    json={"enabled": True})
    user_client.post(f"/api/projects/{pid}/synthesis/outcomes",
                     json={"label": "Mortality",
                           "synthesis_method": "meta_analysis"})
    keys = [c["key"] for c in user_client.get(_api(pid)).json()["checklists"]]
    assert keys == ["prisma2020"], "a fully meta-analysed review is out of scope"

    user_client.post(f"/api/projects/{pid}/synthesis/outcomes",
                     json={"label": "Adherence",
                           "synthesis_method": "vote_counting"})
    keys = [c["key"] for c in user_client.get(_api(pid)).json()["checklists"]]
    assert keys == ["prisma2020", "swim"]


# -- what the pipeline can evidence -------------------------------------------

def test_the_pipeline_evidences_what_it_actually_recorded(user_client,
                                                          ext_project):
    rows, _ = _rows(user_client, ext_project["pid"])
    # eligibility criteria, selection process and the flow diagram are things
    # the app watched happen
    assert rows["5"]["status"] == "evidenced"
    assert "exclusion criteria" in rows["5"]["fact"]
    assert rows["8"]["status"] == "evidenced"
    assert "hidden from other reviewers" in rows["8"]["fact"]
    assert rows["16a"]["status"] == "evidenced"
    assert "identified" in rows["16a"]["fact"]


def test_a_stage_that_never_ran_reads_not_done_rather_than_blank(user_client,
                                                                 ext_project):
    """An empty cell reads as an oversight; "not done" reads as a finding —
    that distinction is the reason the file is worth having."""
    rows, _ = _rows(user_client, ext_project["pid"])
    assert rows["11"]["status"] == "not_done"     # no appraisal yet
    assert "No study was critically appraised" in rows["11"]["fact"]
    assert rows["15"]["status"] == "not_done"     # no certainty framework
    assert "methodological expectation" in rows["15"]["fact"]
    assert rows["13d"]["status"] == "not_done"    # synthesis undeclared


def test_the_review_type_default_is_never_presented_as_what_was_done(
        user_client, ext_project):
    rows, _ = _rows(user_client, ext_project["pid"])
    fact = rows["13d"]["fact"]
    assert "not a record of what was done" in fact


def test_items_outside_the_software_are_the_author_s(user_client, ext_project):
    rows, _ = _rows(user_client, ext_project["pid"])
    for number in ("1", "2", "3", "23a", "25", "26", "27"):
        assert rows[number]["status"] == "author", number


def test_registration_flows_into_item_24a(user_client, ext_project):
    pid = ext_project["pid"]
    rows, _ = _rows(user_client, pid)
    assert rows["24a"]["status"] == "not_done"

    user_client.put(f"/api/projects/{pid}", json={"registry": "none"})
    rows, _ = _rows(user_client, pid)
    # "we did not register" is an answer, not a gap
    assert rows["24a"]["status"] == "evidenced"
    assert "not registered" in rows["24a"]["fact"]

    user_client.put(f"/api/projects/{pid}", json={
        "registry": "prospero", "registration_id": "CRD42026000001"})
    rows, _ = _rows(user_client, pid)
    assert "CRD42026000001" in rows["24a"]["fact"]


# -- what the author adds ------------------------------------------------------

def test_an_author_can_add_a_page_reference_and_override_a_status(user_client,
                                                                   ext_project):
    pid = ext_project["pid"]
    user_client.put(f"{_api(pid)}/answer", json={
        "checklist": "prisma2020", "item": "25", "page_ref": "p. 14",
        "note": "Funded by ANR, no role in the review."})
    rows, _ = _rows(user_client, pid)
    assert rows["25"]["page_ref"] == "p. 14"
    assert rows["25"]["note"].startswith("Funded")
    assert rows["25"]["overridden"] is False

    # only a human knows an item does not apply to their review
    user_client.put(f"{_api(pid)}/answer", json={
        "checklist": "prisma2020", "item": "13f", "status_override": "n_a"})
    rows, _ = _rows(user_client, pid)
    assert rows["13f"]["status"] == "n_a"
    assert rows["13f"]["overridden"] is True


def test_the_checklist_exports_as_the_supplementary_file(user_client,
                                                         ext_project):
    pid = ext_project["pid"]
    user_client.put(f"{_api(pid)}/answer", json={
        "checklist": "prisma2020", "item": "25", "page_ref": "p. 14",
        "note": "Funded by ANR."})
    r = user_client.get(f"{_api(pid)}/prisma2020.csv")
    assert r.status_code == 200
    assert "Location where item is reported" in r.text
    assert "p. 14" in r.text and "Funded by ANR." in r.text
    # a checklist that does not apply is a 404, not an empty file
    assert user_client.get(f"{_api(pid)}/swim.csv").status_code == 404


# -- triage triggers -----------------------------------------------------------

def test_the_triggers_name_the_problems_crest_looks_for(user_client,
                                                        ext_project):
    _, data = _rows(user_client, ext_project["pid"])
    keys = {t["key"] for t in data["triggers"]}
    assert "no_appraisal" in keys
    assert "synthesis_undeclared" in keys
    assert "no_registration" in keys
    blocking = [t for t in data["triggers"] if t["severity"] == "blocking"]
    assert blocking and blocking[0] == data["triggers"][0], "blocking first"


def test_a_trigger_disappears_once_the_problem_is_fixed(user_client,
                                                        ext_project):
    pid = ext_project["pid"]
    rid = ext_project["included"][0]
    _, data = _rows(user_client, pid)
    assert "no_appraisal" in {t["key"] for t in data["triggers"]}

    user_client.put(f"/api/projects/{pid}/extraction/records/{rid}/design",
                    json={"design": "rct"})
    user_client.put(f"/api/projects/{pid}/extraction/records/{rid}/jbi",
                    json={"answers": {"q1": {"answer": "yes", "comment": ""}},
                          "overall": "include"})
    _, data = _rows(user_client, pid)
    keys = {t["key"] for t in data["triggers"]}
    assert "no_appraisal" not in keys
    # …and the softer one takes its place, because one assessor is not two
    assert "single_assessor" in keys


def test_no_certainty_trigger_without_outcomes_to_rate(user_client,
                                                       ext_project):
    """A review that declared no outcome is not yet failing to rate them."""
    _, data = _rows(user_client, ext_project["pid"])
    assert "no_certainty" not in {t["key"] for t in data["triggers"]}

    pid = ext_project["pid"]
    user_client.put(f"/api/projects/{pid}/synthesis/plan", json={"enabled": True})
    user_client.post(f"/api/projects/{pid}/synthesis/outcomes",
                     json={"label": "Mortality"})
    _, data = _rows(user_client, pid)
    assert "no_certainty" in {t["key"] for t in data["triggers"]}


def test_the_triggers_report_problems_not_a_score(user_client, ext_project):
    """Reproducing CREST's 1-5 scoring would turn an editor's tool into an
    author's, and a self-awarded 4 is the very self-declaration it catches."""
    _, data = _rows(user_client, ext_project["pid"])
    for trigger in data["triggers"]:
        assert set(trigger) == {"key", "domain", "severity", "message"}
        assert trigger["severity"] in ("blocking", "advisory")


def test_a_clean_project_gets_no_wall_of_green_ticks(user_client):
    """Only present problems are listed — a tick nobody reads is noise."""
    from app.core.db import SessionLocal
    from app.services.reporting.checklists import crest
    from app.services.reporting.audit import review_dossier
    pid = user_client.post("/api/projects", json={"name": "P"}).json()["id"]
    with SessionLocal() as db:
        triggers = crest.evaluate(review_dossier(db, pid))
    # an empty project has no appraisal to miss and no outcome to rate; the
    # only thing it is really missing is the registration answer
    assert {t["key"] for t in triggers} <= {"no_registration",
                                            "no_characteristics_table",
                                            "synthesis_undeclared"}
