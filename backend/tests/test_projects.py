def test_create_and_list_projects(user_client):
    r = user_client.post("/api/projects", json={
        "name": "My Review", "description": "Test project"})
    assert r.status_code == 200
    assert r.json()["my_role"] == "admin"

    r = user_client.get("/api/projects")
    assert r.status_code == 200
    assert len(r.json()) == 1
    assert r.json()[0]["name"] == "My Review"


def test_members_flow(user_client):
    project_id = user_client.post("/api/projects", json={"name": "P"}).json()["id"]

    # unknown email -> awaiting-registration account, member right away
    r = user_client.post(f"/api/projects/{project_id}/members", json={
        "email": "reviewer@example.com", "role": "reviewer"})
    assert r.status_code == 200
    assert r.json()["status"] == "awaiting"
    assert r.json()["user_id"] is not None

    members = user_client.get(f"/api/projects/{project_id}/members").json()
    assert {m["email"] for m in members} == {"admin@example.com", "reviewer@example.com"}
    assert {m["status"] for m in members} == {"member", "awaiting"}

    # registering with that email claims the account (chosen display name)
    user_client.post("/api/auth/logout")
    user_client.cookies.clear()
    r = user_client.post("/api/auth/register", json={
        "email": "reviewer@example.com", "password": "password123",
        "display_name": "Rev"})
    assert r.status_code == 200
    reviewer_cookies = dict(user_client.cookies)

    user_client.cookies.clear()
    user_client.post("/api/auth/login", json={
        "email": "admin@example.com", "password": "password123"})
    members = user_client.get(f"/api/projects/{project_id}/members").json()
    rev = next(m for m in members if m["email"] == "reviewer@example.com")
    assert rev["status"] == "member" and rev["display_name"] == "Rev"

    # reviewer cannot add members (not project admin)
    user_client.cookies.clear()
    user_client.cookies.update(reviewer_cookies)
    r = user_client.post(f"/api/projects/{project_id}/members", json={
        "email": "admin@example.com", "role": "admin"})
    assert r.status_code == 403


def test_awaiting_member_usable_as_screening_reviewer(user_client):
    """An awaiting-registration colleague can be configured as a reviewer and
    receive assignments BEFORE registering — that unblocks preparing the round
    and exporting the project snapshot ahead of their first login."""
    pid = user_client.post("/api/projects", json={"name": "P"}).json()["id"]
    r = user_client.post(f"/api/projects/{pid}/members", json={
        "email": "bob@remote.org", "role": "reviewer"})
    bob_id = r.json()["user_id"]

    ris = b"TY  - JOUR\nTI  - A study\nDO  - 10.1/x\nER  -\n"
    user_client.post(f"/api/projects/{pid}/imports/upload",
                     files={"file": ("s.ris", ris, "text/plain")},
                     data={"source_name": "pubmed", "source_type": "database"})
    user_client.post(f"/api/projects/{pid}/dedup/run")

    info = user_client.get(f"/api/projects/{pid}/screening/config").json()
    bob = next(m for m in info["members"] if m["user_id"] == bob_id)
    assert bob["registered"] is False

    r = user_client.put(f"/api/projects/{pid}/screening/config", json={
        "n_reviewers": 2, "decision_rule": "all", "maybe_policy": "conflict",
        "allocation": "all", "overlap_pct": 20,
        "conflict_resolution": "consensus", "ai_enabled": False,
        "ai_mode": "suggestion", "reviewer_ids": [1, bob_id]})
    assert r.status_code == 200, r.text
    r = user_client.post(f"/api/projects/{pid}/screening/start")
    assert r.status_code == 200, r.text

    # bob registers afterwards and can vote on his queue immediately
    user_client.post("/api/auth/logout")
    user_client.cookies.clear()
    user_client.post("/api/auth/register", json={
        "email": "bob@remote.org", "password": "password123",
        "display_name": "Bobby"})
    queue = user_client.get(
        f"/api/projects/{pid}/screening/queue").json()
    assert queue["total"] == 1
    r = user_client.post(f"/api/projects/{pid}/screening/vote", json={
        "record_id": queue["items"][0]["id"], "decision": "include",
        "reasons": [], "justification": ""})
    assert r.status_code == 200, r.text


def test_unauthenticated_gets_401(client):
    assert client.get("/api/projects").status_code == 401


def test_delete_project_cascades(user_client):
    pid = user_client.post("/api/projects", json={"name": "To delete"}).json()["id"]
    # add data that references the project (records via an import)
    ris = b"TY  - JOUR\nTI  - A study\nDO  - 10.1/x\nER  -\n"
    user_client.post(f"/api/projects/{pid}/imports/upload",
                     files={"file": ("s.ris", ris, "text/plain")},
                     data={"source_name": "pubmed", "source_type": "database"})
    assert user_client.get(f"/api/projects/{pid}/records").json()["total"] == 1

    r = user_client.delete(f"/api/projects/{pid}")
    assert r.status_code == 200
    assert user_client.get("/api/projects").json() == []
    # child rows are gone with the project (cascade) -> project 404 now
    assert user_client.get(f"/api/projects/{pid}/records").status_code == 404


def test_archive_restore_and_permanent_delete(user_client):
    pid = user_client.post("/api/projects", json={"name": "Archivable"}).json()["id"]

    # archive -> hidden from the active list, shown in the archive
    assert user_client.post(f"/api/projects/{pid}/archive").status_code == 200
    assert user_client.get("/api/projects").json() == []
    archived = user_client.get("/api/projects?archived=true").json()
    assert [p["id"] for p in archived] == [pid]
    assert archived[0]["archived_at"] is not None

    # restore -> back in the active list
    assert user_client.post(f"/api/projects/{pid}/unarchive").status_code == 200
    assert [p["id"] for p in user_client.get("/api/projects").json()] == [pid]
    assert user_client.get("/api/projects?archived=true").json() == []

    # permanent delete works from either state
    user_client.post(f"/api/projects/{pid}/archive")
    assert user_client.delete(f"/api/projects/{pid}").status_code == 200
    assert user_client.get("/api/projects?archived=true").json() == []


def test_reviewer_cannot_delete_project(user_client):
    pid = user_client.post("/api/projects", json={"name": "P"}).json()["id"]
    user_client.post("/api/auth/register", json={
        "email": "rev2@example.com", "password": "password123",
        "display_name": "Rev2"})
    user_client.post("/api/auth/login", json={
        "email": "admin@example.com", "password": "password123"})
    user_client.post(f"/api/projects/{pid}/members",
                     json={"email": "rev2@example.com", "role": "reviewer"})
    user_client.post("/api/auth/login", json={
        "email": "rev2@example.com", "password": "password123"})
    assert user_client.delete(f"/api/projects/{pid}").status_code == 403
