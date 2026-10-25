# SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
# SPDX-License-Identifier: AGPL-3.0-or-later
"""AI title triage: bulk exclusion proposals from TITLES ONLY.

Many hits of a broad search are visibly off-topic from the title alone. The
reviewer sends every not-yet-voted title of the round to the LLM (with the
protocol and research question as context); the model proposes exclusions it
is confident about (threshold, default 95%). A human reviews the checklist
and validates — depending on the config's `ai_triage` mode the validated
records are globally excluded (audited, admin only) or receive the validating
reviewer's own exclude votes. Records with any human vote are never sent.
"""
from app.core.db import SessionLocal
from app.models import Assignment, Record, ScreeningConfig, TriageControl, Vote
from app.services.llm.base import LLMError
from app.services.llm.credentials import open_provider_chain
from app.services.llm.prompts import resolve_prompt
from app.services.protocol.service import validated_protocol
from app.services.screening.core import (
    eligible_record_ids, record_outcome, screening_outcomes,
)
from app.workers.runner import register_handler

BATCH_SIZE = 100

TRIAGE_SCHEMA = {
    "type": "object",
    "properties": {
        "exclusions": {
            "type": "array",
            "description": "ONLY the papers you are confident should be "
                           "excluded. Omit every paper you are not sure about.",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer",
                           "description": "The paper's id, exactly as given"},
                    "confidence": {
                        "type": "number", "minimum": 0, "maximum": 1,
                        "description": "Your probability that a careful human "
                                       "reviewer would also exclude it"},
                    "reason": {"type": "string",
                               "description": "One short sentence: why the "
                                              "title is off-topic"},
                },
                "required": ["id", "confidence", "reason"],
            },
        },
    },
    "required": ["exclusions"],
}


def control_record_ids(db, config: ScreeningConfig,
                       held_by: int | None = None) -> set[int]:
    """Records held back as triage controls for this round (by everyone, or
    by one validator)."""
    query = (db.query(TriageControl.record_id)
             .filter_by(project_id=config.project_id, stage=config.stage,
                        round=config.round))
    if held_by is not None:
        query = query.filter_by(held_by=held_by)
    return {rid for (rid,) in query}


def candidate_ids(db, config: ScreeningConfig, user_id: int) -> list[int]:
    """Round records with NO human vote at all and no outcome yet — a started
    human judgement is never overridden. In `reviewers` mode, restricted to
    the caller's own assignments (the validation casts THEIR votes). Records
    already held back as controls are never proposed again: a second pass
    would otherwise exclude what the first one deliberately kept."""
    eligible = eligible_record_ids(db, config.project_id, config.stage,
                                   config.round)
    voted = {rid for (rid,) in db.query(Vote.record_id)
             .filter_by(project_id=config.project_id, stage=config.stage,
                        round=config.round, is_ai=False).distinct()}
    decided = set(screening_outcomes(db, config))
    controls = control_record_ids(
        db, config, user_id if config.ai_triage == "reviewers" else None)
    ids = [rid for rid in eligible
           if rid not in voted and rid not in decided and rid not in controls]
    if config.ai_triage == "reviewers":
        mine = {a.record_id for a in db.query(Assignment)
                .filter_by(config_id=config.id, user_id=user_id)}
        ids = [rid for rid in ids if rid in mine]
    return ids


def control_sample_size(n: int, pct: int) -> int:
    """How many of n validated exclusions are held back at pct % (rounded
    half up, so a short list at 10 % still yields one control from 5)."""
    if n <= 0 or pct <= 0:
        return 0
    return min(n, int(n * pct / 100 + 0.5))


def _human_decision(db, config: ScreeningConfig, control: TriageControl) -> str | None:
    """What the humans did with a control: in reviewers mode the holder's own
    vote (the triage would have cast it); otherwise the record's outcome
    (unanimous votes or a resolution). None while undecided."""
    if config.ai_triage == "reviewers":
        vote = (db.query(Vote)
                .filter_by(project_id=config.project_id, stage=config.stage,
                           round=config.round, record_id=control.record_id,
                           voter_user_id=control.held_by, is_ai=False)
                .first())
        return vote.decision if vote else None
    return record_outcome(db, config, control.record_id)


def control_report(db, config: ScreeningConfig,
                   held_by: int | None = None) -> dict:
    """Blind-safe report on the control sample: undecided controls are
    counted but never listed (the reviewers must not learn which titles are
    controls); decided ones come with the AI's and the humans' verdicts."""
    query = (db.query(TriageControl)
             .filter_by(project_id=config.project_id, stage=config.stage,
                        round=config.round))
    if held_by is not None:
        query = query.filter_by(held_by=held_by)
    controls = query.order_by(TriageControl.created_at, TriageControl.id).all()
    from app.services.screening.anonymity import namer_for
    users = namer_for(db, config)  # pseudonyms while the round is anonymous
    rows: list[dict] = []
    pending = confirmed = contradicted = 0
    for c in controls:
        human = _human_decision(db, config, c)
        if human is None:
            pending += 1
            continue
        ok = human == "exclude"
        confirmed += ok
        contradicted += not ok
        record = db.get(Record, c.record_id)
        rows.append({
            "record_id": c.record_id,
            "title": record.title if record else "",
            "authors": (record.authors if record else None) or [],
            "year": record.year if record else None,
            "confidence": c.confidence, "reason": c.reason or "",
            "held_by": users(c.held_by),
            "created_at": c.created_at.isoformat() if c.created_at else "",
            "human": human,
            "status": "confirmed" if ok else "contradicted",
        })
    decided = confirmed + contradicted
    return {
        "total": len(controls), "pending": pending, "decided": decided,
        "confirmed": confirmed, "contradicted": contradicted,
        "agreement_pct": round(100 * confirmed / decided) if decided else None,
        "pct": config.triage_control_pct or 0,
        "rows": rows,
    }


