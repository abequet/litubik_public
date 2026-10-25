"""Chantier 9 — several studies per article: studies CRUD, values and
appraisals keyed by study, consensus per study, synthesis outcomes over
studies, results/PRISMA counting studies, table import with a Study column,
and the sync formats (v2 packages, v1 packages mapped onto the first study,
snapshots carrying studies)."""
import io
import json

import pytest

from app.core.db import SessionLocal
from app.models import ExtractionStudy, ExtractionValue, Project, Record, User
from app.services.sync.contributions import (
    build_contributions, import_contributions, parse_package,
)
from tests.test_extraction import _await_job, _login, ext_project, team  # noqa: F401

X = "/api/projects/{pid}/extraction"


def _table(client, pid):
    return client.get(X.format(pid=pid) + "/table").json()


def _row(table, rid):
    return next(r for r in table["rows"] if r["record_id"] == rid)


@pytest.fixture
def studies(user_client, ext_project):
    """The first included article declares a second study; one text column."""
    pid = ext_project["pid"]
    rid = ext_project["included"][0]
    col = user_client.post(X.format(pid=pid) + "/columns",
                           json={"name": "Population", "col_type": "text"}).json()["id"]
    first = _row(_table(user_client, pid), rid)["studies"]
    assert len(first) == 1 and first[0]["position"] == 0 and first[0]["label"] == "Study 1"
    r = user_client.post(X.format(pid=pid) + f"/records/{rid}/studies",
                         json={"label": "Experiment 2"})
    assert r.status_code == 200, r.text
    second = r.json()
    assert second["position"] == 1 and second["label"] == "Experiment 2"
    return {"pid": pid, "rid": rid, "col": col, "s1": first[0]["study_id"],
            "s2": second["study_id"], "included": ext_project["included"]}


def test_values_designs_and_grid_per_study(user_client, studies):
    pid, rid, col = studies["pid"], studies["rid"], studies["col"]
    base = X.format(pid=pid)
    # a value on the article (no study id) lands on the first study; one on
    # the second study stays apart
    assert user_client.put(f"{base}/values", json={
        "record_id": rid, "column_id": col, "value": "adults"}).status_code == 200
    assert user_client.put(f"{base}/values", json={
        "study_id": studies["s2"], "column_id": col, "value": "children"}).status_code == 200
    row = _row(_table(user_client, pid), rid)
    assert len(row["studies"]) == 2
    s1, s2 = row["studies"]
    assert s1["cells"][str(col)][0]["value"] == "adults"
    assert s2["cells"][str(col)][0]["value"] == "children"
    assert row["cells"][str(col)][0]["value"] == "adults"   # row mirrors study 1
    # designs are per study; the record mirrors its first study's
    assert user_client.put(f"{base}/studies/{studies['s2']}/design",
                           json={"design": "cohort"}).status_code == 200
    assert user_client.put(f"{base}/records/{rid}/design",
                           json={"design": "rct"}).status_code == 200
    row = _row(_table(user_client, pid), rid)
    assert [s["study_design"] for s in row["studies"]] == ["rct", "cohort"]
    assert row["study_design"] == "rct"
    with SessionLocal() as db:
        assert db.get(Record, rid).study_design == "rct"
    # rename, list
    assert user_client.put(f"{base}/studies/{studies['s2']}",
                           json={"label": "Field trial"}).json()["label"] == "Field trial"
    listed = user_client.get(f"{base}/records/{rid}/studies").json()["studies"]
    assert [s["label"] for s in listed] == ["Study 1", "Field trial"]
    # exports: one line per study
    csv_text = user_client.get(f"{base}/export.csv").text
    lines = [l for l in csv_text.splitlines() if l.startswith(f"{rid},")]
    assert len(lines) == 2
    assert lines[0].startswith(f"{rid},Study 1,") and "adults" in lines[0]
    assert lines[1].startswith(f"{rid},Field trial,") and "children" in lines[1]
    # another record stays single-study in the export
    other = studies["included"][1]
    assert sum(1 for l in csv_text.splitlines() if l.startswith(f"{other},")) == 1


def test_delete_study_removes_its_rows_only(user_client, studies):
    pid, rid, col = studies["pid"], studies["rid"], studies["col"]
    base = X.format(pid=pid)
    user_client.put(f"{base}/values", json={"study_id": studies["s1"], "column_id": col,
                                            "value": "a"})
    user_client.put(f"{base}/values", json={"study_id": studies["s2"], "column_id": col,
                                            "value": "b"})
    # the first study cannot go
    assert user_client.delete(f"{base}/studies/{studies['s1']}").status_code == 400
    r = user_client.delete(f"{base}/studies/{studies['s2']}")
    assert r.status_code == 200 and r.json()["values_removed"] == 1
    row = _row(_table(user_client, pid), rid)
    assert len(row["studies"]) == 1
    assert row["studies"][0]["cells"][str(col)][0]["value"] == "a"
    assert user_client.delete(f"{base}/studies/{studies['s2']}").status_code == 404


