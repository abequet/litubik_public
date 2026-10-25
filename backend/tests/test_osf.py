import httpx
import pytest

from app.services.protocol import osf


# ---- url parsing ------------------------------------------------------------

def test_guid_from_url():
    assert osf._guid_from_url("https://osf.io/ab12c/") == "ab12c"
    assert osf._guid_from_url("https://www.osf.io/AB12C") == "ab12c"
    assert osf._guid_from_url("https://osf.io/ab12c/files/osfstorage") == "ab12c"
    assert osf._guid_from_url("https://example.com/ab12c/") == ""
    assert osf._guid_from_url("not a url") == ""


def test_is_download_url():
    assert osf._is_download_url("https://osf.io/download/ab12c/")
    assert osf._is_download_url("https://osf.io/ab12c/download")
    assert not osf._is_download_url("https://osf.io/ab12c/")


# ---- form rendering ---------------------------------------------------------

def test_render_form_md():
    md = osf.render_form_md("My prereg", {
        "hypothesis": "X improves Y",
        "study_design": ["between subjects", "longitudinal"],
        "sample": {"size": 120, "population": "adults"},
    }, "https://osf.io/ab12c/")
    assert md.startswith("# My prereg")
    assert "## Hypothesis" in md
    assert "X improves Y" in md
    assert "- between subjects" in md
    assert "size: 120" in md
    assert "https://osf.io/ab12c/" in md


def test_form_responses_fallback_to_registered_meta():
    attrs = {"registration_responses": {},
             "registered_meta": {"q1": {"value": "the hypothesis"}, "q2": {"value": ""}}}
    assert osf._form_responses(attrs) == {"q1": "the hypothesis"}


# ---- resolution with a mocked OSF API ----------------------------------------

NODE_FILES = {
    "data": [
        {"attributes": {"kind": "file", "name": "protocol.pdf", "size": 1234},
         "links": {"download": "https://osf.io/download/fff01/"}},
        {"attributes": {"kind": "file", "name": "dataset.csv", "size": 99},
         "links": {"download": "https://osf.io/download/fff02/"}},
        {"attributes": {"kind": "folder", "name": "docs"},
         "relationships": {"files": {"links": {"related": {
             "href": "https://api.osf.io/v2/nodes/ab12c/files/osfstorage/sub/"}}}}},
    ]
}
SUB_FILES = {
    "data": [
        {"attributes": {"kind": "file", "name": "appendix.docx", "size": 55},
         "links": {"download": "https://osf.io/download/fff03/"}},
    ]
}


def _fake_get_json(payloads):
    def fake(url, params=None):
        for key, payload in payloads.items():
            if key in url:
                return payload
        raise AssertionError(f"unexpected OSF call: {url}")
    return fake


def test_resolve_node_lists_supported_files_recursively(monkeypatch):
    monkeypatch.setattr(osf, "_get_json", _fake_get_json({
        "/guids/ab12c/": {"data": {"type": "nodes", "attributes": {"title": "P"}}},
        "/files/osfstorage/sub/": SUB_FILES,
        "/files/osfstorage/": NODE_FILES,
    }))
    candidates = osf._resolve_url("https://osf.io/ab12c/")
    names = [c["name"] for c in candidates]
    assert names == ["protocol.pdf", "appendix.docx"]  # csv filtered out


def test_resolve_registration_offers_form_first(monkeypatch):
    monkeypatch.setattr(osf, "_get_json", _fake_get_json({
        "/guids/reg1c/": {"data": {"type": "registrations", "attributes": {
            "title": "Prereg", "registration_responses": {"hypothesis": "X"}}}},
        "/files/osfstorage/": {"data": []},
    }))
    candidates = osf._resolve_url("https://osf.io/reg1c/")
    assert candidates[0]["kind"] == "form"
    assert candidates[0]["guid"] == "reg1c"


