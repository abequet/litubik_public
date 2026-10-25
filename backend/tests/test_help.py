"""Help/FAQ endpoints (M4): topic list and markdown content, en + fr."""


def test_help_requires_auth(client):
    assert client.get("/api/help/en").status_code == 401


def test_topics_listed_in_both_languages(user_client):
    en = user_client.get("/api/help/en").json()
    fr = user_client.get("/api/help/fr").json()
    assert len(en) >= 5
    # same reference list (English filenames), localized titles
    assert [topic["slug"] for topic in en] == [topic["slug"] for topic in fr]
    slugs = [topic["slug"] for topic in en]
    assert slugs == sorted(slugs)  # NN- prefix ordering
    assert any(topic["slug"].endswith("faq") for topic in en)


def test_topic_content_served(user_client):
    slug = user_client.get("/api/help/en").json()[0]["slug"]
    page = user_client.get(f"/api/help/en/{slug}").json()
    assert page["slug"] == slug
    assert page["content"].startswith("# ")
    assert page["title"] in page["content"]
    fr_page = user_client.get(f"/api/help/fr/{slug}").json()
    assert fr_page["content"]  # localized or english fallback


def test_unknown_language_and_traversal_rejected(user_client):
    assert user_client.get("/api/help/de").status_code == 404
    assert user_client.get("/api/help/en/nope").status_code == 404
    assert user_client.get("/api/help/en/..%2F..%2Fsecrets").status_code == 404
