"""M9 — extraction table: allocation (1 vs 2 extractors), typed columns +
template, values (human/AI, validation, double-extraction comparison), study
design + JBI appraisal, exports."""
import time

import pytest

_TITLES = [
    "Gamified speed feedback for young drivers",
    "Serious games in nursing education outcomes",
    "Cycling safety interventions in dense cities",
    "Virtual reality exposure for driving anxiety",
]
RIS = "".join(f"""TY  - JOUR
TI  - {title}
AU  - Author{i}, A.
PY  - 20{10 + i}
DO  - 10.1/ext.{i}
AB  - Abstract of study {i}.
ER  -
""" for i, title in enumerate(_TITLES, start=1))


def _login(client, who):
    email = "admin@example.com" if who == "admin" else "rev@example.com"
    client.post("/api/auth/login", json={"email": email, "password": "password123"})


def _await_job(client, job_id):
    for _ in range(100):
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in ("done", "failed"):
            return job
        time.sleep(0.05)
    raise AssertionError("job never finished")


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
def ext_project(user_client, team):
    """Project with 4 records taken through T/A + FT screening: 3 FT-includes
    (the extraction corpus), 1 FT-exclude."""
    pid = user_client.post("/api/projects", json={"name": "M9 demo"}).json()["id"]
    user_client.post(f"/api/projects/{pid}/members",
                     json={"email": "rev@example.com", "role": "reviewer"})
    user_client.post(f"/api/projects/{pid}/imports/upload",
                     files={"file": ("s.ris", RIS.encode(), "text/plain")},
                     data={"source_name": "pubmed", "source_type": "database"})
    _await_job(user_client, user_client.post(
        f"/api/projects/{pid}/dedup/run").json()["job_id"])
    user_client.post(f"/api/projects/{pid}/protocols/upload",
                     files={"file": ("p.md", b"# P\n\nText", "text/markdown")})
    prot = user_client.get(f"/api/projects/{pid}/protocols").json()[0]
    user_client.put(f"/api/projects/{pid}/protocols/{prot['id']}", json={
        "protocol_md": "# P", "criteria": [
            {"code": "E1", "type": "exclude", "label": "wrong population",
             "description": ""}]})
    user_client.post(f"/api/projects/{pid}/protocols/{prot['id']}/validate")

    reviewers = [team["admin"]["id"], team["reviewer"]["id"]]
    user_client.put(f"/api/projects/{pid}/screening/config", json={
        "stage": "ta", "allocation": "all", "conflict_resolution": "consensus",
        "reviewer_ids": reviewers})
    user_client.post(f"/api/projects/{pid}/screening/start")
    ta_ids = [i["id"] for i in user_client.get(
        f"/api/projects/{pid}/screening/queue?limit=10").json()["items"]]
    for who in ("admin", "reviewer"):
        _login(user_client, who)
        for rid in ta_ids:
            user_client.post(f"/api/projects/{pid}/screening/vote",
                             json={"record_id": rid, "decision": "include"})
    _login(user_client, "admin")
    user_client.put(f"/api/projects/{pid}/screening/config", json={
        "stage": "ft", "allocation": "all", "conflict_resolution": "consensus",
        "reviewer_ids": reviewers})
    user_client.post(f"/api/projects/{pid}/screening/start?stage=ft")
    for who in ("admin", "reviewer"):
        _login(user_client, who)
        for idx, rid in enumerate(ta_ids):
            payload = {"record_id": rid, "decision": "include"}
            if idx == 3:
                payload = {"record_id": rid, "decision": "exclude",
                           "reasons": ["E1"]}
            user_client.post(f"/api/projects/{pid}/screening/vote?stage=ft",
                             json=payload)
    _login(user_client, "admin")
    return {"pid": pid, "included": ta_ids[:3], "excluded": ta_ids[3],
            "reviewers": reviewers}


