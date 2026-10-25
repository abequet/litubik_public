"""Synthesis declaration (SWiM) and certainty of the evidence (GRADE).

Three things are under test. That the stage stays optional and invisible until
a project turns it on. That the SWiM items a review must report have somewhere
to live, and that the synthesis method is declared rather than assumed from the
review type. And that GRADE is applied per outcome, over the studies that
contribute to *that* outcome, with the app proposing and the assessor deciding.
"""
import pytest

from app.services.synthesis import grade, methods
from tests.test_extraction import ext_project, team, _login, _await_job  # noqa: F401


def _api(pid):
    return f"/api/projects/{pid}/synthesis"


@pytest.fixture
def outcome(user_client, ext_project):
    """A project with the synthesis stage on, GRADE picked, and one outcome
    fed by the three included studies."""
    pid = ext_project["pid"]
    user_client.put(f"{_api(pid)}/plan", json={
        "enabled": True, "certainty_framework": "grade",
        "grouping_md": "Grouped by intervention type."})
    r = user_client.post(f"{_api(pid)}/outcomes", json={
        "label": "All-cause mortality", "comparison": "Breakfast cereals",
        "intent": "association", "direction": "decrease",
        "metric": "Risk ratio", "synthesis_method": "vote_counting",
        "record_ids": ext_project["included"]})
    assert r.status_code == 200, r.text
    return {"pid": pid, "outcome_id": r.json()["id"],
            "included": ext_project["included"]}


# -- the catalogues -----------------------------------------------------------

def test_every_synthesis_method_states_the_question_it_answers():
    """SWiM item 9 asks authors to report the limitation the choice of method
    imposes; the question each method answers is that limitation."""
    for m in methods.METHODS.values():
        assert m.label and m.question, m.key
    # the distinction SWiM exists for
    assert methods.method("meta_analysis").without_meta_analysis is False
    assert methods.method("vote_counting").without_meta_analysis is True
    assert methods.swim_applies(["meta_analysis", "vote_counting"]) is True
    assert methods.swim_applies(["meta_analysis"]) is False


def test_unknown_method_and_framework_keys_degrade(user_client, ext_project):
    assert methods.method("from-the-future").key == methods.DEFAULT_METHOD
    assert methods.method(None).key == methods.DEFAULT_METHOD
    r = user_client.put(f"{_api(ext_project['pid'])}/plan",
                        json={"enabled": True, "certainty_framework": "nawak"})
    assert r.status_code == 400


def test_the_catalogue_speaks_the_project_s_own_framework(user_client,
                                                          ext_project):
    """PICO says Outcome and has a comparator; SPIDER says Evaluation and has
    none. Asking a SPIDER review for its 'comparison' is how a tool teaches
    people to write 'n/a'."""
    pid = ext_project["pid"]
    cat = user_client.get(f"{_api(pid)}/catalogue").json()
    assert cat["outcome_slot"] == "Outcome"
    assert cat["comparison_slot"] == "Comparison"

    user_client.put(f"/api/projects/{pid}", json={"question_framework": "spider"})
    cat = user_client.get(f"{_api(pid)}/catalogue").json()
    assert cat["outcome_slot"] == "Evaluation"
    assert cat["comparison_slot"] == ""


# -- staying optional ---------------------------------------------------------

def test_a_project_that_never_opens_the_stage_declares_nothing(user_client,
                                                               ext_project):
    plan = user_client.get(f"{_api(ext_project['pid'])}/plan").json()
    assert plan["enabled"] is False
    assert plan["certainty_framework"] == "none"
    assert user_client.get(
        f"{_api(ext_project['pid'])}/outcomes").json()["outcomes"] == []


def test_certainty_is_refused_while_no_framework_is_picked(user_client,
                                                           ext_project):
    pid = ext_project["pid"]
    user_client.put(f"{_api(pid)}/plan", json={"enabled": True})
    oid = user_client.post(f"{_api(pid)}/outcomes",
                           json={"label": "Mortality"}).json()["id"]
    r = user_client.put(f"{_api(pid)}/outcomes/{oid}/certainty",
                        json={"final": "high"})
    assert r.status_code == 400


def test_grade_warns_but_does_not_forbid_on_a_qualitative_framing(user_client,
                                                                  ext_project):
    """GRADE rates quantitative estimates; CERQual is its qualitative
    counterpart. The team stays the judge of its own evidence."""
    pid = ext_project["pid"]
    user_client.put(f"/api/projects/{pid}", json={"question_framework": "spider"})
    r = user_client.put(f"{_api(pid)}/plan",
                        json={"enabled": True, "certainty_framework": "grade"})
    assert r.status_code == 200
    assert "CERQual" in r.json()["certainty_warning"]


