# SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Per-reviewer activity folded over the whole review.

The screening dashboards answer "where does this round stand?"; the PRISMA
page answers "what did the team do, end to end?". So every number here is
summed over every title/abstract and full-text round (initial search plus
each snowballing iteration), then joined with the other places a member
leaves a trace: duplicate rulings, conflict resolutions, extracted cells and
appraisals.

Human work only: AI votes are not counted, and the validated AI title triage
is reported apart (what it took off a reviewer's plate is not something the
reviewer read).
"""
from collections import defaultdict

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import (
    Assignment, Conflict, DedupPair, ExtractionColumn, ExtractionValue,
    JbiAppraisal, ProjectMember, Record, ScreeningConfig, User, Vote,
)
from app.services.screening.core import (
    _agreement_data, _maybe_as_include, _pair_matrices,
)

STAGES = ("ta", "ft")


def _empty_stage() -> dict:
    return {"assigned": 0, "done": 0, "include": 0, "exclude": 0,
            "maybe": 0, "triage_excluded": 0, "triage_votes": 0}


def _stage_counts(db: Session, project_id: int, stage: str,
                  configs: list[ScreeningConfig]) -> dict[int, dict]:
    """Assignments and human votes of one stage, summed over its rounds."""
    out: dict[int, dict] = defaultdict(_empty_stage)
    if not configs:
        return out
    config_ids = [c.id for c in configs]
    rounds = [c.round for c in configs]
    for uid, n in (db.query(Assignment.user_id, func.count(Assignment.id))
                   .filter(Assignment.config_id.in_(config_ids))
                   .group_by(Assignment.user_id)):
        out[uid]["assigned"] += n
    for uid, decision, n in (
            db.query(Vote.voter_user_id, Vote.decision, func.count(Vote.id))
            .filter(Vote.project_id == project_id, Vote.stage == stage,
                    Vote.round.in_(rounds), Vote.is_ai.is_(False),
                    Vote.voter_user_id.isnot(None))
            .group_by(Vote.voter_user_id, Vote.decision)):
        out[uid]["done"] += n
        if decision in ("include", "exclude", "maybe"):
            out[uid][decision] += n
    # AI title triage (title/abstract only): admin mode excludes assigned
    # records globally, reviewers mode writes the reviewer's own exclude
    # votes — same split as screening_stats, summed over the rounds
    triaged = (db.query(Conflict.record_id)
               .filter(Conflict.project_id == project_id,
                       Conflict.stage == stage, Conflict.round.in_(rounds),
                       Conflict.status == "resolved",
                       Conflict.origin == "ai_triage"))
    for uid, n in (db.query(Assignment.user_id, func.count(Assignment.id))
                   .filter(Assignment.config_id.in_(config_ids),
                           Assignment.record_id.in_(triaged.scalar_subquery()))
                   .group_by(Assignment.user_id)):
        out[uid]["triage_excluded"] += n
    for uid, n in (db.query(Vote.voter_user_id, func.count(Vote.id))
                   .filter(Vote.project_id == project_id, Vote.stage == stage,
                           Vote.round.in_(rounds), Vote.is_ai.is_(False),
                           Vote.decision == "exclude",
                           Vote.justification.like("AI title triage%"))
                   .group_by(Vote.voter_user_id)):
        out[uid]["triage_votes"] += n
    return out


def _pooled_agreement(db: Session, stage: str,
                      configs: list[ScreeningConfig]) -> dict:
    """Cohen's kappa per pair of reviewers over every round of a stage.

    Pooling the rounds is legitimate because each record belongs to exactly
    one round, so the per-record vote sets never overlap; the pair statistic
    then simply has more records behind it. Title/abstract keeps the "maybe
    counts as include" convention of the per-round statistic."""
    maybe_as_include = stage == "ta"
    data: dict[tuple[int, int], dict[int, str]] = {}
    for config in configs:
        for rid, raters in _agreement_data(db, config).items():
            data[(config.round, rid)] = raters
    pairs = _pair_matrices(data, maybe_as_include) if data else []
    # the raw agreement across every double-voted record, all pairs folded
    folded = ({k: {u: _maybe_as_include(d) for u, d in r.items()}
               for k, r in data.items()} if maybe_as_include else data)
    agree = sum(1 for r in folded.values() if len(set(r.values())) == 1)
    return {
        "n_records": len(data),
        "percent": agree / len(data) if data else None,
        "pairs": pairs,
        "maybe_as_include": maybe_as_include,
        "n_rounds": len(configs),
    }