def test_config_allocation_single_and_dual(user_client, team, ext_project):
    pid = ext_project["pid"]
    info = user_client.get(f"/api/projects/{pid}/extraction/config").json()
    assert info["eligible_records"] == 3
    assert info["config"] is None

    # 1 extractor per article, 2 extractors -> 3 records split between the two
    r = user_client.put(f"/api/projects/{pid}/extraction/config", json={
        "n_extractors": 1, "extractor_ids": ext_project["reviewers"]})
    assert r.status_code == 200
    r = user_client.post(f"/api/projects/{pid}/extraction/start")
    assert r.json()["assignments_created"] == 3

    table = user_client.get(f"/api/projects/{pid}/extraction/table").json()
    assert len(table["rows"]) == 3
    per_row = [row["assigned_to"] for row in table["rows"]]
    assert all(len(a) == 1 for a in per_row)
    assert {u for a in per_row for u in a} == set(ext_project["reviewers"])

    # switch to double extraction: the missing pairs are topped up
    user_client.put(f"/api/projects/{pid}/extraction/config", json={
        "n_extractors": 2, "extractor_ids": ext_project["reviewers"]})
    created = user_client.post(
        f"/api/projects/{pid}/extraction/start").json()["assignments_created"]
    assert created == 0  # existing single assignments untouched...
    # (records already assigned keep their extractor; only new records pair up)

    # non-member extractor rejected
    r = user_client.put(f"/api/projects/{pid}/extraction/config", json={
        "n_extractors": 1, "extractor_ids": [99999]})
    assert r.status_code == 400


def test_columns_template_and_typed_values(user_client, team, ext_project):
    pid = ext_project["pid"]
    rid = ext_project["included"][0]

    # template + custom typed columns
    created = user_client.post(
        f"/api/projects/{pid}/extraction/columns/template").json()["created"]
    assert created == len(user_client.get(
        f"/api/projects/{pid}/extraction/columns").json())
    r = user_client.post(f"/api/projects/{pid}/extraction/columns", json={
        "name": "Design category", "col_type": "choice",
        "options": ["experimental", "observational"]})
    choice_id = r.json()["id"]
    r = user_client.post(f"/api/projects/{pid}/extraction/columns", json={
        "name": "Blinded", "col_type": "bool"})
    bool_id = r.json()["id"]
    # choice/multi without options rejected
    r = user_client.post(f"/api/projects/{pid}/extraction/columns", json={
        "name": "Bad", "col_type": "choice"})
    assert r.status_code == 400

    columns = user_client.get(f"/api/projects/{pid}/extraction/columns").json()
    n_col = next(c["id"] for c in columns if c["name"] == "Sample size (N)")

    # typed coercion: number ok / bad number rejected / choice validated
    r = user_client.put(f"/api/projects/{pid}/extraction/values", json={
        "record_id": rid, "column_id": n_col, "value": "42"})
    assert r.status_code == 200
    r = user_client.put(f"/api/projects/{pid}/extraction/values", json={
        "record_id": rid, "column_id": n_col, "value": "not a number"})
    assert r.status_code == 400
    r = user_client.put(f"/api/projects/{pid}/extraction/values", json={
        "record_id": rid, "column_id": choice_id, "value": "wrong option"})
    assert r.status_code == 400
    user_client.put(f"/api/projects/{pid}/extraction/values", json={
        "record_id": rid, "column_id": choice_id, "value": "experimental"})
    user_client.put(f"/api/projects/{pid}/extraction/values", json={
        "record_id": rid, "column_id": bool_id, "value": True})

    table = user_client.get(f"/api/projects/{pid}/extraction/table").json()
    row = next(x for x in table["rows"] if x["record_id"] == rid)
    assert row["cells"][str(n_col)][0]["value"] == 42
    assert row["cells"][str(n_col)][0]["validated"] is True
    assert row["cells"][str(choice_id)][0]["value"] == "experimental"
    assert row["cells"][str(bool_id)][0]["value"] is True


def test_double_extraction_cells_and_export(user_client, team, ext_project):
    pid = ext_project["pid"]
    rid = ext_project["included"][0]
    user_client.post(f"/api/projects/{pid}/extraction/columns", json={
        "name": "Country", "col_type": "text"})
    col = user_client.get(f"/api/projects/{pid}/extraction/columns").json()[0]["id"]

    # two extractors fill the same cell with different values
    user_client.put(f"/api/projects/{pid}/extraction/values", json={
        "record_id": rid, "column_id": col, "value": "France"})
    _login(user_client, "reviewer")
    user_client.put(f"/api/projects/{pid}/extraction/values", json={
        "record_id": rid, "column_id": col, "value": "Belgium"})
    _login(user_client, "admin")

    table = user_client.get(f"/api/projects/{pid}/extraction/table").json()
    row = next(x for x in table["rows"] if x["record_id"] == rid)
    cell = row["cells"][str(col)]
    assert len(cell) == 2  # one value per extractor, comparable

    # CSV export marks the disagreement with both extractors named
    csv_out = user_client.get(f"/api/projects/{pid}/extraction/export.csv")
    assert csv_out.status_code == 200
    body = csv_out.text
    assert "France" in body and "Belgium" in body and "|" in body

    # XLSX export answers with a real workbook
    xlsx = user_client.get(f"/api/projects/{pid}/extraction/export.xlsx")
    assert xlsx.status_code == 200
    assert xlsx.content[:2] == b"PK"


