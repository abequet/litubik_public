"""Living review (roadmap chantier 5): "since" restriction, update plan,
update pass job (new round, dedup, screening round, run row, notifications),
"fetch now" during an active round, PRISMA round labels, deletion guards,
scheduler, sync serialization."""
import time
from datetime import date, datetime, timedelta, timezone

import pytest

from app.core.db import SessionLocal
from app.models import (
    Assignment, Notification, ScreeningConfig, SearchUpdatePlan,
    SearchUpdateRun, Source,
)
from app.services.connectors import fetch as fetchers
from app.services.equations import counts
from app.services.living import service
from app.services.living.since import since_date, since_query

RIS = "".join(f"""TY  - JOUR
TI  - {title}
AU  - Author{i}, A.
PY  - 20{10 + i}
DO  - 10.1/living.{i}
AB  - Abstract {i} on gamification and driving.
ER  -
""" for i, title in enumerate([
    "Gamified speed feedback for young drivers",
    "Serious games in nursing education outcomes",
    "Cycling safety interventions in dense cities",
], start=1))


def _login(client, who):
    email = "admin@example.com" if who == "admin" else "rev@example.com"
    client.post("/api/auth/login", json={"email": email, "password": "password123"})


def _await(client, job_id, timeout=30):
    t0 = time.time()
    while time.time() - t0 < timeout:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in ("done", "failed"):
            return job
        time.sleep(0.05)
    raise AssertionError("job never finished")


# ---- since -------------------------------------------------------------------------

def test_since_date_and_query_clauses():
    assert since_date({}) is None
    assert since_date({"since": "2026-09-01T10:00:00+00:00"}) == date(2026, 9, 1)
    assert since_date({"since": "nonsense"}) is None
    d = date(2026, 9, 1)
    assert since_query("europepmc", "TITLE:x", d) == "(TITLE:x) AND FIRST_IDATE:[2026-09-01 TO 3000-12-31]"
    assert "submittedDate:[202609010000 TO" in since_query("arxiv", "ti:x", d)
    assert since_query("hal", "title_t:x", d).endswith("submittedDate_tdate:[2026-09-01T00:00:00Z TO *]")
    assert since_query("doaj", "q", d).endswith("created_date:[2026-09-01T00:00:00Z TO *]")
    assert since_query("scopus", "TITLE(x)", d) == "(TITLE(x)) AND LOAD-DATE AFT 20260901"
    assert since_query("pubmed", "x[tiab]", d) == "x[tiab]"  # parameter-based
    assert since_query("ieee", "x", d) == "x"  # cannot filter: over-fetch


def test_since_in_parameter_based_filters():
    p = {"since": "2026-09-01"}
    assert "from_created_date:2026-09-01" in counts.openalex_filters("q", p)
    assert "from-created-date:2026-09-01" in counts.crossref_filters(p)
    assert counts.pubmed_since_params(p) == {"datetype": "edat", "mindate": "2026/09/01",
                                             "maxdate": "3000/12/31"}
    assert counts.pubmed_since_params({}) == {}
    assert counts.s2_search_params("q", {"since": "2026-09-01", "year_from": 2015})["year"] == "2026-"


# ---- fixtures ----------------------------------------------------------------------

@pytest.fixture
def team(user_client):
    me = user_client.get("/api/auth/me").json()
    user_client.post("/api/auth/register", json={
        "email": "rev@example.com", "password": "password123",
        "display_name": "Reviewer"})
    rev = user_client.get("/api/auth/me").json()
    _login(user_client, "admin")
    return {"admin": me, "reviewer": rev}


