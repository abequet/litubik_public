"""Chantier 4 — Zotero integration: item ↔ record mapping, personal key and
library choice, collections, import job (records + links + PDFs) and export
job (create, then update instead of duplicate), against a fake Zotero Web
API served through an httpx.MockTransport."""
import json
import time

import httpx
import pytest

from app.services.integrations import zotero
from app.services.integrations.zotero import item_to_record, record_to_item

KEY = "abcdefghijklmnopqrstuvwx"
PDF = b"%PDF-1.4 fake"


class FakeZotero:
    """Just enough of api.zotero.org for the integration: one user library
    (write), one group (read-only), two nested collections, items with a PDF
    child, batch writes that hand out keys and honour key+version updates."""

    def __init__(self):
        self.collections = {
            "COLL0001": {"name": "Driving", "parentCollection": False, "numItems": 2},
            "COLL0002": {"name": "Simulators", "parentCollection": "COLL0001",
                         "numItems": 1},
        }
        self.items = {
            "ITEM0001": {"itemType": "journalArticle", "title": "Alpha paper",
                         "creators": [{"creatorType": "author", "firstName": "Ann",
                                       "lastName": "Doe"},
                                      {"creatorType": "editor", "name": "Ed Itor"}],
                         "date": "2019-05-01", "publicationTitle": "J. Tests",
                         "DOI": "10.5/alpha", "abstractNote": "A.",
                         "collections": ["COLL0001"], "tags": [{"tag": "keep"}]},
            "ITEM0002": {"itemType": "preprint", "title": "Beta preprint",
                         "creators": [{"creatorType": "author", "name": "Bob Roe"}],
                         "date": "March 2021", "repository": "arXiv",
                         "extra": "DOI: 10.5/beta\nsomething",
                         "abstractNote": "B.", "collections": ["COLL0001"], "tags": []},
            "ATT00001": {"itemType": "attachment", "parentItem": "ITEM0001",
                         "contentType": "application/pdf", "linkMode": "imported_file",
                         "filename": "alpha.pdf"},
        }
        self.versions = {k: 10 for k in self.items}
        self.posted: list[list[dict]] = []
        self.next_key = 100

    def _obj(self, key):
        data = {**self.items[key], "key": key, "version": self.versions[key]}
        return {"key": key, "version": self.versions[key], "data": data}

    def _top(self, keys):
        return [self._obj(k) for k in keys
                if self.items[k]["itemType"] not in ("attachment", "note")]

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        q = dict(request.url.params)
        assert request.headers.get("Zotero-API-Version") == "3"
        if path == f"/keys/{KEY}":
            return httpx.Response(200, json={
                "key": KEY, "userID": 777, "username": "reviewer",
                "access": {"user": {"library": True, "write": True, "files": True},
                           "groups": {"4242": {"library": True, "write": False}}}})
        if path.startswith("/keys/"):
            return httpx.Response(403, text="Invalid key")
        if request.headers.get("Zotero-API-Key") != KEY:
            return httpx.Response(403, text="Forbidden")
        if path == "/users/777/groups":
            return httpx.Response(200, json=[{"id": 4242, "data": {"name": "Lab group"}}],
                                  headers={"Total-Results": "1"})
        if path == "/users/777/collections" and request.method == "GET":
            rows = [{"key": k, "version": 1, "data": {"key": k, **v},
                     "meta": {"numItems": v["numItems"]}}
                    for k, v in self.collections.items()]
            return httpx.Response(200, json=rows, headers={"Total-Results": str(len(rows))})
        if path == "/users/777/collections/COLL0001/items/top":
            rows = self._top(["ITEM0001", "ITEM0002"])
            start, limit = int(q.get("start", 0)), int(q.get("limit", 100))
            return httpx.Response(200, json=rows[start:start + limit],
                                  headers={"Total-Results": str(len(rows))})
        if path == "/users/777/items/top":
            rows = self._top(list(self.items))
            return httpx.Response(200, json=rows, headers={"Total-Results": str(len(rows))})
        if path == "/users/777/items" and request.method == "GET":
            keys = q.get("itemKey", "").split(",")
            rows = [self._obj(k) for k in keys if k in self.items]
            return httpx.Response(200, json=rows, headers={"Total-Results": str(len(rows))})
        if path == "/users/777/items/ITEM0001/children":
            return httpx.Response(200, json=[self._obj("ATT00001")],
                                  headers={"Total-Results": "1"})
        if path.endswith("/children"):
            return httpx.Response(200, json=[], headers={"Total-Results": "0"})
        if path == "/users/777/items/ATT00001/file":
            return httpx.Response(302, headers={"Location": "https://files.zotero.example/a.pdf"})
        if request.url.host == "files.zotero.example":
            return httpx.Response(200, content=PDF)
        if path == "/users/777/collections" and request.method == "POST":
            body = json.loads(request.content)
            key = f"COLL{self.next_key:04d}"
            self.next_key += 1
            self.collections[key] = {"name": body[0]["name"], "parentCollection": False,
                                     "numItems": 0}
            return httpx.Response(200, json={"successful": {"0": {"key": key}},
                                             "success": {"0": key}, "failed": {}})
        if path == "/users/777/items" and request.method == "POST":
            assert request.headers.get("Zotero-Write-Token")
            body = json.loads(request.content)
            assert len(body) <= 50
            self.posted.append(body)
            successful, failed = {}, {}
            for i, obj in enumerate(body):
                if "key" in obj:
                    key = obj["key"]
                    if key not in self.items:
                        failed[str(i)] = {"code": 404, "message": "Item not found"}
                        continue
                    if obj.get("version") != self.versions[key]:
                        failed[str(i)] = {"code": 412, "message": "Version mismatch"}
                        continue
                    self.items[key] = {k: v for k, v in obj.items()
                                       if k not in ("key", "version")}
                    self.versions[key] += 1
                else:
                    key = f"ITEM{self.next_key:04d}"
                    self.next_key += 1
                    self.items[key] = dict(obj)
                    self.versions[key] = 1
                successful[str(i)] = {"key": key, "version": self.versions[key]}
            return httpx.Response(200, json={"successful": successful, "failed": failed,
                                             "unchanged": {}})
        return httpx.Response(404, text=f"no route for {request.method} {path}")