def test_design_and_jbi_appraisal(user_client, team, ext_project):
    pid = ext_project["pid"]
    rid = ext_project["included"][0]

    # JBI needs a qualified design first
    r = user_client.put(f"/api/projects/{pid}/extraction/records/{rid}/jbi",
                        json={"answers": {}, "overall": "include"})
    assert r.status_code == 400

    # catalogue is served (8 checklists)
    catalogue = user_client.get(
        f"/api/projects/{pid}/extraction/jbi/checklists").json()
    assert len(catalogue["checklists"]) == 8
    rct = next(c for c in catalogue["checklists"] if c["key"] == "rct")
    assert sum(len(d["questions"]) for d in rct["domains"]) == 13

    # qualify manually, then fill the checklist
    r = user_client.put(f"/api/projects/{pid}/extraction/records/{rid}/design",
                        json={"design": "rct"})
    assert r.status_code == 200
    r = user_client.put(f"/api/projects/{pid}/extraction/records/{rid}/jbi",
                        json={"answers": {
                            "q1": {"answer": "yes", "comment": "table 1"},
                            "q2": {"answer": "unclear", "comment": ""},
                        }, "overall": "include", "comment": "solid"})
    assert r.status_code == 200
    # invalid answer rejected
    r = user_client.put(f"/api/projects/{pid}/extraction/records/{rid}/jbi",
                        json={"answers": {"q1": {"answer": "peut-être"}},
                              "overall": ""})
    assert r.status_code == 400

    # the second assessor sees mine read-only, adds their own
    _login(user_client, "reviewer")
    got = user_client.get(
        f"/api/projects/{pid}/extraction/records/{rid}/jbi").json()
    assert got["design"] == "rct"
    assert got["mine"] is None
    assert len(got["others"]) == 1
    assert got["others"][0]["answers"]["q1"]["answer"] == "yes"
    user_client.put(f"/api/projects/{pid}/extraction/records/{rid}/jbi",
                    json={"answers": {"q1": {"answer": "no", "comment": ""}},
                          "overall": "seek_info"})
    _login(user_client, "admin")
    got = user_client.get(
        f"/api/projects/{pid}/extraction/records/{rid}/jbi").json()
    assert got["mine"]["overall"] == "include"
    assert got["others"][0]["overall"] == "seek_info"

    # unknown design rejected
    r = user_client.put(f"/api/projects/{pid}/extraction/records/{rid}/design",
                        json={"design": "astrology"})
    assert r.status_code == 400


def test_ai_prefill_never_overwrites_human(user_client, team, ext_project,
                                           monkeypatch, tmp_path):
    pid = ext_project["pid"]
    rid = ext_project["included"][0]
    user_client.post(f"/api/projects/{pid}/extraction/columns", json={
        "name": "Country", "col_type": "text"})
    user_client.post(f"/api/projects/{pid}/extraction/columns", json={
        "name": "Sample size", "col_type": "number"})
    columns = user_client.get(f"/api/projects/{pid}/extraction/columns").json()
    country_id, n_id = columns[0]["id"], columns[1]["id"]

    # human value present in Country
    user_client.put(f"/api/projects/{pid}/extraction/values", json={
        "record_id": rid, "column_id": country_id, "value": "France"})

    # stored PDF + fake LLM proposing both cells
    import fitz
    pdf_path = tmp_path / "r.pdf"
    doc = fitz.open()
    doc.new_page().insert_text((72, 72), "A study conducted in Spain, N=120.")
    doc.save(pdf_path)
    user_client.post(
        f"/api/projects/{pid}/fulltext/records/{rid}/upload",
        files={"file": ("r.pdf", pdf_path.read_bytes(), "application/pdf")})
    user_client.put("/api/llm/credentials", json={
        "provider": "anthropic", "api_key": "sk-ant-fake-key-123"})

    class FakeProvider:
        model = "claude-fake"

        def generate_json(self, messages, json_schema, system=None,
                          max_tokens=4096):
            from app.services.llm.base import LLMResult
            return LLMResult(text="{}", data={"fields": {
                str(country_id): "Spain", str(n_id): 120}})

    monkeypatch.setattr("app.services.extraction.ai.open_provider_chain",
                        lambda *a, **kw: FakeProvider())

    out = user_client.post(
        f"/api/projects/{pid}/extraction/records/{rid}/prefill").json()
    assert out["written"] == 1 and out["skipped_human"] == 1 and out["notes"] == ""
    assert "cost_usd" in out["cost"]  # per-call cost estimate returned

    table = user_client.get(f"/api/projects/{pid}/extraction/table").json()
    row = next(x for x in table["rows"] if x["record_id"] == rid)
    country = row["cells"][str(country_id)][0]
    assert country["value"] == "France" and country["origin"] == "human"
    n_cell = row["cells"][str(n_id)][0]
    assert n_cell == {"user_id": team["admin"]["id"], "value": 120,
                      "origin": "ai", "validated": False}

    # validating the AI cell
    r = user_client.post(f"/api/projects/{pid}/extraction/values/validate",
                         json={"record_id": rid, "column_id": n_id})
    assert r.status_code == 200
    table = user_client.get(f"/api/projects/{pid}/extraction/table").json()
    row = next(x for x in table["rows"] if x["record_id"] == rid)
    assert row["cells"][str(n_id)][0]["validated"] is True