@pytest.fixture
def living_project(user_client, team):
    """Round 1 imported from pubmed and deduplicated, a frozen equation, a
    T/A round active with both reviewers."""
    pid = user_client.post("/api/projects", json={"name": "Living"}).json()["id"]
    user_client.post(f"/api/projects/{pid}/members",
                     json={"email": "rev@example.com", "role": "reviewer"})
    user_client.post(f"/api/projects/{pid}/concepts",
                     json={"name": "I", "keywords": ["gamification"]})
    concepts = user_client.get(f"/api/projects/{pid}/concepts").json()
    eq = user_client.post(f"/api/projects/{pid}/equations", json={
        "label": "final", "concept_ids": [concepts[0]["id"]], "params": {}}).json()
    user_client.post(f"/api/projects/{pid}/equations/{eq['id']}/freeze")
    user_client.post(f"/api/projects/{pid}/imports/upload",
                     files={"file": ("s.ris", RIS.encode(), "text/plain")},
                     data={"source_name": "pubmed", "source_type": "database",
                           "equation_id": str(eq["id"])})
    _await(user_client, user_client.post(
        f"/api/projects/{pid}/dedup/run").json()["job_id"])
    user_client.post(f"/api/projects/{pid}/protocols/upload",
                     files={"file": ("p.md", b"# P", "text/markdown")})
    prot = user_client.get(f"/api/projects/{pid}/protocols").json()[0]
    user_client.put(f"/api/projects/{pid}/protocols/{prot['id']}", json={
        "protocol_md": "# P", "criteria": [
            {"code": "E1", "type": "exclude", "label": "off topic", "description": ""}]})
    user_client.post(f"/api/projects/{pid}/protocols/{prot['id']}/validate")
    reviewers = [team["admin"]["id"], team["reviewer"]["id"]]
    user_client.put(f"/api/projects/{pid}/screening/config", json={
        "stage": "ta", "allocation": "all", "conflict_resolution": "consensus",
        "reviewer_ids": reviewers})
    r = user_client.post(f"/api/projects/{pid}/screening/start")
    assert r.status_code == 200, r.text
    return {"pid": pid, "equation_id": eq["id"], "reviewers": reviewers}


def _fake_openalex(records):
    def fake(query, params, cap, progress):
        fake.calls.append({"query": query, "params": dict(params)})
        return records
    fake.calls = []
    return fake


NEW = {"doi": "10.1/living.new", "title": "A brand new gamified intervention",
       "authors": ["New, A."], "year": 2026, "journal": "", "abstract": "New.", "raw": ""}
DUP = {"doi": "10.1/living.1", "title": "Gamified speed feedback for young drivers",
       "authors": [], "year": 2011, "journal": "", "abstract": "", "raw": ""}


# ---- plan ----------------------------------------------------------------------------

def test_plan_roundtrip_and_validation(user_client, living_project):
    pid = living_project["pid"]
    plan = user_client.get(f"/api/projects/{pid}/search/update-plan").json()
    assert plan["enabled"] is False and plan["intervals"] == [7, 14, 30, 90]
    r = user_client.put(f"/api/projects/{pid}/search/update-plan", json={
        "enabled": True, "interval_days": 7, "databases": ["openalex", "pubmed"],
        "equation_id": living_project["equation_id"]})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["enabled"] and out["databases"] == ["openalex", "pubmed"]
    assert out["next_run_at"] is not None and out["last_run_at"] is None
    assert user_client.put(f"/api/projects/{pid}/search/update-plan", json={
        "enabled": True, "interval_days": 5, "databases": ["openalex"]}).status_code == 422
    assert user_client.put(f"/api/projects/{pid}/search/update-plan", json={
        "enabled": True, "interval_days": 7, "databases": ["ebsco"]}).status_code == 400
    assert user_client.put(f"/api/projects/{pid}/search/update-plan", json={
        "enabled": True, "interval_days": 7, "databases": []}).status_code == 422
    _login(user_client, "reviewer")
    assert user_client.put(f"/api/projects/{pid}/search/update-plan", json={
        "enabled": False, "interval_days": 7, "databases": []}).status_code == 403
    assert user_client.get(f"/api/projects/{pid}/search/update-plan").status_code == 200


# ---- the pass ------------------------------------------------------------------------

