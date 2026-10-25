# SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
# SPDX-License-Identifier: AGPL-3.0-or-later
"""What the AI actually did in this review — journal plus outcome evidence.

Two layers, and the difference matters:

- the **journal** (`AiUsage`) says which helper was called, how often, on which
  model, by whom, over which days. It is complete by construction: nothing can
  call a provider without going through the logged chain.
- the **evidence** counts what became of that output: how many suggestions a
  human agreed with, how many AI-prefilled cells were validated, how many bulk
  triage proposals ended up as exclusions. A disclosure that says "AI supported
  screening" without saying that 118 of its 412 suggestions were overruled
  tells the reader much less than one that does.

Both feed the DAISY-style form the author reviews before generating the
statement, so the numbers in the statement are the numbers in the database.
"""
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import (
    AiUsage, Conflict, ExtractionColumn, ExtractionValue, Protocol, Record,
    ScreeningConfig, User, Vote,
)
from app.services.llm import pricing
from app.services.reporting.catalog import (
    ACTIVITIES, ACTIVITY_ORDER, FEATURES,
)
from app.services.screening.core import screening_outcomes

LEVELS = ("none", "low", "medium", "high")


LOCAL_SAFEGUARDS = (
    "All AI calls were made to a locally hosted model (provider \"local\" in "
    "the usage journal): no record, abstract or full text was transmitted to a "
    "third-party service.")


def _level_from_coverage(share: float) -> str:
    """DAISY asks for a level of support per activity. When the activity has a
    natural denominator (records screened, cells filled) the level is measured,
    not guessed."""
    if share <= 0:
        return "none"
    if share < 0.25:
        return "low"
    if share < 0.75:
        return "medium"
    return "high"


def _level_from_calls(n_calls: int) -> str:
    """Fallback for activities with no denominator (one protocol, one strategy
    critique): a single call is 'low', a sustained back-and-forth is not."""
    if n_calls <= 0:
        return "none"
    if n_calls <= 2:
        return "low"
    if n_calls < 20:
        return "medium"
    return "high"


def _usage_rows(db: Session, project_id: int) -> list[dict]:
    rows = (db.query(AiUsage).filter_by(project_id=project_id)
            .order_by(AiUsage.feature, AiUsage.day).all())
    names = dict(db.query(User.id, User.display_name).all())
    by_feature: dict[str, dict] = {}
    for row in rows:
        spec = FEATURES.get(row.feature, {})
        entry = by_feature.setdefault(row.feature, {
            "feature": row.feature,
            "label": spec.get("label", row.feature),
            "activity": spec.get("activity"),
            "stage": spec.get("stage"),
            "inputs": spec.get("inputs", ""),
            "n_calls": 0, "tokens_in": 0, "tokens_out": 0, "cost_usd": 0.0,
            "models": {}, "users": set(), "first_at": None, "last_at": None,
        })
        entry["n_calls"] += row.n_calls
        entry["tokens_in"] += row.tokens_in
        entry["tokens_out"] += row.tokens_out
        entry["cost_usd"] += row.cost_usd
        key = f"{row.provider}:{row.model}" if row.model else row.provider
        entry["models"][key] = entry["models"].get(key, 0) + row.n_calls
        if row.user_id:
            entry["users"].add(names.get(row.user_id, "?"))
        first = row.first_at.isoformat() if row.first_at else None
        last = row.last_at.isoformat() if row.last_at else None
        if first and (entry["first_at"] is None or first < entry["first_at"]):
            entry["first_at"] = first
        if last and (entry["last_at"] is None or last > entry["last_at"]):
            entry["last_at"] = last

    out = []
    for entry in by_feature.values():
        entry["models"] = [{"model": m, "n_calls": n}
                           for m, n in sorted(entry["models"].items(),
                                              key=lambda kv: -kv[1])]
        entry["users"] = sorted(entry["users"])
        entry["cost_label"] = pricing.format_usd(entry["cost_usd"])
        out.append(entry)
    out.sort(key=lambda e: (ACTIVITY_ORDER.index(e["activity"])
                            if e["activity"] in ACTIVITY_ORDER else 99,
                            -e["n_calls"]))
    return out


def _n_revealed_early(db: Session, config: ScreeningConfig) -> int:
    from app.services.reporting.audit import _n_revealed_early as count
    return count(db, config)


