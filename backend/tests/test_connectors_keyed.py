"""Chantier 6b: CORE, Lens.org, Springer Nature, Web of Science Starter —
translators, "since" clauses, counters and fetchers against recorded
responses, key management accepting the new providers."""
from datetime import date

from app.services.connectors import fetch as fetchers
from app.services.connectors.keys import KEYED_PROVIDERS
from app.services.equations import counts as counters
from app.services.equations.translate import DATABASES, translate_all
from app.services.living.since import since_query

STRUCTURE = {"concepts": [
    {"keywords": ["gamification", "serious games"]},
    {"keywords": ["driving"]},
]}


def _q(db, params=None):
    return translate_all(STRUCTURE, params or {})[db]


def test_registries():
    assert KEYED_PROVIDERS == ("scopus", "ieee", "core", "lens", "springer", "wos")
    for p in KEYED_PROVIDERS:
        assert p in counters.KEYED_COUNTERS and p in fetchers.KEYED_FETCHERS
    ids = {d["id"]: d for d in DATABASES}
    for p in ("core", "lens", "springer", "wos"):
        assert ids[p]["count"] == "manual"  # automatic only once a key is stored


def test_translate_core_lens_springer():
    core = _q("core", {"year_from": 2015, "year_to": 2020})
    assert core.startswith('((title:gamification OR abstract:gamification) OR '
                           '(title:"serious games" OR abstract:"serious games"))')
    assert core.endswith("AND yearPublished>=2015 AND yearPublished<=2020")
    assert "keyword" not in _q("core", {"fields": ["title", "abstract", "keywords"]})

    lens = _q("lens", {"year_to": 2021, "fields": ["title", "keywords"]})
    assert "(title:gamification OR keyword:gamification)" in lens
    assert lens.endswith("year_published:[1900 TO 2021]")

    assert _q("springer", {"fields": ["title"]}).startswith('(title:gamification OR title:"serious games")')
    assert _q("springer", {"fields": ["keywords"]}).startswith("(keyword:gamification")
    full = _q("springer", {"year_from": 2019, "year_to": 2021})
    assert full.startswith('(gamification OR "serious games") AND (driving)')
    assert full.endswith("AND (year:2019 OR year:2020 OR year:2021)")
    # a huge range is capped, never an unbounded expansion
    assert _q("springer", {"year_from": 1900}).count("year:") == 40

    assert _q("wos").startswith("(TI=(")


def test_since_clauses():
    d = date(2026, 9, 1)
    assert since_query("core", "title:x", d) == '(title:x) AND createdDate>="2026-09-01"'
    assert since_query("lens", "title:x", d) == "(title:x) AND created:[2026-09-01 TO *]"
    assert since_query("springer", "x", d) == "x"  # over-fetch
    assert since_query("wos", "TS=(x)", d) == "TS=(x)"


# ---- recorded responses -------------------------------------------------------------

CORE_PAGE = {"totalHits": 1, "results": [
    {"doi": "10.1/core1", "title": "Open gamified driving", "yearPublished": 2020,
     "authors": [{"name": "Ada Lovelace"}], "journals": [{"title": "Open J"}],
     "abstract": "CORE abstract."}]}
LENS_PAGE = {"total": 1, "data": [
    {"lens_id": "000-1", "title": "Lens driving paper", "year_published": 2018,
     "authors": [{"first_name": "Alan", "last_name": "Turing"}],
     "source": {"title": "Lens Journal"}, "abstract": "Lens abstract.",
     "external_ids": [{"type": "pmid", "value": "1"}, {"type": "doi", "value": "10.1/lens1"}]}]}
SPRINGER_PAGE = {"result": [{"total": "1"}], "records": [
    {"doi": "10.1/spr1", "title": "Springer gamification", "publicationDate": "2021-03-04",
     "creators": [{"creator": "Hopper, Grace"}], "publicationName": "BMC Something",
     "abstract": "Springer abstract."}]}
WOS_PAGE = {"metadata": {"total": 1, "page": 1, "limit": 50}, "hits": [
    {"title": "WoS driving study", "identifiers": {"doi": "10.1/wos1"},
     "names": {"authors": [{"displayName": "Curie, Marie"}]},
     "source": {"publishYear": 2017, "sourceTitle": "Accident Analysis"}}]}


def test_keyed_counters(monkeypatch):
    seen = {}

    def fake_get(url, params, extra_headers=None, as_json=True):
        seen[url] = (params, extra_headers or {})
        if url == counters.CORE_SEARCH:
            return {"totalHits": 5}
        if url == counters.SPRINGER_SEARCH:
            return {"result": [{"total": "7"}]}
        if url == counters.WOS_SEARCH:
            return {"metadata": {"total": 9}}
        raise AssertionError(url)

    def fake_post(url, body, extra_headers=None):
        seen[url] = (body, extra_headers or {})
        return {"total": 3}
    monkeypatch.setattr(counters, "_get", fake_get)
    monkeypatch.setattr(counters, "_post_json", fake_post)
    assert counters.core_count("q", {}, "K") == 5
    assert seen[counters.CORE_SEARCH][1]["Authorization"] == "Bearer K"
    assert counters.lens_count("q", {}, "T") == 3
    assert seen[counters.LENS_SEARCH][0]["size"] == 1
    assert counters.springer_count("q", {}, "S") == 7
    assert seen[counters.SPRINGER_SEARCH][0]["api_key"] == "S"
    assert counters.wos_count("TS=(q)", {}, "W") == 9
    assert seen[counters.WOS_SEARCH][1]["X-ApiKey"] == "W"
    assert seen[counters.WOS_SEARCH][0]["db"] == "WOS"


