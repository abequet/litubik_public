"""M7 — full-text screening: eligibility, mandatory exclusion reasons, per-reason
PRISMA counts, conflict resolution reasons, and shared PDF annotations."""
import time

import pytest

_TITLES = [
    "Gamified speed feedback for young drivers",
    "Serious games in nursing education outcomes",
    "Cycling safety interventions in dense cities",
    "Virtual reality exposure for driving anxiety",
    "Reward schedules and pedestrian attention",
    "Motivation design of fitness applications",
]
RIS = "".join(f"""TY  - JOUR
TI  - {title}
AU  - Author{i}, A.
PY  - 20{10 + i}
DO  - 10.1/ft.{i}
AB  - Abstract of study {i} on gamification and driving.
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
def ft_project(user_client, team):
    """A project taken through dedup + a validated E1/E2 protocol + T/A screening
    with 5 unanimous includes, then a started FT screening. Returns ids."""
    pid = user_client.post("/api/projects", json={"name": "M7 demo"}).json()["id"]
    user_client.post(f"/api/projects/{pid}/members",
                     json={"email": "rev@example.com", "role": "reviewer"})
    user_client.post(f"/api/projects/{pid}/imports/upload",
                     files={"file": ("s.ris", RIS.encode(), "text/plain")},
                     data={"source_name": "pubmed", "source_type": "database"})
    _await_job(user_client, user_client.post(
        f"/api/projects/{pid}/dedup/run").json()["job_id"])

    # validated protocol with two exclusion criteria (the reason catalogue)
    user_client.post(f"/api/projects/{pid}/protocols/upload",
                     files={"file": ("p.md", b"# P\n\nText", "text/markdown")})
    prot = user_client.get(f"/api/projects/{pid}/protocols").json()[0]
    user_client.put(f"/api/projects/{pid}/protocols/{prot['id']}", json={
        "protocol_md": "# P", "criteria": [
            {"code": "E1", "type": "exclude", "label": "wrong population",
             "description": ""},
            {"code": "E2", "type": "exclude", "label": "not empirical",
             "description": ""}]})
    user_client.post(f"/api/projects/{pid}/protocols/{prot['id']}/validate")

    # T/A screening: 5 unanimous includes (records 0..4), record 5 excluded
    reviewers = [team["admin"]["id"], team["reviewer"]["id"]]
    user_client.put(f"/api/projects/{pid}/screening/config", json={
        "stage": "ta", "allocation": "all", "conflict_resolution": "consensus",
        "reviewer_ids": reviewers})
    user_client.post(f"/api/projects/{pid}/screening/start")
    ta_ids = [i["id"] for i in user_client.get(
        f"/api/projects/{pid}/screening/queue?limit=10").json()["items"]]
    for who in ("admin", "reviewer"):
        _login(user_client, who)
        for idx, rid in enumerate(ta_ids):
            decision = "include" if idx < 5 else "exclude"
            user_client.post(f"/api/projects/{pid}/screening/vote",
                             json={"record_id": rid, "decision": decision})
    _login(user_client, "admin")
    return {"pid": pid, "ta_ids": ta_ids, "included": ta_ids[:5],
            "reviewers": reviewers}


def _start_ft(client, pid, reviewers, **overrides):
    payload = {"stage": "ft", "allocation": "all",
               "conflict_resolution": "consensus", "reviewer_ids": reviewers,
               **overrides}
    r = client.put(f"/api/projects/{pid}/screening/config", json=payload)
    assert r.status_code == 200, r.text
    r = client.post(f"/api/projects/{pid}/screening/start?stage=ft")
    assert r.status_code == 200, r.text
    return r.json()


# ---- eligibility --------------------------------------------------------------

def test_ft_eligibility_is_ta_includes(user_client, ft_project):
    pid = ft_project["pid"]
    info = user_client.get(f"/api/projects/{pid}/screening/config?stage=ft").json()
    assert info["eligible_records"] == 5  # the 5 T/A includes, not all 6
    summary = _start_ft(user_client, pid, ft_project["reviewers"])
    assert summary["records"] == 5
    queue = user_client.get(f"/api/projects/{pid}/screening/queue?stage=ft").json()
    assert queue["total"] == 5
    # queue carries full-text availability for the viewer
    assert all("has_pdf" in i and "fulltext_status" in i for i in queue["items"])


def test_ft_eligibility_zero_after_ta_reset(user_client, ft_project):
    """Field incident: a T/A round reset (config back to draft) made FT
    eligibility fall back to 'every unique record', silently re-inflating a
    finished FT round with the whole corpus. A configured-but-inactive T/A
    round must yield an empty FT eligibility instead."""
    pid = ft_project["pid"]
    _start_ft(user_client, pid, ft_project["reviewers"])
    r = user_client.post(f"/api/projects/{pid}/screening/reset")
    assert r.status_code == 200, r.text
    info = user_client.get(f"/api/projects/{pid}/screening/config?stage=ft").json()
    assert info["eligible_records"] == 0
    # the FT queue keeps its existing assignments and gains none from a fallback
    queue = user_client.get(f"/api/projects/{pid}/screening/queue?stage=ft").json()
    assert queue["total"] == 5


def test_config_reports_round_votes(user_client, ft_project):
    """The reset confirmation names how many votes the round holds."""
    pid = ft_project["pid"]
    info = user_client.get(f"/api/projects/{pid}/screening/config").json()
    assert info["n_votes"] == 12  # 2 reviewers x 6 records at T/A
    info = user_client.get(f"/api/projects/{pid}/screening/config?stage=ft").json()
    assert info["n_votes"] == 0


# ---- reasons ------------------------------------------------------------------

def test_reasons_catalogue(user_client, ft_project):
    pid = ft_project["pid"]
    _start_ft(user_client, pid, ft_project["reviewers"])
    data = user_client.get(f"/api/projects/{pid}/screening/reasons?stage=ft").json()
    codes = [r["code"] for r in data["reasons"]]
    assert codes == ["E1", "E2", "NOTFOUND"]
    assert data["notfound_code"] == "NOTFOUND"


def test_ft_exclude_requires_reason(user_client, ft_project):
    pid = ft_project["pid"]
    _start_ft(user_client, pid, ft_project["reviewers"])
    rid = ft_project["included"][0]
    # exclude with no reason -> refused
    r = user_client.post(f"/api/projects/{pid}/screening/vote?stage=ft",
                         json={"record_id": rid, "decision": "exclude"})
    assert r.status_code == 400
    # bogus code is dropped -> still no valid reason
    r = user_client.post(f"/api/projects/{pid}/screening/vote?stage=ft",
                         json={"record_id": rid, "decision": "exclude",
                               "reasons": ["ZZ"]})
    assert r.status_code == 400
    # a valid primary reason is accepted
    r = user_client.post(f"/api/projects/{pid}/screening/vote?stage=ft",
                         json={"record_id": rid, "decision": "exclude",
                               "reasons": ["E1"]})
    assert r.status_code == 200
    # include needs no reason
    r = user_client.post(f"/api/projects/{pid}/screening/vote?stage=ft",
                         json={"record_id": ft_project["included"][1],
                               "decision": "include"})
    assert r.status_code == 200


# ---- full flow + PRISMA per reason -------------------------------------------

def test_ft_flow_and_prisma_reasons(user_client, ft_project):
    pid = ft_project["pid"]
    inc = ft_project["included"]
    _start_ft(user_client, pid, ft_project["reviewers"])

    def vote(who, rid, decision, reasons=None):
        _login(user_client, who)
        return user_client.post(
            f"/api/projects/{pid}/screening/vote?stage=ft",
            json={"record_id": rid, "decision": decision, "reasons": reasons or []})

    # A include/include; B exclude E1 x2; C exclude E2 x2; D not-found x2
    vote("admin", inc[0], "include"); vote("reviewer", inc[0], "include")
    vote("admin", inc[1], "exclude", ["E1"]); vote("reviewer", inc[1], "exclude", ["E1"])
    vote("admin", inc[2], "exclude", ["E2"]); vote("reviewer", inc[2], "exclude", ["E2"])
    vote("admin", inc[3], "exclude", ["NOTFOUND"])
    vote("reviewer", inc[3], "exclude", ["NOTFOUND"])
    # E: disagreement -> conflict, resolved to exclude with a recorded reason
    vote("admin", inc[4], "include"); vote("reviewer", inc[4], "exclude", ["E1"])
    _login(user_client, "admin")
    conflicts = user_client.get(
        f"/api/projects/{pid}/screening/conflicts?stage=ft").json()
    assert len(conflicts) == 1
    # resolving a full-text exclusion without a reason is refused
    r = user_client.post(
        f"/api/projects/{pid}/screening/conflicts/{conflicts[0]['id']}/resolve?stage=ft",
        json={"decision": "exclude"})
    assert r.status_code == 400
    r = user_client.post(
        f"/api/projects/{pid}/screening/conflicts/{conflicts[0]['id']}/resolve?stage=ft",
        json={"decision": "exclude", "reasons": ["E2"], "note": "still not empirical"})
    assert r.status_code == 200

    stats = user_client.get(
        f"/api/projects/{pid}/screening/stats?stage=ft").json()
    assert stats["included"] == 1
    # raw outcome tally counts every 'exclude' (B, C, D, E)
    assert stats["excluded"] == 4
    # the content/not-retrievable split lives in the ft breakdown
    by_reason = {r["code"]: r["n"] for r in stats["ft"]["excluded_by_reason"]}
    assert by_reason == {"E1": 1, "E2": 2}  # E resolved to E2
    assert stats["ft"]["not_retrieved"] == 1
    assert stats["ft"]["assessed"] == 4
    # each reason lists the excluded reports with metadata (dashboard drill-down)
    e2 = next(r for r in stats["ft"]["excluded_by_reason"] if r["code"] == "E2")
    assert len(e2["records"]) == 2
    assert all(rec.get("title") and "authors" in rec for rec in e2["records"])

    prisma = user_client.get(f"/api/projects/{pid}/prisma").json()
    assert prisma["reports_sought"] == 5
    assert prisma["reports_assessed"] == 4
    assert prisma["reports_excluded"] == 3
    assert prisma["reports_not_retrieved"] == 1
    assert prisma["studies_included"] == 1
    pr = {r["code"]: r["n"] for r in prisma["reports_excluded_by_reason"]}
    assert pr == {"E1": 1, "E2": 2}
    labels = {r["code"]: r["label"] for r in prisma["reports_excluded_by_reason"]}
    assert labels["E1"] == "wrong population"


# ---- annotations --------------------------------------------------------------

def test_ft_my_votes_carry_reasons(user_client, ft_project):
    pid = ft_project["pid"]
    inc = ft_project["included"]
    _start_ft(user_client, pid, ft_project["reviewers"])
    user_client.post(f"{'/api/projects'}/{pid}/screening/vote?stage=ft",
                     json={"record_id": inc[0], "decision": "exclude",
                           "reasons": ["E2", "E1"], "justification": "review"})
    history = user_client.get(
        f"/api/projects/{pid}/screening/my-votes?stage=ft").json()
    entry = next(h for h in history if h["record"]["id"] == inc[0])
    assert entry["decision"] == "exclude"
    assert entry["reasons"] == ["E2", "E1"]           # primary first, revisitable
    assert entry["reason_labels"][0] == "not empirical"
    assert "has_pdf" in entry["record"]


def test_pdf_annotations_shared_and_permissions(user_client, ft_project):
    pid = ft_project["pid"]
    rid = ft_project["included"][0]
    base = f"/api/projects/{pid}/records/{rid}/annotations"

    # admin annotates
    r = user_client.post(base, json={
        "page": 1, "rects": [{"x": 0.1, "y": 0.2, "w": 0.3, "h": 0.02}],
        "quote": "small sample", "note": "check N", "color": "yellow"})
    assert r.status_code == 200, r.text
    ann_id = r.json()["id"]
    assert r.json()["mine"] is True and r.json()["author"] == "Admin"

    # reviewer sees it (shared) but it is not theirs
    _login(user_client, "reviewer")
    listed = user_client.get(base).json()
    assert len(listed) == 1 and listed[0]["quote"] == "small sample"
    assert listed[0]["mine"] is False
    # reviewer cannot delete the admin's annotation
    assert user_client.delete(f"{base}/{ann_id}").status_code == 403
    # reviewer adds their own
    r = user_client.post(base, json={
        "page": 2, "rects": [{"x": 0, "y": 0, "w": 0.5, "h": 0.03}],
        "note": "relevant outcome"})
    assert r.status_code == 200
    rev_ann = r.json()["id"]
    assert user_client.delete(f"{base}/{rev_ann}").status_code == 200

    # admin (project admin) can delete anyone's
    _login(user_client, "admin")
    assert user_client.delete(f"{base}/{ann_id}").status_code == 200
    assert user_client.get(base).json() == []


def test_ft_ai_estimate_no_pdfs(user_client, ft_project):
    pid = ft_project["pid"]
    _start_ft(user_client, pid, ft_project["reviewers"])
    est = user_client.get(f"/api/projects/{pid}/screening/ai-estimate?stage=ft").json()
    assert est["records_with_pdf"] == 0
    assert est["records_without_pdf"] == 5


def _make_pdf(text: str, pages: int = 1) -> bytes:
    import pymupdf
    doc = pymupdf.open()
    for _ in range(pages):
        page = doc.new_page()
        page.insert_text((72, 72), text)
    return doc.tobytes()


def test_ft_ai_suggestion_reads_pdf(user_client, ft_project, monkeypatch):
    pid = ft_project["pid"]
    rid = ft_project["included"][0]
    _start_ft(user_client, pid, ft_project["reviewers"], ai_enabled=True)
    user_client.put("/api/llm/credentials", json={
        "provider": "anthropic", "api_key": "sk-ant-fake-key-123"})
    # store a real PDF for the record
    pdf = _make_pdf("This report is a narrative review, not an empirical study.")
    r = user_client.post(f"/api/projects/{pid}/fulltext/records/{rid}/upload",
                         files={"file": ("r.pdf", pdf, "application/pdf")})
    assert r.status_code == 200, r.text

    seen = {}

    class Fake:
        model = "claude-fake"

        def generate_json(self, messages, json_schema, system=None, max_tokens=4096):
            from app.services.llm.base import LLMResult
            seen["content"] = messages[0]["content"]
            assert "FULL-TEXT eligibility screening" in system
            return LLMResult(text="{}", data={
                "analysis": "It is a review.", "decision": "exclude",
                "confidence": 0.9, "reasons": ["E2"],
                "criteria": [{"code": "E2", "assessment": "met"}],
                "justification": "Narrative review, not empirical."})

    monkeypatch.setattr("app.services.screening.ai.open_provider_chain", lambda *a, **kw: Fake())
    r = user_client.post(
        f"/api/projects/{pid}/screening/records/{rid}/suggest?stage=ft")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["decision"] == "exclude"
    assert body["reasons"] == ["E2"]
    # the extracted PDF text reached the model
    assert "narrative review" in seen["content"].lower()

    # estimate now sees the stored PDF
    est = user_client.get(
        f"/api/projects/{pid}/screening/ai-estimate?stage=ft").json()
    assert est["records_with_pdf"] == 1


def test_ft_ai_suggestion_without_pdf_errors(user_client, ft_project, monkeypatch):
    pid = ft_project["pid"]
    rid = ft_project["included"][1]
    _start_ft(user_client, pid, ft_project["reviewers"], ai_enabled=True)
    user_client.put("/api/llm/credentials", json={
        "provider": "anthropic", "api_key": "sk-ant-fake-key-123"})

    class Fake:
        model = "claude-fake"

        def generate_json(self, *a, **k):  # pragma: no cover - must not be called
            raise AssertionError("should not call the model without a PDF")

    monkeypatch.setattr("app.services.screening.ai.open_provider_chain", lambda *a, **kw: Fake())
    r = user_client.post(
        f"/api/projects/{pid}/screening/records/{rid}/suggest?stage=ft")
    assert r.status_code == 400
    assert "full text" in r.json()["detail"].lower()


def test_ft_ai_refuses_pdf_over_page_limit(user_client, ft_project, monkeypatch):
    """A 46-page "report" is a book or a proceedings volume: it is never sent
    to the model, and the estimate says so before anyone clicks."""
    from app.services.screening.ai import AI_PDF_MAX_PAGES
    pid = ft_project["pid"]
    short, long = ft_project["included"][:2]
    _start_ft(user_client, pid, ft_project["reviewers"], ai_enabled=True)
    user_client.put("/api/llm/credentials", json={
        "provider": "anthropic", "api_key": "sk-ant-fake-key-123"})
    for rid, pages in ((short, AI_PDF_MAX_PAGES), (long, AI_PDF_MAX_PAGES + 1)):
        r = user_client.post(
            f"/api/projects/{pid}/fulltext/records/{rid}/upload",
            files={"file": ("r.pdf", _make_pdf("Some study text.", pages),
                            "application/pdf")})
        assert r.status_code == 200, r.text

    class Fake:
        model = "claude-fake"

        def generate_json(self, *a, **k):  # pragma: no cover - must not be called
            raise AssertionError("an over-long PDF must not reach the model")

    monkeypatch.setattr("app.services.screening.ai.open_provider_chain",
                        lambda *a, **kw: Fake())
    r = user_client.post(
        f"/api/projects/{pid}/screening/records/{long}/suggest?stage=ft")
    assert r.status_code == 400
    assert f"{AI_PDF_MAX_PAGES + 1} pages" in r.json()["detail"]

    base = f"/api/projects/{pid}/screening/records"
    est = user_client.get(f"{base}/{long}/ai-estimate?stage=ft").json()
    assert est["cost"] is None and "page" in est["blocked"]
    # exactly at the limit still goes through
    est = user_client.get(f"{base}/{short}/ai-estimate?stage=ft").json()
    assert est["blocked"] is None and est["cost"] is not None
    # the extraction AI buttons read the same PDF: same refusal
    ext = f"/api/projects/{pid}/extraction/records/{long}"
    assert "page" in user_client.get(
        f"{ext}/ai-estimate?kind=prefill").json()["blocked"]
    assert user_client.get(
        f"{ext}/ai-estimate?kind=design").json()["blocked"] is None


# ---- reviewer fixes the PDF, or defers the record -----------------------------

_MINI_PDF = b"%PDF-1.4\n1 0 obj<</Type/Catalog>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF"


def test_reviewer_can_upload_or_replace_pdf_but_not_delete(user_client, ft_project):
    """A reviewer who meets a missing or wrong PDF mid-screening replaces it
    on the spot (retrieval tab, library, screening screen all hit this
    endpoint); removing a PDF stays an admin gesture."""
    pid = ft_project["pid"]
    rid = ft_project["included"][0]
    _login(user_client, "reviewer")
    r = user_client.post(f"/api/projects/{pid}/fulltext/records/{rid}/upload",
                         files={"file": ("mine.pdf", _MINI_PDF, "application/pdf")})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "manual" and r.json()["has_file"]
    # replacing works the same way
    r = user_client.post(f"/api/projects/{pid}/fulltext/records/{rid}/upload",
                         files={"file": ("better.pdf", _MINI_PDF, "application/pdf")})
    assert r.status_code == 200
    assert r.json()["filename"] == "better.pdf"
    assert user_client.delete(
        f"/api/projects/{pid}/fulltext/records/{rid}").status_code == 403
    # an outsider still cannot upload
    user_client.post("/api/auth/register", json={
        "email": "outsider-ft@example.com", "password": "password123",
        "display_name": "O"})
    assert user_client.post(
        f"/api/projects/{pid}/fulltext/records/{rid}/upload",
        files={"file": ("x.pdf", _MINI_PDF, "application/pdf")}).status_code == 403


def test_ft_skip_decide_later(user_client, ft_project):
    """"Skip" at full-text screening: the record stays in my queue, sinks to
    the back, and is flagged when it comes around again."""
    pid = ft_project["pid"]
    _start_ft(user_client, pid, ft_project["reviewers"])
    _login(user_client, "reviewer")
    queue = user_client.get(f"/api/projects/{pid}/screening/queue?stage=ft&limit=10").json()
    assert queue["total"] == 5 and queue["skipped"] == 0
    first = queue["items"][0]["id"]
    r = user_client.post(f"/api/projects/{pid}/screening/skip?stage=ft",
                         json={"record_id": first})
    assert r.status_code == 200, r.text
    queue = user_client.get(f"/api/projects/{pid}/screening/queue?stage=ft&limit=10").json()
    assert queue["total"] == 5 and queue["done"] == 0 and queue["skipped"] == 1
    assert queue["items"][0]["id"] != first
    assert queue["items"][-1]["id"] == first and queue["items"][-1]["skipped"] is True
    # a record not assigned to me cannot be skipped
    assert user_client.post(f"/api/projects/{pid}/screening/skip?stage=ft",
                            json={"record_id": 0}).status_code == 403