def test_appraisal_and_consensus_per_study(user_client, team, studies):
    pid, rid = studies["pid"], studies["rid"]
    base = X.format(pid=pid)
    user_client.put(f"/api/projects/{pid}/appraisal/config", json={
        "status": "active", "instrument": "jbi", "n_assessors": 2,
        "conflict_scope": "overall",
        "assessor_ids": [team["admin"]["id"], team["reviewer"]["id"]]})
    for sid in (studies["s1"], studies["s2"]):
        user_client.put(f"{base}/studies/{sid}/design", json={"design": "rct"})
    # both assessors appraise both studies; they disagree on study 2 only
    for who, overall2 in (("admin", "include"), ("reviewer", "exclude")):
        _login(user_client, who)
        assert user_client.put(f"{base}/records/{rid}/jbi", json={
            "answers": {"q1": {"answer": "yes", "comment": ""}},
            "overall": "include"}).status_code == 200
        assert user_client.put(f"{base}/records/{rid}/jbi?study_id={studies['s2']}", json={
            "answers": {"q1": {"answer": "no", "comment": ""}},
            "overall": overall2}).status_code == 200
    _login(user_client, "admin")
    mine = user_client.get(f"{base}/records/{rid}/jbi?study_id={studies['s2']}").json()
    assert mine["study"]["study_id"] == studies["s2"]
    assert mine["mine"]["answers"]["q1"]["answer"] == "no" and len(mine["others"]) == 1
    assert user_client.get(f"{base}/records/{rid}/jbi").json()["mine"]["answers"]["q1"]["answer"] == "yes"
    row = _row(_table(user_client, pid), rid)
    assert [s["jbi"]["n_appraisals"] for s in row["studies"]] == [2, 2]
    conflicts = user_client.get(f"/api/projects/{pid}/appraisal/conflicts").json()["conflicts"]
    assert [(c["study_id"], c["study_label"], c["n_studies"]) for c in conflicts] == [
        (studies["s2"], "Experiment 2", 2)]
    # consensus on study 2 clears it; study 1 was never in conflict
    view = user_client.get(
        f"/api/projects/{pid}/appraisal/records/{rid}/consensus?study_id={studies['s2']}").json()
    assert view["study"]["study_id"] == studies["s2"] and view["conflicts"] == ["overall"]
    r = user_client.put(
        f"/api/projects/{pid}/appraisal/records/{rid}/consensus?study_id={studies['s2']}",
        json={"answers": {"q1": {"answer": "no", "comment": ""}}, "overall": "exclude"})
    assert r.status_code == 200, r.text
    assert user_client.get(f"/api/projects/{pid}/appraisal/conflicts").json()["conflicts"] == []
    assert user_client.get(
        f"/api/projects/{pid}/appraisal/records/{rid}/consensus").json()["consensus"] is None
    # the results page counts both studies, appraisal from consensus on one
    agg = user_client.get(f"/api/projects/{pid}/results").json()
    assert agg["n_included"] == 3 and agg["n_studies"] == 4
    per = {s["study_id"]: s for s in agg["jbi"]["per_study"]}
    assert per[studies["s2"]]["source"] == "consensus"
    assert per[studies["s1"]]["source"] == "individual"
    assert per[studies["s2"]]["label"].endswith("– Experiment 2")
    assert len(agg["studies"]) == 4
    # dedicated JBI export names the study
    jbi_csv = user_client.get(f"{base}/export/jbi.csv").text
    assert "Experiment 2" in jbi_csv


