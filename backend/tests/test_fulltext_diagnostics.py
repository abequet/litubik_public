"""Retrieval failures must say why.

Before this, a missing browser, refused credentials and an article that simply
is not available all produced the same empty result — which is exactly how the
hosted image ran for months with no Chromium installed and nobody could tell.
"""
import pytest

from app.services.fulltext import doibatch


@pytest.fixture(autouse=True)
def _reset_playwright_probe():
    """The availability probe is cached per process; isolate each test."""
    before = (doibatch._playwright_available, doibatch._playwright_error)
    yield
    doibatch._playwright_available, doibatch._playwright_error = before


INST = {"name": "Toulouse 2", "ezproxy_url": "https://proxy.example/login?url=$@",
        "username": "u", "password": "p", "scope": "ut2"}


def test_missing_browser_is_named_not_swallowed(monkeypatch):
    doibatch._playwright_available = False
    doibatch._playwright_error = "aucun navigateur Chromium ne démarre"
    diag: list[str] = []
    pdf, name = doibatch.fetch_institutional_pdf("10.1/x", [INST], diag=diag)
    assert (pdf, name) == (None, None)
    assert any("navigateur" in d for d in diag), diag


def test_incomplete_credentials_are_named(monkeypatch):
    doibatch._playwright_available = True
    doibatch._playwright_error = ""
    half = dict(INST, password="")
    diag: list[str] = []
    pdf, _ = doibatch.fetch_institutional_pdf("10.1/x", [half], diag=diag)
    assert pdf is None
    assert any("identifiant ET mot de passe" in d for d in diag), diag


def test_internal_proxy_url_is_refused_with_a_reason(monkeypatch):
    monkeypatch.setattr(doibatch, "_url_guard",
                        lambda url: (_ for _ in ()).throw(ValueError("private")))
    diag: list[str] = []
    out = doibatch._try_ezproxy("https://doi.org/10.1/x", INST, diag=diag)
    assert out is None
    assert any("adresse interne" in d for d in diag), diag


def _stub_open_sources(monkeypatch):
    """Every open tier answers "nothing", quickly. The real _run_tier_parallel
    still runs, so tier 3 genuinely executes."""
    monkeypatch.setattr(doibatch, "fetch_crossref",
                        lambda doi: {"first_author": "A", "year": 2020,
                                     "title": "T"})
    monkeypatch.setattr(doibatch, "fetch_pmc_pdf",
                        lambda doi, hint_pmc_ids=None: None)
    monkeypatch.setattr(doibatch, "fetch_publisher_pdf", lambda doi: (None, None))
    monkeypatch.setattr(doibatch, "fetch_playwright_pdf",
                        lambda doi, oa_url=None: None)


def test_the_reason_reaches_the_pipeline_error(monkeypatch):
    """What retrieve_one stores in FullText.error, and the UI shows."""
    _stub_open_sources(monkeypatch)
    doibatch._playwright_available = False
    doibatch._playwright_error = "aucun navigateur Chromium ne démarre"
    result, pdf = doibatch.process_doi("10.1/x", email="", institutions=[INST],
                                       use_extensions=False)
    assert pdf is None and result["status"] == "failed"
    assert "Aucun PDF trouvé" in result["error"]
    assert "navigateur" in result["error"], result["error"]


def test_error_stays_terse_when_nothing_is_wrong(monkeypatch):
    """No institution configured and a working browser: no noise added."""
    _stub_open_sources(monkeypatch)
    doibatch._playwright_available = True
    doibatch._playwright_error = ""
    result, _ = doibatch.process_doi("10.1/x", email="", use_extensions=False)
    assert result["error"] == ("Aucun PDF trouvé (Unpaywall + PMC + "
                               "Publisher OA + Playwright)")
