"""Chantier 11 — thematic map: the clustering engine on a synthetic corpus
with three obvious topics, the run job and its API (points carry the
screening status, history, CSV), manual and AI labels (fake provider)."""
import random
import time

import pytest

from app.services.llm.base import LLMResult
from app.services.topics import service
from app.services.topics.engine import compute_topics, record_keywords

TOPICS = {
    "driving": ["driving simulator", "driver behaviour", "road safety", "vehicle",
                "steering", "speed", "lane keeping", "crash risk", "traffic"],
    "nutrition": ["dietary intake", "obesity", "calorie", "vitamin", "food",
                  "nutrition education", "body mass index", "meal", "sugar"],
    "software": ["software testing", "unit tests", "code review", "bug", "refactoring",
                 "continuous integration", "programming", "compiler", "developer"],
}


def _docs(n_per_topic=12, seed=1):
    rng = random.Random(seed)
    docs = []
    i = 0
    for topic, words in TOPICS.items():
        for _ in range(n_per_topic):
            picked = rng.sample(words, 5)
            docs.append({"id": i, "topic": topic,
                         "title": f"{NAMES[(i * 7) % len(NAMES)]} report {i} on "
                                  f"{picked[0]}, {picked[1]}, {picked[2]} and {picked[3]}",
                         "abstract": " ".join(rng.choice(words) for _ in range(40)),
                         "keywords": picked[4:]})
            i += 1
    return docs


def test_engine_recovers_three_topics():
    docs = _docs()
    out = compute_topics(docs)
    assert out["n_docs"] == 36 and out["projection"] == "tsne"
    assert out["k"] == 3 and out["silhouette"] > 0.3
    # every cluster is pure: one topic per cluster
    by_cluster = {}
    for p, d in zip(out["points"], docs):
        by_cluster.setdefault(p["cluster"], set()).add(d["topic"])
        assert -1 <= p["x"] <= 1 and -1 <= p["y"] <= 1
    assert all(len(topics) == 1 for topics in by_cluster.values())
    terms = {c["id"]: c["terms"] for c in out["clusters"]}
    assert all(1 <= len(t) <= 8 for t in terms.values())
    assert all(c["size"] == 12 for c in out["clusters"])
    # a requested k is honoured
    assert compute_topics(docs, k_requested=5)["k"] == 5


def test_clusters_are_regions_of_the_map():
    """Clusters are cut on the 2-D layout: a dot's nearest neighbours on
    the map share its colour, clusters are numbered by decreasing size and
    the layout fills [-1, 1] on both axes (robust rescale, outliers
    clipped)."""
    docs = _docs(n_per_topic=30, seed=5)
    # one topic is made bigger so the numbering has something to order
    docs = docs[:30] + docs[30:45] + docs[60:90]
    out = compute_topics(docs, k_requested=3)
    sizes = [c["size"] for c in out["clusters"]]
    assert sizes == sorted(sizes, reverse=True)
    xs = [p["x"] for p in out["points"]]
    ys = [p["y"] for p in out["points"]]
    assert min(xs) == -1 and max(xs) == 1 and min(ys) == -1 and max(ys) == 1
    agree = 0
    for p in out["points"]:
        near = sorted(out["points"], key=lambda q: (q["x"] - p["x"]) ** 2 + (q["y"] - p["y"]) ** 2)[1:6]
        agree += sum(q["cluster"] == p["cluster"] for q in near)
    assert agree / (5 * len(docs)) > 0.95


def test_engine_guards():
    with pytest.raises(ValueError):
        compute_topics(_docs(n_per_topic=1))
    assert record_keywords("TY  - JOUR\nKW  - alpha\nKW  - beta gamma\nER  - ") == \
        ["alpha", "beta gamma"]


NAMES = ["Abbott", "Baker", "Chen", "Diaz", "Evans", "Fischer", "Garcia", "Hughes",
         "Ito", "Jones", "Khan", "Lopez", "Meyer", "Nguyen", "Okafor", "Patel",
         "Quinn", "Rossi", "Silva", "Tanaka", "Usman", "Vogel", "Weber", "Xu",
         "Yilmaz", "Zhang", "Andersen", "Brown", "Costa", "Dubois", "Eriksen",
         "Fontaine", "Gomez", "Haddad", "Ivanov", "Jansen"]


def _ris(docs):
    # distinct first authors: the dedup pairs near-identical titles when the
    # first author and year agree, which synthetic docs would otherwise trip
    return "".join(
        f"TY  - JOUR\nTI  - {d['title']}\nAU  - {NAMES[d['id'] % len(NAMES)]}, A.\n"
        f"PY  - {2005 + d['id'] % 15}\n"
        f"AB  - {d['abstract']}\n" + "".join(f"KW  - {k}\n" for k in d["keywords"])
        + f"DO  - 10.5/t.{d['id']}\nER  - \n" for d in docs)


def _await(client, job_id):
    for _ in range(600):
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in ("done", "failed"):
            return job
        time.sleep(0.05)
    raise AssertionError("job never finished")


@pytest.fixture
def project(user_client):
    project = user_client.post("/api/projects", json={"name": "themes"}).json()
    pid = project["id"]
    r = user_client.post(f"/api/projects/{pid}/imports/upload",
                         files={"file": ("s.ris", _ris(_docs()).encode(), "text/plain")},
                         data={"source_name": "pubmed", "source_type": "database"})
    assert r.status_code == 200, r.text
    _await(user_client, user_client.post(f"/api/projects/{pid}/dedup/run").json()["job_id"])
    return project