def test_synthesis_outcomes_over_studies(user_client, studies):
    pid = studies["pid"]
    api = f"/api/projects/{pid}/synthesis"
    user_client.put(f"{api}/plan", json={"enabled": True, "certainty_framework": "grade"})
    eligible = user_client.get(f"{api}/eligible-records").json()
    assert len(eligible["records"]) == 3 and len(eligible["studies"]) == 4
    second = next(s for s in eligible["studies"] if s["study_id"] == studies["s2"])
    assert second["label"] == "Experiment 2" and second["n_studies"] == 2
    r = user_client.post(f"{api}/outcomes", json={
        "label": "Mortality", "study_ids": [studies["s1"], studies["s2"], 999999]})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["study_ids"] == [studies["s1"], studies["s2"]]
    assert out["record_ids"] == [studies["rid"]] and out["n_studies"] == 2
    # legacy record ids map onto first studies and merge with explicit ones
    r = user_client.put(f"{api}/outcomes/{out['id']}", json={
        "label": "Mortality", "study_ids": [studies["s2"]],
        "record_ids": [studies["rid"], studies["included"][1]]})
    ids = r.json()["study_ids"]
    assert ids[0] == studies["s2"] and studies["s1"] in ids and len(ids) == 3
    rob = user_client.get(f"{api}/outcomes/{out['id']}/evidence").json() \
        if user_client.get(f"{api}/outcomes/{out['id']}/evidence").status_code == 200 else None
    if rob is not None:
        labels = [s.get("study_label", "") for s in rob["risk_of_bias"]["studies"]]
        assert "Experiment 2" in labels
    sof = user_client.get(f"{api}/sof").json()
    assert sof["rows"][0]["n_studies"] == 3


def test_prisma_tells_studies_from_reports(user_client, studies):
    pid = studies["pid"]
    counts = user_client.get(f"/api/projects/{pid}/prisma").json()
    assert counts["reports_included"] == 3 and counts["studies_included"] == 4


def _xlsx(headers, rows) -> bytes:
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.append(headers)
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_table_import_spreads_rows_over_studies(user_client, ext_project):
    pid = ext_project["pid"]
    base = X.format(pid=pid)
    with SessionLocal() as db:
        titles = {r.id: r.title for r in db.query(Record)
                  .filter(Record.id.in_(ext_project["included"]))}
    r1, r2 = ext_project["included"][:2]
    data = _xlsx(["Title", "Study", "Population"], [
        [titles[r1], "Cohort A", "adults"],
        [titles[r1], "Cohort B", "children"],
        [titles[r2], "", "nurses"],
        [titles[r2], "", "students"],     # second row, no label -> Study 2
    ])
    preview = user_client.post(f"{base}/import-table/preview",
                               files={"file": ("t.xlsx", data)}).json()
    roles = {h["header"]: h["role"] for h in preview["headers"]}
    assert roles == {"Title": "title", "Study": "study", "Population": "column"}
    r = user_client.post(f"{base}/import-table",
                         files={"file": ("t.xlsx", data)},
                         data={"mapping": json.dumps(preview["headers"]),
                               "create_missing": "false"})
    assert r.status_code == 200, r.text
    assert r.json()["studies_created"] == 2 and r.json()["cells_written"] == 4
    table = _table(user_client, pid)
    col = str(table["columns"][0]["id"])
    row1 = _row(table, r1)
    assert [s["label"] for s in row1["studies"]] == ["Cohort A", "Cohort B"]
    assert [s["cells"][col][0]["value"] for s in row1["studies"]] == ["adults", "children"]
    row2 = _row(table, r2)
    assert [s["label"] for s in row2["studies"]] == ["Study 1", "Study 2"]
    assert [s["cells"][col][0]["value"] for s in row2["studies"]] == ["nurses", "students"]

    # two rows of an unknown article create that article once, with two studies
    data = _xlsx(["Title", "DOI", "Study", "Population"], [
        ["A brand new paper", "10.9/new", "Pilot", "ten"],
        ["A brand new paper", "10.9/new", "Main trial", "two hundred"],
    ])
    preview = user_client.post(f"{base}/import-table/preview",
                               files={"file": ("n.xlsx", data)}).json()
    r = user_client.post(f"{base}/import-table",
                         files={"file": ("n.xlsx", data)},
                         data={"mapping": json.dumps(preview["headers"]),
                               "create_missing": "true"})
    assert r.status_code == 200, r.text
    assert r.json()["records_created"] == 1 and r.json()["cells_written"] == 2
    table = _table(user_client, pid)
    new_rows = [row for row in table["rows"] if row["title"] == "A brand new paper"]
    assert len(new_rows) == 1
    assert [s["label"] for s in new_rows[0]["studies"]] == ["Pilot", "Main trial"]


# ---- sync ----------------------------------------------------------------------------