@pytest.fixture
def fake(monkeypatch):
    server = FakeZotero()
    monkeypatch.setattr(zotero, "_transport", httpx.MockTransport(server.handler))
    monkeypatch.setattr(zotero.time, "sleep", lambda s: None)
    # the redirect guard resolves hosts through DNS; the fake storage host is not real
    monkeypatch.setattr(zotero, "block_private_redirects", lambda response: None)
    return server


def _await(client, job_id):
    for _ in range(200):
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in ("done", "failed"):
            return job
        time.sleep(0.05)
    raise AssertionError("job never finished")


# ---- mapping -------------------------------------------------------------------

def test_item_to_record_mapping(fake):
    alpha = item_to_record(fake._obj("ITEM0001"))
    assert alpha["title"] == "Alpha paper"
    assert alpha["authors"] == ["Doe, Ann"]        # editors dropped when authors exist
    assert alpha["year"] == 2019 and alpha["journal"] == "J. Tests"
    assert alpha["doi"] == "10.5/alpha" and "TY  - JOUR" in alpha["raw"]
    beta = item_to_record(fake._obj("ITEM0002"))
    assert beta["doi"] == "10.5/beta"              # from the extra field
    assert beta["year"] == 2021 and beta["journal"] == "arXiv"
    assert beta["authors"] == ["Bob Roe"]


class _Rec:
    uuid = "u-1"
    title = "T"
    authors = ["Doe, Ann", "Bob Roe", "Cher"]
    year = 2020
    journal = "J"
    doi = "10.5/x"
    abstract = "A"


def test_record_to_item_create_and_update():
    item = record_to_item(_Rec(), status="included", tags=["intro"], collection_key="C1")
    assert item["itemType"] == "journalArticle" and item["collections"] == ["C1"]
    assert item["creators"][0] == {"creatorType": "author", "lastName": "Doe",
                                   "firstName": "Ann"}
    assert item["creators"][1] == {"creatorType": "author", "lastName": "Roe",
                                   "firstName": "Bob"}
    assert item["creators"][2] == {"creatorType": "author", "name": "Cher"}
    assert [t["tag"] for t in item["tags"]] == ["litubik:included", "intro"]
    assert "LitUbik: u-1" in item["extra"] and "key" not in item
    existing = {"key": "K", "version": 7, "data": {
        "itemType": "preprint", "version": 7, "collections": ["C0"],
        "tags": [{"tag": "litubik:undecided"}, {"tag": "mine"}]}}
    upd = record_to_item(_Rec(), status="excluded", tags=[], collection_key="C1",
                         existing=existing)
    assert upd["key"] == "K" and upd["version"] == 7
    assert upd["collections"] == ["C0", "C1"]
    assert [t["tag"] for t in upd["tags"]] == ["litubik:excluded", "mine"]
    assert upd["itemType"] == "preprint" and "DOI" not in upd


