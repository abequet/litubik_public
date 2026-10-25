import time

import pytest

from app.services.equations import counts as counters
from app.services.equations.translate import translate_all

STRUCTURE = {"concepts": [
    {"id": 1, "name": "Population", "keywords": ["older adults", "elderly"]},
    {"id": 2, "name": "Intervention", "keywords": ["gamification", "serious games"]},
]}
PARAMS = {"year_from": 2010, "year_to": 2025, "languages": ["en", "fr"]}


# ---- translation --------------------------------------------------------------

def test_translate_pubmed():
    q = translate_all(STRUCTURE, PARAMS)["pubmed"]
    assert '"older adults"[tiab] OR "elderly"[tiab]' in q
    assert ') AND ("gamification"[tiab]' in q
    assert '("2010"[dp] : "2025"[dp])' in q
    assert "(english[la] OR french[la])" in q


def test_translate_wos_scopus_default_fields():
    t = translate_all(STRUCTURE, PARAMS)
    generic = '("older adults" OR elderly) AND (gamification OR "serious games")'
    # default fields = title+abstract
    assert t["wos"] == f"(TI=({generic}) OR AB=({generic})) AND PY=(2010-2025)"
    assert t["scopus"].startswith(f"TITLE-ABS({generic})")
    assert "PUBYEAR > 2009" in t["scopus"] and "PUBYEAR < 2026" in t["scopus"]


def test_translate_fields_variants():
    generic = '("older adults" OR elderly) AND (gamification OR "serious games")'
    with_kw = {**PARAMS, "fields": ["title", "abstract", "keywords"]}
    t = translate_all(STRUCTURE, with_kw)
    assert t["wos"].startswith(f"TS=({generic})")
    assert t["scopus"].startswith(f"TITLE-ABS-KEY({generic})")
    assert '"older adults"[tw]' in t["pubmed"]
    assert "KW (" in t["ebsco"]
    assert "Keyword:(" in t["acm"]
    assert '"Author Keywords":' in t["ieee"]

    title_only = {**PARAMS, "fields": ["title"]}
    t = translate_all(STRUCTURE, title_only)
    assert t["wos"].startswith(f"TI=({generic})")
    assert t["scopus"].startswith(f"TITLE({generic})")
    assert '"older adults"[ti]' in t["pubmed"]
    assert t["googlescholar"].startswith('(intitle:"older adults" OR intitle:elderly)')
    assert '"Document Title":"older adults"' in t["ieee"]

    abstract_only = {**PARAMS, "fields": ["abstract"]}
    t = translate_all(STRUCTURE, abstract_only)
    assert t["wos"].startswith(f"AB=({generic})")
    assert t["scopus"].startswith(f"ABS({generic})")
    assert '"older adults"[tiab]' in t["pubmed"]  # PubMed has no abstract-only tag


def test_translate_doc_types_and_disciplines():
    params = {**PARAMS, "doc_types": ["article", "review", "preprint"],
              "disciplines": ["psyc", "comp"]}
    t = translate_all(STRUCTURE, params)
    assert "(journal article[pt] OR review[pt] OR preprint[pt])" in t["pubmed"]
    assert 'DT=(Article OR Review)' in t["wos"]          # preprint unsupported on WoS
    assert 'SU=(Psychology OR "Computer Science")' in t["wos"]
    assert "(DOCTYPE(ar) OR DOCTYPE(re))" in t["scopus"]
    assert "(SUBJAREA(PSYC) OR SUBJAREA(COMP))" in t["scopus"]
    # no doc types / disciplines -> no clauses
    t = translate_all(STRUCTURE, PARAMS)
    assert "[pt]" not in t["pubmed"] and "DT=" not in t["wos"]
    assert "SUBJAREA" not in t["scopus"]


def test_api_filter_params_doc_types_disciplines():
    from app.services.equations.counts import (
        crossref_filters, openalex_filters, s2_search_params,
    )
    params = {"year_from": 2015, "doc_types": ["article", "conference"],
              "disciplines": ["psyc", "neur"]}
    f = openalex_filters("q", params)
    assert "type:article" in f                      # conference unsupported
    assert "primary_topic.field.id:fields/32|fields/28" in f
    s2 = s2_search_params("q", params)
    assert s2["publicationTypes"] == "JournalArticle,Conference"
    assert s2["fieldsOfStudy"] == "Psychology"      # neuroscience unmapped on S2
    assert "type:journal-article" in crossref_filters(params)
    assert "type:proceedings-article" in crossref_filters(params)