def _context(db, project_id: int) -> str:
    from app.models import Project
    parts = []
    project = db.get(Project, project_id)
    if project is not None and project.research_question:
        parts.append(f"Research question: {project.research_question}")
    protocol = validated_protocol(db, project_id)
    if protocol is not None:
        parts.append("Review protocol:\n" + protocol.protocol_md[:8000])
    if not parts:
        raise LLMError("Validate the protocol (or set the research question) "
                       "first — the triage needs to know the review's topic")
    return "\n\n".join(parts)


# Output per title, measured on a real 3,400-title triage (≈2,000 tokens per
# batch of 100, hidden reasoning included).
_EST_OUTPUT_TOKENS_PER_TITLE = 20


def estimate_triage(db, config: ScreeningConfig, user_id: int) -> dict:
    """Titles the triage would send + a rough total cost, for the confirm
    dialog shown before launching it."""
    from app.services.llm import pricing
    from app.services.llm.credentials import resolve_model
    ids = candidate_ids(db, config, user_id)
    out = {"candidates": len(ids),
           "n_batches": (len(ids) + BATCH_SIZE - 1) // BATCH_SIZE}
    model = resolve_model(db, config.project_id, feature="title_triage")
    if model is None or not ids:
        return out
    try:
        system_chars = (len(resolve_prompt(db, config.project_id, "title_triage"))
                        + len(_context(db, config.project_id)))
    except LLMError:
        system_chars = 0  # no protocol yet: the run itself will say so
    title_chars = sum(len(f"[{rid}] {title or ''}") + 1 for rid, title in
                      db.query(Record.id, Record.title).filter(Record.id.in_(ids)))
    chars = out["n_batches"] * (system_chars + 400) + title_chars
    provider, model_id = model
    out["cost"] = {**pricing.cost_breakdown(
        provider, model_id, pricing.chars_to_tokens(chars),
        _EST_OUTPUT_TOKENS_PER_TITLE * len(ids)), "estimated": True}
    return out


@register_handler("ta_triage")
def ta_triage_handler(job_id: int, params: dict, progress) -> dict:
    """Propose exclusions from titles only. PROPOSALS — nothing is written;
    the reviewer validates a checklist, then /triage/apply does the writing."""
    project_id = params["project_id"]
    threshold = float(params.get("threshold") or 95) / 100.0

    with SessionLocal() as db:
        config = (db.query(ScreeningConfig)
                  .filter_by(project_id=project_id, stage="ta",
                             round=params["round"], status="active").first())
        if config is None:
            raise LLMError("Start the title/abstract screening round first")
        if config.ai_triage == "off":
            raise LLMError("Enable AI title triage in the screening settings")
        ids = candidate_ids(db, config, params["user_id"])
        records = (db.query(Record).filter(Record.id.in_(ids))
                   .order_by(Record.id).all()) if ids else []
        items = [{"id": r.id, "title": r.title, "year": r.year,
                  "author": (r.authors or [""])[0]} for r in records]
        context = _context(db, project_id)
        instructions = resolve_prompt(db, project_id, "title_triage")
        provider = open_provider_chain(db, project_id, feature="title_triage",
                                       user_id=params["user_id"])

    if not items:
        return {"proposals": [], "n_screened": 0,
                "threshold": round(threshold * 100)}

    system = instructions + "\n\n" + context

    proposals: list[dict] = []
    by_id = {item["id"]: item for item in items}
    n_batches = (len(items) + BATCH_SIZE - 1) // BATCH_SIZE
    for b in range(n_batches):
        progress(b, n_batches,
                 f"Screening titles — batch {b + 1}/{n_batches}...")
        batch = items[b * BATCH_SIZE:(b + 1) * BATCH_SIZE]
        prompt = "Titles to pre-screen:\n" + "\n".join(
            f"[{item['id']}] {item['title']}" for item in batch)
        result = provider.generate_json(
            [{"role": "user", "content": prompt}],
            json_schema=TRIAGE_SCHEMA, system=system, max_tokens=8000)
        data = result.data if isinstance(result.data, dict) else {}
        batch_ids = {item["id"] for item in batch}
        for entry in data.get("exclusions") or []:
            if not isinstance(entry, dict):
                continue
            rid = entry.get("id")
            confidence = float(entry.get("confidence") or 0)
            # Keep every proposal the model returns (not just those above the
            # threshold): the result is persisted with the job, so the reviewer
            # can re-threshold the saved list later without re-running the LLM.
            if rid not in batch_ids:
                continue
            item = by_id[rid]
            proposals.append({
                "record_id": rid, "title": item["title"],
                "year": item["year"], "author": item["author"],
                "confidence": round(confidence, 3),
                "reason": str(entry.get("reason", ""))[:300],
            })

    proposals.sort(key=lambda p: -p["confidence"])
    progress(n_batches, n_batches, "Done")
    # `threshold` is the default the UI pre-ticks at; the full proposal set is
    # returned so the slider can re-filter it client-side.
    return {"proposals": proposals, "n_screened": len(items),
            "threshold": round(threshold * 100)}