def test_fetch_protocol_single_candidate_downloads(monkeypatch):
    monkeypatch.setattr(osf, "_get_json", _fake_get_json({
        "/guids/ab12c/": {"data": {"type": "nodes", "attributes": {}}},
        "/files/osfstorage/": {"data": NODE_FILES["data"][:1]},
    }))
    monkeypatch.setattr(osf, "_download_file",
                        lambda url, name: (name or "protocol.pdf", b"%PDF"))
    assert osf.fetch_protocol("https://osf.io/ab12c/") == ("protocol.pdf", b"%PDF")


def test_fetch_protocol_rejects_non_osf():
    with pytest.raises(osf.OsfError, match="Not an OSF link"):
        osf.fetch_protocol("https://example.com/protocol.pdf")


# ---- API endpoint -----------------------------------------------------------

@pytest.fixture
def project(user_client):
    return user_client.post("/api/projects", json={"name": "OSF demo"}).json()


@pytest.fixture(autouse=True)
def _no_osf_lookup(monkeypatch):
    """The endpoint asks OSF whether the link is a registration: never on the
    network in tests — a project link unless a test says otherwise."""
    monkeypatch.setattr(osf, "registration_of", lambda url: None)


def _project_row(pid):
    from app.core.db import SessionLocal
    from app.models import Project
    with SessionLocal() as db:
        return db.get(Project, pid)


def test_registration_link_fills_the_number(user_client, project, monkeypatch):
    """PRISMA 24a: a registration's GUID is its number, filled at import; the
    date comes along. A project link leaves the number to the team."""
    monkeypatch.setattr(osf, "fetch_protocol",
                        lambda url, pick=None: ("prereg.md", b"# Prereg"))
    monkeypatch.setattr(osf, "registration_of", lambda url: {
        "guid": "reg1c", "date_registered": "2026-07-29T10:15:00.000000Z"})
    r = user_client.post(f"/api/projects/{project['id']}/protocols/import-osf",
                         json={"url": "https://osf.io/reg1c/"})
    assert r.status_code == 200, r.text
    p = _project_row(project["id"])
    assert (p.registry, p.registration_id) == ("osf", "reg1c")
    assert p.registered_at.date().isoformat() == "2026-07-29"


def test_project_link_leaves_the_number_empty(user_client, project, monkeypatch):
    monkeypatch.setattr(osf, "fetch_protocol",
                        lambda url, pick=None: ("prereg.md", b"# Prereg"))
    user_client.post(f"/api/projects/{project['id']}/protocols/import-osf",
                     json={"url": "https://osf.io/ab12c/"})
    p = _project_row(project["id"])
    assert (p.registry, p.registration_id) == ("osf", "")


def test_registration_of_tells_registrations_apart(monkeypatch):
    replies = {"reg1c": {"data": {"type": "registrations",
                                  "attributes": {"date_registered": "2026-07-29"}}},
               "ab12c": {"data": {"type": "nodes", "attributes": {}}}}
    monkeypatch.undo()  # the real function, with OSF faked below
    monkeypatch.setattr(osf, "_get_json",
                        lambda url, params=None: replies[url.split("/")[-2]])
    assert osf.registration_of("https://osf.io/reg1c/") == {
        "guid": "reg1c", "date_registered": "2026-07-29"}
    assert osf.registration_of("https://osf.io/ab12c/") is None
    assert osf.registration_of("https://example.com/x") is None


def test_import_osf_creates_version(user_client, project, monkeypatch):
    monkeypatch.setattr(osf, "fetch_protocol",
                        lambda url, pick=None: ("prereg.md", b"# Prereg\n\ninclude adults"))
    r = user_client.post(f"/api/projects/{project['id']}/protocols/import-osf",
                         json={"url": "https://osf.io/ab12c/"})
    assert r.status_code == 200, r.text
    protocol = r.json()["protocol"]
    assert protocol["version"] == 1
    assert protocol["source_filename"] == "prereg.md"
    assert protocol["source_text_chars"] > 0


