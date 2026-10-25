"""Chantier 6a: Europe PMC, arXiv, HAL and DOAJ — translators, feed parsing,
counters and fetchers against recorded responses."""
import json

import pytest

from app.services.connectors import fetch as fetchers
from app.services.connectors.arxiv import arxiv_id, parse_arxiv_feed
from app.services.equations import counts as counters
from app.services.equations.translate import DATABASES, translate_all

STRUCTURE = {"concepts": [
    {"keywords": ["gamification", "serious games"]},
    {"keywords": ["driving"]},
]}


def _q(db, params=None):
    return translate_all(STRUCTURE, params or {})[db]


# ---- translators ----------------------------------------------------------------

def test_catalogue_and_registries_know_the_four():
    ids = {d["id"] for d in DATABASES if d["count"] == "api"}
    assert {"europepmc", "arxiv", "hal", "doaj"} <= ids
    for db in ("europepmc", "arxiv", "hal", "doaj"):
        assert db in counters.COUNTERS and db in fetchers.FETCHERS
    from app.api.equations import API_DATABASES
    assert "europepmc" in API_DATABASES


def test_translate_europepmc_default_fields_years_types():
    q = _q("europepmc", {"year_from": 2015, "year_to": 2020,
                         "languages": ["en", "fr"], "doc_types": ["preprint", "review"]})
    assert q.startswith('((TITLE:gamification OR ABSTRACT:gamification) OR '
                        '(TITLE:"serious games" OR ABSTRACT:"serious games")) AND '
                        '((TITLE:driving OR ABSTRACT:driving))')
    assert "PUB_YEAR:[2015 TO 2020]" in q
    assert "(LANG:eng OR LANG:fre)" in q
    assert 'SRC:PPR' in q and 'PUB_TYPE:"review"' in q


def test_translate_europepmc_title_only_and_keywords():
    assert _q("europepmc", {"fields": ["title"]}).startswith(
        "(TITLE:gamification OR TITLE:\"serious games\")")
    q = _q("europepmc", {"fields": ["title", "abstract", "keywords"]})
    assert "KW:gamification" in q


def test_translate_arxiv():
    q = _q("arxiv", {"year_from": 2020})
    assert q.startswith("((ti:gamification OR abs:gamification)")
    assert "submittedDate:[202001010000 TO 210012312359]" in q
    assert _q("arxiv", {"fields": ["keywords"]}).startswith("(all:gamification")


def test_translate_hal_and_doaj():
    q = _q("hal", {"year_to": 2021, "languages": ["fr"], "doc_types": ["conference"]})
    assert "(title_t:gamification OR abstract_t:gamification)" in q
    assert "producedDateY_i:[1900 TO 2021]" in q
    assert "language_s:(fr)" in q and "docType_s:(COMM)" in q
    d = _q("doaj", {"year_from": 2010, "year_to": 2012})
    assert "(bibjson.title:driving OR bibjson.abstract:driving)" in d
    assert d.endswith("bibjson.year:[2010 TO 2012]")


# ---- arXiv feed ----------------------------------------------------------------------

ARXIV_FEED = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>ArXiv Query: search_query=ti:gamification</title>
  <opensearch:totalResults xmlns:opensearch="http://a9.com/-/spec/opensearch/1.1/">2</opensearch:totalResults>
  <opensearch:startIndex xmlns:opensearch="http://a9.com/-/spec/opensearch/1.1/">0</opensearch:startIndex>
  <entry>
    <id>http://arxiv.org/abs/2301.01234v2</id>
    <published>2023-01-03T10:00:00Z</published>
    <title>Gamified speed feedback
  for young drivers</title>
    <summary>  We study gamification of speed feedback.
  Results show fewer violations.  </summary>
    <author><name>Ada Lovelace</name></author>
    <author><name>Alan Turing</name></author>
    <arxiv:journal_ref xmlns:arxiv="http://arxiv.org/schemas/atom">Transp. Res. F 95 (2023)</arxiv:journal_ref>
  </entry>
  <entry>
    <id>http://arxiv.org/abs/cs/0601001v1</id>
    <published>2006-01-01T00:00:00Z</published>
    <title>Serious games for driving</title>
    <summary>Abstract.</summary>
    <author><name>Grace Hopper</name></author>
    <arxiv:doi xmlns:arxiv="http://arxiv.org/schemas/atom">10.1000/xyz123</arxiv:doi>
  </entry>
