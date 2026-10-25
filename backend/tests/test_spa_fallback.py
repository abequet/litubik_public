from pathlib import Path

import pytest

DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"


@pytest.mark.skipif(not DIST.exists(), reason="frontend not built")
def test_deep_link_serves_index_html(client):
    r = client.get("/projects/1/search")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert "<div id=" in r.text  # the SPA shell, not a JSON 404


@pytest.mark.skipif(not DIST.exists(), reason="frontend not built")
def test_api_404_stays_json(client):
    r = client.get("/api/definitely-not-a-route")
    assert r.status_code == 404
    assert r.json()["detail"] == "Not Found"
