import time

import pytest

# titles deliberately unrelated so deduplication keeps all four records
_TITLES = [
    "Gamified feedback for novice drivers on rural roads",
    "Serious games in undergraduate nursing curricula",
    "Cycling helmet legislation and head injuries",
    "Virtual reality therapy for aviation phobia",
]
RIS = "".join(f"""TY  - JOUR
TI  - {title}
AU  - Author{i}, A.
PY  - 20{10 + i * 2}
DO  - 10.5/ft.{i}
AB  - Abstract {i}.
ER  -
""" for i, title in enumerate(_TITLES, start=1))

def _pdf_bytes(text: str = "Fake article full text.") -> bytes:
    """A real one-page PDF; with text it passes the blank-PDF guard."""
    import fitz

    doc = fitz.open()
    page = doc.new_page()
    if text:
        page.insert_text((72, 72), text)
    return doc.tobytes()


PDF_BYTES = _pdf_bytes()
BLANK_PDF_BYTES = _pdf_bytes(text="")


@pytest.fixture
def project_with_records(user_client):
    project = user_client.post("/api/projects", json={"name": "M6 demo"}).json()
    pid = project["id"]
    user_client.post(f"/api/projects/{pid}/imports/upload",
                     files={"file": ("s.ris", RIS.encode(), "text/plain")},
                     data={"source_name": "pubmed", "source_type": "database"})
    job = user_client.post(f"/api/projects/{pid}/dedup/run").json()["job_id"]
    for _ in range(100):
        if user_client.get(f"/api/jobs/{job}").json()["status"] in ("done", "failed"):
            break
        time.sleep(0.05)
    return project


def test_config_roundtrip_encrypts_password(user_client, project_with_records):
    pid = project_with_records["id"]
    r = user_client.put(f"/api/projects/{pid}/fulltext/config", json={
        "unpaywall_email": "me@lab.org",
        "institutions": [{"name": "MyUni", "ezproxy_url": "https://ezp.uni.edu/login",
                          "username": "user1", "password": "secret", "scope": "",
                          "auth_type": ""}]})
    assert r.status_code == 200
    body = r.json()
    assert body["unpaywall_email"] == "me@lab.org"
    assert body["institutions"][0]["has_password"] is True
    assert "secret" not in str(body)  # password never returned

    # the stored config decrypts the password for retrieval
    from app.core.db import SessionLocal
    from app.services.fulltext.service import resolve_config
    with SessionLocal() as db:
        cfg = resolve_config(db, pid)
    assert cfg["email"] == "me@lab.org"
    assert cfg["institutions"][0]["password"] == "secret"

    # updating without a password keeps the stored one
    user_client.put(f"/api/projects/{pid}/fulltext/config", json={
        "unpaywall_email": "me2@lab.org",
        "institutions": [{"name": "MyUni", "ezproxy_url": "https://ezp.uni.edu/login",
                          "username": "user1", "password": "", "scope": "",
                          "auth_type": ""}]})
    with SessionLocal() as db:
        cfg = resolve_config(db, pid)
    assert cfg["institutions"][0]["password"] == "secret"


def test_retrieve_job_writes_pdf_and_feeds_prisma(user_client, project_with_records,
                                                  monkeypatch):
    pid = project_with_records["id"]
    records = user_client.get(f"/api/projects/{pid}/records").json()["items"]
    ids = sorted(r["id"] for r in records)

    # deterministic fake: even records succeed, odd records fail
    def fake_process_doi(doi, email, institutions=None,
                         use_extensions=True):
        n = int(doi.rsplit(".", 1)[-1])
        if n % 2 == 0:
            return ({"source": "unpaywall", "filename": f"paper{n}.pdf",
                     "title": "T", "oa_url": ""}, PDF_BYTES)
        return ({"source": None, "filename": None, "title": "T",
                 "oa_url": "https://publisher/landing"}, None)

    # retrieve_one imports process_doi lazily from the downloader module
    monkeypatch.setattr("app.services.fulltext.downloader.process_doi",
                        fake_process_doi)

    r = user_client.post(f"/api/projects/{pid}/fulltext/retrieve", json={})
    assert r.status_code == 200
    job_id = r.json()["job_id"]
    for _ in range(200):
        job = user_client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in ("done", "failed"):
            break
        time.sleep(0.05)
    assert job["status"] == "done", job.get("error")
    assert job["result"]["retrieved"] == 2
    assert job["result"]["not_found"] == 2

    rows = user_client.get(f"/api/projects/{pid}/fulltext").json()
    by_id = {r["record_id"]: r for r in rows}
    even = [i for i in ids if int(by_id[i]["doi"].rsplit(".", 1)[-1]) % 2 == 0]
    assert all(by_id[i]["status"] == "retrieved" and by_id[i]["has_file"]
               for i in even)
    odd = [i for i in ids if i not in even]
    assert all(by_id[i]["status"] == "not_found" for i in odd)
    assert by_id[odd[0]]["oa_url"] == "https://publisher/landing"

    # serve the stored PDF (inline)
    r = user_client.get(f"/api/projects/{pid}/fulltext/records/{even[0]}/file")
    assert r.status_code == 200
    assert r.content.startswith(b"%PDF")
    assert "inline" in r.headers["content-disposition"]

    summary = user_client.get(f"/api/projects/{pid}/fulltext/summary").json()
    assert summary == {"eligible": 4, "retrieved": 2, "not_found": 2, "pending": 0}

    prisma = user_client.get(f"/api/projects/{pid}/prisma").json()
    # no T/A screening here -> included set is empty -> retrieval not shown in PRISMA
    assert prisma["reports_not_retrieved"] is None


