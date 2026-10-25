"""Reference export at any review stage: scopes (all/included/excluded/
undecided) from the current screening state, formats RIS / BibTeX / CSV."""
import time

import pytest

_TITLES = ["Alpha study", "Beta study", "Gamma study", "Delta study"]
RIS = "".join(f"""TY  - JOUR
TI  - {title}
AU  - Doe, J{i}.
PY  - 20{10 + i}
JO  - Journal of Exports
DO  - 10.5/exp.{i}
AB  - Abstract {i}.
ER  -
""" for i, title in enumerate(_TITLES, start=1))


@pytest.fixture
def project(user_client):
    me = user_client.get("/api/auth/me").json()
    project = user_client.post("/api/projects", json={"name": "export demo"}).json()
    pid = project["id"]
    user_client.post(f"/api/projects/{pid}/imports/upload",
                     files={"file": ("s.ris", RIS.encode(), "text/plain")},
                     data={"source_name": "pubmed", "source_type": "database"})
    job_id = user_client.post(f"/api/projects/{pid}/dedup/run").json()["job_id"]
    for _ in range(100):
        if user_client.get(f"/api/jobs/{job_id}").json()["status"] in ("done", "failed"):
            break
        time.sleep(0.05)
    project["me"] = me
    return project


def _decide(user_client, project):
    """Single-reviewer T/A screening: include 2, exclude 1, leave 1 pending."""
    pid = project["id"]
    r = user_client.put(f"/api/projects/{pid}/screening/config", json={
        "stage": "ta", "allocation": "all", "conflict_resolution": "consensus",
        "ai_enabled": False, "reviewer_ids": [project["me"]["id"]]})
    assert r.status_code == 200, r.text
    assert user_client.post(f"/api/projects/{pid}/screening/start").status_code == 200
    records = user_client.get(f"/api/projects/{pid}/records").json()["items"]
    by_title = {r["title"]: r["id"] for r in records}
    for title, decision in [("Alpha study", "include"), ("Beta study", "include"),
                            ("Gamma study", "exclude")]:
        r = user_client.post(f"/api/projects/{pid}/screening/vote", json={
            "record_id": by_title[title], "decision": decision})
        assert r.status_code == 200, r.text


def test_summary_counts(user_client, project):
    pid = project["id"]
    assert user_client.get(f"/api/projects/{pid}/export/references/summary"
                           ).json() == {"all": 4, "included": 0, "excluded": 0,
                                        "undecided": 4}
    _decide(user_client, project)
    assert user_client.get(f"/api/projects/{pid}/export/references/summary"
                           ).json() == {"all": 4, "included": 2, "excluded": 1,
                                        "undecided": 1}


def test_export_scopes_and_formats(user_client, project):
    pid = project["id"]
    _decide(user_client, project)

    # RIS, included only
    r = user_client.get(f"/api/projects/{pid}/export/references"
                        "?scope=included&fmt=ris")
    assert r.status_code == 200
    assert "research-info-systems" in r.headers["content-type"]
    assert 'filename="references_included.ris"' in r.headers["content-disposition"]
    assert "Alpha study" in r.text and "Beta study" in r.text
    assert "Gamma study" not in r.text and "Delta study" not in r.text

    # the RIS round-trips through our own parser
    from app.services.ris.parse import parse_file
    parsed = parse_file("x.ris", r.content)
    assert {p["title"] for p in parsed} == {"Alpha study", "Beta study"}
    assert parsed[0]["journal"] == "Journal of Exports"

    # BibTeX, excluded only — parseable by the import parser too
    r = user_client.get(f"/api/projects/{pid}/export/references"
                        "?scope=excluded&fmt=bibtex")
    assert r.status_code == 200
    assert r.text.startswith("@article{doe2013,")
    parsed = parse_file("x.bib", r.content)
    assert [p["title"] for p in parsed] == ["Gamma study"]
    assert parsed[0]["doi"] == "10.5/exp.3"

    # CSV, everything, with the screening status column
    r = user_client.get(f"/api/projects/{pid}/export/references"
                        "?scope=all&fmt=csv")
    assert r.status_code == 200
    lines = r.text.lstrip("﻿").splitlines()
    assert lines[0] == "doi,title,authors,year,journal,abstract,screening_status"
    assert len(lines) == 5
    statuses = {line.split(",")[1]: line.rsplit(",", 1)[-1] for line in lines[1:]}
    assert statuses["Alpha study"] == "include"
    assert statuses["Gamma study"] == "exclude"
    assert statuses["Delta study"] == "undecided"

    # undecided scope
    r = user_client.get(f"/api/projects/{pid}/export/references"
                        "?scope=undecided&fmt=csv")
    assert "Delta study" in r.text and "Alpha study" not in r.text

    # validation
    assert user_client.get(f"/api/projects/{pid}/export/references?scope=nope"
                           ).status_code == 400
    assert user_client.get(f"/api/projects/{pid}/export/references?fmt=docx"
                           ).status_code == 400


def test_export_requires_membership(user_client, project):
    pid = project["id"]
    user_client.post("/api/auth/register", json={
        "email": "stranger@example.com", "password": "password123",
        "display_name": "S"})
    assert user_client.get(f"/api/projects/{pid}/export/references"
                           ).status_code == 403