def test_build_structure_ors_concepts_sharing_a_block():
    """OR-ing two concepts = merging their keyword lists, so the structure
    stays a flat AND-of-ORs and every translator keeps working."""
    from types import SimpleNamespace

    from app.services.equations.translate import build_structure
    pop = SimpleNamespace(id=1, name="Population", keywords=["older adults", "elderly"])
    setting = SimpleNamespace(id=2, name="Setting", keywords=["nursing home", "ELDERLY"])
    inter = SimpleNamespace(id=3, name="Intervention", keywords=["gamification"])

    structure = build_structure([[pop, setting], [inter]])
    block = structure["concepts"][0]
    assert block["name"] == "Population OR Setting"
    assert block["keywords"] == ["older adults", "elderly", "nursing home"]  # deduped
    assert block["members"] == [{"id": 1, "name": "Population"},
                                {"id": 2, "name": "Setting"}]
    assert "id" not in block                      # ambiguous for a merged block
    assert structure["concepts"][1]["id"] == 3    # single-concept block: unchanged

    q = translate_all(structure, {})["openalex"]
    assert q == ('("older adults" OR elderly OR "nursing home") AND (gamification)')


def test_equation_groups_or_between_concepts(user_client, project, concepts):
    pid = project["id"]
    r = user_client.post(f"/api/projects/{pid}/equations", json={
        "label": "or-block", "groups": [[c["id"] for c in concepts]], "params": {}})
    assert r.status_code == 200, r.text
    eq = r.json()
    assert eq["translations"]["auto"]["openalex"] == (
        '("older adults" OR elderly OR gamification OR "serious games")')
    assert eq["structure"]["concepts"][0]["name"] == "Population OR Intervention"
    # a concept listed in two blocks lands in the first one only
    r = user_client.post(f"/api/projects/{pid}/equations", json={
        "label": "dup", "params": {},
        "groups": [[concepts[0]["id"]], [concepts[0]["id"], concepts[1]["id"]]]})
    names = [b["name"] for b in r.json()["structure"]["concepts"]]
    assert names == ["Population", "Intervention"]
    # empty selection is refused
    r = user_client.post(f"/api/projects/{pid}/equations", json={
        "label": "none", "groups": [[]], "params": {}})
    assert r.status_code == 422


def test_equation_params_validation_drops_unknown(user_client, project, concepts):
    r = user_client.post(f"/api/projects/{project['id']}/equations", json={
        "label": "v", "concept_ids": [concepts[0]["id"]],
        "params": {"doc_types": ["article", "nonsense"],
                   "disciplines": ["psyc", "bogus"]}})
    assert r.status_code == 200
    assert r.json()["params"]["doc_types"] == ["article"]
    assert r.json()["params"]["disciplines"] == ["psyc"]


def test_openalex_search_filter_choice():
    from app.services.equations.counts import openalex_search_filter
    assert openalex_search_filter({}) == "title_and_abstract.search"
    assert openalex_search_filter({"fields": ["title"]}) == "title.search"
    assert openalex_search_filter({"fields": ["abstract"]}) == "abstract.search"
    assert openalex_search_filter(
        {"fields": ["title", "abstract", "keywords"]}) == "title_and_abstract.search"


def test_translate_s2_and_generic():
    t = translate_all(STRUCTURE, PARAMS)
    assert t["semanticscholar"] == ('("older adults" | elderly) + '
                                    '(gamification | "serious games")')
    assert t["openalex"] == ('("older adults" OR elderly) AND '
                             '(gamification OR "serious games")')
    assert t["ebsco"].count("TI (") == 2 and t["ebsco"].count("OR AB (") == 2


def test_translate_trid():
    # TRID has no in-box field tag: the same boolean string whatever the
    # fields, pasted into the box the instructions name. Years and languages
    # are sidebar filters there, so they must not leak into the query.
    generic = '("older adults" OR elderly) AND (gamification OR "serious games")'
    assert translate_all(STRUCTURE, PARAMS)["trid"] == generic
    for fields in (["title"], ["abstract"], ["title", "abstract", "keywords"]):
        assert translate_all(STRUCTURE, {**PARAMS, "fields": fields})["trid"] == generic