def test_update_pass_creates_round_dedups_screens_and_notifies(user_client, living_project,
                                                              monkeypatch):
    pid = living_project["pid"]
    fake = _fake_openalex([NEW, DUP])
    monkeypatch.setitem(fetchers.FETCHERS, "openalex", fake)
    r = user_client.post(f"/api/projects/{pid}/search/updates/run",
                         json={"databases": ["openalex"]})
    assert r.status_code == 200, r.text
    job = _await(user_client, r.json()["job_id"])
    assert job["status"] == "done", job.get("error")
    result = job["result"]
    assert result["round"] == 2 and result["n_fetched"] == 2
    assert result["n_new_unique"] == 1 and result["ta_round_started"] is True
    # the fetch was restricted to what came after the round-1 import
    assert fake.calls[0]["params"]["since"] is not None
    assert result["since"] is not None

    with SessionLocal() as db:
        src = db.query(Source).filter_by(project_id=pid, round=2).one()
        assert src.type == "database" and src.name == "openalex"
        run = db.query(SearchUpdateRun).filter_by(project_id=pid).one()
        assert run.round == 2 and run.triggered_by == "manual"
        assert run.n_new_unique == 1 and run.databases == ["openalex"]
        ta2 = db.query(ScreeningConfig).filter_by(project_id=pid, stage="ta", round=2).one()
        assert ta2.status == "active" and ta2.reviewer_ids == living_project["reviewers"]
        assert db.query(Assignment).filter_by(config_id=ta2.id).count() == 2  # 1 record × 2
        # no full-text round was ever configured: nothing to copy as a draft
        assert db.query(ScreeningConfig).filter_by(project_id=pid, stage="ft", round=2).count() == 0
        notes = db.query(Notification).filter_by(project_id=pid).all()
        assert {n.user_id for n in notes} == set(living_project["reviewers"])
        assert notes[0].payload["n_new_unique"] == 1 and notes[0].kind == "search_update"

    runs = user_client.get(f"/api/projects/{pid}/search/updates").json()
    assert runs[0]["label"] == "Search update 1" and runs[0]["deletable"] is True

    # PRISMA labels the rounds by their run kind
    prisma = user_client.get(f"/api/projects/{pid}/prisma").json()
    assert [(r["kind"], r["label"]) for r in prisma["rounds"]] == [
        ("initial", "Initial search"), ("update", "Search update 1")]

    # the reviewer sees the notification, reads it, the summary drops
    _login(user_client, "reviewer")
    summary = user_client.get("/api/notifications/summary").json()
    assert summary["unread"] == 1 and summary["by_project"] == {str(pid): 1}
    items = user_client.get("/api/notifications?unread=true").json()
    assert items[0]["payload"]["round"] == 2
    user_client.post(f"/api/notifications/{items[0]['id']}/read")
    assert user_client.get("/api/notifications/summary").json()["unread"] == 0
    # cannot read someone else's
    _login(user_client, "admin")
    mine = user_client.get("/api/notifications").json()
    assert all(n["project_id"] == pid for n in mine)
    assert user_client.post(f"/api/notifications/{items[0]['id']}/read").status_code == 404

    # a second manual pass while nothing new: no screening round, run recorded
    fake2 = _fake_openalex([DUP])
    monkeypatch.setitem(fetchers.FETCHERS, "openalex", fake2)
    job = _await(user_client, user_client.post(
        f"/api/projects/{pid}/search/updates/run", json={"databases": ["openalex"]}
    ).json()["job_id"])
    assert job["status"] == "done" and job["result"]["n_new_unique"] == 0
    runs = user_client.get(f"/api/projects/{pid}/search/updates").json()
    assert [r["label"] for r in runs] == ["Search update 1", "Search update 2"]
    assert [r["deletable"] for r in runs] == [False, True]

    # delete the latest pass, then the first one
    assert user_client.delete(f"/api/projects/{pid}/search/updates/2").status_code == 409
    assert user_client.delete(f"/api/projects/{pid}/search/updates/3").status_code == 200
    assert user_client.delete(f"/api/projects/{pid}/search/updates/2").status_code == 200
    with SessionLocal() as db:
        assert db.query(SearchUpdateRun).filter_by(project_id=pid).count() == 0
        assert db.query(Source).filter_by(project_id=pid, round=2).count() == 0
        assert db.query(ScreeningConfig).filter_by(project_id=pid, round=2).count() == 0


