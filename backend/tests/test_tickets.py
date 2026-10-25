"""Support tickets: creation, visibility (own vs admin), status transitions,
comments."""


def _login(client, email):
    client.post("/api/auth/login", json={"email": email, "password": "password123"})


def test_ticket_lifecycle(user_client):
    # a second, non-admin user (the first registered account is the app admin)
    user_client.post("/api/auth/register", json={
        "email": "rev@example.com", "password": "password123",
        "display_name": "Reviewer"})

    # reviewer reports a bug from a project page
    r = user_client.post("/api/tickets", json={
        "title": "Graph won't zoom", "body": "Wheel does nothing on Firefox",
        "kind": "bug", "severity": "major", "page": "/projects/1/snowballing"})
    assert r.status_code == 200
    ticket = r.json()
    assert ticket["status"] == "open" and ticket["author"] == "Reviewer"

    # reviewer sees their ticket, cannot move it to in_progress, can close it
    mine = user_client.get("/api/tickets").json()
    assert [t["id"] for t in mine] == [ticket["id"]]
    r = user_client.put(f"/api/tickets/{ticket['id']}/status",
                        json={"status": "in_progress"})
    assert r.status_code == 403
    assert user_client.get("/api/tickets/summary").json() == {"open": 1}

    # reviewer comments
    r = user_client.post(f"/api/tickets/{ticket['id']}/comments",
                         json={"body": "Happens on the included-only view too"})
    assert r.status_code == 200

    # admin sees it, triages it, replies
    _login(user_client, "admin@example.com")
    all_tickets = user_client.get("/api/tickets").json()
    assert [t["id"] for t in all_tickets] == [ticket["id"]]
    assert all_tickets[0]["n_comments"] == 1
    r = user_client.put(f"/api/tickets/{ticket['id']}/status",
                        json={"status": "in_progress"})
    assert r.status_code == 200
    user_client.post(f"/api/tickets/{ticket['id']}/comments",
                     json={"body": "Reproduced, fixing"})
    r = user_client.put(f"/api/tickets/{ticket['id']}/status",
                        json={"status": "resolved"})
    assert r.status_code == 200

    detail = user_client.get(f"/api/tickets/{ticket['id']}").json()
    assert detail["status"] == "resolved"
    assert [c["author"] for c in detail["comments"]] == ["Reviewer", "Admin"]
    assert user_client.get("/api/tickets/summary").json() == {"open": 0}


def test_ticket_export_admin_only(user_client):
    user_client.post("/api/auth/register", json={
        "email": "rev@example.com", "password": "password123",
        "display_name": "Reviewer"})
    user_client.post("/api/tickets", json={
        "title": "Graph won't zoom", "kind": "bug", "severity": "major"})
    ticket_id = user_client.get("/api/tickets").json()[0]["id"]
    user_client.post(f"/api/tickets/{ticket_id}/comments",
                     json={"body": "Happens on Firefox"})

    # non-admin: forbidden
    assert user_client.get("/api/tickets/export.csv").status_code == 403

    _login(user_client, "admin@example.com")
    r = user_client.get("/api/tickets/export.csv")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    body = r.content.decode("utf-8-sig")
    assert "Graph won't zoom" in body
    assert "Happens on Firefox" in body
    # status filter applies
    r = user_client.get("/api/tickets/export.csv?status=closed")
    assert "Graph won't zoom" not in r.content.decode("utf-8-sig")


def test_ticket_privacy(user_client):
    # admin files a ticket
    user_client.post("/api/tickets", json={"title": "Admin note", "kind": "feedback"})
    # another user must not see it, nor open it by id
    user_client.post("/api/auth/register", json={
        "email": "other@example.com", "password": "password123",
        "display_name": "Other"})
    assert user_client.get("/api/tickets").json() == []
    ticket_id = 1
    assert user_client.get(f"/api/tickets/{ticket_id}").status_code == 404
    assert user_client.post(f"/api/tickets/{ticket_id}/comments",
                            json={"body": "hi"}).status_code == 404