def test_blank_pdf_discarded(user_client, project_with_records, monkeypatch):
    pid = project_with_records["id"]

    def fake_process_doi(doi, email, institutions=None,
                         use_extensions=True):
        return ({"source": "institution (X)", "filename": "blank.pdf",
                 "title": "T", "oa_url": ""}, BLANK_PDF_BYTES)

    monkeypatch.setattr("app.services.fulltext.downloader.process_doi",
                        fake_process_doi)

    r = user_client.post(f"/api/projects/{pid}/fulltext/retrieve", json={})
    job_id = r.json()["job_id"]
    for _ in range(200):
        job = user_client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in ("done", "failed"):
            break
        time.sleep(0.05)
    assert job["status"] == "done", job.get("error")
    assert job["result"]["retrieved"] == 0
    assert job["result"]["not_found"] == 4

    rows = user_client.get(f"/api/projects/{pid}/fulltext").json()
    assert all(row["status"] == "not_found" and not row["has_file"]
               for row in rows)
    assert "Blank/empty PDF discarded" in rows[0]["error"]


def test_manual_upload_and_delete(user_client, project_with_records):
    pid = project_with_records["id"]
    rid = user_client.get(f"/api/projects/{pid}/records").json()["items"][0]["id"]

    # reject a non-PDF
    r = user_client.post(f"/api/projects/{pid}/fulltext/records/{rid}/upload",
                         files={"file": ("x.pdf", b"not a pdf", "application/pdf")})
    assert r.status_code == 400

    r = user_client.post(f"/api/projects/{pid}/fulltext/records/{rid}/upload",
                         files={"file": ("mine.pdf", PDF_BYTES, "application/pdf")})
    assert r.status_code == 200
    assert r.json()["status"] == "manual" and r.json()["via"] == "upload"

    r = user_client.get(f"/api/projects/{pid}/fulltext/records/{rid}/file")
    assert r.status_code == 200 and r.content.startswith(b"%PDF")

    r = user_client.delete(f"/api/projects/{pid}/fulltext/records/{rid}")
    assert r.status_code == 200
    assert user_client.get(
        f"/api/projects/{pid}/fulltext/records/{rid}/file").status_code == 404


def test_export_filename_follows_the_author_year_title_convention():
    """Filing convention: first author, year, five first title words."""
    from types import SimpleNamespace

    from app.services.fulltext.service import export_filename

    def rec(authors, year, title):
        return SimpleNamespace(authors=authors, year=year, title=title)

    assert export_filename(rec(["Dupont, Jean"], 2019,
                               "Éco-conduite: a review of the state of the art")) \
        == "Dupont_2019_Eco_conduite_a_review_of.pdf"
    # 'Given Family' and 'Family Initials' both yield the family name
    assert export_filename(rec(["Jean Dupont"], 2019, "A B C")).startswith("Dupont_")
    assert export_filename(rec(["Dupont J"], 2019, "A B C")).startswith("Dupont_")
    # missing metadata still produces a usable name
    assert export_filename(rec([], None, "")) == "anonymous_ND_untitled.pdf"
    # two papers that collide are suffixed, never silently overwritten
    taken: set[str] = set()
    same = rec(["Dupont, Jean"], 2019, "Same five opening words, other subtitle")
    assert export_filename(same, taken) == "Dupont_2019_Same_five_opening_words_other.pdf"
    assert export_filename(same, taken) == "Dupont_2019_Same_five_opening_words_other_2.pdf"