def test_update_pass_one_database_down_keeps_the_others(user_client, living_project,
                                                        monkeypatch):
    pid = living_project["pid"]

    def broken(query, params, cap, progress):
        raise fetchers.FetchError("503 from api.crossref.org")
    monkeypatch.setitem(fetchers.FETCHERS, "crossref", broken)
    monkeypatch.setitem(fetchers.FETCHERS, "openalex", _fake_openalex([NEW]))
    job = _await(user_client, user_client.post(
        f"/api/projects/{pid}/search/updates/run",
        json={"databases": ["openalex", "crossref"]}).json()["job_id"])
    assert job["status"] == "done", job.get("error")
    assert job["result"]["errors"] == {"crossref": "503 from api.crossref.org"}
    assert job["result"]["n_new_unique"] == 1
    # all down: the job fails, nothing is written
    monkeypatch.setitem(fetchers.FETCHERS, "openalex", broken)
    job = _await(user_client, user_client.post(
        f"/api/projects/{pid}/search/updates/run",
        json={"databases": ["openalex"]}).json()["job_id"])
    assert job["status"] == "failed" and "Nothing fetched" in job["error"]
    with SessionLocal() as db:
        assert db.query(SearchUpdateRun).filter_by(project_id=pid).count() == 1


def test_run_rejected_while_running_and_without_databases(user_client, living_project):
    pid = living_project["pid"]
    assert user_client.post(f"/api/projects/{pid}/search/updates/run",
                            json={"databases": []}).status_code == 422
    assert user_client.post(f"/api/projects/{pid}/search/updates/run",
                            json={"databases": ["ebsco"]}).status_code == 400


# ---- "fetch now" during an active round --------------------------------------------

def test_fetch_now_during_active_round_is_an_update_pass(user_client, living_project,
                                                         monkeypatch):
    pid = living_project["pid"]
    monkeypatch.setitem(fetchers.FETCHERS, "openalex", _fake_openalex([NEW, DUP]))
    job = _await(user_client, user_client.post(
        f"/api/projects/{pid}/search/fetch",
        json={"equation_id": living_project["equation_id"], "database": "openalex",
              "cap": 100}).json()["job_id"])
    assert job["status"] == "done", job.get("error")
    assert job["result"]["round"] == 2 and job["result"]["n_new_unique"] == 1
    with SessionLocal() as db:
        run = db.query(SearchUpdateRun).filter_by(project_id=pid).one()
        assert run.triggered_by == "fetch" and run.round == 2
        assert db.query(ScreeningConfig).filter_by(
            project_id=pid, stage="ta", round=2, status="active").count() == 1
        # the admin who launched it is not notified, the reviewer is
        assert [n.user_id for n in db.query(Notification).filter_by(project_id=pid)] == [
            living_project["reviewers"][1]]
    imports = user_client.get(f"/api/projects/{pid}/imports").json()
    assert {i["round"] for i in imports} == {1, 2}


def test_fetch_before_any_screening_stays_in_round_1_and_dedups(user_client, team,
                                                                monkeypatch):
    pid = user_client.post("/api/projects", json={"name": "Fresh"}).json()["id"]
    user_client.post(f"/api/projects/{pid}/concepts",
                     json={"name": "I", "keywords": ["gamification"]})
    concepts = user_client.get(f"/api/projects/{pid}/concepts").json()
    eq = user_client.post(f"/api/projects/{pid}/equations", json={
        "label": "v1", "concept_ids": [concepts[0]["id"]], "params": {}}).json()
    monkeypatch.setitem(fetchers.FETCHERS, "openalex", _fake_openalex([NEW, dict(NEW)]))
    job = _await(user_client, user_client.post(
        f"/api/projects/{pid}/search/fetch",
        json={"equation_id": eq["id"], "database": "openalex", "cap": 100}
    ).json()["job_id"])
    assert job["status"] == "done", job.get("error")
    assert job["result"]["round"] == 1 and "n_new_unique" not in job["result"]
    records = user_client.get(f"/api/projects/{pid}/records").json()["items"]
    assert sorted(r["dedup_status"] for r in records) == ["duplicate", "unique"]
    with SessionLocal() as db:
        assert db.query(SearchUpdateRun).filter_by(project_id=pid).count() == 0


# ---- deletion guard with snowballing ----------------------------------------------