def test_validate_all_ai_values(user_client, team, ext_project, monkeypatch,
                                tmp_path):
    """The 'validate all' action flips every amber AI cell of mine at once,
    and never touches human cells."""
    pid = ext_project["pid"]
    rid = ext_project["included"][0]
    user_client.post(f"/api/projects/{pid}/extraction/columns", json={
        "name": "Country", "col_type": "text"})
    user_client.post(f"/api/projects/{pid}/extraction/columns", json={
        "name": "Sample size", "col_type": "number"})
    columns = user_client.get(f"/api/projects/{pid}/extraction/columns").json()
    country_id, n_id = columns[0]["id"], columns[1]["id"]

    # one human cell (must stay untouched) + a stored PDF for AI prefill
    user_client.put(f"/api/projects/{pid}/extraction/values", json={
        "record_id": rid, "column_id": country_id, "value": "France"})
    import fitz
    pdf_path = tmp_path / "r.pdf"
    doc = fitz.open()
    doc.new_page().insert_text((72, 72), "A study in Spain, N=120.")
    doc.save(pdf_path)
    user_client.post(
        f"/api/projects/{pid}/fulltext/records/{rid}/upload",
        files={"file": ("r.pdf", pdf_path.read_bytes(), "application/pdf")})
    user_client.put("/api/llm/credentials", json={
        "provider": "anthropic", "api_key": "sk-ant-fake-key-123"})

    class FakeProvider:
        model = "claude-fake"

        def generate_json(self, messages, json_schema, system=None,
                          max_tokens=4096):
            from app.services.llm.base import LLMResult
            return LLMResult(text="{}", data={"fields": {str(n_id): 120}})

    monkeypatch.setattr("app.services.extraction.ai.open_provider_chain",
                        lambda *a, **kw: FakeProvider())
    user_client.post(f"/api/projects/{pid}/extraction/records/{rid}/prefill")

    r = user_client.post(f"/api/projects/{pid}/extraction/values/validate-all")
    assert r.status_code == 200 and r.json()["validated"] == 1

    table = user_client.get(f"/api/projects/{pid}/extraction/table").json()
    row = next(x for x in table["rows"] if x["record_id"] == rid)
    assert row["cells"][str(n_id)][0]["validated"] is True     # AI cell accepted
    country = row["cells"][str(country_id)][0]
    assert country["origin"] == "human" and country["validated"] is True

    # idempotent: nothing left to validate
    r = user_client.post(f"/api/projects/{pid}/extraction/values/validate-all")
    assert r.json()["validated"] == 0


def test_jbi_ai_suggestions(user_client, team, ext_project, monkeypatch,
                            tmp_path):
    """B5: on-demand AI proposals for the JBI checklist — valid answers only,
    nothing persisted until the assessor saves."""
    pid = ext_project["pid"]
    rid = ext_project["included"][0]
    url = f"/api/projects/{pid}/extraction/records/{rid}/jbi/suggest"
    user_client.put("/api/llm/credentials", json={
        "provider": "anthropic", "api_key": "sk-ant-fake-key-123"})

    # design gates the endpoint
    assert user_client.post(url).status_code == 400
    user_client.put(f"/api/projects/{pid}/extraction/records/{rid}/design",
                    json={"design": "rct"})
    # ... and so does the missing PDF
    assert user_client.post(url).status_code == 400

    import fitz
    pdf_path = tmp_path / "r.pdf"
    doc = fitz.open()
    doc.new_page().insert_text((72, 72), "Randomized, allocation concealed.")
    doc.save(pdf_path)
    user_client.post(
        f"/api/projects/{pid}/fulltext/records/{rid}/upload",
        files={"file": ("r.pdf", pdf_path.read_bytes(), "application/pdf")})

    class FakeProvider:
        model = "claude-fake"

        def generate_json(self, messages, json_schema, system=None,
                          max_tokens=4096):
            from app.services.llm.base import LLMResult
            assert "critical appraisal" in system
            return LLMResult(text="{}", data={"answers": {
                "q1": {"answer": "yes", "comment": "randomized (p. 1)"},
                "q2": {"answer": "maybe", "comment": "invalid option"},
                "q99": {"answer": "yes", "comment": "unknown question"},
            }})

    monkeypatch.setattr("app.services.extraction.ai.open_provider_chain",
                        lambda *a, **kw: FakeProvider())
    r = user_client.post(url)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["design"] == "rct"
    # invalid option and unknown question filtered out
    assert out["answers"] == {
        "q1": {"answer": "yes", "comment": "randomized (p. 1)"}}

    # nothing was saved server-side
    got = user_client.get(
        f"/api/projects/{pid}/extraction/records/{rid}/jbi").json()
    assert got["mine"] is None