def test_download_zip_bundles_the_selection(user_client, project_with_records):
    import io
    import zipfile

    pid = project_with_records["id"]
    records = user_client.get(f"/api/projects/{pid}/records").json()["items"]
    ids = sorted(r["id"] for r in records)
    for rid in ids[:2]:
        user_client.post(f"/api/projects/{pid}/fulltext/records/{rid}/upload",
                         files={"file": ("mine.pdf", PDF_BYTES, "application/pdf")})

    # no selection = the whole library
    r = user_client.get(f"/api/projects/{pid}/fulltext/download-zip")
    assert r.status_code == 200
    assert "attachment" in r.headers["content-disposition"]
    names = zipfile.ZipFile(io.BytesIO(r.content)).namelist()
    assert len(names) == 2
    assert all(n.startswith("Author") and n.endswith(".pdf") for n in names), names

    # an explicit selection only carries what was ticked
    r = user_client.get(f"/api/projects/{pid}/fulltext/download-zip",
                        params={"ids": str(ids[0])})
    archive = zipfile.ZipFile(io.BytesIO(r.content))
    assert len(archive.namelist()) == 1
    assert archive.read(archive.namelist()[0]).startswith(b"%PDF")

    # a selection without any stored PDF is a 404, not an empty zip
    assert user_client.get(f"/api/projects/{pid}/fulltext/download-zip",
                           params={"ids": str(ids[3])}).status_code == 404
    assert user_client.get(f"/api/projects/{pid}/fulltext/download-zip",
                           params={"ids": "abc"}).status_code == 400

    # a non-member cannot pull the library
    user_client.post("/api/auth/register", json={
        "email": "outsider-zip@example.com", "password": "password123",
        "display_name": "O"})
    assert user_client.get(
        f"/api/projects/{pid}/fulltext/download-zip").status_code == 403


def test_global_institutions_and_email_fallback(user_client, project_with_records):
    pid = project_with_records["id"]
    from app.core.db import SessionLocal
    from app.services.fulltext.service import resolve_config, seed_global_institutions

    with SessionLocal() as db:
        seed_global_institutions(db, [
            {"name": "Toulouse 2", "ezproxy_url": "https://gorgone/login?url=$@",
             "username": "u1", "password": "toulousepwd", "scope": "ut2"}])

    # global institution is inherited (read-only) in the project config view
    cfg = user_client.get(f"/api/projects/{pid}/fulltext/config").json()
    assert cfg["default_email"] == "admin@example.com"  # login email
    assert [i["name"] for i in cfg["inherited_institutions"]] == ["Toulouse 2"]
    assert cfg["inherited_institutions"][0]["has_password"] is True

    # a project-specific institution is merged AFTER the global ones
    user_client.put(f"/api/projects/{pid}/fulltext/config", json={
        "unpaywall_email": "",
        "institutions": [{"name": "Local", "ezproxy_url": "https://x/login",
                          "username": "u2", "password": "p2", "scope": "",
                          "auth_type": ""}]})
    with SessionLocal() as db:
        resolved = resolve_config(db, pid, fallback_email="login@lab.org")
    assert [i["name"] for i in resolved["institutions"]] == ["Toulouse 2", "Local"]
    assert resolved["institutions"][0]["password"] == "toulousepwd"
    # no email set anywhere -> falls back to the login email
    assert resolved["email"] == "login@lab.org"


def test_reviewer_can_retrieve_but_not_configure(user_client, project_with_records):
    """M4b: any member launches retrieval (with their own browser-held
    credentials if they wish); project retrieval *settings* stay admin-only."""
    pid = project_with_records["id"]
    user_client.post("/api/auth/register", json={
        "email": "rev6@example.com", "password": "password123", "display_name": "R"})
    user_client.post("/api/auth/login", json={
        "email": "admin@example.com", "password": "password123"})
    user_client.post(f"/api/projects/{pid}/members",
                     json={"email": "rev6@example.com", "role": "reviewer"})
    user_client.post("/api/auth/login", json={
        "email": "rev6@example.com", "password": "password123"})
    assert user_client.get(f"/api/projects/{pid}/fulltext").status_code == 200
    assert user_client.get(f"/api/projects/{pid}/fulltext/config").status_code == 403
    assert user_client.post(f"/api/projects/{pid}/fulltext/retrieve",
                            json={}).status_code == 200
    # a non-member still cannot launch retrieval
    user_client.post("/api/auth/register", json={
        "email": "outsider6@example.com", "password": "password123",
        "display_name": "O"})
    assert user_client.post(f"/api/projects/{pid}/fulltext/retrieve",
                            json={}).status_code == 403


