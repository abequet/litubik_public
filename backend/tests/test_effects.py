"""Chantier 10 — meta-analysis bridge: effect-size formulas against metafor's
escalc() reference values, the per-outcome spec and computation API, the
metafor zip / RevMan CSV / long CSV exports, and the spec travelling by
column uuid in a snapshot."""
import csv
import io
import json
import zipfile

import pytest

from app.core.db import SessionLocal
from app.models import ExtractionColumn, Project, SynthesisOutcome
from app.services.sync.serialize import serialize_project
from app.services.synthesis import effects
from tests.test_extraction import _await_job, _login, ext_project, team  # noqa: F401


def test_formulas_match_metafor():
    # dat.bcg, Aronson 1948: escalc(measure="RR", ai=4, n1i=123, ci=11, n2i=139)
    yi, vi = effects.log_rr(4, 123, 11, 139)
    assert round(yi, 4) == -0.8893 and round(vi, 4) == 0.3256
    yi, vi = effects.log_or(4, 123, 11, 139)
    assert round(yi, 4) == -0.9387 and round(vi, 4) == 0.3571
    # Hedges' g with the small-sample correction J = 1 - 3/(4*df - 1)
    g, vi = effects.smd(10, 5, 2, 10, 3, 2)
    assert round(g, 6) == 0.957746 and round(vi, 6) == 0.222932
    assert effects.md(10, 5, 2, 10, 3, 2) == (2, 0.8)
    z, vi = effects.fisher_z(0.5, 30)
    assert round(z, 6) == 0.549306 and round(vi, 6) == 0.037037
    # zero cells get metafor's default continuity correction
    yi, vi = effects.log_or(0, 10, 5, 10)
    assert yi < 0 and vi > 0
    with pytest.raises(effects.EffectError):
        effects.smd(1, 5, 2, 10, 3, 2)
    with pytest.raises(effects.EffectError):
        effects.fisher_z(1.0, 30)
    ci = effects.confidence(-0.8893, 0.3256, "RR")
    assert round(ci["estimate"], 3) == 0.411 and ci["ci_low"] < -0.8893 < ci["ci_high"]
    assert round(ci["estimate_high"], 3) == round(2.718281828 ** ci["ci_high"], 3)


@pytest.fixture
def quantitative(user_client, ext_project):
    """Three included articles with event/total columns filled for two of
    them (the third misses its control events) and one outcome over the
    three; the second article reports a second study."""
    pid = ext_project["pid"]
    base = f"/api/projects/{pid}/extraction"
    cols = {}
    for name in ("Events intervention", "N intervention", "Events control",
                 "N control", "Notes"):
        r = user_client.post(f"{base}/columns", json={
            "name": name, "col_type": "text" if name == "Notes" else "number"})
        cols[name] = r.json()["id"]
    r1, r2, r3 = ext_project["included"]
    second = user_client.post(f"{base}/records/{r2}/studies",
                              json={"label": "Trial B"}).json()["study_id"]
    cells = {
        ("record", r1): (4, 123, 11, 139),
        ("record", r2): (10, 50, 20, 50),
        ("study", second): (0, 30, 5, 30),
        ("record", r3): (7, 40, None, 40),
    }
    for (kind, ident), values in cells.items():
        for name, value in zip(("Events intervention", "N intervention",
                                "Events control", "N control"), values):
            if value is None:
                continue
            body = {"column_id": cols[name], "value": value}
            body["record_id" if kind == "record" else "study_id"] = ident
            assert user_client.put(f"{base}/values", json=body).status_code == 200
    api = f"/api/projects/{pid}/synthesis"
    user_client.put(f"{api}/plan", json={"enabled": True, "certainty_framework": "grade"})
    outcome = user_client.post(f"{api}/outcomes", json={
        "label": "Crash involvement", "comparison": "Gamified feedback vs none",
        "study_ids": [second], "record_ids": [r1, r2, r3]}).json()
    return {"pid": pid, "api": api, "cols": cols, "outcome": outcome,
            "records": (r1, r2, r3), "second": second}