def test_translate_skips_empty_concepts():
    structure = {"concepts": [
        {"id": 1, "name": "A", "keywords": ["x"]},
        {"id": 2, "name": "B", "keywords": []},
    ]}
    assert translate_all(structure, {})["openalex"] == "(x)"


def test_translate_no_years():
    q = translate_all(STRUCTURE, {})["pubmed"]
    assert "[dp]" not in q and "[la]" not in q


# ---- API flow -------------------------------------------------------------------

@pytest.fixture
def project(user_client):
    return user_client.post("/api/projects", json={"name": "EQ demo"}).json()


@pytest.fixture
def concepts(user_client, project):
    out = []
    for name, kws in [("Population", ["older adults", "elderly"]),
                      ("Intervention", ["gamification", "serious games"])]:
        r = user_client.post(f"/api/projects/{project['id']}/concepts",
                             json={"name": name, "keywords": kws})
        assert r.status_code == 200
        out.append(r.json())
    return out


def test_concepts_crud_dedups_keywords(user_client, project):
    r = user_client.post(f"/api/projects/{project['id']}/concepts", json={
        "name": "C", "keywords": ["Anxiety", "anxiety ", " anxiety", "stress"]})
    assert [k.lower() for k in r.json()["keywords"]] == ["anxiety", "stress"]
    cid = r.json()["id"]
    r = user_client.put(f"/api/projects/{project['id']}/concepts/{cid}",
                        json={"name": "C2", "keywords": ["a b  c"]})
    assert r.json()["keywords"] == ["a b c"]
    r = user_client.delete(f"/api/projects/{project['id']}/concepts/{cid}")
    assert r.status_code == 200
    assert user_client.get(f"/api/projects/{project['id']}/concepts").json() == []


def test_equation_lifecycle(user_client, project, concepts):
    pid = project["id"]
    # create a variant from both concepts
    r = user_client.post(f"/api/projects/{pid}/equations", json={
        "label": "standard", "concept_ids": [c["id"] for c in concepts],
        "params": {"year_from": 2010, "year_to": 2025, "languages": ["en"]}})
    assert r.status_code == 200, r.text
    eq = r.json()
    assert eq["translations"]["auto"]["pubmed"].startswith('("older adults"[tiab]')
    assert eq["status"] == "draft"

    # manual override of one database string
    r = user_client.put(f"/api/projects/{pid}/equations/{eq['id']}/override",
                        json={"database": "wos", "query": "TS=(custom)"})
    assert r.json()["translations"]["overrides"]["wos"] == "TS=(custom)"

    # concept edit + re-snapshot keeps the override
    user_client.put(f"/api/projects/{pid}/concepts/{concepts[0]['id']}", json={
        "name": "Population", "keywords": ["older adults", "elderly", "seniors"]})
    r = user_client.put(f"/api/projects/{pid}/equations/{eq['id']}", json={
        "label": "standard", "concept_ids": [c["id"] for c in concepts],
        "params": {"year_from": 2010, "year_to": 2025, "languages": ["en"]}})
    assert "seniors" in r.json()["translations"]["auto"]["openalex"]
    assert r.json()["translations"]["overrides"]["wos"] == "TS=(custom)"

    # manual count for a closed database
    r = user_client.post(f"/api/projects/{pid}/equations/{eq['id']}/counts/manual",
                         json={"database": "wos", "count": 412})
    counts = r.json()["counts"]
    assert counts[-1]["database_name"] == "wos"
    assert counts[-1]["count"] == 412
    assert counts[-1]["method"] == "manual"

    # freeze locks everything
    r = user_client.post(f"/api/projects/{pid}/equations/{eq['id']}/freeze")
    assert r.json()["status"] == "frozen"
    assert r.json()["frozen_at"] is not None
    r = user_client.put(f"/api/projects/{pid}/equations/{eq['id']}", json={
        "label": "x", "concept_ids": [concepts[0]["id"]], "params": {}})
    assert r.status_code == 400
    assert user_client.delete(f"/api/projects/{pid}/equations/{eq['id']}").status_code == 400


