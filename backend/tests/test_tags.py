"""Tags on papers (tickets #16/#T13): CRUD, on-the-fly creation while
attaching, tagged-papers list with screening status, CSV export."""
import time

import pytest

RIS = """TY  - JOUR
TI  - Paper one about driving simulators
AU  - Alpha, A.
PY  - 2019
DO  - 10.1/tag.1
ER  -
TY  - JOUR
TI  - Paper two about cycling safety
AU  - Beta, B.
PY  - 2021
DO  - 10.1/tag.2
ER  -
"""


def _await_job(client, job_id):
    for _ in range(100):
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in ("done", "failed"):
            return job
        time.sleep(0.05)
    raise AssertionError("job never finished")


@pytest.fixture
def project(user_client):
    pid = user_client.post("/api/projects", json={"name": "tags"}).json()["id"]
    user_client.post(f"/api/projects/{pid}/imports/upload",
                     files={"file": ("s.ris", RIS.encode(), "text/plain")},
                     data={"source_name": "pubmed", "source_type": "database"})
    _await_job(user_client, user_client.post(
        f"/api/projects/{pid}/dedup/run").json()["job_id"])
    records = user_client.get(
        f"/api/projects/{pid}/records?limit=10").json()["items"]
    return {"pid": pid, "rids": [r["id"] for r in records]}


def test_tag_crud(user_client, project):
    pid = project["pid"]
    base = f"/api/projects/{pid}/tags"

    tag = user_client.post(base, json={"name": "Intro/Discussion"}).json()
    assert tag["name"] == "Intro/Discussion" and tag["n_records"] == 0
    # get-or-create is case-insensitive: no duplicate
    again = user_client.post(base, json={"name": "intro/discussion"}).json()
    assert again["id"] == tag["id"]

    user_client.post(base, json={"name": "methodology"})
    names = [t["name"] for t in user_client.get(base).json()]
    assert names == ["Intro/Discussion", "methodology"]  # alpha order

    # rename, with clash guard
    other = [t for t in user_client.get(base).json()
             if t["name"] == "methodology"][0]
    r = user_client.put(f"{base}/{other['id']}",
                        json={"name": "INTRO/discussion"})
    assert r.status_code == 409
    assert user_client.put(f"{base}/{other['id']}",
                           json={"name": "background"}).json()["name"] == \
        "background"

    assert user_client.delete(f"{base}/{other['id']}").json() == {"ok": True}
    assert [t["name"] for t in user_client.get(base).json()] == \
        ["Intro/Discussion"]


def test_attach_detach_and_list(user_client, project):
    pid, (r1, r2) = project["pid"], project["rids"][:2]
    base = f"/api/projects/{pid}/tags"

    # attach by name creates the tag on the fly
    tags = user_client.post(f"{base}/records/{r1}",
                            json={"name": "Intro/Discussion"}).json()
    assert [t["name"] for t in tags] == ["Intro/Discussion"]
    user_client.post(f"{base}/records/{r1}", json={"name": "simulator"})
    user_client.post(f"{base}/records/{r2}", json={"name": "simulator"})
    # double-attach is a no-op
    tags = user_client.post(f"{base}/records/{r1}",
                            json={"name": "simulator"}).json()
    assert len(tags) == 2

    by_name = {t["name"]: t for t in user_client.get(base).json()}
    assert by_name["Intro/Discussion"]["n_records"] == 1
    assert by_name["simulator"]["n_records"] == 2

    rows = user_client.get(f"{base}/records").json()
    assert len(rows) == 2
    tagged = {row["record_id"]: row for row in rows}
    assert tagged[r1]["tags"] == ["Intro/Discussion", "simulator"]
    assert tagged[r1]["status"] == "not screened yet"
    assert tagged[r2]["tags"] == ["simulator"]

    # filter by tag
    only = user_client.get(
        f"{base}/records?tag_id={by_name['Intro/Discussion']['id']}").json()
    assert [row["record_id"] for row in only] == [r1]

    # detach
    tags = user_client.delete(
        f"{base}/records/{r1}/{by_name['simulator']['id']}").json()
    assert [t["name"] for t in tags] == ["Intro/Discussion"]

    # deleting a tag drops its attachments
    user_client.delete(f"{base}/{by_name['simulator']['id']}")
    assert user_client.get(f"{base}/records/{r2}").json() == []


def test_csv_export(user_client, project):
    pid, r1 = project["pid"], project["rids"][0]
    base = f"/api/projects/{pid}/tags"
    user_client.post(f"{base}/records/{r1}",
                     json={"name": "Intro/Discussion"})
    resp = user_client.get(f"{base}/records.csv")
    assert resp.status_code == 200
    body = resp.content.decode("utf-8-sig")
    assert body.splitlines()[0] == \
        "Tags,Title,Authors,Year,Journal,DOI,Screening status"
    assert "Intro/Discussion" in body


def test_bad_inputs(user_client, project):
    pid = project["pid"]
    base = f"/api/projects/{pid}/tags"
    assert user_client.post(base, json={"name": "  "}).status_code == 400
    assert user_client.post(f"{base}/records/999999",
                            json={"name": "x"}).status_code == 404
    assert user_client.put(f"{base}/999999",
                           json={"name": "x"}).status_code == 404