def reviewer_summary(db: Session, project_id: int) -> dict:
    """`withheld` is true while a round keeps its reviewers anonymous: the
    per-person table would let anyone match a pseudonym to a colleague
    through their other work (dedup, extraction), so it is empty until the
    round is complete."""
    from app.services.screening.anonymity import project_names_hidden
    if project_names_hidden(db, project_id):
        configs = {stage: (db.query(ScreeningConfig)
                           .filter_by(project_id=project_id, stage=stage,
                                      status="active")
                           .order_by(ScreeningConfig.round).all())
                   for stage in STAGES}
        return {
            "withheld": True, "reviewers": [],
            "agreement": {stage: {"n_records": 0, "percent": None,
                                  "pairs": [], "maybe_as_include": stage == "ta",
                                  "n_rounds": len(configs[stage])}
                          for stage in STAGES},
            "rounds": {stage: [c.round for c in configs[stage]]
                       for stage in STAGES},
        }
    configs = {stage: (db.query(ScreeningConfig)
                       .filter_by(project_id=project_id, stage=stage,
                                  status="active")
                       .order_by(ScreeningConfig.round).all())
               for stage in STAGES}
    per_stage = {stage: _stage_counts(db, project_id, stage, configs[stage])
                 for stage in STAGES}

    resolved: dict[int, dict] = defaultdict(lambda: {"ta": 0, "ft": 0})
    for uid, stage, n in (
            db.query(Conflict.resolved_by, Conflict.stage, func.count(Conflict.id))
            .filter(Conflict.project_id == project_id,
                    Conflict.status == "resolved", Conflict.origin == "votes",
                    Conflict.resolved_by.isnot(None))
            .group_by(Conflict.resolved_by, Conflict.stage)):
        resolved[uid][stage] += n

    dedup = dict(db.query(DedupPair.resolved_by, func.count(DedupPair.id))
                 .filter(DedupPair.project_id == project_id,
                         DedupPair.resolved_by.isnot(None),
                         DedupPair.status.in_(["merged", "distinct"]))
                 .group_by(DedupPair.resolved_by))

    # extraction: the cells a person owns — typed by hand, or AI-filled and
    # validated by them (an unvalidated AI cell is nobody's work yet)
    extraction: dict[int, dict] = defaultdict(lambda: {"records": 0, "cells": 0})
    for uid, n_records, n_cells in (
            db.query(ExtractionValue.user_id,
                     func.count(func.distinct(ExtractionValue.record_id)),
                     func.count(ExtractionValue.id))
            .join(ExtractionColumn, ExtractionColumn.id == ExtractionValue.column_id)
            .filter(ExtractionColumn.project_id == project_id,
                    ExtractionValue.user_id.isnot(None),
                    (ExtractionValue.origin == "human")
                    | ExtractionValue.validated.is_(True))
            .group_by(ExtractionValue.user_id)):
        extraction[uid] = {"records": n_records, "cells": n_cells}

    appraisals = dict(db.query(JbiAppraisal.user_id, func.count(JbiAppraisal.id))
                      .join(Record, Record.id == JbiAppraisal.record_id)
                      .filter(Record.project_id == project_id)
                      .group_by(JbiAppraisal.user_id))

    # members first (in membership order), then anyone who left a trace but
    # is no longer a member (removed from the project, or a sync author)
    members = (db.query(ProjectMember)
               .filter_by(project_id=project_id)
               .order_by(ProjectMember.id).all())
    roles = {m.user_id: m.role for m in members}
    seen: set[int] = set()
    for source in (*per_stage.values(), resolved, dedup, extraction, appraisals):
        seen |= set(source)
    ordered = [m.user_id for m in members] + sorted(seen - set(roles))
    users = {u.id: u.display_name for u in db.query(User)
             .filter(User.id.in_(ordered))} if ordered else {}

    reviewers = []
    for uid in ordered:
        reviewers.append({
            "user_id": uid,
            "display_name": users.get(uid, "?"),
            "role": roles.get(uid),  # None = former member
            "ta": dict(per_stage["ta"].get(uid, _empty_stage())),
            "ft": dict(per_stage["ft"].get(uid, _empty_stage())),
            "conflicts_resolved": dict(resolved.get(uid, {"ta": 0, "ft": 0})),
            "dedup_decisions": dedup.get(uid, 0),
            "extraction": dict(extraction.get(uid, {"records": 0, "cells": 0})),
            "appraisals": appraisals.get(uid, 0),
        })

    agreement = {stage: _pooled_agreement(db, stage, configs[stage])
                 for stage in STAGES}
    for stage in STAGES:
        for pair in agreement[stage]["pairs"]:
            pair["rows_name"] = users.get(pair["rows_user_id"], "?")
            pair["cols_name"] = users.get(pair["cols_user_id"], "?")
    return {
        "withheld": False,
        "reviewers": reviewers,
        "agreement": agreement,
        "rounds": {stage: [c.round for c in configs[stage]] for stage in STAGES},
    }