def _screening_evidence(db: Session, project_id: int) -> dict:
    """How AI screening output fared against the humans' final decisions."""
    per_stage: dict[str, dict] = {}
    for config in (db.query(ScreeningConfig)
                   .filter_by(project_id=project_id, status="active")):
        entry = per_stage.setdefault(config.stage, {
            "n_ai_suggestions": 0, "n_decided": 0, "n_compared": 0,
            "n_agreed": 0, "n_overruled": 0, "n_ai_maybe": 0,
            # after_vote rounds: votes cast after the reviewer chose to see
            # the suggestion first (the rest were made blind to it)
            "n_revealed_before_vote": 0, "reveal_modes": []})
        if config.ai_reveal not in entry["reveal_modes"]:
            entry["reveal_modes"].append(config.ai_reveal)
        entry["n_revealed_before_vote"] += _n_revealed_early(db, config)
        ai_votes = {v.record_id: v.decision for v in db.query(Vote).filter_by(
            project_id=project_id, stage=config.stage, round=config.round,
            is_ai=True)}
        outcomes = screening_outcomes(db, config)
        entry["n_ai_suggestions"] += len(ai_votes)
        entry["n_decided"] += len(outcomes)
        for record_id, ai_decision in ai_votes.items():
            final = outcomes.get(record_id)
            if final is None:
                continue
            if ai_decision == "maybe":
                entry["n_ai_maybe"] += 1
                continue
            entry["n_compared"] += 1
            if ai_decision == final:
                entry["n_agreed"] += 1
            else:
                entry["n_overruled"] += 1
    return per_stage


def _triage_evidence(db: Session, project_id: int) -> dict:
    """Bulk title triage: only what a human validated is counted anywhere."""
    n_validated = (db.query(func.count(Conflict.id))
                   .filter_by(project_id=project_id, origin="ai_triage",
                              status="resolved").scalar() or 0)
    return {"n_validated_exclusions": n_validated}


def _extraction_evidence(db: Session, project_id: int) -> dict:
    rows = (db.query(ExtractionValue.origin, ExtractionValue.validated,
                     func.count(ExtractionValue.id))
            .join(ExtractionColumn,
                  ExtractionColumn.id == ExtractionValue.column_id)
            .filter(ExtractionColumn.project_id == project_id)
            .group_by(ExtractionValue.origin, ExtractionValue.validated).all())
    n_ai = sum(n for origin, _, n in rows if origin == "ai")
    n_ai_validated = sum(n for origin, validated, n in rows
                         if origin == "ai" and validated)
    n_total = sum(n for _, _, n in rows)
    n_design_ai = (db.query(func.count(Record.id))
                   .filter_by(project_id=project_id, design_origin="ai")
                   .scalar() or 0)
    return {"n_cells": n_total, "n_ai_cells": n_ai,
            "n_ai_cells_validated": n_ai_validated,
            "n_designs_classified_by_ai": n_design_ai}


def _protocol_evidence(db: Session, project_id: int) -> dict:
    latest = (db.query(Protocol).filter_by(project_id=project_id)
              .order_by(Protocol.version.desc()).first())
    if latest is None:
        return {"ai_extracted": False, "validated_by_human": False}
    return {"ai_extracted": bool(latest.generated_with),
            "generated_with": latest.generated_with,
            "validated_by_human": latest.validated_at is not None}


