"""The review-framing catalogue: internal consistency, safe degradation on
unknown keys, and the context block the AI features append."""
from app.services import framing


def test_every_review_type_points_at_a_framework_and_a_template_that_exist():
    from app.services.extraction.service import TEMPLATES
    for rt in framing.REVIEW_TYPES.values():
        assert rt.default_framework in framing.FRAMEWORKS, rt.key
        assert rt.default_template in TEMPLATES, rt.key


def test_every_framework_has_at_least_one_slot_with_unique_keys():
    for fw in framing.FRAMEWORKS.values():
        assert fw.slots, fw.key
        keys = [s.key for s in fw.slots]
        assert len(keys) == len(set(keys)), fw.key
        assert all(s.label and s.hint for s in fw.slots), fw.key


def test_free_framing_still_carries_one_slot():
    """So the schema builder and the markdown renderer stay branch-free."""
    assert len(framing.framework("free").slots) == 1


def test_unknown_keys_degrade_to_the_defaults_instead_of_raising():
    # a snapshot written by another version must not break the project
    assert framing.framework("nawak").key == framing.DEFAULT_FRAMEWORK
    assert framing.review_type("nawak").key == framing.DEFAULT_REVIEW_TYPE
    assert framing.framework(None).key == framing.DEFAULT_FRAMEWORK
    assert framing.review_type("").key == framing.DEFAULT_REVIEW_TYPE


def test_resolve_accepts_a_missing_project():
    rt, fw = framing.resolve(None)
    assert (rt.key, fw.key) == (framing.DEFAULT_REVIEW_TYPE,
                                framing.DEFAULT_FRAMEWORK)


class _Project:
    def __init__(self, review_type, question_framework):
        self.review_type = review_type
        self.question_framework = question_framework


def test_review_context_names_the_type_the_framework_and_its_slots():
    text = framing.review_context(_Project("best_fit", "spider"))
    assert "SPIDER" in text
    assert "Cooke, Smith & Booth, 2012" in text
    assert "Phenomenon of interest" in text
    assert "Carroll & Booth, 2013" in text
    # the override clause is what lets the shipped PICO prompts stand unedited
    assert "use this framing's vocabulary instead" in text


def test_review_context_of_a_default_project_stays_picos():
    text = framing.review_context(_Project("systematic", "picos"))
    assert "PICOS" in text
    assert "SPIDER" not in text


def test_framings_endpoint_lists_the_catalogue(user_client):
    data = user_client.get("/api/framings").json()
    keys = {r["key"] for r in data["review_types"]}
    assert {"systematic", "best_fit"} <= keys
    spider = next(f for f in data["frameworks"] if f["key"] == "spider")
    assert [s["letter"] for s in spider["slots"]] == ["S", "PI", "D", "E", "R"]
    assert data["default_framework"] == framing.DEFAULT_FRAMEWORK
    # best_fit must carry the note saying what the software does not do
    best_fit = next(r for r in data["review_types"] if r["key"] == "best_fit")
    assert best_fit["tooling_note"]


def test_framings_endpoint_requires_a_login(client):
    assert client.get("/api/framings").status_code == 401