</feed>
"""


def test_parse_arxiv_feed():
    total, records = parse_arxiv_feed(ARXIV_FEED)
    assert total == 2
    first, second = records
    assert first["doi"] == "10.48550/arxiv.2301.01234"  # DataCite DOI, normalized
    assert first["title"] == "Gamified speed feedback for young drivers"
    assert first["authors"] == ["Ada Lovelace", "Alan Turing"]
    assert first["year"] == 2023
    assert first["journal"] == "Transp. Res. F 95 (2023)"
    assert first["abstract"].startswith("We study gamification")
    assert second["doi"] == "10.1000/xyz123" and second["journal"] == "arXiv"
    assert arxiv_id("http://arxiv.org/abs/math/0601001v3") == "math/0601001"


# ---- counters and fetchers against recorded responses ---------------------------------

EUROPEPMC_PAGE1 = {
    "hitCount": 3, "nextCursorMark": "AoIIP4AAACgxMjM=",
    "resultList": {"result": [
        {"id": "33000001", "source": "MED", "pmid": "33000001", "doi": "10.1/epmc1",
         "title": "Gamification and driving.", "pubYear": "2021",
         "journalInfo": {"journal": {"title": "Accid Anal Prev"}},
         "authorList": {"author": [{"fullName": "Smith J"}, {"fullName": "Doe A"}]},
         "abstractText": "Background: ..."},
        {"id": "PPR400000", "source": "PPR", "doi": "10.1101/2022.01.01.000001",
         "title": "A preprint on serious games", "pubYear": "2022",
         "authorString": "Lee K, Park M.",
         "abstractText": "Preprint abstract."},
    ]},
}
EUROPEPMC_PAGE2 = {
    "hitCount": 3, "nextCursorMark": "AoIIP4AAACgxMjM=",
    "resultList": {"result": [
        {"id": "33000003", "source": "MED", "title": "Third", "pubYear": "2020",
         "journalTitle": "J Safety Res", "authorString": "Solo A."},
    ]},
}
HAL_PAGE = {
    "response": {"numFound": 1, "docs": [
        {"docid": 123, "doiId_s": "10.1/hal1", "title_s": ["Jeux sérieux et conduite"],
         "abstract_s": ["Résumé HAL."], "authFullName_s": ["Marie Curie"],
         "producedDateY_i": 2019, "journalTitle_s": "Le travail humain",
         "halId_s": "hal-01234567"}]},
    "nextCursorMark": "AoEjMTIz",
}
DOAJ_PAGE = {
    "total": 1, "page": 1, "pageSize": 100,
    "results": [{"bibjson": {
        "title": "Open access gamification study",
        "abstract": "DOAJ abstract.", "year": "2018",
        "author": [{"name": "Nikola Tesla"}],
        "journal": {"title": "PLoS ONE"},
        "identifier": [{"type": "eissn", "id": "1932-6203"},
                       {"type": "DOI", "id": "10.1371/journal.pone.0000001"}],
    }}],
}


def _recorded(url_map):
    """A fake `_get(client, url, params, ...)` answering from recorded pages;
    multi-page sources answer in order."""
    calls = []

    def fake(client, url, params, *, as_json=True, headers=None):
        calls.append((url, dict(params)))
        pages = url_map[next(k for k in url_map if url.startswith(k))]
        page = pages.pop(0) if isinstance(pages, list) else pages
        return page if as_json else page  # arXiv page is already text
    fake.calls = calls
    return fake


def test_europepmc_fetch_follows_cursor_until_it_repeats(monkeypatch):
    fake = _recorded({counters.EUROPEPMC_SEARCH: [EUROPEPMC_PAGE1, EUROPEPMC_PAGE2]})
    monkeypatch.setattr(fetchers, "_get", fake)
    monkeypatch.setattr(fetchers.time, "sleep", lambda s: None)
    seen = []
    records = fetchers.europepmc_fetch("TITLE:x", {}, 100, lambda d, t: seen.append((d, t)))
    assert [r["doi"] for r in records] == ["10.1/epmc1", "10.1101/2022.01.01.000001", None]
    assert records[0]["authors"] == ["Smith J", "Doe A"]
    assert records[0]["journal"] == "Accid Anal Prev"
    assert records[1]["authors"] == ["Lee K", "Park M"]
    assert records[2]["journal"] == "J Safety Res" and records[2]["year"] == 2020
    assert seen[-1] == (3, 3)
    assert fake.calls[0][1]["cursorMark"] == "*" and fake.calls[0][1]["resultType"] == "core"
    assert fake.calls[1][1]["cursorMark"] == "AoIIP4AAACgxMjM="
    assert len(fake.calls) == 2  # the repeated cursor stops the loop


def test_europepmc_fetch_respects_cap(monkeypatch):
    fake = _recorded({counters.EUROPEPMC_SEARCH: [EUROPEPMC_PAGE1]})
    monkeypatch.setattr(fetchers, "_get", fake)
    records = fetchers.europepmc_fetch("TITLE:x", {}, 1, lambda d, t: None)
    assert len(records) == 1 and fake.calls[0][1]["pageSize"] == 1


def test_arxiv_fetch_parses_feed_and_paginates(monkeypatch):
    fake = _recorded({counters.ARXIV_QUERY: [ARXIV_FEED]})
    monkeypatch.setattr(fetchers, "_get", fake)
    monkeypatch.setattr(fetchers.time, "sleep", lambda s: None)
    records = fetchers.arxiv_fetch("ti:x", {}, 50, lambda d, t: None)
    assert len(records) == 2 and fake.calls[0][1]["start"] == 0
    assert fake.calls[0][1]["max_results"] == 50


def test_hal_and_doaj_fetch(monkeypatch):
    fake = _recorded({counters.HAL_SEARCH: [HAL_PAGE],
                      counters.DOAJ_SEARCH: [DOAJ_PAGE]})
    monkeypatch.setattr(fetchers, "_get", fake)
    monkeypatch.setattr(fetchers.time, "sleep", lambda s: None)
    hal = fetchers.hal_fetch("title_t:x", {}, 100, lambda d, t: None)
    assert hal[0]["doi"] == "10.1/hal1" and hal[0]["title"] == "Jeux sérieux et conduite"
    assert hal[0]["abstract"] == "Résumé HAL." and hal[0]["authors"] == ["Marie Curie"]
    assert fake.calls[0][1]["sort"] == "docid asc"
    doaj = fetchers.doaj_fetch('bibjson.title:"x y"', {}, 100, lambda d, t: None)
    assert doaj[0]["doi"] == "10.1371/journal.pone.0000001"
    assert doaj[0]["authors"] == ["Nikola Tesla"] and doaj[0]["year"] == 2018
    # the query travels URL-encoded in the path
    assert fake.calls[1][0] == counters.DOAJ_SEARCH + "bibjson.title%3A%22x%20y%22"


def test_counters(monkeypatch):
    def fake_get(url, params, extra_headers=None, as_json=True):
        if url == counters.EUROPEPMC_SEARCH:
            return {"hitCount": 42}
        if url == counters.ARXIV_QUERY:
            assert not as_json
            return ARXIV_FEED
        if url == counters.HAL_SEARCH:
            assert params["rows"] == 0
            return {"response": {"numFound": 7}}
        if url.startswith(counters.DOAJ_SEARCH):
            return {"total": 9}
        raise AssertionError(url)
    monkeypatch.setattr(counters, "_get", fake_get)
    assert counters.europepmc_count("q", {}) == 42
    assert counters.arxiv_count("q", {}) == 2
    assert counters.hal_count("q", {}) == 7
    assert counters.doaj_count("q", {}) == 9


def test_records_serialize_to_ris():
    _total, records = parse_arxiv_feed(ARXIV_FEED)
    assert "TY  - JOUR" in records[0]["raw"]
    assert json.dumps(records[0])  # plain JSON-able dicts, as the job runner stores