# ---- personal key + library -----------------------------------------------------

def test_probe_save_status_remove(user_client, fake):
    assert user_client.get("/api/integrations/zotero").json()["configured"] is False
    r = user_client.post("/api/integrations/zotero/probe", json={"api_key": "bad"})
    assert r.status_code == 400 and "permission" in r.json()["detail"]
    r = user_client.post("/api/integrations/zotero/probe", json={"api_key": KEY})
    assert r.status_code == 200, r.text
    probe = r.json()
    assert probe["username"] == "reviewer"
    assert [(l["type"], l["id"], l["write"]) for l in probe["libraries"]] == [
        ("user", 777, True), ("group", 4242, False)]
    # a library the key does not open is refused
    r = user_client.put("/api/integrations/zotero",
                        json={"api_key": KEY, "library_type": "group", "library_id": 1})
    assert r.status_code == 400
    r = user_client.put("/api/integrations/zotero",
                        json={"api_key": KEY, "library_type": "user", "library_id": 777})
    assert r.status_code == 200, r.text
    status = r.json()
    assert status["configured"] and status["library_name"] == "My library"
    assert status["write"] is True and status["username"] == "reviewer"
    # the stored key is reused when none is pasted
    assert user_client.post("/api/integrations/zotero/probe", json={}).status_code == 200
    cols = user_client.get("/api/integrations/zotero/collections").json()
    assert [(c["name"], c["depth"]) for c in cols] == [("Driving", 0), ("Simulators", 1)]
    r = user_client.put("/api/integrations/zotero",
                        json={"library_type": "group", "library_id": 4242})
    assert r.status_code == 200 and r.json()["write"] is False
    # another account sees nothing of it
    user_client.post("/api/auth/logout")
    user_client.post("/api/auth/register", json={
        "email": "other@example.com", "password": "password123", "display_name": "O"})
    assert user_client.get("/api/integrations/zotero").json()["configured"] is False
    assert user_client.get("/api/integrations/zotero/collections").status_code == 400
    user_client.post("/api/auth/logout")
    user_client.post("/api/auth/login", json={"email": "admin@example.com",
                                              "password": "password123"})
    assert user_client.delete("/api/integrations/zotero").status_code == 200
    assert user_client.get("/api/integrations/zotero").json()["configured"] is False


# ---- import ----------------------------------------------------------------------

@pytest.fixture
def project(user_client, fake):
    project = user_client.post("/api/projects", json={"name": "zotero demo"}).json()
    r = user_client.put("/api/integrations/zotero",
                        json={"api_key": KEY, "library_type": "user", "library_id": 777})
    assert r.status_code == 200, r.text
    return project


def test_import_collection_with_pdfs(user_client, fake, project):
    pid = project["id"]
    r = user_client.post(f"/api/projects/{pid}/zotero/import", json={
        "collection_key": "COLL0001", "collection_name": "Driving",
        "source_type": "database", "with_pdfs": True})
    assert r.status_code == 200, r.text
    job = _await(user_client, r.json()["job_id"])
    assert job["status"] == "done", job["error"]
    assert job["result"]["n_records"] == 2 and job["result"]["n_pdfs"] == 1
    imports = user_client.get(f"/api/projects/{pid}/imports").json()
    assert len(imports) == 1
    assert imports[0]["source_name"] == "zotero:Driving"
    assert imports[0]["source_type"] == "database" and imports[0]["n_records"] == 2
    assert imports[0]["filename"].endswith("zotero_Driving.json")
    records = user_client.get(f"/api/projects/{pid}/records").json()["items"]
    assert sorted(r["title"] for r in records) == ["Alpha paper", "Beta preprint"]
    assert {r["dedup_status"] for r in records} == {"unique"}   # dedup ran
    from app.core.db import SessionLocal
    from app.models import FullText, Record, RecordExternalLink
    with SessionLocal() as db:
        links = db.query(RecordExternalLink).all()
        assert sorted(l.external_key for l in links) == ["ITEM0001", "ITEM0002"]
        assert {l.library for l in links} == {"users/777"}
        alpha = db.query(Record).filter_by(title="Alpha paper").one()
        ft = db.query(FullText).filter_by(record_id=alpha.id).one()
        assert ft.via == "zotero" and ft.filename == "alpha.pdf"
        assert open(ft.file_path, "rb").read() == PDF


