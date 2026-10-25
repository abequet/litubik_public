# SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Batch AI suggestion for title/abstract screening.

Pre-computes the on-click AI suggestion (title+abstract assessed against the
protocol's inclusion/exclusion criteria) for every record a reviewer still has
to vote on in the round, so the recommendation is already cached under each
article when they reach it. Same engine and cache as the per-record button
(`get_or_create_suggestion`) — proposals only, never votes.

Distinct from AI *title triage* (`triage.py`), which proposes bulk exclusions
from titles alone above a confidence threshold.
"""
from app.core.db import SessionLocal
from app.models import Assignment, Conflict, Record, ScreeningConfig, User, Vote
from app.services.llm import pricing
from app.services.llm.base import LLMError
from app.services.llm.credentials import resolve_model
from app.services.protocol.service import validated_protocol
from app.services.screening.ai import (
    _EST_OUTPUT_TOKENS, _EST_PROMPT_CHARS, get_or_create_suggestion,
)
from app.workers.runner import register_handler


def batch_candidate_ids(db, config: ScreeningConfig, user_id: int) -> list[int]:
    """The reviewer's records still to vote on in this round: assigned to them,
    without their own human vote, and not globally resolved (e.g. an admin AI
    title-triage exclusion resolves a record for everyone)."""
    assigned = {rid for (rid,) in db.query(Assignment.record_id)
                .filter_by(config_id=config.id, user_id=user_id)}
    voted = {rid for (rid,) in db.query(Vote.record_id)
             .filter_by(project_id=config.project_id, stage=config.stage,
                        round=config.round, voter_user_id=user_id, is_ai=False)}
    resolved = {rid for (rid,) in db.query(Conflict.record_id)
                .filter_by(project_id=config.project_id, stage=config.stage,
                           round=config.round, status="resolved")}
    return sorted(rid for rid in assigned
                  if rid not in voted and rid not in resolved)


def needs_suggestion(db, config: ScreeningConfig, ids: list[int]) -> list[int]:
    """Subset of `ids` with no AI suggestion cached yet (the ones that will
    actually cost an LLM call)."""
    if not ids:
        return []
    have = {rid for (rid,) in db.query(Vote.record_id)
            .filter(Vote.project_id == config.project_id,
                    Vote.stage == config.stage, Vote.round == config.round,
                    Vote.is_ai.is_(True), Vote.record_id.in_(ids))}
    return [rid for rid in ids if rid not in have]


def estimate_batch(db, config: ScreeningConfig, user_id: int) -> dict:
    """Records still to suggest + a rough total cost, for the confirm dialog."""
    candidates = batch_candidate_ids(db, config, user_id)
    todo = needs_suggestion(db, config, candidates)
    protocol = validated_protocol(db, config.project_id)
    proto_chars = len((protocol.protocol_md or "")[:12000]) if protocol else 0
    chars = 0
    if todo:
        for r in db.query(Record).filter(Record.id.in_(todo)):
            chars += _EST_PROMPT_CHARS + proto_chars + len(r.abstract or "") + 400
    out = {"n_candidates": len(candidates), "n_to_generate": len(todo),
           "already_suggested": len(candidates) - len(todo)}
    model = resolve_model(db, config.project_id, feature="screening_ta_suggest")
    if model is not None and todo:
        provider, model_id = model
        out["cost"] = {**pricing.cost_breakdown(
            provider, model_id, pricing.chars_to_tokens(chars),
            _EST_OUTPUT_TOKENS * len(todo)), "estimated": True}
    return out


@register_handler("ta_ai_batch")
def ta_ai_batch_handler(job_id: int, params: dict, progress) -> dict:
    """Generate the AI suggestion for each of the reviewer's not-yet-voted
    records that has none yet. Cached as is_ai Votes — nothing is auto-voted;
    each suggestion then shows under its article like the per-record button."""
    project_id = params["project_id"]

    with SessionLocal() as db:
        config = (db.query(ScreeningConfig)
                  .filter_by(project_id=project_id, stage="ta",
                             round=params["round"], status="active").first())
        if config is None:
            raise LLMError("Start the title/abstract screening round first")
        if not config.ai_enabled or not config.ai_batch:
            raise LLMError("Batch AI suggestion is disabled for this round")
        todo = needs_suggestion(
            db, config, batch_candidate_ids(db, config, params["user_id"]))
        requester = db.get(User, params["user_id"])
        generated_by = requester.email if requester else None

    generated = failed = 0
    last_error = ""
    total = len(todo)
    for i, rid in enumerate(todo):
        progress(i, total, f"AI-screening title/abstract {i + 1}/{total}...")
        with SessionLocal() as db:
            config = (db.query(ScreeningConfig)
                      .filter_by(project_id=project_id, stage="ta",
                                 round=params["round"], status="active").first())
            record = db.get(Record, rid)
            if config is None or record is None:
                continue
            try:
                get_or_create_suggestion(db, config, record,
                                         generated_by=generated_by,
                                         user_id=params["user_id"])
                generated += 1
            except LLMError as e:
                failed += 1
                last_error = str(e)
    progress(total, total, "Done")
    return {"generated": generated, "failed": failed, "n_todo": total,
            "last_error": last_error}