def test_run_api_and_labels(user_client, project, monkeypatch):
    pid = project["id"]
    base = f"/api/projects/{pid}/topics"
    empty = user_client.get(base).json()
    assert empty["run"] is None and empty["sizes"] == {
        "unique": 36, "ta_included": 0, "ft_included": 0}
    # too small a scope is refused up front
    r = user_client.post(f"{base}/run", json={"scope": "ft_included"})
    assert r.status_code == 400

    r = user_client.post(f"{base}/run", json={"scope": "unique"})
    assert r.status_code == 200, r.text
    job = _await(user_client, r.json()["job_id"])
    assert job["status"] == "done", job["error"]
    assert job["result"]["k"] == 3

    data = user_client.get(base).json()
    run = data["run"]
    assert run["n_docs"] == 36 and run["k"] == 3 and run["scope"] == "unique"
    assert len(run["points"]) == 36 and len(run["clusters"]) == 3
    assert {p["status"] for p in run["points"]} == {"undecided"}
    assert all(p["title"] and p["author"].endswith(", A.") for p in run["points"])
    assert len(data["history"]) == 1 and data["history"][0]["id"] == run["id"]

    # manual label
    r = user_client.put(f"{base}/{run['id']}/clusters/0", json={"label": "Driving"})
    assert r.status_code == 200
    c0 = next(c for c in r.json()["clusters"] if c["id"] == 0)
    assert c0["label"] == "Driving" and c0["label_is_ai"] is False
    assert user_client.put(f"{base}/{run['id']}/clusters/9",
                           json={"label": "x"}).status_code == 404

    # AI labels through a fake provider: provenance kept, manual label overwritten
    class FakeProvider:
        name = "openai"
        model = "fake-model"

        def generate_json(self, messages, json_schema, system=None, max_tokens=0):
            assert "Cluster 0" in messages[0]["content"] and "terms:" in messages[0]["content"]
            return LLMResult(text="", tokens_input=100, tokens_output=20,
                             data={"labels": [{"cluster": i, "label": f"Topic {i}"}
                                              for i in range(3)]})

    monkeypatch.setattr(service, "open_provider_chain",
                        lambda db, project_id, **kw: FakeProvider())
    assert user_client.get(f"{base}/{run['id']}/label-estimate").json()["cost"] is None
    r = user_client.post(f"{base}/{run['id']}/label")
    assert r.status_code == 200, r.text
    assert [c["label"] for c in r.json()["clusters"]] == ["Topic 0", "Topic 1", "Topic 2"]
    assert all(c["label_is_ai"] for c in r.json()["clusters"])
    assert r.json()["cost"]["provider"] == "openai"
    assert user_client.get(base).json()["run"]["label_model"] == "fake-model"

    # CSV carries the assignment
    csv_text = user_client.get(f"{base}/{run['id']}/export.csv").text
    lines = csv_text.strip().splitlines()
    assert lines[0].lstrip("﻿").startswith("record_id,doi,title,year,cluster,cluster_label")
    assert len(lines) == 37 and "Topic 0" in csv_text

    # a second run with a fixed k becomes the latest; the first stays in history
    job = _await(user_client, user_client.post(
        f"{base}/run", json={"scope": "unique", "k": 4}).json()["job_id"])
    assert job["status"] == "done", job["error"]
    data = user_client.get(base).json()
    assert data["run"]["k"] == 4 and len(data["history"]) == 2
    first = user_client.get(f"{base}?run_id={run['id']}").json()["run"]
    assert first["id"] == run["id"] and first["k"] == 3
    assert user_client.delete(f"{base}/{run['id']}").status_code == 200
    assert len(user_client.get(base).json()["history"]) == 1


def test_scope_follows_screening(user_client, project):
    """Title/abstract includes define ta_included; the map marks decisions."""
    pid = project["id"]
    me = user_client.get("/api/auth/me").json()
    r = user_client.put(f"/api/projects/{pid}/screening/config", json={
        "stage": "ta", "allocation": "all", "conflict_resolution": "consensus",
        "ai_enabled": False, "reviewer_ids": [me["id"]]})
    assert r.status_code == 200, r.text
    assert user_client.post(f"/api/projects/{pid}/screening/start").status_code == 200
    records = user_client.get(f"/api/projects/{pid}/records?page_size=100").json()["items"]
    for rec in records[:8]:
        user_client.post(f"/api/projects/{pid}/screening/vote",
                         json={"record_id": rec["id"], "decision": "include"})
    for rec in records[8:12]:
        user_client.post(f"/api/projects/{pid}/screening/vote",
                         json={"record_id": rec["id"], "decision": "exclude"})
    sizes = user_client.get(f"/api/projects/{pid}/topics").json()["sizes"]
    assert sizes == {"unique": 36, "ta_included": 8, "ft_included": 0}
    job = _await(user_client, user_client.post(
        f"/api/projects/{pid}/topics/run", json={"scope": "unique"}).json()["job_id"])
    assert job["status"] == "done", job["error"]
    points = user_client.get(f"/api/projects/{pid}/topics").json()["run"]["points"]
    counts = {}
    for p in points:
        counts[p["status"]] = counts.get(p["status"], 0) + 1
    assert counts == {"include": 8, "exclude": 4, "undecided": 24}
    job = _await(user_client, user_client.post(
        f"/api/projects/{pid}/topics/run", json={"scope": "ta_included"}).json()["job_id"])
    assert job["status"] == "done", job["error"]
    assert user_client.get(f"/api/projects/{pid}/topics").json()["run"]["n_docs"] == 8
