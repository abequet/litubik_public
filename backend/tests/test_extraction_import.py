"""External-review import: an extraction table filled on another platform
(xlsx) is mapped, matched to existing records (DOI, then title), missing
articles are created and every touched article is force-included into the
extraction corpus without a local FT screening round."""
import io
import json

import pytest
from openpyxl import Workbook

RIS = "".join(f"""TY  - JOUR
TI  - Imported study number {i}
AU  - Author{i}, A.
PY  - 20{10 + i}
DO  - 10.1/imp.{i}
AB  - Abstract {i}.
ER  -
""" for i in (1, 2, 3))


def _xlsx(header: list, rows: list[list]) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(header)
    for row in rows:
        sheet.append(row)
    out = io.BytesIO()
    workbook.save(out)
    return out.getvalue()


@pytest.fixture
def project(user_client):
    """A project with 3 records straight from a search import (never
    screened): the external review's articles partially overlap them."""
    pid = user_client.post("/api/projects", json={"name": "ext import"}).json()["id"]
    user_client.post(f"/api/projects/{pid}/imports/upload",
                     files={"file": ("s.ris", RIS.encode(), "text/plain")},
                     data={"source_name": "pubmed", "source_type": "database"})
    user_client.post(f"/api/projects/{pid}/extraction/columns", json={
        "name": "Sample size (N)", "col_type": "number"})
    return pid


HEADER = ["Title", "DOI", "Authors", "Year", "Country", "Sample size (N)"]
ROWS = [
    # matches record 1 by DOI
    ["Imported study number 1", "10.1/imp.1", "Author1, A.", 2011,
     "France", 42],
    # matches record 2 by (normalized) title, bad number -> warning
    ["Imported Study NUMBER 2!", "", "Author2, A.", 2012,
     "Belgium", "n/a"],
    # unknown article -> created + force-included
    ["A study screened elsewhere", "10.9/other.1", "New, N.; Other, O.",
     2020, "Spain", 120],
]


def test_preview_mapping_and_match_stats(user_client, project):
    r = user_client.post(
        f"/api/projects/{project}/extraction/import-table/preview",
        files={"file": ("table.xlsx", _xlsx(HEADER, ROWS))})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["n_rows"] == 3
    roles = {h["header"]: h["role"] for h in out["headers"]}
    assert roles["Title"] == "title" and roles["DOI"] == "doi"
    assert roles["Authors"] == "authors" and roles["Year"] == "year"
    assert roles["Country"] == "column" and roles["Sample size (N)"] == "column"
    by_header = {h["header"]: h for h in out["headers"]}
    assert by_header["Country"]["column_id"] is None          # to create
    assert by_header["Sample size (N)"]["column_id"] is not None  # existing
    assert out["matched"] == 2
    assert out["matched_not_included"] == 2  # never FT-screened here
    assert out["unmatched"] == 1
    assert "A study screened elsewhere" in out["unmatched_sample"][0]


def test_apply_creates_columns_records_and_values(user_client, project):
    preview = user_client.post(
        f"/api/projects/{project}/extraction/import-table/preview",
        files={"file": ("table.xlsx", _xlsx(HEADER, ROWS))}).json()
    mapping = json.dumps([{"index": h["index"], "role": h["role"],
                           "column_id": h["column_id"]}
                          for h in preview["headers"]])
    r = user_client.post(
        f"/api/projects/{project}/extraction/import-table",
        files={"file": ("table.xlsx", _xlsx(HEADER, ROWS))},
        data={"mapping": mapping, "create_missing": "true"})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["records_created"] == 1
    assert out["records_force_included"] == 3
    assert out["columns_created"] == 1  # Country ("Sample size (N)" existed)
    # 3 Country cells + 2 valid numbers ("n/a" skipped with a warning)
    assert out["cells_written"] == 5
    assert len(out["warnings"]) == 1 and "Sample size (N)" in out["warnings"][0]

    # the extraction grid now shows all 3 articles with the imported cells
    table = user_client.get(
        f"/api/projects/{project}/extraction/table").json()
    assert len(table["rows"]) == 3
    columns = {c["name"]: c["id"] for c in table["columns"]}
    by_title = {r["title"]: r for r in table["rows"]}
    row1 = by_title["Imported study number 1"]
    assert row1["cells"][str(columns["Country"])][0]["value"] == "France"
    assert row1["cells"][str(columns["Sample size (N)"])][0]["value"] == 42
    assert row1["cells"][str(columns["Country"])][0]["validated"] is True
    created = by_title["A study screened elsewhere"]
    assert created["doi"] == "10.9/other.1"
    assert created["cells"][str(columns["Sample size (N)"])][0]["value"] == 120

    # re-import: rows now all match (upsert) — nothing new is created
    again = user_client.post(
        f"/api/projects/{project}/extraction/import-table",
        files={"file": ("table.xlsx", _xlsx(HEADER, ROWS))},
        data={"mapping": mapping, "create_missing": "true"}).json()
    assert again["records_created"] == 0
    assert again["matched"] == 3
    table = user_client.get(
        f"/api/projects/{project}/extraction/table").json()
    assert len(table["rows"]) == 3


def test_apply_without_create_missing_skips_unknown(user_client, project):
    preview = user_client.post(
        f"/api/projects/{project}/extraction/import-table/preview",
        files={"file": ("table.xlsx", _xlsx(HEADER, ROWS))}).json()
    mapping = json.dumps([{"index": h["index"], "role": h["role"],
                           "column_id": h["column_id"]}
                          for h in preview["headers"]])
    out = user_client.post(
        f"/api/projects/{project}/extraction/import-table",
        files={"file": ("table.xlsx", _xlsx(HEADER, ROWS))},
        data={"mapping": mapping, "create_missing": "false"}).json()
    assert out["records_created"] == 0
    assert out["skipped_rows"] == 1
    table = user_client.get(
        f"/api/projects/{project}/extraction/table").json()
    assert len(table["rows"]) == 2


def test_mapping_must_carry_title_or_doi(user_client, project):
    mapping = json.dumps([{"index": 0, "role": "ignore", "column_id": None}])
    r = user_client.post(
        f"/api/projects/{project}/extraction/import-table",
        files={"file": ("table.xlsx", _xlsx(HEADER, ROWS))},
        data={"mapping": mapping})
    assert r.status_code == 400
    assert "Title or a DOI" in r.json()["detail"]


def test_import_is_admin_only(user_client, project):
    user_client.post("/api/auth/register", json={
        "email": "rev2@example.com", "password": "password123",
        "display_name": "Reviewer"})
    # the fresh account is logged in but not even a member -> forbidden
    r = user_client.post(
        f"/api/projects/{project}/extraction/import-table/preview",
        files={"file": ("table.xlsx", _xlsx(HEADER, ROWS))})
    assert r.status_code in (403, 404)
    user_client.post("/api/auth/login", json={
        "email": "admin@example.com", "password": "password123"})


def test_bad_workbook_rejected(user_client, project):
    r = user_client.post(
        f"/api/projects/{project}/extraction/import-table/preview",
        files={"file": ("table.xlsx", b"not an xlsx at all")})
    assert r.status_code == 400