def test_counts_job_with_mocked_apis(user_client, project, concepts, monkeypatch):
    pid = project["id"]
    eq = user_client.post(f"/api/projects/{pid}/equations", json={
        "label": "v1", "concept_ids": [concepts[0]["id"]], "params": {}}).json()

    monkeypatch.setitem(counters.COUNTERS, "pubmed", lambda q, p: 123)
    monkeypatch.setitem(counters.COUNTERS, "openalex", lambda q, p: 456)

    r = user_client.post(f"/api/projects/{pid}/equations/{eq['id']}/counts",
                         json={"databases": ["pubmed", "openalex"]})
    assert r.status_code == 200, r.text
    job_id = r.json()["job_id"]
    for _ in range(100):
        job = user_client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in ("done", "failed"):
            break
        time.sleep(0.05)
    assert job["status"] == "done", job.get("error")
    assert job["result"]["results"] == {"pubmed": {"count": 123},
                                        "openalex": {"count": 456}}
    eq = user_client.get(f"/api/projects/{pid}/equations").json()[0]
    by_db = {c["database_name"]: c for c in eq["counts"]}
    assert by_db["pubmed"]["count"] == 123 and by_db["pubmed"]["method"] == "api"


def test_counts_job_rejects_manual_db(user_client, project, concepts):
    pid = project["id"]
    eq = user_client.post(f"/api/projects/{pid}/equations", json={
        "label": "v1", "concept_ids": [concepts[0]["id"]], "params": {}}).json()
    r = user_client.post(f"/api/projects/{pid}/equations/{eq['id']}/counts",
                         json={"databases": ["wos"]})
    assert r.status_code == 400


def test_golden_set_and_check(user_client, project, concepts, monkeypatch):
    pid = project["id"]
    # DOI normalization + dedup
    r = user_client.post(f"/api/projects/{pid}/golden",
                         json={"doi": "https://doi.org/10.1000/ABC", "title": "T1"})
    assert r.json()["doi"] == "10.1000/abc"
    user_client.post(f"/api/projects/{pid}/golden", json={"doi": "10.1000/abc"})
    user_client.post(f"/api/projects/{pid}/golden", json={"doi": "10.1000/xyz"})
    refs = user_client.get(f"/api/projects/{pid}/golden").json()
    assert len(refs) == 2
    r = user_client.post(f"/api/projects/{pid}/golden", json={"doi": "not-a-doi"})
    assert r.status_code == 400

    eq = user_client.post(f"/api/projects/{pid}/equations", json={
        "label": "v1", "concept_ids": [concepts[0]["id"]], "params": {}}).json()

    monkeypatch.setattr(counters, "golden_ref_found",
                        lambda q, p, doi: doi == "10.1000/abc")
    r = user_client.post(f"/api/projects/{pid}/equations/{eq['id']}/golden-check")
    job_id = r.json()["job_id"]
    for _ in range(100):
        job = user_client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in ("done", "failed"):
            break
        time.sleep(0.05)
    assert job["status"] == "done", job.get("error")
    eq = user_client.get(f"/api/projects/{pid}/equations").json()[0]
    assert eq["golden_results"]["found"] == 1
    assert eq["golden_results"]["total"] == 2
    assert eq["golden_results"]["missing"] == ["10.1000/xyz"]
    # the retrieved papers come back identified, not as bare DOIs (here the
    # Crossref lookup found nothing, so the title stands in for the authors)
    assert eq["golden_results"]["found_refs"] == [
        {"doi": "10.1000/abc", "citation": "T1"}]


CROSSREF_MSG = {
    "author": [{"family": "Steinberger", "given": "Fabius"},
               {"family": "Schroeter", "given": "Ronald"},
               {"family": "Watling", "given": "Christopher N."}],
    "issued": {"date-parts": [[2017]]},
    "published-print": {"date-parts": [[2017, 9]]},
    "title": ["From road distraction to safe driving."],
    "container-title": ["Computers in Human Behavior"],
    "volume": "75", "issue": "2", "page": "714-726",
    "DOI": "10.1016/j.chb.2017.06.019",
}


def test_format_apa():
    from app.services.equations.apa import format_apa
    apa = format_apa(CROSSREF_MSG)
    assert apa == ("Steinberger, F., Schroeter, R., & Watling, C. N. (2017). "
                   "From road distraction to safe driving. "
                   "Computers in Human Behavior, 75(2), 714-726. "
                   "https://doi.org/10.1016/j.chb.2017.06.019")