# -- outcomes -----------------------------------------------------------------

def test_an_outcome_carries_its_method_and_the_question_that_method_answers(
        user_client, outcome):
    row = user_client.get(
        f"{_api(outcome['pid'])}/outcomes").json()["outcomes"][0]
    assert row["synthesis_method"] == "vote_counting"
    # the method and the question it can answer travel together, so a review
    # cannot declare vote counting and then report an average effect
    assert "any evidence of an effect" in row["synthesis_method_question"]
    assert row["n_studies"] == 3


def test_only_included_studies_can_contribute_to_an_outcome(user_client,
                                                            ext_project):
    """A study excluded at full text contributing to a rated outcome would
    make the rating meaningless."""
    pid = ext_project["pid"]
    excluded = ext_project["excluded"]
    user_client.put(f"{_api(pid)}/plan", json={"enabled": True})
    row = user_client.post(f"{_api(pid)}/outcomes", json={
        "label": "Mortality",
        "record_ids": [excluded] + ext_project["included"]}).json()
    assert excluded not in row["record_ids"]
    assert row["n_studies"] == len(ext_project["included"])


# -- GRADE step 3: the starting point -----------------------------------------

def test_the_same_evidence_starts_high_or_low_depending_on_the_intent(
        user_client, outcome):
    """The paper's central point: observational evidence answering a causation
    question starts at low, the same evidence answering an association
    question starts at high."""
    pid, oid = outcome["pid"], outcome["outcome_id"]
    for rid in outcome["included"]:
        user_client.put(f"/api/projects/{pid}/extraction/records/{rid}/design",
                        json={"design": "cohort"})

    view = user_client.get(f"{_api(pid)}/outcomes/{oid}/certainty").json()
    assert view["suggestions"]["starting_point"]["starting_point"] == "high"

    user_client.put(f"{_api(pid)}/outcomes/{oid}", json={
        "label": "All-cause mortality", "intent": "causation",
        "record_ids": outcome["included"]})
    view = user_client.get(f"{_api(pid)}/outcomes/{oid}/certainty").json()
    proposal = view["suggestions"]["starting_point"]
    assert proposal["starting_point"] == "low"
    assert "causation" in proposal["rationale"]
    # the counts that motivate the proposal are shown, not just the verdict
    assert proposal["design_counts"][0]["design"] == "cohort"


def test_randomised_evidence_starts_high_for_a_causation_question(user_client,
                                                                  outcome):
    pid, oid = outcome["pid"], outcome["outcome_id"]
    for rid in outcome["included"]:
        user_client.put(f"/api/projects/{pid}/extraction/records/{rid}/design",
                        json={"design": "rct"})
    user_client.put(f"{_api(pid)}/outcomes/{oid}", json={
        "label": "Mortality", "intent": "causation",
        "record_ids": outcome["included"]})
    view = user_client.get(f"{_api(pid)}/outcomes/{oid}/certainty").json()
    assert view["suggestions"]["starting_point"]["starting_point"] == "high"


# -- GRADE step 4: the evidence put in front of the assessor ------------------

def test_the_risk_of_bias_domain_shows_the_appraisals_of_those_studies_only(
        user_client, outcome):
    pid, oid = outcome["pid"], outcome["outcome_id"]
    rid = outcome["included"][0]
    user_client.put(f"/api/projects/{pid}/extraction/records/{rid}/design",
                    json={"design": "rct"})
    user_client.put(f"/api/projects/{pid}/extraction/records/{rid}/jbi",
                    json={"answers": {"q1": {"answer": "yes", "comment": ""}},
                          "overall": "include"})
    rob = user_client.get(
        f"{_api(pid)}/outcomes/{oid}/certainty").json()["suggestions"]["risk_of_bias"]
    assert rob["n_studies"] == 3 and rob["n_appraised"] == 1
    assert rob["instrument"].startswith("JBI")
    assert "single assessor" in rob["note"]


def test_an_unappraised_corpus_says_so_rather_than_looking_clean(user_client,
                                                                 outcome):
    rob = user_client.get(
        f"{_api(outcome['pid'])}/outcomes/{outcome['outcome_id']}/certainty"
    ).json()["suggestions"]["risk_of_bias"]
    assert rob["n_appraised"] == 0
    assert "nothing to base this domain on" in rob["note"]


