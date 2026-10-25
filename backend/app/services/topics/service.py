# SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Thematic map of the corpus: corpus selection by scope, the background job
that stores a run, AI cluster labelling (human-editable, provenance kept)
and the CSV export."""
import csv
import io

from sqlalchemy.orm import Session

from app.core.csvsafe import safe_row
from app.core.db import SessionLocal
from app.models import CorpusTopicRun, Record, ScreeningConfig
from app.services.llm import pricing
from app.services.llm.base import LLMError
from app.services.llm.credentials import open_provider_chain, resolve_model
from app.services.llm.prompts import resolve_prompt
from app.services.screening.core import screening_outcomes
from app.services.topics.engine import compute_topics, record_keywords
from app.workers.runner import register_handler

SCOPES = ("unique", "ta_included", "ft_included")
SAMPLE_TITLES = 5
LABEL_OUT_TOKENS = 600


def _stage_decisions(db: Session, project_id: int, stage: str) -> dict[int, str]:
    out: dict[int, str] = {}
    for config in (db.query(ScreeningConfig)
                   .filter_by(project_id=project_id, stage=stage, status="active")
                   .order_by(ScreeningConfig.round)):
        out.update(screening_outcomes(db, config))
    return out


def corpus_for_scope(db: Session, project_id: int, scope: str
                     ) -> tuple[list[Record], dict[int, str]]:
    """The unique records of the scope, and every record's current decision
    (title/abstract outcome overridden by the full-text one) — the map
    shows the decision as a marker so gaps are visible."""
    records = (db.query(Record)
               .filter_by(project_id=project_id, dedup_status="unique")
               .order_by(Record.id).all())
    ta = _stage_decisions(db, project_id, "ta")
    ft = _stage_decisions(db, project_id, "ft")
    status: dict[int, str] = {}
    for r in records:
        if r.ft_forced_included:
            status[r.id] = "include"
        else:
            status[r.id] = ft.get(r.id) or ta.get(r.id, "undecided")
    if scope == "ta_included":
        records = [r for r in records if ta.get(r.id) == "include"
                   or r.ft_forced_included]
    elif scope == "ft_included":
        records = [r for r in records if ft.get(r.id) == "include"
                   or r.ft_forced_included]
    return records, status


@register_handler("corpus_topics")
def corpus_topics_handler(job_id: int, params: dict, progress) -> dict:
    project_id = int(params["project_id"])
    scope = params.get("scope") or "unique"
    k_requested = params.get("k") or None

    progress(0, 0, "Collecting the corpus...")
    with SessionLocal() as db:
        records, status = corpus_for_scope(db, project_id, scope)
        docs = [{"id": r.id, "title": r.title, "abstract": r.abstract,
                 "keywords": record_keywords(r.raw_ris)} for r in records]

    progress(0, len(docs), f"Mapping {len(docs)} documents (TF-IDF, t-SNE, k-means)...")
    result = compute_topics(docs, k_requested)
    points = [{"record_id": p["id"], "x": p["x"], "y": p["y"],
               "cluster": p["cluster"], "status": status.get(p["id"], "undecided")}
              for p in result["points"]]
    clusters = [{**c, "label": "", "label_is_ai": False} for c in result["clusters"]]

    with SessionLocal() as db:
        run = CorpusTopicRun(
            project_id=project_id, scope=scope, k_requested=k_requested,
            k=result["k"], n_docs=result["n_docs"], silhouette=result["silhouette"],
            projection=result["projection"],
            params={"scope": scope, "k": k_requested, "ngram": "1-2",
                    "svd_dims": 100, "stop_words": "en+fr",
                    "clustering": "layout"},
            result={"points": points, "clusters": clusters},
            created_by=params.get("user_id"))
        db.add(run)
        db.commit()
        run_id = run.id
    progress(len(docs), len(docs), "Done")
    return {"run_id": run_id, "k": result["k"], "n_docs": result["n_docs"]}


# -- AI labels ----------------------------------------------------------------------

LABELS_SCHEMA = {
    "type": "object",
    "properties": {
        "labels": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"cluster": {"type": "integer"},
                               "label": {"type": "string"}},
                "required": ["cluster", "label"],
            },
        },
    },
    "required": ["labels"],
}


def _clusters_block(db: Session, run: CorpusTopicRun) -> str:
    by_cluster: dict[int, list[int]] = {}
    for p in run.result.get("points", []):
        by_cluster.setdefault(int(p["cluster"]), []).append(int(p["record_id"]))
    lines = []
    for c in run.result.get("clusters", []):
        ids = by_cluster.get(int(c["id"]), [])[:SAMPLE_TITLES]
        titles = [t for (t,) in db.query(Record.title)
                  .filter(Record.id.in_(ids)).all()] if ids else []
        lines.append(f"Cluster {c['id']} ({c['size']} documents)\n"
                     f"  terms: {', '.join(c.get('terms', []))}\n"
                     + "".join(f"  - {t[:160]}\n" for t in titles))
    return "\n".join(lines)


def estimate_label_cost(db: Session, run: CorpusTopicRun) -> dict | None:
    model = resolve_model(db, run.project_id, feature="results_topics")
    if model is None:
        return None
    provider, model_id = model
    chars = len(resolve_prompt(db, run.project_id, "results_topics")) \
        + len(_clusters_block(db, run))
    return {**pricing.cost_breakdown(provider, model_id,
                                     pricing.chars_to_tokens(chars), LABEL_OUT_TOKENS),
            "estimated": True}


def label_clusters(db: Session, run: CorpusTopicRun, user_id: int | None) -> dict:
    """Ask the configured LLM for one label per cluster; stored as AI
    suggestions (label_is_ai) the team can overwrite."""
    provider = open_provider_chain(db, run.project_id, feature="results_topics",
                                   user_id=user_id)
    system = resolve_prompt(db, run.project_id, "results_topics")
    content = ("Name each cluster.\n\n" + _clusters_block(db, run)
               + "\nAnswer with JSON: {\"labels\": [{\"cluster\": id, \"label\": \"...\"}]}")
    result = provider.generate_json([{"role": "user", "content": content}],
                                    json_schema=LABELS_SCHEMA, system=system,
                                    max_tokens=LABEL_OUT_TOKENS)
    data = result.data if isinstance(result.data, dict) else {}
    labels = {int(x["cluster"]): str(x["label"]).strip()[:80]
              for x in data.get("labels", [])
              if isinstance(x, dict) and "cluster" in x and x.get("label")}
    if not labels:
        raise LLMError("The model returned no label — try again")
    clusters = []
    for c in run.result.get("clusters", []):
        if int(c["id"]) in labels:
            c = {**c, "label": labels[int(c["id"])], "label_is_ai": True}
        clusters.append(c)
    cost = pricing.call_cost(provider, result)
    run.result = {**run.result, "clusters": clusters}
    run.label_provider = cost["provider"]
    run.label_model = cost["model"]
    run.label_cost_usd = cost["cost_usd"]
    db.commit()
    return cost


def set_label(db: Session, run: CorpusTopicRun, cluster_id: int, label: str) -> None:
    clusters = []
    found = False
    for c in run.result.get("clusters", []):
        if int(c["id"]) == cluster_id:
            c = {**c, "label": label.strip()[:80], "label_is_ai": False}
            found = True
        clusters.append(c)
    if not found:
        raise ValueError("Cluster not found")
    run.result = {**run.result, "clusters": clusters}
    db.commit()


def export_csv(db: Session, run: CorpusTopicRun) -> str:
    labels = {int(c["id"]): c.get("label", "") for c in run.result.get("clusters", [])}
    terms = {int(c["id"]): "; ".join(c.get("terms", []))
             for c in run.result.get("clusters", [])}
    ids = [int(p["record_id"]) for p in run.result.get("points", [])]
    records = {r.id: r for r in db.query(Record).filter(Record.id.in_(ids)).all()} \
        if ids else {}
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(["record_id", "doi", "title", "year", "cluster", "cluster_label",
                     "cluster_terms", "screening_status", "x", "y"])
    for p in run.result.get("points", []):
        r = records.get(int(p["record_id"]))
        if r is None:
            continue
        writer.writerow(safe_row([
            r.id, r.doi or "", r.title, r.year or "", p["cluster"],
            labels.get(int(p["cluster"]), ""), terms.get(int(p["cluster"]), ""),
            p.get("status", ""), p["x"], p["y"]]))
    return buffer.getvalue()


def run_summary(run: CorpusTopicRun) -> dict:
    return {"id": run.id, "scope": run.scope, "k": run.k, "n_docs": run.n_docs,
            "silhouette": run.silhouette, "projection": run.projection,
            "k_requested": run.k_requested,
            "created_at": run.created_at.isoformat() if run.created_at else "",
            "label_provider": run.label_provider, "label_model": run.label_model}