def test_spec_compute_and_exports(user_client, quantitative):
    q = quantitative
    api, oid, cols = q["api"], q["outcome"]["id"], q["cols"]
    measures = user_client.get(f"{api}/effects/measures").json()
    assert {m["key"] for m in measures["measures"]} == {"SMD", "MD", "OR", "RR", "COR"}
    assert "Notes" not in {c["name"] for c in measures["columns"]}  # numeric only
    # the mapping must point at numeric columns
    r = user_client.put(f"{api}/outcomes/{oid}/effects", json={
        "measure": "RR", "mapping": {"events_i": cols["Notes"]}})
    assert r.status_code == 400
    r = user_client.put(f"{api}/outcomes/{oid}/effects", json={
        "measure": "RR", "mapping": {
            "events_i": cols["Events intervention"], "n_i": cols["N intervention"],
            "events_c": cols["Events control"], "n_c": cols["N control"]}})
    assert r.status_code == 200, r.text
    result = r.json()
    assert result["measure"] == "RR" and result["log_scale"] is True
    assert result["n_studies"] == 4 and result["n_computed"] == 3
    by_record = {}
    for s in result["studies"]:
        by_record.setdefault(s["record_id"], []).append(s)
    aronson = by_record[q["records"][0]][0]
    assert round(aronson["yi"], 4) == -0.8893 and round(aronson["vi"], 4) == 0.3256
    assert round(aronson["estimate"], 3) == 0.411 and aronson["problems"] == []
    third = by_record[q["records"][2]][0]
    assert "yi" not in third and third["problems"] == ["Events (control): missing"]
    two = by_record[q["records"][1]]
    assert len(two) == 2
    trial_b = next(s for s in two if s["label"].endswith("– Trial B"))
    assert trial_b["raw"]["events_i"] == 0 and "yi" in trial_b  # continuity corrected
    # the outcome carries its spec
    outcomes = user_client.get(f"{api}/outcomes").json()["outcomes"]
    assert outcomes[0]["effect_spec"]["measure"] == "RR"
    assert user_client.get(f"{api}/outcomes/{oid}/effects").json()["n_computed"] == 3

    # metafor bundle
    r = user_client.get(f"{api}/outcomes/{oid}/export/metafor.zip")
    assert r.status_code == 200
    zf = zipfile.ZipFile(io.BytesIO(r.content))
    assert set(zf.namelist()) == {"data.csv", "analysis.R"}
    rows = list(csv.DictReader(io.StringIO(zf.read("data.csv").decode("utf-8"))))
    assert len(rows) == 4 and rows[0]["measure"] == "RR"
    assert {"yi", "vi", "events_i", "n_c", "study_label", "doi"} <= set(rows[0])
    assert any(row["problems"] for row in rows)
    script = zf.read("analysis.R").decode("utf-8")
    assert 'escalc(measure = "RR"' in script and "rma(yi, vi" in script
    assert "atransf = exp" in script and "Crash involvement" in script
    # RevMan layout: one row per arm, no row for the study missing a cell? no —
    # the arm rows carry what exists, blanks where the sheet had none
    r = user_client.get(f"{api}/outcomes/{oid}/export/revman.csv")
    assert r.status_code == 200
    rev = list(csv.reader(io.StringIO(r.text.lstrip("﻿"))))
    assert rev[0] == ["Study ID", "Outcome", "Arm", "Total", "Events", "Mean", "SD"]
    assert len(rev) == 1 + 4 * 2
    aronson_rows = [row for row in rev[1:] if row[0] == aronson["label"]]
    assert [row[2:5] for row in aronson_rows] == [["Intervention", "123", "4"],
                                                  ["Control", "139", "11"]]
    # whole-project long CSV
    r = user_client.get(f"{api}/export/effects.csv")
    long = list(csv.DictReader(io.StringIO(r.text.lstrip("﻿"))))
    assert len(long) == 4 and long[0]["outcome"] == "Crash involvement"
    assert "mean_i" in long[0] and long[0]["mean_i"] == ""
    # clearing the spec
    r = user_client.put(f"{api}/outcomes/{oid}/effects", json={"measure": ""})
    assert r.json()["measure"] is None and r.json()["n_computed"] == 0


def test_spec_travels_by_column_uuid(user_client, quantitative):
    q = quantitative
    api, oid, cols = q["api"], q["outcome"]["id"], q["cols"]
    user_client.put(f"{api}/outcomes/{oid}/effects", json={
        "measure": "OR", "mapping": {
            "events_i": cols["Events intervention"], "n_i": cols["N intervention"],
            "events_c": cols["Events control"], "n_c": cols["N control"]}})
    with SessionLocal() as db:
        project = db.get(Project, q["pid"])
        data = serialize_project(db, project)
        spec = data["synthesis_outcomes"][0]["effect_spec"]
        uuids = {c.id: c.uuid for c in db.query(ExtractionColumn)
                 .filter_by(project_id=q["pid"])}
        assert spec["measure"] == "OR"
        assert spec["mapping"]["events_i"] == uuids[cols["Events intervention"]]
        assert set(spec["mapping"]) == {"events_i", "n_i", "events_c", "n_c"}
        stored = db.get(SynthesisOutcome, oid).effect_spec
        assert stored["mapping"]["n_c"] == cols["N control"]
        json.dumps(data)  # serialisable