def test_the_publication_bias_domain_shows_the_search_that_was_run(user_client,
                                                                   outcome):
    pub = user_client.get(
        f"{_api(outcome['pid'])}/outcomes/{outcome['outcome_id']}/certainty"
    ).json()["suggestions"]["publication_bias"]
    assert pub["grey_literature"] is False
    assert "grey-literature" in pub["note"]


# -- GRADE step 5: proposing without applying ---------------------------------

def test_the_arithmetic_proposal_follows_grade():
    assert grade.suggest_final("high", {}, {}) == "high"
    assert grade.suggest_final("low", {}, {}) == "low"
    assert grade.suggest_final(
        "high", {"inconsistency": {"judgement": "serious"}}, {}) == "moderate"
    assert grade.suggest_final(
        "low", {"inconsistency": {"judgement": "serious"}}, {}) == "very_low"
    assert grade.suggest_final(
        "high", {"imprecision": {"judgement": "very_serious"}}, {}) == "low"
    # an upgrade only applies when nothing was rated down — otherwise the two
    # would read as cancelling out, which GRADE does not allow
    assert grade.suggest_final(
        "low", {}, {"dose_response": {"applied": True}}) == "moderate"
    assert grade.suggest_final(
        "low", {"risk_of_bias": {"judgement": "serious"}},
        {"dose_response": {"applied": True}}) == "very_low"


def test_the_assessor_may_diverge_from_the_arithmetic_and_it_shows(user_client,
                                                                   outcome):
    """GRADE allows two half-serious concerns in different domains to cost one
    level between them. No formula reproduces that, so the decision is stored
    and the divergence is surfaced rather than silenced."""
    pid, oid = outcome["pid"], outcome["outcome_id"]
    r = user_client.put(f"{_api(pid)}/outcomes/{oid}/certainty", json={
        "starting_point": "high",
        "domains": {"inconsistency": {"judgement": "serious", "note": "I2=77%"},
                    "indirectness": {"judgement": "serious", "note": "one cereal"}},
        "final": "moderate"})
    assert r.status_code == 200
    body = r.json()
    assert body["suggested_final"] == "low"     # two serious concerns
    assert body["final"] == "moderate"          # what the assessor decided
    assert body["diverges"] is True


def test_an_agreed_rating_is_reserved_to_an_admin_and_wins(user_client, team,
                                                           outcome):
    pid, oid = outcome["pid"], outcome["outcome_id"]
    _login(user_client, "reviewer")
    user_client.put(f"{_api(pid)}/outcomes/{oid}/certainty",
                    json={"starting_point": "low", "final": "very_low"})
    r = user_client.put(f"{_api(pid)}/outcomes/{oid}/certainty",
                        json={"final": "high", "is_consensus": True})
    assert r.status_code == 403

    _login(user_client, "admin")
    user_client.put(f"{_api(pid)}/outcomes/{oid}/certainty",
                    json={"starting_point": "high", "final": "moderate",
                          "is_consensus": True})
    row = user_client.get(f"{_api(pid)}/outcomes").json()["outcomes"][0]
    assert row["certainty"]["final"] == "moderate"
    assert row["certainty"]["is_consensus"] is True


# -- informative statements ---------------------------------------------------

def test_the_statement_carries_the_certainty_in_its_verb():
    """GRADE guideline 26: 'probably reduces' is the moderate-certainty
    statement, not a hedge added to a high-certainty one."""
    say = grade.informative_statement
    assert say("causation", "decrease", "high", "mortality", "Cereals") == \
        "Cereals reduces mortality."
    assert "probably reduces" in say("causation", "decrease", "moderate",
                                     "mortality", "Cereals")
    assert "may reduce" in say("causation", "decrease", "low", "mortality",
                              "Cereals")
    assert "very uncertain about the effect" in say(
        "causation", "decrease", "very_low", "mortality", "Cereals")
    # an association question never claims an effect
    assert "associated with a lower" in say("association", "decrease", "high",
                                            "mortality", "Cereals")
    assert "very uncertain about the association" in say(
        "association", "decrease", "very_low", "mortality", "Cereals")
    # an unclear direction cannot be phrased as one
    assert "very uncertain" in say("causation", "unclear", "high", "mortality",
                                   "Cereals")


def test_the_statement_endpoint_drafts_without_storing(user_client, outcome):
    pid, oid = outcome["pid"], outcome["outcome_id"]
    r = user_client.get(f"{_api(pid)}/outcomes/{oid}/statement?final=moderate")
    assert "probably associated with a lower" in r.json()["statement"]
    view = user_client.get(f"{_api(pid)}/outcomes/{oid}/certainty").json()
    assert view["mine"] is None      # nothing was written