def test_import_requires_admin_and_integration(user_client, fake, project):
    pid = project["id"]
    # a reviewer member without integration: 403 before anything else
    user_client.post("/api/auth/logout")
    user_client.post("/api/auth/register", json={
        "email": "rev@example.com", "password": "password123", "display_name": "R"})
    user_client.post("/api/auth/logout")
    user_client.post("/api/auth/login", json={"email": "admin@example.com",
                                              "password": "password123"})
    user_client.post(f"/api/projects/{pid}/members",
                     json={"email": "rev@example.com", "role": "reviewer"})
    user_client.post("/api/auth/logout")
    user_client.post("/api/auth/login", json={"email": "rev@example.com",
                                              "password": "password123"})
    r = user_client.post(f"/api/projects/{pid}/zotero/import", json={})
    assert r.status_code == 403
    # export needs the member's own integration
    r = user_client.post(f"/api/projects/{pid}/zotero/export", json={"scope": "all"})
    assert r.status_code == 400 and "Connect" in r.json()["detail"]


# ---- export ----------------------------------------------------------------------

RIS = "".join(f"""TY  - JOUR
TI  - Study {i}
AU  - Doe, J{i}.
PY  - 201{i}
JO  - Journal of Exports
DO  - 10.5/exp.{i}
AB  - Abstract {i}.
ER  -
""" for i in range(1, 4))


def test_export_creates_then_updates(user_client, fake, project):
    pid = project["id"]
    user_client.post(f"/api/projects/{pid}/imports/upload",
                     files={"file": ("s.ris", RIS.encode(), "text/plain")},
                     data={"source_name": "pubmed", "source_type": "database"})
    _await(user_client, user_client.post(f"/api/projects/{pid}/dedup/run").json()["job_id"])
    records = user_client.get(f"/api/projects/{pid}/records").json()["items"]
    r = user_client.post(f"/api/projects/{pid}/tags/records/{records[0]['id']}",
                         json={"name": "intro"})
    assert r.status_code == 200, r.text

    r = user_client.post(f"/api/projects/{pid}/zotero/export", json={"scope": "all"})
    assert r.status_code == 200, r.text
    job = _await(user_client, r.json()["job_id"])
    assert job["status"] == "done", job["error"]
    res = job["result"]
    assert (res["created"], res["updated"], res["failed"]) == (3, 0, 0)
    assert res["collection_name"] == "LitUbik – zotero demo"
    coll = res["collection_key"]
    assert fake.collections[coll]["name"] == "LitUbik – zotero demo"
    sent = fake.posted[-1]
    assert len(sent) == 3 and all("key" not in it for it in sent)
    by_title = {it["title"]: it for it in sent}
    assert by_title["Study 1"]["DOI"] == "10.5/exp.1"
    assert by_title["Study 1"]["collections"] == [coll]
    assert {t["tag"] for t in by_title["Study 1"]["tags"]} >= {"litubik:undecided"}
    assert any("intro" in {t["tag"] for t in it["tags"]} for it in sent)
    assert "LitUbik decision: undecided" in by_title["Study 2"]["extra"]

    # second run, same scope: every item is updated in place, none duplicated
    n_items_before = len(fake.items)
    job = _await(user_client, user_client.post(
        f"/api/projects/{pid}/zotero/export",
        json={"scope": "all", "collection_key": coll}).json()["job_id"])
    assert job["status"] == "done", job["error"]
    assert (job["result"]["created"], job["result"]["updated"]) == (0, 3)
    assert len(fake.items) == n_items_before
    assert all("key" in it and it["version"] == 1 for it in fake.posted[-1])

    # an item deleted on the Zotero side is simply re-created
    gone = fake.posted[-1][0]["key"]
    del fake.items[gone]
    job = _await(user_client, user_client.post(
        f"/api/projects/{pid}/zotero/export",
        json={"scope": "all", "collection_key": coll}).json()["job_id"])
    assert (job["result"]["created"], job["result"]["updated"]) == (1, 2)


def test_export_needs_write_access(user_client, fake, project):
    pid = project["id"]
    r = user_client.put("/api/integrations/zotero",
                        json={"library_type": "group", "library_id": 4242})
    assert r.status_code == 200 and r.json()["write"] is False
    r = user_client.post(f"/api/projects/{pid}/zotero/export", json={"scope": "all"})
    assert r.status_code == 400 and "write access" in r.json()["detail"]
    r = user_client.post(f"/api/projects/{pid}/zotero/export", json={"scope": "nope"})
    assert r.status_code == 400