def _default_form(usage: list[dict], evidence: dict) -> dict:
    """The DAISY-style form, pre-answered from the journal.

    Pre-answering is the point: DAISY showed structured prompts make authors
    report where and how much AI was used, which is exactly what they forget.
    Here the app already knows, so the author's job shrinks to checking and
    correcting rather than remembering.
    """
    by_activity: dict[str, dict] = {}
    for entry in usage:
        activity = entry["activity"] or "reporting"
        agg = by_activity.setdefault(activity, {"n_calls": 0, "features": [],
                                                "models": set()})
        agg["n_calls"] += entry["n_calls"]
        agg["features"].append(entry["label"])
        agg["models"].update(m["model"] for m in entry["models"])

    screening = evidence["screening"]
    n_ai_screening = sum(s["n_ai_suggestions"] for s in screening.values())
    n_decided = sum(s["n_decided"] for s in screening.values())
    extraction = evidence["extraction"]

    activities = []
    for key in ACTIVITY_ORDER:
        spec = ACTIVITIES[key]
        agg = by_activity.get(key)
        n_calls = agg["n_calls"] if agg else 0
        if key == "screening" and n_decided:
            level = _level_from_coverage(n_ai_screening / n_decided)
        elif key == "extraction" and extraction["n_cells"]:
            level = _level_from_coverage(
                extraction["n_ai_cells"] / extraction["n_cells"])
        else:
            level = _level_from_calls(n_calls)
        activities.append({
            "key": key,
            "label": spec["label"],
            "control": spec["control"],
            "level": level,
            "n_calls": n_calls,
            "features": agg["features"] if agg else [],
            "note": "",           # the author's own words, free text
        })

    models = sorted({m["model"] for entry in usage for m in entry["models"]})
    inputs = sorted({entry["inputs"] for entry in usage if entry["inputs"]})
    # Only the journal can say this: a configured local key proves nothing
    # about which provider actually answered each call.
    all_local = bool(models) and all(m.split(":", 1)[0] == "local" for m in models)
    return {
        "activities": activities,
        "tools": models,
        "inputs_shared": inputs,
        # author-declared, because the app cannot verify them: what the
        # provider was configured to do with the data (training opt-out,
        # retention, zero-data-retention endpoints). Pre-filled only in the
        # one case the journal can vouch for: every call went to a
        # self-hosted model.
        "safeguards": LOCAL_SAFEGUARDS if all_local else "",
        "human_validation_note": "",
        "authorship": "AI tools are not authors. The authors take full "
                      "responsibility for the content of the review.",
        "scope_note": "This statement covers the use of AI in conducting the "
                      "review (search, selection, appraisal, extraction, "
                      "synthesis). It does not cover the writing of the "
                      "manuscript, which was not carried out in this tool.",
    }


def _journal_gap(db: Session, project_id: int, usage: list[dict]) -> dict:
    """Did AI run before the journal existed?

    The journal shipped with the reporting stage; a project that used AI
    before that has outputs in
    its tables and nothing in `ai_usage`. Silently writing "no AI was used"
    over that would be the exact failure this feature exists to prevent, so the
    gap is detected and surfaced instead of guessed at.
    """
    earliest_trace = (db.query(func.min(Vote.created_at))
                      .filter_by(project_id=project_id, is_ai=True).scalar())
    protocol_ai = (db.query(func.count(Protocol.id))
                   .filter(Protocol.project_id == project_id,
                           Protocol.generated_with != "").scalar() or 0)
    n_ai_cells = (db.query(func.count(ExtractionValue.id))
                  .join(ExtractionColumn,
                        ExtractionColumn.id == ExtractionValue.column_id)
                  .filter(ExtractionColumn.project_id == project_id,
                          ExtractionValue.origin == "ai").scalar() or 0)
    has_traces = bool(earliest_trace) or protocol_ai > 0 or n_ai_cells > 0
    first_journal = min((e["first_at"] for e in usage if e["first_at"]),
                        default=None)
    incomplete = has_traces and (
        first_journal is None
        or (earliest_trace is not None
            and earliest_trace.isoformat() < first_journal))
    return {"incomplete": incomplete,
            "first_journal_entry": first_journal,
            "earliest_ai_trace": (earliest_trace.isoformat()
                                  if earliest_trace else None)}


def ai_dossier(db: Session, project_id: int) -> dict:
    usage = _usage_rows(db, project_id)
    evidence = {
        "screening": _screening_evidence(db, project_id),
        "triage": _triage_evidence(db, project_id),
        "extraction": _extraction_evidence(db, project_id),
        "protocol": _protocol_evidence(db, project_id),
    }
    total_cost = sum(e["cost_usd"] for e in usage)
    days = [d for e in usage for d in (e["first_at"], e["last_at"]) if d]
    return {
        "usage": usage,
        "evidence": evidence,
        "totals": {
            "n_calls": sum(e["n_calls"] for e in usage),
            "cost_usd": total_cost,
            "cost_label": pricing.format_usd(total_cost),
            "models": sorted({m["model"] for e in usage for m in e["models"]}),
            "first_at": min(days) if days else None,
            "last_at": max(days) if days else None,
        },
        "form": _default_form(usage, evidence),
        "any_ai_used": bool(usage),
        # AI traces older than the journal itself (project predates it)
        "journal": _journal_gap(db, project_id, usage),
    }