# -- Summary of Findings ------------------------------------------------------

def test_the_sof_table_reports_an_unrated_outcome_as_unrated(user_client,
                                                             outcome):
    """An empty certainty cell must not read as high certainty by omission."""
    data = user_client.get(f"{_api(outcome['pid'])}/sof").json()
    row = data["rows"][0]
    assert row["rated"] is False and row["certainty"] == ""
    assert data["n_rated"] == 0
    csv_out = user_client.get(f"{_api(outcome['pid'])}/sof.csv")
    assert csv_out.status_code == 200
    assert "not rated" in csv_out.text


def test_the_sof_table_totals_participants_from_the_extraction_table(
        user_client, outcome):
    pid = outcome["pid"]
    col = user_client.post(f"/api/projects/{pid}/extraction/columns", json={
        "name": "Sample size (N)", "col_type": "number"}).json()
    for i, rid in enumerate(outcome["included"], start=1):
        user_client.put(f"/api/projects/{pid}/extraction/values",
                        json={"record_id": rid, "column_id": col["id"],
                              "value": i * 10, "validated": True})
    data = user_client.get(f"{_api(pid)}/sof").json()
    assert data["participants_column"] == "Sample size (N)"
    assert data["rows"][0]["n_participants"] == 60


def test_the_sof_table_leaves_participants_empty_when_nothing_is_recorded(
        user_client, outcome):
    """A total built from no study would read as the whole."""
    data = user_client.get(f"{_api(outcome['pid'])}/sof").json()
    assert data["rows"][0]["n_participants"] is None


# -- what the manuscript reads ------------------------------------------------

def test_the_declared_method_beats_the_review_type_default(user_client,
                                                           outcome):
    """framing.ReviewType names a method typical of the review *type*. Citing
    it as what the authors did is the self-declared compliance editorial
    triage penalises, so the dossier keeps the two apart."""
    from app.core.db import SessionLocal
    from app.services.reporting.audit import review_dossier
    with SessionLocal() as db:
        block = review_dossier(db, outcome["pid"])["synthesis"]
    assert block["declared"] is True
    assert block["methods_declared"] == [
        "Vote counting based on the direction of effect"]
    assert "narrative synthesis" in block["method_default"]  # kept, labelled
    assert block["swim_applies"] is True
    assert block["uses_meta_analysis"] is False
    assert block["outcomes"][0]["question_the_method_answers"].startswith(
        "Is there any evidence")


def test_a_project_declaring_nothing_leaves_the_default_unclaimed(user_client,
                                                                  ext_project):
    from app.core.db import SessionLocal
    from app.services.reporting.audit import review_dossier
    with SessionLocal() as db:
        block = review_dossier(db, ext_project["pid"])["synthesis"]
    assert block["declared"] is False
    assert block["methods_declared"] == []
    assert block["n_outcomes"] == 0


def test_the_narrative_prompt_carries_the_declaration(user_client, outcome):
    from app.core.db import SessionLocal
    from app.services.results import narrative
    with SessionLocal() as db:
        system, _ = narrative.build_prompt(db, outcome["pid"])
    assert "SWiM items 1 to 9" in system
    assert "Vote counting" in system
    assert "Never claim more than the method supports" in system


def test_the_synthesis_travels_in_a_snapshot(user_client, outcome):
    """A satellite must report the coordinator's synthesis, not one of its
    own — so the plan, the outcomes and their ratings are structural."""
    from app.core.db import SessionLocal
    from app.models import Project
    from app.services.sync.serialize import serialize_project
    pid, oid = outcome["pid"], outcome["outcome_id"]
    user_client.put(f"{_api(pid)}/outcomes/{oid}/certainty",
                    json={"starting_point": "high", "final": "moderate",
                          "statement_md": "Cereals probably…"})
    with SessionLocal() as db:
        data = serialize_project(db, db.get(Project, pid))
    assert data["synthesis_plan"]["certainty_framework"] == "grade"
    outcomes = data["synthesis_outcomes"]
    assert len(outcomes) == 1
    # contributing studies travel by record uuid, like every other reference
    assert len(outcomes[0]["studies"]) == 3
    assert all(s["study"] and s["record"] for s in outcomes[0]["studies"])
    assert outcomes[0]["certainty_assessments"][0]["final"] == "moderate"