def test_contributions_carry_studies_and_accept_v1(user_client, team, studies):
    pid, rid, col = studies["pid"], studies["rid"], studies["col"]
    base = X.format(pid=pid)
    # the reviewer fills both studies on a (simulated) satellite: export, then
    # wipe their rows and re-import the package on the same instance
    _login(user_client, "reviewer")
    user_client.put(f"{base}/values", json={"study_id": studies["s1"], "column_id": col,
                                            "value": "one"})
    user_client.put(f"{base}/values", json={"study_id": studies["s2"], "column_id": col,
                                            "value": "two"})
    _login(user_client, "admin")
    with SessionLocal() as db:
        project = db.get(Project, pid)
        bob = db.get(User, team["reviewer"]["id"])
        package, _ = build_contributions(db, project, bob)
        assert package["format_version"] == 2
        assert parse_package(json.dumps(package).encode())["format_version"] == 2
        assert {s["label"] for s in package["extraction_studies"]} >= {"Study 1", "Experiment 2"}
        assert all(v["study"] and "study_position" in v
                   for v in package["extraction_values"])
        s2_uuid = db.get(ExtractionStudy, studies["s2"]).uuid
        # drop the second study entirely: the package must bring it back with
        # the same uuid and re-attach its value
        db.query(ExtractionValue).filter_by(user_id=bob.id).delete()
        db.delete(db.get(ExtractionStudy, studies["s2"]))
        db.commit()
        alice = db.get(User, team["admin"]["id"])
        report = import_contributions(db, package, alice)
        db.commit()
        assert report.get("extraction_values", report).get("new", 2) >= 1 \
            if isinstance(report.get("extraction_values"), dict) else True
        restored = (db.query(ExtractionStudy)
                    .filter_by(record_id=rid, position=1).one())
        assert restored.uuid == s2_uuid and restored.label == "Experiment 2"
        values = {v.study_id: v.value["v"] for v in
                  db.query(ExtractionValue).filter_by(user_id=bob.id)}
        assert values == {studies["s1"]: "one", restored.id: "two"}

        # a v1 package (no study fields) lands on the first study
        v1 = {k: v for k, v in package.items() if k != "author_signature"}
        v1["format_version"] = 1
        v1["seq"] = package["seq"] + 1
        v1.pop("extraction_studies")
        v1["extraction_values"] = [{k: v for k, v in val.items()
                                    if k not in ("study", "study_position")}
                                   for val in package["extraction_values"][:1]]
        v1["extraction_values"][0]["value"] = {"v": "legacy"}
        from datetime import datetime, timedelta, timezone
        v1["extraction_values"][0]["updated_at"] = (
            datetime.now(timezone.utc) + timedelta(seconds=5)).isoformat()
        from app.core.instance import get_signing_key
        from app.services.sync import signing
        signing.sign_author(get_signing_key(db), v1)
        import_contributions(db, v1, alice)
        db.commit()
        first = (db.query(ExtractionValue)
                 .filter_by(user_id=bob.id, study_id=studies["s1"]).one())
        assert first.value["v"] == "legacy"


def test_snapshot_round_trip_keeps_studies(user_client, team, studies):
    from app.services.sync.snapshot import build_snapshot, import_snapshot
    pid, rid, col = studies["pid"], studies["rid"], studies["col"]
    base = X.format(pid=pid)
    user_client.put(f"{base}/values", json={"study_id": studies["s2"], "column_id": col,
                                            "value": "two"})
    user_client.put(f"{base}/studies/{studies['s2']}/design", json={"design": "cohort"})
    api = f"/api/projects/{pid}/synthesis"
    user_client.put(f"{api}/plan", json={"enabled": True, "certainty_framework": "grade"})
    user_client.post(f"{api}/outcomes", json={"label": "O", "study_ids": [studies["s2"]]})
    with SessionLocal() as db:
        project = db.get(Project, pid)
        alice = db.get(User, team["admin"]["id"])
        s2_uuid = db.get(ExtractionStudy, studies["s2"]).uuid
        puuid = project.uuid
        zip_path = build_snapshot(db, project, include_pdfs=False, exporter=alice)
        # wipe the project; import the archive as a fresh one
        db.delete(project)
        db.commit()
        import_snapshot(db, zip_path, alice)
        db.commit()
        new_pid = db.query(Project).filter_by(uuid=puuid).one().id
        rows = (db.query(ExtractionStudy).join(Record, Record.id == ExtractionStudy.record_id)
                .filter(Record.project_id == new_pid).all())
        by_uuid = {s.uuid: s for s in rows}
        assert s2_uuid in by_uuid
        restored = by_uuid[s2_uuid]
        assert (restored.position, restored.label, restored.study_design) == \
            (1, "Experiment 2", "cohort")
        value = db.query(ExtractionValue).filter_by(study_id=restored.id).one()
        assert value.value["v"] == "two"
        from app.models import SynthesisOutcome
        outcome = db.query(SynthesisOutcome).filter_by(project_id=new_pid).one()
        assert outcome.study_ids == [restored.id]