def test_jbi_score_and_dedicated_export(user_client, team, ext_project):
    """1 point per 'yes'; score exposed on the grid rows and in the dedicated
    JBI table export (wide answers, one line per record x assessor)."""
    pid = ext_project["pid"]
    rid = ext_project["included"][0]
    user_client.put(f"/api/projects/{pid}/extraction/records/{rid}/design",
                    json={"design": "rct"})
    user_client.put(f"/api/projects/{pid}/extraction/records/{rid}/jbi",
                    json={"answers": {
                        "q1": {"answer": "yes", "comment": "table 1"},
                        "q2": {"answer": "yes", "comment": ""},
                        "q3": {"answer": "no", "comment": ""},
                        "q4": {"answer": "unclear", "comment": ""},
                    }, "overall": "include"})

    table = user_client.get(f"/api/projects/{pid}/extraction/table").json()
    row = next(x for x in table["rows"] if x["record_id"] == rid)
    assert row["jbi"]["scores"] == [{
        "user_id": team["admin"]["id"], "overall": "include",
        "n_yes": 2, "n_questions": 13, "n_answered": 4}]

    # main export gained the JBI score column
    csv_main = user_client.get(f"/api/projects/{pid}/extraction/export.csv")
    header = csv_main.text.splitlines()[0]
    assert "JBI score" in header
    line = next(l for l in csv_main.text.splitlines() if l.startswith(f"{rid},"))
    assert "2/13" in line

    # dedicated JBI table: wide answers + score
    csv_jbi = user_client.get(f"/api/projects/{pid}/extraction/export/jbi.csv")
    assert csv_jbi.status_code == 200
    import csv as csv_mod
    import io as io_mod
    parsed = list(csv_mod.reader(io_mod.StringIO(csv_jbi.text.lstrip("﻿"))))
    header_row, data = parsed[0], parsed[1:]
    # one column per criterion under the instrument's own ids (JBI: q1..q13)
    assert header_row[:15] == ["Record ID", "Study", "First author", "Year",
                               "Title", "DOI", "Design", "Instrument",
                               "Assessor", "Score (yes)", "Out of", "Answered",
                               "Overall appraisal", "Overall comment", "q1"]
    cells = next(r for r in data if r[0] == str(rid))
    q_offset = header_row.index("q1")
    assert cells[header_row.index("Score (yes)")] == "2"
    assert cells[header_row.index("Out of")] == "13"
    assert cells[q_offset:q_offset + 4] == ["yes", "yes", "no", "unclear"]

    r = user_client.get(f"/api/projects/{pid}/extraction/export/jbi.xlsx")
    assert r.status_code == 200
    assert r.headers["content-disposition"].endswith('"jbi_appraisal.xlsx"')


def test_column_names_cannot_inject_formulas_in_exports(user_client, team,
                                                        ext_project):
    """A column name is typed by a project admin and becomes a header cell:
    neutralised like every other cell (CSV/DDE formula injection)."""
    import io

    from openpyxl import load_workbook
    pid = ext_project["pid"]
    user_client.post(f"/api/projects/{pid}/extraction/columns", json={
        "name": '=HYPERLINK("http://evil.example","x")', "col_type": "text"})
    body = user_client.get(f"/api/projects/{pid}/extraction/export.csv").text
    header = body.splitlines()[0]
    assert "'=HYPERLINK" in header and ",=HYPERLINK" not in header
    xlsx = user_client.get(f"/api/projects/{pid}/extraction/export.xlsx")
    sheet = load_workbook(io.BytesIO(xlsx.content)).active
    assert not any(str(c.value or "").startswith("=") for c in sheet[1])