def test_keyed_fetchers(monkeypatch):
    calls = []

    def fake_get(client, url, params, *, as_json=True, headers=None):
        calls.append((url, dict(params), headers or {}))
        return {counters.CORE_SEARCH: CORE_PAGE, counters.SPRINGER_SEARCH: SPRINGER_PAGE,
                counters.WOS_SEARCH: WOS_PAGE}[url]

    def fake_post(client, url, body, headers=None):
        calls.append((url, dict(body), headers or {}))
        return LENS_PAGE
    monkeypatch.setattr(fetchers, "_get", fake_get)
    monkeypatch.setattr(fetchers, "_post", fake_post)
    monkeypatch.setattr(fetchers.time, "sleep", lambda s: None)
    noop = lambda d, t: None  # noqa: E731

    core = fetchers.core_fetch("q", {}, 100, noop, "K")
    assert core[0]["doi"] == "10.1/core1" and core[0]["journal"] == "Open J"
    assert core[0]["authors"] == ["Ada Lovelace"] and core[0]["abstract"] == "CORE abstract."
    assert calls[-1][2]["Authorization"] == "Bearer K" and calls[-1][1]["offset"] == 0

    lens = fetchers.lens_fetch("q", {}, 100, noop, "T")
    assert lens[0]["doi"] == "10.1/lens1" and lens[0]["authors"] == ["Alan Turing"]
    assert lens[0]["journal"] == "Lens Journal" and lens[0]["year"] == 2018
    assert calls[-1][1]["from"] == 0 and "abstract" in calls[-1][1]["include"]

    springer = fetchers.springer_fetch("q", {}, 100, noop, "S")
    assert springer[0]["doi"] == "10.1/spr1" and springer[0]["year"] == 2021
    assert springer[0]["authors"] == ["Hopper, Grace"]
    assert calls[-1][1]["s"] == 1 and calls[-1][1]["api_key"] == "S"

    wos = fetchers.wos_fetch("TS=(q)", {}, 100, noop, "W")
    assert wos[0]["doi"] == "10.1/wos1" and wos[0]["abstract"] == ""
    assert wos[0]["authors"] == ["Curie, Marie"] and wos[0]["year"] == 2017
    assert calls[-1][2]["X-ApiKey"] == "W" and calls[-1][1]["page"] == 1
    # one page each: the total was reached, no second request
    assert len(calls) == 4


# ---- key management ---------------------------------------------------------------------

def test_keys_api_accepts_new_providers_and_flips_the_card(user_client):
    keys = {k["provider"]: k for k in user_client.get("/api/database-credentials").json()}
    assert set(keys) == set(KEYED_PROVIDERS)
    assert keys["lens"]["label"] == "Lens.org" and keys["core"]["help_url"].startswith("https://core.ac.uk")
    pid = user_client.post("/api/projects", json={"name": "K"}).json()["id"]
    before = {d["id"]: d for d in user_client.get(
        f"/api/projects/{pid}/equations/databases").json()["databases"]}
    assert before["core"]["count"] == "manual" and before["core"]["key_required"] is True
    assert before["wos"]["count"] == "manual"
    assert "Add an API key" not in before["core"]["instructions"]  # the front adds it, translated
    r = user_client.put("/api/database-credentials",
                        json={"provider": "core", "api_key": "core-secret-key"})
    assert r.status_code == 200 and r.json()["label"] == "CORE"
    r = user_client.put("/api/database-credentials",
                        json={"provider": "wos", "api_key": "wos-starter-key",
                              "project_id": pid})
    assert r.status_code == 200
    assert user_client.put("/api/database-credentials",
                           json={"provider": "ebsco", "api_key": "nope-nope"}).status_code == 422
    after = {d["id"]: d for d in user_client.get(
        f"/api/projects/{pid}/equations/databases").json()["databases"]}
    assert after["core"]["count"] == "api" and after["wos"]["count"] == "api"
    assert after["springer"]["count"] == "manual"
    listing = {d["id"]: d for d in user_client.get(
        f"/api/database-credentials/databases?project_id={pid}").json()}
    assert listing["lens"]["mode"] == "api_key"
    # project-side sharing accepts the new providers too
    r = user_client.put(f"/api/projects/{pid}/sync/database-keys",
                        json={"provider": "springer", "api_key": "springer-key-1", "shared": True})
    assert r.status_code == 200, r.text