def test_import_osf_candidate_roundtrip(user_client, project, monkeypatch):
    candidates = [
        {"kind": "form", "name": "Registration form — Prereg", "guid": "reg1c"},
        {"kind": "file", "name": "protocol.pdf",
         "download_url": "https://osf.io/download/fff01/", "size": 1234},
    ]

    def fake_fetch(url, pick=None):
        if pick is None:
            return candidates
        assert pick["kind"] == "form"
        return "osf_registration_reg1c.md", b"# Prereg form"

    monkeypatch.setattr(osf, "fetch_protocol", fake_fetch)
    base = f"/api/projects/{project['id']}/protocols/import-osf"

    r = user_client.post(base, json={"url": "https://osf.io/reg1c/"})
    assert r.status_code == 200
    assert [c["kind"] for c in r.json()["candidates"]] == ["form", "file"]

    r = user_client.post(base, json={"url": "https://osf.io/reg1c/",
                                     "pick": candidates[0]})
    assert r.status_code == 200
    assert r.json()["protocol"]["source_filename"] == "osf_registration_reg1c.md"


def test_import_osf_error_is_400(user_client, project, monkeypatch):
    def boom(url, pick=None):
        raise osf.OsfError("This OSF item is private")
    monkeypatch.setattr(osf, "fetch_protocol", boom)
    r = user_client.post(f"/api/projects/{project['id']}/protocols/import-osf",
                         json={"url": "https://osf.io/ab12c/"})
    assert r.status_code == 400
    assert "private" in r.json()["detail"]

def test_download_links_are_osf_hosts_only():
    assert osf._is_osf_host("https://osf.io/download/abcde/")
    assert osf._is_osf_host("https://files.de-1.osf.io/v1/resources/abcde/x")
    for url in ("http://127.0.0.1:8000/api/health", "http://localhost/x",
                "https://osf.io.evil.example/x", "https://osf.io@127.0.0.1/x",
                "https://evil.example/osf.io/x", "file:///etc/passwd",
                "https://notosf.io/x"):
        assert not osf._is_osf_host(url), url


def test_a_picked_link_is_never_fetched_off_osf(user_client, project, monkeypatch):
    """The candidate picked after a multi-file answer comes back from the
    client: a forged download_url must not make the server fetch an internal
    or foreign address (SSRF), nor a forged guid leave the OSF API."""
    def no_network(*args, **kwargs):
        raise AssertionError("the server tried to fetch the forged link")

    monkeypatch.setattr(osf.httpx, "Client", no_network)
    base = f"/api/projects/{project['id']}/protocols/import-osf"
    for pick in ({"kind": "file", "name": "x.txt",
                  "download_url": "http://127.0.0.1:8000/api/auth/me"},
                 {"kind": "file", "name": "x.txt",
                  "download_url": "https://osf.io@internal.example/x"},
                 {"kind": "form", "guid": "../../users/me"}):
        r = user_client.post(base, json={"url": "https://osf.io/abcde/",
                                         "pick": pick})
        assert r.status_code == 400, pick


def test_an_osf_link_redirected_inward_is_refused(monkeypatch):
    monkeypatch.setattr(osf, "validate_public_url", lambda url: url)

    def handler(request):
        return httpx.Response(302, headers={"location": "http://127.0.0.1:8000/"})

    real_client = httpx.Client
    monkeypatch.setattr(osf.httpx, "Client", lambda **kw: real_client(
        transport=httpx.MockTransport(handler), **kw))
    with pytest.raises(osf.OsfError, match="does not lead to OSF"):
        osf._download_file("https://osf.io/download/abcde/", "")


def test_platform_internal_ranges_are_blocked():
    """CGNAT (a hosting platform's own network) and IPv6 site-local are not
    "private" to `ipaddress`, but are internal all the same."""
    from app.core.ssrf import SSRFError, _ip_is_blocked, validate_public_url
    for ip in ("100.64.0.1", "100.127.255.254", "fec0::1", "10.0.0.1",
               "169.254.169.254", "::1"):
        assert _ip_is_blocked(ip), ip
    assert not _ip_is_blocked("8.8.8.8")
    with pytest.raises(SSRFError):
        validate_public_url("http://100.64.0.7:8080/")