def test_format_apa_minimal():
    from app.services.equations.apa import format_apa
    assert format_apa({"title": ["Only a title"]}) == "(n.d.). Only a title."


def test_short_citation():
    from app.services.equations.apa import format_apa, short_citation
    # 3+ authors -> et al.; the APA string is the only input needed
    assert short_citation(format_apa(CROSSREF_MSG)) == "Steinberger et al. (2017)"
    two = {**CROSSREF_MSG, "author": CROSSREF_MSG["author"][:2]}
    assert short_citation(format_apa(two)) == "Steinberger & Schroeter (2017)"
    one = {**CROSSREF_MSG, "author": CROSSREF_MSG["author"][:1]}
    assert short_citation(format_apa(one)) == "Steinberger (2017)"
    # institutional author, and a compound family name
    org = {**CROSSREF_MSG, "author": [{"name": "World Health Organization"}]}
    assert short_citation(format_apa(org)) == "World Health Organization (2017)"
    dutch = {**CROSSREF_MSG,
             "author": [{"family": "van der Berg", "given": "Jan Willem"},
                        {"family": "Doe", "given": "A."}]}
    assert short_citation(format_apa(dutch)) == "van der Berg & Doe (2017)"
    # 20+ authors: APA elides the middle, the lead author still comes through
    many = {**CROSSREF_MSG,
            "author": [{"family": f"N{i}", "given": "X"} for i in range(25)]}
    assert short_citation(format_apa(many)) == "N0 et al. (2017)"


def test_short_citation_without_authors():
    from app.services.equations.apa import short_citation
    # no author list in the APA string -> the title carries the identification
    assert short_citation("(n.d.). Only a title.", title="Only a title") == \
        "Only a title (n.d.)"
    # nothing was ever fetched for this DOI: year and title from the row
    assert short_citation("", year=2020, title="A paper") == "A paper (2020)"
    assert short_citation("", doi="10.1/x") == "10.1/x"
    assert short_citation("", title="w " * 60).endswith("…")


def test_golden_add_enriches_apa(user_client, project, monkeypatch):
    monkeypatch.setattr("app.api.equations.fetch_reference",
                        lambda doi: {"title": "T", "year": 2017, "apa": "Full APA ref."})
    r = user_client.post(f"/api/projects/{project['id']}/golden",
                         json={"doi": "10.1016/j.chb.2017.06.019"})
    body = r.json()
    assert body["apa"] == "Full APA ref."
    assert body["title"] == "T" and body["year"] == 2017


def test_golden_add_survives_lookup_failure(user_client, project, monkeypatch):
    monkeypatch.setattr("app.api.equations.fetch_reference", lambda doi: {})
    r = user_client.post(f"/api/projects/{project['id']}/golden",
                         json={"doi": "10.1/xx"})
    assert r.status_code == 200
    assert r.json()["apa"] == ""


def test_propose_from_protocol(user_client, project, monkeypatch):
    pid = project["id"]
    # a protocol with content + an existing concept that must not be duplicated
    user_client.post(f"/api/projects/{pid}/protocols/upload",
                     files={"file": ("p.md", b"# P\n\nRQ here", "text/markdown")})
    protocols = user_client.get(f"/api/projects/{pid}/protocols").json()
    user_client.put(f"/api/projects/{pid}/protocols/{protocols[0]['id']}", json={
        "protocol_md": "# P\n\n## Research questions\n1. Does X improve Y?",
        "criteria": [{"code": "I1", "type": "include", "label": "a", "description": ""}]})
    user_client.post(f"/api/projects/{pid}/concepts",
                     json={"name": "Intervention", "keywords": ["x"]})
    user_client.put("/api/llm/credentials", json={
        "provider": "anthropic", "api_key": "sk-ant-fake-key-123"})

    class FakeProvider:
        model = "claude-fake"

        def generate_json(self, messages, json_schema, system=None, max_tokens=4096):
            from app.services.llm.base import LLMResult
            assert "Does X improve Y?" in messages[0]["content"]
            # the concepts already listed reach the model, so it can complete
            # them instead of proposing near-duplicates
            assert "- Intervention: x" in messages[0]["content"]
            return LLMResult(text="{}", data={
                "research_question": "Does X improve Y in adults?",
                "concepts": [
                    {"name": "Intervention", "keywords": ["x", "extra"]},  # merged
                    {"name": "Outcome", "description": "Y",
                     "keywords": ["improvement", "gain"]},
                ],
            })

    monkeypatch.setattr("app.api.concepts.open_provider_chain", lambda *a, **kw: FakeProvider())
    r = user_client.post(f"/api/projects/{pid}/concepts/propose")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["research_question"] == "Does X improve Y in adults?"
    assert [c["name"] for c in body["created"]] == ["Outcome"]
    assert [c["name"] for c in body["enriched"]] == ["Intervention"]

    concepts = user_client.get(f"/api/projects/{pid}/concepts").json()
    assert [c["name"] for c in concepts] == ["Intervention", "Outcome"]
    # the reviewers' own keyword is kept, the new one appended
    assert concepts[0]["keywords"] == ["x", "extra"]
    projects = user_client.get("/api/projects").json()
    assert projects[0]["research_question"] == "Does X improve Y in adults?"