def test_snowballing_delete_guard_uses_the_latest_round(user_client, living_project,
                                                        monkeypatch):
    from app.models import SnowballRun
    pid = living_project["pid"]
    with SessionLocal() as db:
        db.add(Source(project_id=pid, type="snowballing", name="snowballing r2", round=2))
        db.add(SnowballRun(project_id=pid, round=2, seed_record_ids=[], n_seeds=0))
        db.commit()
    monkeypatch.setitem(fetchers.FETCHERS, "openalex", _fake_openalex([NEW]))
    job = _await(user_client, user_client.post(
        f"/api/projects/{pid}/search/updates/run", json={"databases": ["openalex"]}
    ).json()["job_id"])
    assert job["status"] == "done" and job["result"]["round"] == 3
    r = user_client.delete(f"/api/projects/{pid}/snowballing/iterations/2")
    assert r.status_code == 409 and "search update" in r.json()["detail"]
    prisma = user_client.get(f"/api/projects/{pid}/prisma").json()
    assert [r["label"] for r in prisma["rounds"]] == [
        "Initial search", "Snowballing iteration 1", "Search update 1"]
    assert user_client.delete(f"/api/projects/{pid}/search/updates/3").status_code == 200
    assert user_client.delete(f"/api/projects/{pid}/snowballing/iterations/2").status_code == 200


# ---- scheduler ----------------------------------------------------------------------

def test_run_due_plans_submits_once(user_client, living_project, monkeypatch):
    pid = living_project["pid"]
    user_client.put(f"/api/projects/{pid}/search/update-plan", json={
        "enabled": True, "interval_days": 7, "databases": ["openalex"]})
    submitted = []
    monkeypatch.setattr(service, "runner", None, raising=False)
    from app.workers import runner as runner_module

    class FakeJob:
        id = 999

    def fake_submit(job_type, params, project_id, user_id):
        submitted.append((job_type, params, project_id))
        return FakeJob()
    monkeypatch.setattr(runner_module.runner, "submit", fake_submit)
    assert service.run_due_plans() == []  # not due yet
    future = datetime.now(timezone.utc) + timedelta(days=8)
    assert service.run_due_plans(now=future) == [999]
    assert submitted[0][0] == "search_update" and submitted[0][1]["triggered_by"] == "schedule"
    # pushed forward: the same tick does not resubmit
    assert service.run_due_plans(now=future) == []
    with SessionLocal() as db:
        plan = db.query(SearchUpdatePlan).filter_by(project_id=pid).one()
        assert plan.next_run_at.replace(tzinfo=timezone.utc) > future


def test_fail_stale_jobs(user_client):
    from app.models import Job
    from app.workers.runner import fail_stale_jobs
    with SessionLocal() as db:
        db.add(Job(type="search_update", status="running", params={}))
        db.add(Job(type="search_update", status="done", params={}))
        db.commit()
    assert fail_stale_jobs() == 1
    with SessionLocal() as db:
        assert db.query(Job).filter_by(status="failed").one().error.startswith("Interrupted")


# ---- sync ---------------------------------------------------------------------------

def test_plan_and_runs_serialize(user_client, living_project, monkeypatch):
    from app.models import Project
    from app.services.sync.serialize import serialize_project
    pid = living_project["pid"]
    user_client.put(f"/api/projects/{pid}/search/update-plan", json={
        "enabled": True, "interval_days": 14, "databases": ["openalex"],
        "equation_id": living_project["equation_id"]})
    monkeypatch.setitem(fetchers.FETCHERS, "openalex", _fake_openalex([NEW]))
    _await(user_client, user_client.post(
        f"/api/projects/{pid}/search/updates/run", json={"databases": ["openalex"]}
    ).json()["job_id"])
    with SessionLocal() as db:
        data = serialize_project(db, db.get(Project, pid))
    assert data["search_update_plan"]["interval_days"] == 14
    assert data["search_update_plan"]["equation"] is not None
    assert data["search_update_plan"]["last_run_at"] is not None
    assert data["search_update_runs"][0]["round"] == 2
    assert "notifications" not in data
    # the audit block carries the passes for the Methods draft
    audit = user_client.get(f"/api/projects/{pid}/reporting/dossier").json()
    living = audit["search"]["living_review"]
    assert living["n_passes"] == 1 and living["plan"]["interval_days"] == 14