def test_app_wide_institutions_editable_by_the_app_admin(user_client,
                                                         project_with_records):
    """The global institutions were visible (read-only) from a project but had
    no screen of their own — this is that screen's API."""
    pid = project_with_records["id"]
    assert user_client.get("/api/fulltext/institutions").json() == []

    r = user_client.put("/api/fulltext/institutions", json={"institutions": [
        {"name": "Toulouse 2", "ezproxy_url": "https://gorgone/login?url=$@",
         "username": "u1", "password": "toulousepwd", "scope": "ut2",
         "auth_type": ""},
        {"name": "", "ezproxy_url": "", "username": "", "password": "",
         "scope": "", "auth_type": ""}]})  # empty form row is dropped
    assert r.status_code == 200
    assert [i["name"] for i in r.json()] == ["Toulouse 2"]
    assert r.json()[0]["has_password"] is True and "password" not in r.json()[0]

    # every project inherits them, and the retrieval config resolves the password
    cfg = user_client.get(f"/api/projects/{pid}/fulltext/config").json()
    assert [i["name"] for i in cfg["inherited_institutions"]] == ["Toulouse 2"]
    from app.core.db import SessionLocal
    from app.services.fulltext.service import resolve_config
    with SessionLocal() as db:
        resolved = resolve_config(db, pid, fallback_email="l@lab.org")
    assert resolved["institutions"][0]["password"] == "toulousepwd"

    # saving again without a password keeps the stored one
    user_client.put("/api/fulltext/institutions", json={"institutions": [
        {"name": "Toulouse 2", "ezproxy_url": "https://gorgone/login?url=$@",
         "username": "u1", "password": "", "scope": "ut2", "auth_type": ""}]})
    with SessionLocal() as db:
        resolved = resolve_config(db, pid, fallback_email="l@lab.org")
    assert resolved["institutions"][0]["password"] == "toulousepwd"

    # SSRF guard applies here as it does on the project form
    assert user_client.put("/api/fulltext/institutions", json={"institutions": [
        {"name": "Bad", "ezproxy_url": "http://169.254.169.254/latest",
         "username": "", "password": "", "scope": "",
         "auth_type": ""}]}).status_code == 400

    # a plain user cannot read or write the app-wide list
    user_client.post("/api/auth/register", json={
        "email": "plain-inst@example.com", "password": "password123",
        "display_name": "Plain"})
    assert user_client.get("/api/fulltext/institutions").status_code == 403
    assert user_client.put("/api/fulltext/institutions",
                           json={"institutions": []}).status_code == 403


def test_retrieve_ignores_record_ids_of_another_project(user_client,
                                                        project_with_records,
                                                        monkeypatch):
    """The record ids come from the client: a member of one project must not
    rewrite another project's full texts, nor read their titles in the job's
    progress stream, by listing that project's record ids."""
    victim_pid = project_with_records["id"]
    victim_ids = [r["id"] for r in user_client.get(
        f"/api/projects/{victim_pid}/records").json()["items"]]
    calls = []

    def fake_process_doi(doi, email, institutions=None, use_extensions=True):
        calls.append(doi)
        return ({"source": None, "filename": None, "title": "T",
                 "oa_url": ""}, None)

    monkeypatch.setattr("app.services.fulltext.downloader.process_doi",
                        fake_process_doi)
    user_client.post("/api/auth/register", json={
        "email": "intruder@example.com", "password": "password123",
        "display_name": "I"})
    user_client.post("/api/auth/login", json={
        "email": "intruder@example.com", "password": "password123"})
    own_pid = user_client.post("/api/projects", json={"name": "Mine"}).json()["id"]

    r = user_client.post(f"/api/projects/{own_pid}/fulltext/retrieve",
                         json={"record_ids": victim_ids, "force": True})
    assert r.status_code == 200
    job_id = r.json()["job_id"]
    for _ in range(200):
        job = user_client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in ("done", "failed"):
            break
        time.sleep(0.05)
    assert job["status"] == "done", job.get("error")
    assert calls == []
    assert job["result"]["retrieved"] == 0 and job["result"]["not_found"] == 0
    assert not any(title in str(job) for title in _TITLES)

    user_client.post("/api/auth/login", json={
        "email": "admin@example.com", "password": "password123"})
    rows = user_client.get(f"/api/projects/{victim_pid}/fulltext").json()
    assert all(row["status"] not in ("retrieved", "not_found") for row in rows)
