import io
import time
import zipfile

from tests.test_fulltext import PDF_BYTES


def _fake_process_doi(doi, email, institutions=None,
                      use_extensions=True):
    if doi.endswith("missing"):
        return ({"source": None, "filename": None, "title": "Lost paper",
                 "oa_url": "https://publisher/landing",
                 "error": "Aucun PDF trouvé"}, None)
    # same author/year/title on purpose: the names must not collide
    return ({"source": "unpaywall", "filename": "Dupont_2020_A_study_of.pdf",
             "title": "A study of things", "oa_url": ""}, PDF_BYTES)


def _run(client, text):
    r = client.post("/api/paper-download", json={"text": text})
    assert r.status_code == 200, r.text
    job_id = r.json()["job_id"]
    for _ in range(200):
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in ("done", "failed"):
            break
        time.sleep(0.05)
    assert job["status"] == "done", job.get("error")
    return job


def test_parse_dois():
    from app.services.fulltext.standalone import parse_dois
    text = ("https://doi.org/10.1000/abc.1, doi:10.1000/ABC.1\n"
            "10.2000/xyz(2).  see (10.3000/k-9); nothing here")
    assert parse_dois(text) == ["10.1000/abc.1", "10.2000/xyz(2)", "10.3000/k-9"]


def test_single_doi_serves_the_pdf(user_client, monkeypatch):
    monkeypatch.setattr("app.services.fulltext.downloader.process_doi",
                        _fake_process_doi)
    job = _run(user_client, "10.1000/one")
    assert job["result"]["retrieved"] == 1
    r = user_client.get(f"/api/paper-download/{job['id']}/file")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/pdf"
    assert "Dupont_2020_A_study_of.pdf" in r.headers["content-disposition"]
    assert r.content.startswith(b"%PDF")


def test_several_dois_serve_a_zip(user_client, monkeypatch):
    monkeypatch.setattr("app.services.fulltext.downloader.process_doi",
                        _fake_process_doi)
    job = _run(user_client, "10.1000/one\n10.1000/two\n10.1000/missing")
    result = job["result"]
    assert (result["retrieved"], result["not_found"]) == (2, 1)
    assert [i["doi"] for i in result["items"]] == [
        "10.1000/one", "10.1000/two", "10.1000/missing"]
    assert result["items"][2]["oa_url"] == "https://publisher/landing"

    r = user_client.get(f"/api/paper-download/{job['id']}/file")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/zip"
    names = sorted(zipfile.ZipFile(io.BytesIO(r.content)).namelist())
    assert names == ["Dupont_2020_A_study_of.pdf", "Dupont_2020_A_study_of_2.pdf"]


def test_module_is_granted_per_user_and_rate_limited(user_client, monkeypatch):
    from fastapi.testclient import TestClient

    from app.main import app
    monkeypatch.setattr("app.services.fulltext.downloader.process_doi",
                        _fake_process_doi)
    # no `with`: a second lifespan would swap the job runner's event loop
    other = TestClient(app)
    me = other.post("/api/auth/register", json={
        "email": "reviewer@example.com", "password": "password123",
        "display_name": "Reviewer"}).json()
    assert me["can_download_papers"] is False
    # not ticked by the superadmin: the module is closed
    assert other.post("/api/paper-download",
                      json={"text": "10.1000/one"}).status_code == 403
    assert other.get("/api/paper-download/quota").status_code == 403
    # and only the superadmin manages the grant
    assert other.get("/api/admin/users").status_code == 403
    assert other.patch(f"/api/admin/users/{me['id']}",
                       json={"can_download_papers": True}).status_code == 403

    users = user_client.get("/api/admin/users").json()
    assert {u["email"] for u in users} == {"admin@example.com",
                                          "reviewer@example.com"}
    r = user_client.patch(f"/api/admin/users/{me['id']}",
                          json={"can_download_papers": True})
    assert r.status_code == 200 and r.json()["can_download_papers"] is True
    assert other.get("/api/auth/me").json()["can_download_papers"] is True

    # 5 papers per sliding hour: 6 at once is refused outright…
    six = "\n".join(f"10.1000/p{i}" for i in range(6))
    assert other.post("/api/paper-download",
                      json={"text": six}).status_code == 429
    # …4 pass, a miss is not charged, then only 1 is left
    job = _run(other, "\n".join(f"10.1000/p{i}" for i in range(4))
               + "\n10.1000/missing")
    assert job["result"]["retrieved"] == 4
    quota = other.get("/api/paper-download/quota").json()
    assert (quota["limit"], quota["used"], quota["remaining"]) == (5, 4, 1)
    assert quota["resets_at"]
    assert other.post("/api/paper-download",
                      json={"text": "10.1000/a 10.1000/b"}).status_code == 429
    _run(other, "10.1000/a")
    assert other.get("/api/paper-download/quota").json()["remaining"] == 0

    # another user's files stay out of reach, even for a granted account
    assert user_client.get(
        f"/api/paper-download/{job['id']}/file").status_code == 404

    # the superadmin has no limit
    assert user_client.get("/api/paper-download/quota").json()["limit"] is None
    ten = "\n".join(f"10.1000/q{i}" for i in range(10))
    assert _run(user_client, ten)["result"]["retrieved"] == 10


def test_no_doi_is_rejected(user_client):
    r = user_client.post("/api/paper-download", json={"text": "nothing useful"})
    assert r.status_code == 400


def test_superadmin_sees_downloads_per_user(user_client, monkeypatch):
    from fastapi.testclient import TestClient

    from app.main import app
    monkeypatch.setattr("app.services.fulltext.downloader.process_doi",
                        _fake_process_doi)
    other = TestClient(app)
    me = other.post("/api/auth/register", json={
        "email": "reader@example.com", "password": "password123",
        "display_name": "Reader"}).json()
    user_client.patch(f"/api/admin/users/{me['id']}",
                      json={"can_download_papers": True})
    _run(other, "10.1000/one\n10.1000/missing")
    _run(other, "10.1000/two")
    _run(user_client, "10.1000/three")

    # the record is the superadmin's alone
    assert other.get("/api/admin/users/paper-downloads").status_code == 403
    assert other.get(
        f"/api/admin/users/paper-downloads/{me['id']}").status_code == 403

    rows = user_client.get("/api/admin/users/paper-downloads").json()
    by_email = {r["email"]: r for r in rows}
    reader = by_email["reader@example.com"]
    assert (reader["runs"], reader["requested"], reader["retrieved"]) == (2, 3, 2)
    assert reader["last_at"]
    admin = by_email["admin@example.com"]
    assert (admin["runs"], admin["retrieved"], admin["is_admin"]) == (1, 1, True)

    runs = user_client.get(
        f"/api/admin/users/paper-downloads/{me['id']}").json()
    assert [r["requested"] for r in runs] == [1, 2]  # most recent first
    items = runs[1]["items"]
    assert [(i["doi"], i["status"]) for i in items] == [
        ("10.1000/one", "retrieved"), ("10.1000/missing", "not_found")]
    assert items[0]["via"] == "unpaywall"
    assert items[0]["filename"] == "Dupont_2020_A_study_of.pdf"