def test_suggest_keywords_gets_the_full_context(user_client, project, concepts,
                                                monkeypatch):
    """An imported-but-not-validated protocol is still context, and the model
    is told the research question and the other concepts' axes."""
    pid = project["id"]
    user_client.post(f"/api/projects/{pid}/protocols/upload",
                     files={"file": ("p.md", b"# P", "text/markdown")})
    protocols = user_client.get(f"/api/projects/{pid}/protocols").json()
    user_client.put(f"/api/projects/{pid}/protocols/{protocols[0]['id']}", json={
        "protocol_md": "# P\n\n## Search concepts\n\n- **Population**: seniors",
        "criteria": []})
    user_client.put(f"/api/projects/{pid}", json={"research_question": "RQ text"})
    user_client.put("/api/llm/credentials", json={
        "provider": "anthropic", "api_key": "sk-ant-fake-key-123"})

    captured = {}

    class FakeProvider:
        model = "claude-fake"

        def generate_json(self, messages, json_schema, system=None, max_tokens=1024):
            from app.services.llm.base import LLMResult
            captured["prompt"] = messages[0]["content"]
            captured["system"] = system
            return LLMResult(text="{}", data={"keywords": ["seniors", "elderly"]})

    monkeypatch.setattr("app.api.concepts.open_provider_chain",
                        lambda *a, **kw: FakeProvider())
    r = user_client.post(f"/api/projects/{pid}/concepts/{concepts[0]['id']}/suggest")
    assert r.status_code == 200, r.text
    assert "Search concepts" in captured["system"]      # unvalidated draft used
    assert "RQ text" in captured["prompt"]
    assert "Intervention" in captured["prompt"]          # the other block's axis
    # suggestions are merged, never replacing what the reviewers wrote
    assert r.json()["keywords"] == ["older adults", "elderly", "seniors"]


def test_project_update_research_question(user_client, project):
    r = user_client.put(f"/api/projects/{project['id']}",
                        json={"research_question": "Manual RQ"})
    assert r.status_code == 200
    assert r.json()["research_question"] == "Manual RQ"


def test_reviewer_read_only(user_client, project, concepts):
    pid = project["id"]
    user_client.post("/api/auth/register", json={
        "email": "rev2@example.com", "password": "password123", "display_name": "R"})
    user_client.post("/api/auth/login", json={
        "email": "admin@example.com", "password": "password123"})
    user_client.post(f"/api/projects/{pid}/members",
                     json={"email": "rev2@example.com", "role": "reviewer"})
    user_client.post("/api/auth/login", json={
        "email": "rev2@example.com", "password": "password123"})
    assert user_client.get(f"/api/projects/{pid}/concepts").status_code == 200
    r = user_client.post(f"/api/projects/{pid}/concepts",
                         json={"name": "X", "keywords": []})
    assert r.status_code == 403
    r = user_client.post(f"/api/projects/{pid}/golden", json={"doi": "10.1/1"})
    assert r.status_code == 403


# ---- AI strategy advice (B4) --------------------------------------------------------

