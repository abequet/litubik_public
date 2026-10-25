"""Bulk PDF import: files matched to records by DOI-in-text, DOI-in-filename
or title fuzzy; confident matches stored like manual uploads, the rest
reported with candidates. Also covers the library scope fix: records imported
at the extraction stage (ft_forced_included) belong to the full-text corpus."""
import io
import json
import time

import fitz
import pytest
from openpyxl import Workbook

RIS = """TY  - JOUR
TI  - Gamified feedback improves driving outcomes
AU  - Author1, A.
PY  - 2011
DO  - 10.1/bulk.1
ER  -
TY  - JOUR
TI  - Serious games for nursing education programs
AU  - Author2, A.
PY  - 2012
DO  - 10.1/bulk.2
ER  -
TY  - JOUR
TI  - Cycling infrastructure and commuter safety
AU  - Author3, A.
PY  - 2013
DO  - 10.1/bulk.3
ER  -
TY  - JOUR
TI  - Deep learning for road safety analysis
AU  - Author4, A.
PY  - 2014
ER  -
"""


def _pdf(text: str) -> bytes:
    doc = fitz.open()
    doc.new_page().insert_text((72, 72), text)
    return doc.tobytes()


@pytest.fixture
def project(user_client):
    pid = user_client.post("/api/projects", json={"name": "pdfs"}).json()["id"]
    user_client.post(f"/api/projects/{pid}/imports/upload",
                     files={"file": ("s.ris", RIS.encode(), "text/plain")},
                     data={"source_name": "pubmed", "source_type": "database"})
    # dedup marks the records 'unique' — the full-text library's fallback
    # scope when no T/A screening exists
    job_id = user_client.post(f"/api/projects/{pid}/dedup/run").json()["job_id"]
    for _ in range(100):
        if user_client.get(f"/api/jobs/{job_id}").json()["status"] in (
                "done", "failed"):
            break
        time.sleep(0.05)
    return pid


def _import(client, pid, files, overwrite=False):
    return client.post(
        f"/api/projects/{pid}/fulltext/pdf-import",
        files=[("files", (name, data, "application/pdf"))
               for name, data in files],
        data={"overwrite": "true" if overwrite else "false"})


def test_matching_cascade(user_client, project):
    files = [
        # DOI printed on page 1
        ("whatever.pdf", _pdf("A study.\ndoi: 10.1/bulk.1\nIntroduction…")),
        # DOI only in the filename ('/' exported as '_')
        ("10.1_bulk.2.pdf", _pdf("scanned content without metadata")),
        # full title on page 1, no DOI anywhere
        ("paper3.pdf", _pdf("Cycling infrastructure and commuter safety\n"
                            "Author3\nAbstract…")),
        # Zotero-style filename, useless content
        ("Author4 - 2014 - Deep learning for road safety analysis.pdf",
         _pdf("completely unrelated words")),
        # nothing to match
        ("notes.pdf", _pdf("shopping list, definitely not a paper")),
    ]
    r = _import(user_client, project, files)
    assert r.status_code == 200, r.text
    out = r.json()
    by_name = {x["filename"]: x for x in out["results"]}
    assert by_name["whatever.pdf"]["status"] == "linked"
    assert by_name["whatever.pdf"]["method"] == "doi_text"
    assert by_name["10.1_bulk.2.pdf"]["status"] == "linked"
    assert by_name["10.1_bulk.2.pdf"]["method"] == "doi_name"
    assert by_name["paper3.pdf"]["status"] == "linked"
    assert by_name["paper3.pdf"]["method"] == "title_text"
    zotero = by_name["Author4 - 2014 - Deep learning for road safety analysis.pdf"]
    assert zotero["status"] == "linked"
    assert zotero["method"] == "title_name"
    assert by_name["notes.pdf"]["status"] in ("unmatched", "ambiguous")
    assert out["linked"] == 4

    # the four linked PDFs are in the library, served like manual uploads
    rows = user_client.get(f"/api/projects/{project}/fulltext").json()
    with_file = {row["title"]: row for row in rows if row["has_file"]}
    assert len(with_file) == 4
    assert all(row["via"] == "bulk_import" for row in with_file.values())
    rid = with_file["Gamified feedback improves driving outcomes"]["record_id"]
    served = user_client.get(
        f"/api/projects/{project}/fulltext/records/{rid}/file")
    assert served.status_code == 200
    assert served.content[:5] == b"%PDF-"


def test_existing_pdf_skipped_unless_overwrite(user_client, project):
    first = _pdf("doi: 10.1/bulk.1")
    _import(user_client, project, [("a.pdf", first)])
    again = _import(user_client, project, [("b.pdf", first)]).json()
    assert again["results"][0]["status"] == "already_has_pdf"
    assert again["results"][0]["record_id"] > 0
    forced = _import(user_client, project, [("b.pdf", first)],
                     overwrite=True).json()
    assert forced["results"][0]["status"] == "linked"


def test_non_pdf_rejected_per_file(user_client, project):
    out = _import(user_client, project, [
        ("bad.pdf", b"MZ this is not a pdf"),
        ("good.pdf", _pdf("doi: 10.1/bulk.2")),
    ]).json()
    by_name = {x["filename"]: x for x in out["results"]}
    assert by_name["bad.pdf"]["status"] == "error"
    assert by_name["good.pdf"]["status"] == "linked"


def test_forced_included_records_enter_the_library(user_client, project):
    """An article created by the extraction-table import (screened elsewhere)
    must appear in the full-text library and accept a bulk-imported PDF."""
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["Title", "DOI"])
    sheet.append(["An article screened on another platform", "10.9/elsewhere.1"])
    buf = io.BytesIO()
    workbook.save(buf)
    xlsx = buf.getvalue()
    preview = user_client.post(
        f"/api/projects/{project}/extraction/import-table/preview",
        files={"file": ("t.xlsx", xlsx)}).json()
    mapping = json.dumps([{"index": h["index"], "role": h["role"],
                           "column_id": h["column_id"]}
                          for h in preview["headers"]])
    user_client.post(
        f"/api/projects/{project}/extraction/import-table",
        files={"file": ("t.xlsx", xlsx)},
        data={"mapping": mapping, "create_missing": "true"})

    rows = user_client.get(f"/api/projects/{project}/fulltext").json()
    titles = {row["title"] for row in rows}
    assert "An article screened on another platform" in titles

    out = _import(user_client, project, [
        ("x.pdf", _pdf("doi: 10.9/elsewhere.1"))]).json()
    assert out["results"][0]["status"] == "linked"