def test_advise_from_first_variant_uses_golden_metadata(
        user_client, project, concepts, monkeypatch):
    """The advisor works from the FIRST variant on, and the golden references
    (title + cached abstract, fetched from the DOI) feed its prompt."""
    pid = project["id"]
    # no variant yet -> 400
    r = user_client.post(f"/api/projects/{pid}/equations/advise")
    assert r.status_code == 400

    monkeypatch.setattr(
        "app.services.equations.golden_meta.fetch_abstract",
        lambda doi, timeout=8.0: "Cognitive load rises in virtual exergames")
    r = user_client.post(f"/api/projects/{pid}/golden",
                         json={"doi": "10.1/gold", "title": "Golden paper",
                               "year": 2023})
    assert r.status_code == 200

    assert user_client.post(f"/api/projects/{pid}/equations", json={
        "label": "broad",
        "concept_ids": [concepts[0]["id"]]}).status_code == 200

    captured = {}

    class Advisor:
        model = "claude-fake"

        def generate_json(self, messages, json_schema, system=None,
                          max_tokens=4096):
            from app.services.llm.base import LLMResult
            captured["prompt"] = messages[0]["content"]
            captured["system"] = system
            return LLMResult(text="{}", data={
                "recommended_label": "broad",
                "rationale": "Add the missing terminology.",
                "per_variant": [{"label": "broad", "verdict": "workable"}],
                "improvements": ["add 'exergame' to the intervention block"]})

    user_client.put("/api/llm/credentials", json={
        "provider": "anthropic", "api_key": "sk-ant-fake-key-123"})
    monkeypatch.setattr("app.services.llm.credentials.open_provider_chain",
                        lambda *a, **kw: Advisor())
    r = user_client.post(f"/api/projects/{pid}/equations/advise")
    assert r.status_code == 200, r.text
    # golden metadata (title + abstract from the DOI) reached the model
    assert "Golden paper" in captured["prompt"]
    assert "Cognitive load rises in virtual exergames" in captured["prompt"]
    # single-variant mode: critique, not comparison
    assert "ONE variant" in captured["system"]


def test_advise_compares_variants(user_client, project, concepts, monkeypatch):
    pid = project["id"]
    # no variant at all -> 400
    r = user_client.post(f"/api/projects/{pid}/equations/advise")
    assert r.status_code == 400

    for label, ids in [("broad", [concepts[0]["id"]]),
                       ("narrow", [c["id"] for c in concepts])]:
        assert user_client.post(f"/api/projects/{pid}/equations", json={
            "label": label, "concept_ids": ids}).status_code == 200
    eq = user_client.get(f"/api/projects/{pid}/equations").json()[0]
    user_client.post(f"/api/projects/{pid}/equations/{eq['id']}/counts/manual",
                     json={"database": "wos", "count": 1234})
    user_client.put("/api/llm/credentials", json={
        "provider": "anthropic", "api_key": "sk-ant-fake-key-123"})

    captured = {}

    class Advisor:
        model = "claude-fake"

        def generate_json(self, messages, json_schema, system=None,
                          max_tokens=4096):
            from app.services.llm.base import LLMResult
            captured["prompt"] = messages[0]["content"]
            return LLMResult(text="{}", data={
                "recommended_label": "narrow",
                "rationale": "Counts are workable and recall holds.",
                "per_variant": [
                    {"label": "broad", "verdict": "too many results"},
                    {"label": "narrow", "verdict": "good balance"}],
                "improvements": ["add synonym 'exergame'"]})

    monkeypatch.setattr("app.services.llm.credentials.open_provider_chain",
                        lambda *a, **kw: Advisor())
    r = user_client.post(f"/api/projects/{pid}/equations/advise")
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["recommended_label"] == "narrow"
    assert len(data["per_variant"]) == 2
    # the tested counts reach the model
    assert "1234" in captured["prompt"] and "wos" in captured["prompt"]

    # a hallucinated label is blanked, the rest of the advice kept
    class Hallucinating(Advisor):
        def generate_json(self, messages, json_schema, system=None,
                          max_tokens=4096):
            from app.services.llm.base import LLMResult
            return LLMResult(text="{}", data={
                "recommended_label": "does-not-exist", "rationale": "…",
                "per_variant": [], "improvements": []})

    monkeypatch.setattr("app.services.llm.credentials.open_provider_chain",
                        lambda *a, **kw: Hallucinating())
    r = user_client.post(f"/api/projects/{pid}/equations/advise")
    assert r.json()["recommended_label"] == ""
