# SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Screening engine: reviewer allocation, decision/conflict logic, agreement.

Server-side double blind: a reviewer's queue and record payloads NEVER include
other votes; votes become visible only once the record is complete (conflict
views) — enforced here and in the API, not in the UI.

Decision rule per record (user decisions):
- every required vote is include  -> include
- every required vote is exclude  -> exclude
- anything else (mixed, any "maybe") -> conflict, resolved by consensus of the
  reviewers or by an arbiter (project admin), per config.
"""
import random

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import (
    Assignment, Conflict, Import, Record, ScreeningConfig, Source, Vote,
)

CATEGORIES = ["include", "exclude", "maybe"]


# -- agreement statistics --------------------------------------------------------

def cohen_kappa(pairs: list[tuple[str, str]]) -> float | None:
    """Cohen's kappa for two raters; pairs = [(label_rater1, label_rater2)]."""
    n = len(pairs)
    if n == 0:
        return None
    po = sum(1 for a, b in pairs if a == b) / n
    pe = 0.0
    for cat in CATEGORIES:
        p1 = sum(1 for a, _ in pairs if a == cat) / n
        p2 = sum(1 for _, b in pairs if b == cat) / n
        pe += p1 * p2
    if pe >= 1.0:
        return 1.0
    return (po - pe) / (1 - pe)


def fleiss_kappa(rows: list[list[int]]) -> float | None:
    """Fleiss' kappa; rows = per-subject counts per category, each row summing
    to the same number of raters n >= 2."""
    if not rows:
        return None
    n = sum(rows[0])
    if n < 2 or any(sum(r) != n for r in rows):
        return None
    N = len(rows)
    p_i = [(sum(c * c for c in row) - n) / (n * (n - 1)) for row in rows]
    p_bar = sum(p_i) / N
    p_cat = [sum(row[j] for row in rows) / (N * n) for j in range(len(rows[0]))]
    pe = sum(p * p for p in p_cat)
    if pe >= 1.0:
        return 1.0
    return (p_bar - pe) / (1 - pe)


# -- allocation --------------------------------------------------------------------

def eligible_record_ids(db: Session, project_id: int, stage: str = "ta",
                        round_: int = 1) -> list[int]:
    """Records that enter a screening stage/round.

    ta round r -> unique records whose import source belongs to round r
                  (round 1 = the database/manual searches; round >= 2 = the
                  records a snowballing iteration created).
    ft round r -> records included at title/abstract round r (the ones full
                  texts were sought for). Falls back to all unique records
                  ONLY if T/A screening was never even configured, so a quick
                  demo still works. A configured-but-inactive T/A round (draft,
                  or active then reset) yields nothing: falling back would
                  silently re-inflate the FT round with the whole corpus right
                  after a T/A reset.
    """
    if stage == "ft":
        ta = (db.query(ScreeningConfig)
              .filter_by(project_id=project_id, stage="ta", round=round_)
              .first())
        if ta is not None and ta.status == "active":
            outcomes = screening_outcomes(db, ta)
            included = [rid for rid, decision in outcomes.items()
                        if decision == "include"]
            return sorted(included)
        if ta is not None or round_ > 1:  # T/A pending -> nothing enters FT
            return []
    return [rid for (rid,) in db.query(Record.id)
            .join(Import, Import.id == Record.import_id)
            .join(Source, Source.id == Import.source_id)
            .filter(Record.project_id == project_id,
                    Record.dedup_status == "unique",
                    Source.round == round_)
            .order_by(Record.id).all()]


def generate_assignments(db: Session, config: ScreeningConfig,
                         lots: list[dict] | None = None) -> dict:
    """Create the per-reviewer assignments for the chosen allocation.

    all            -> every reviewer screens every record
    dual           -> each record gets 2 reviewers, balanced round-robin
    single_overlap -> each record 1 reviewer, plus overlap_pct% (stable random,
                      seeded by config id) double-screened for the kappa
    lots           -> lots of `lot_size` records, one rotating pair per lot,
                      weighted shares (services/screening/lots.py); `lots` is
                      the plan as validated by the admin, if any
    lead           -> the lead reviewer screens every record; each record
                      gets one co-reviewer, chosen so that every co-reviewer
                      stays as close as possible to their share (equal by
                      default, `weights` otherwise) — 2 votes per record
    """
    reviewers = list(config.reviewer_ids or [])
    record_ids = eligible_record_ids(db, config.project_id, config.stage,
                                     config.round)
    if config.allocation == "lots":
        from app.services.screening.lots import create_lots
        return create_lots(db, config, record_ids, lots)
    rng = random.Random(config.id * 7919)  # deterministic for reproducibility

    def assign(record_id: int, user_id: int):
        db.add(Assignment(config_id=config.id, record_id=record_id,
                          user_id=user_id))

    n_double = 0
    if config.allocation == "all":
        for record_id in record_ids:
            for user_id in reviewers:
                assign(record_id, user_id)
    elif config.allocation == "dual":
        for i, record_id in enumerate(record_ids):
            first = reviewers[i % len(reviewers)]
            second = reviewers[(i + 1) % len(reviewers)]
            assign(record_id, first)
            assign(record_id, second)
        n_double = len(record_ids)
    elif config.allocation == "lead":
        counts: dict[int, int] = {}
        for record_id in record_ids:
            assign(record_id, config.lead_user_id)
            co = lead_co_reviewer(config, counts)
            assign(record_id, co)
            counts[co] = counts.get(co, 0) + 1
        n_double = len(record_ids)
    else:  # single_overlap
        shuffled = record_ids[:]
        rng.shuffle(shuffled)
        n_double = round(len(shuffled) * config.overlap_pct / 100)
        doubles = set(shuffled[:n_double])
        for i, record_id in enumerate(record_ids):
            first = reviewers[i % len(reviewers)]
            assign(record_id, first)
            if record_id in doubles:
                assign(record_id, reviewers[(i + 1) % len(reviewers)])
    return {"records": len(record_ids), "reviewers": len(reviewers),
            "double_screened": n_double if config.allocation != "all"
            else len(record_ids)}


def lead_co_reviewers(config: ScreeningConfig) -> list[int]:
    """allocation = lead: the reviewers who share the corpus (all but the lead)."""
    return [uid for uid in (config.reviewer_ids or []) if uid != config.lead_user_id]


def lead_co_reviewer(config: ScreeningConfig, counts: dict[int, int]) -> int:
    """allocation = lead: the co-reviewer who takes the next record, given how
    many each already holds — the one furthest below their target share
    (ties go to the first in the reviewer list). With equal shares this is a
    plain alternation A, B, A, B…; with 70/30 the 70 % reviewer takes 7 of
    every 10. Deterministic, so a reproducible allocation."""
    from app.services.screening.lots import effective_weights
    co = lead_co_reviewers(config)
    pct = effective_weights(co, config.weights)
    n_next = sum(counts.get(u, 0) for u in co) + 1
    return max(co, key=lambda u: (pct[u] * n_next / 100 - counts.get(u, 0),
                                  -co.index(u)))


def sync_assignments(db: Session, config: ScreeningConfig) -> int:
    """Assign records that entered the corpus AFTER the round started.

    A record can become eligible late: an import run after /start, a dedup
    ruling turning it unique, or (ft stage) a T/A conflict resolved to
    include. Without an assignment it sits in nobody's queue and the round
    can never complete. Existing assignments are never touched; allocation
    follows the config, continuing the round-robin from the current corpus
    size. Returns the number of records newly assigned."""
    reviewers = list(config.reviewer_ids or [])
    if config.status != "active" or not reviewers:
        return 0
    eligible = eligible_record_ids(db, config.project_id, config.stage,
                                   config.round)
    assigned = {rid for (rid,) in db.query(Assignment.record_id)
                .filter_by(config_id=config.id).distinct()}
    missing = [rid for rid in eligible if rid not in assigned]
    if config.allocation == "lots":
        # late records form new lots on the remaining quotas
        if missing:
            from app.services.screening.lots import add_late_lots
            add_late_lots(db, config, missing, len(eligible))
            db.commit()
        return len(missing)
    if config.allocation == "lead":
        # the lead takes every late record; the co-reviewer continues the
        # balance from what each already holds
        counts = dict(db.query(Assignment.user_id, func.count(Assignment.id))
                      .filter_by(config_id=config.id)
                      .group_by(Assignment.user_id).all())
        for record_id in missing:
            db.add(Assignment(config_id=config.id, record_id=record_id,
                              user_id=config.lead_user_id))
            co = lead_co_reviewer(config, counts)
            db.add(Assignment(config_id=config.id, record_id=record_id,
                              user_id=co))
            counts[co] = counts.get(co, 0) + 1
        if missing:
            db.commit()
        return len(missing)
    for j, record_id in enumerate(missing):
        i = len(assigned) + j
        first = reviewers[i % len(reviewers)]
        second = reviewers[(i + 1) % len(reviewers)]
        if config.allocation == "all":
            for user_id in reviewers:
                db.add(Assignment(config_id=config.id, record_id=record_id,
                                  user_id=user_id))
        elif config.allocation == "dual":
            db.add(Assignment(config_id=config.id, record_id=record_id,
                              user_id=first))
            db.add(Assignment(config_id=config.id, record_id=record_id,
                              user_id=second))
        else:  # single_overlap — stable per-record draw for the double share
            rng = random.Random(config.id * 7919 + record_id)
            db.add(Assignment(config_id=config.id, record_id=record_id,
                              user_id=first))
            if rng.random() * 100 < config.overlap_pct:
                db.add(Assignment(config_id=config.id, record_id=record_id,
                                  user_id=second))
    if missing:
        db.commit()
    return len(missing)


# -- decisions ----------------------------------------------------------------------

def required_votes(db: Session, config: ScreeningConfig, record_id: int) -> int:
    return (db.query(Assignment)
            .filter_by(config_id=config.id, record_id=record_id).count())


def human_votes(db: Session, config: ScreeningConfig, record_id: int) -> list[Vote]:
    return (db.query(Vote)
            .filter_by(project_id=config.project_id, record_id=record_id,
                       stage=config.stage, round=config.round, is_ai=False)
            .all())


def record_outcome(db: Session, config: ScreeningConfig, record_id: int) -> str | None:
    """include | exclude | conflict | None (not complete yet).
    A resolved conflict wins over the raw votes."""
    conflict = (db.query(Conflict)
                .filter_by(project_id=config.project_id, record_id=record_id,
                           stage=config.stage, round=config.round).first())
    if conflict is not None and conflict.status == "resolved":
        return conflict.resolution
    votes = human_votes(db, config, record_id)
    needed = required_votes(db, config, record_id)
    if needed == 0 or len(votes) < needed:
        return None
    decisions = {v.decision for v in votes}
    if decisions == {"include"}:
        return "include"
    if decisions == {"exclude"}:
        return "exclude"
    return "conflict"


def ensure_conflict(db: Session, config: ScreeningConfig, record_id: int):
    """Open a conflict row when a completed record is not unanimous."""
    if record_outcome(db, config, record_id) != "conflict":
        return
    existing = (db.query(Conflict)
                .filter_by(project_id=config.project_id, record_id=record_id,
                           stage=config.stage, round=config.round).first())
    if existing is None:
        db.add(Conflict(project_id=config.project_id, record_id=record_id,
                        stage=config.stage, round=config.round))


def screening_outcomes(db: Session, config: ScreeningConfig) -> dict[int, str]:
    """Final decision per completed record (conflict resolutions included)."""
    outcomes: dict[int, str] = {}
    # resolved conflicts first
    for conflict in db.query(Conflict).filter_by(
            project_id=config.project_id, stage=config.stage,
            round=config.round, status="resolved"):
        outcomes[conflict.record_id] = conflict.resolution
    # unanimous complete records
    needed = dict(db.query(Assignment.record_id, func.count(Assignment.id))
                  .filter_by(config_id=config.id)
                  .group_by(Assignment.record_id).all())
    votes_by_record: dict[int, set] = {}
    counts: dict[int, int] = {}
    for vote in db.query(Vote).filter_by(project_id=config.project_id,
                                         stage=config.stage, round=config.round,
                                         is_ai=False):
        votes_by_record.setdefault(vote.record_id, set()).add(vote.decision)
        counts[vote.record_id] = counts.get(vote.record_id, 0) + 1
    for record_id, decisions in votes_by_record.items():
        if record_id in outcomes:
            continue
        if counts.get(record_id, 0) >= needed.get(record_id, 99):
            if decisions == {"include"}:
                outcomes[record_id] = "include"
            elif decisions == {"exclude"}:
                outcomes[record_id] = "exclude"
    return outcomes


# -- statistics ----------------------------------------------------------------------

def _agreement_data(db: Session, config: ScreeningConfig):
    """Votes grouped per record, only records with >= 2 human votes."""
    votes = (db.query(Vote)
             .filter_by(project_id=config.project_id, stage=config.stage,
                        round=config.round, is_ai=False).all())
    per_record: dict[int, dict[int, str]] = {}
    for v in votes:
        per_record.setdefault(v.record_id, {})[v.voter_user_id] = v.decision
    return {rid: raters for rid, raters in per_record.items() if len(raters) >= 2}


def _cross_matrix(data: dict, all_raters: set) -> dict:
    """Cross-tab of vote pairs. Two raters: rows = first reviewer, cols =
    second. More raters: every unordered pair of votes per record, folded into
    a symmetric half-matrix (category order)."""
    matrix = {a: {b: 0 for b in CATEGORIES} for a in CATEGORIES}
    if len(all_raters) == 2 and all(len(r) == 2 for r in data.values()):
        u1, u2 = sorted(all_raters)
        for raters in data.values():
            matrix[raters[u1]][raters[u2]] += 1
        return {"cells": matrix, "rows_user_id": u1, "cols_user_id": u2}
    order = {c: i for i, c in enumerate(CATEGORIES)}
    for raters in data.values():
        votes = list(raters.values())
        for i in range(len(votes)):
            for j in range(i + 1, len(votes)):
                a, b = sorted((votes[i], votes[j]), key=order.get)
                matrix[a][b] += 1
    return {"cells": matrix, "rows_user_id": None, "cols_user_id": None}


def _pair_matrices(data: dict, maybe_as_include: bool = False) -> list[dict]:
    """One named cross-tab per pair of reviewers, over the records both voted
    on (rows = the lower user id). The folded matrix loses who said what as
    soon as a third reviewer joins; these keep it readable at any team size,
    each with its own Cohen's kappa. The cells always keep the three votes
    apart; `maybe_as_include` only folds "maybe" into "include" for the kappa
    and the raw agreement."""
    votes_by_pair: dict[tuple[int, int], list[tuple[str, str]]] = {}
    for raters in data.values():
        users = sorted(raters)
        for i in range(len(users)):
            for j in range(i + 1, len(users)):
                votes_by_pair.setdefault((users[i], users[j]), []).append(
                    (raters[users[i]], raters[users[j]]))
    out = []
    for (u1, u2), votes in sorted(votes_by_pair.items()):
        cells = {a: {b: 0 for b in CATEGORIES} for a in CATEGORIES}
        for a, b in votes:
            cells[a][b] += 1
        if maybe_as_include:
            votes = [(_maybe_as_include(a), _maybe_as_include(b))
                     for a, b in votes]
        out.append({
            "rows_user_id": u1, "cols_user_id": u2, "cells": cells,
            "n_records": len(votes), "kappa": cohen_kappa(votes),
            "percent": sum(1 for a, b in votes if a == b) / len(votes),
        })
    return out


def _maybe_as_include(decision: str) -> str:
    return "include" if decision == "maybe" else decision


def agreement_stats(db: Session, config: ScreeningConfig) -> dict:
    """Inter-rater agreement over the records that got >= 2 human votes.

    Title/abstract: "maybe" counts as "include" in the kappa and the raw
    agreement — both send the record on to full text, so the statistic
    measures the binary call "goes forward / excluded" (`maybe_as_include`
    in the payload). The cross-matrices keep the three votes apart, and a
    "maybe" still opens a conflict: only the statistic is affected."""
    raw = _agreement_data(db, config)
    maybe_as_include = config.stage == "ta"
    if not raw:
        return {"method": None, "kappa": None, "percent": None, "n_records": 0,
                "matrix": None, "pairs": [],
                "maybe_as_include": maybe_as_include}
    data = ({rid: {uid: _maybe_as_include(d) for uid, d in raters.items()}
             for rid, raters in raw.items()} if maybe_as_include else raw)
    # observed agreement over double+ voted records (pairwise)
    agree = sum(1 for raters in data.values() if len(set(raters.values())) == 1)
    percent = agree / len(data)

    rater_sets = {frozenset(r.keys()) for r in data.values()}
    all_raters = set().union(*rater_sets)
    matrix = _cross_matrix(raw, all_raters)
    by_pair = _pair_matrices(raw, maybe_as_include)
    if len(all_raters) == 2 and all(len(r) == 2 for r in data.values()):
        pairs = []
        u1, u2 = sorted(all_raters)
        for raters in data.values():
            pairs.append((raters[u1], raters[u2]))
        return {"method": "cohen", "kappa": cohen_kappa(pairs),
                "percent": percent, "n_records": len(data), "matrix": matrix,
                "pairs": by_pair, "maybe_as_include": maybe_as_include}
    # Fleiss over records sharing the modal number of raters
    from collections import Counter
    n_modal = Counter(len(r) for r in data.values()).most_common(1)[0][0]
    rows = []
    for raters in data.values():
        if len(raters) != n_modal:
            continue
        counts = [sum(1 for d in raters.values() if d == cat) for cat in CATEGORIES]
        rows.append(counts)
    return {"method": "fleiss", "kappa": fleiss_kappa(rows),
            "percent": percent, "n_records": len(rows), "matrix": matrix,
            "pairs": by_pair, "maybe_as_include": maybe_as_include}


def screening_stats(db: Session, config: ScreeningConfig) -> dict:
    assignments_total = db.query(Assignment).filter_by(config_id=config.id).count()
    per_reviewer_assigned = dict(
        db.query(Assignment.user_id, func.count(Assignment.id))
        .filter_by(config_id=config.id).group_by(Assignment.user_id).all())
    votes = (db.query(Vote.voter_user_id, Vote.decision, func.count(Vote.id))
             .filter_by(project_id=config.project_id, stage=config.stage,
                        round=config.round, is_ai=False)
             .group_by(Vote.voter_user_id, Vote.decision).all())
    per_reviewer: dict[int, dict] = {}
    for user_id, decision, n in votes:
        entry = per_reviewer.setdefault(user_id, {"done": 0, "include": 0,
                                                  "exclude": 0, "maybe": 0})
        entry["done"] += n
        entry[decision] = n
    outcomes = screening_outcomes(db, config)
    from collections import Counter
    outcome_counts = Counter(outcomes.values())
    conflicts_open = db.query(Conflict).filter_by(
        project_id=config.project_id, stage=config.stage, round=config.round,
        status="open", origin="votes").count()
    conflicts_resolved = db.query(Conflict).filter_by(
        project_id=config.project_id, stage=config.stage, round=config.round,
        status="resolved", origin="votes").count()
    auto_excluded = db.query(Conflict).filter_by(
        project_id=config.project_id, stage=config.stage, round=config.round,
        status="resolved", origin="ai_triage").count()
    # AI title triage, per reviewer — what it took off each one's workload:
    # admin mode = assigned records excluded globally (they will never vote on
    # them); reviewers mode = their own validated exclude votes
    triaged = (db.query(Conflict.record_id)
               .filter_by(project_id=config.project_id, stage=config.stage,
                          round=config.round, status="resolved",
                          origin="ai_triage"))
    triage_excluded = dict(
        db.query(Assignment.user_id, func.count(Assignment.id))
        .filter(Assignment.config_id == config.id,
                Assignment.record_id.in_(triaged.scalar_subquery()))
        .group_by(Assignment.user_id).all())
    triage_votes = dict(
        db.query(Vote.voter_user_id, func.count(Vote.id))
        .filter(Vote.project_id == config.project_id,
                Vote.stage == config.stage, Vote.round == config.round,
                Vote.is_ai.is_(False), Vote.decision == "exclude",
                Vote.justification.like("AI title triage%"))
        .group_by(Vote.voter_user_id).all())
    lots_block = {}
    if config.allocation == "lots":
        from app.services.screening.lots import lot_rows, shares
        lots_block = {"lots": lot_rows(db, config), "shares": shares(db, config)}
        db.commit()  # lot statuses closed above
    elif config.allocation == "lead":
        # the lead holds 100 %; the shares are over the co-reviewers
        from app.services.screening.lots import shares_from_counts
        lots_block = {"lead_user_id": config.lead_user_id,
                      "shares": shares_from_counts(lead_co_reviewers(config),
                                                   config.weights,
                                                   per_reviewer_assigned)}
    # control sample of the triage: counts only here (blind-safe), the
    # decided rows come from /triage-controls
    from app.services.screening.triage import control_report
    controls = control_report(db, config)
    controls.pop("rows", None)
    return {
        **lots_block,
        "auto_excluded": auto_excluded,  # validated AI title-triage exclusions
        "triage_controls": controls,
        "assignments_total": assignments_total,
        "votes_done": sum(e["done"] for e in per_reviewer.values()),
        "per_reviewer": [
            {"user_id": uid, "assigned": per_reviewer_assigned.get(uid, 0),
             "triage_excluded": triage_excluded.get(uid, 0),
             "triage_votes": triage_votes.get(uid, 0),
             **per_reviewer.get(uid, {"done": 0, "include": 0, "exclude": 0,
                                      "maybe": 0})}
            for uid in (config.reviewer_ids or [])
        ],
        "completed": len(outcomes),
        "included": outcome_counts.get("include", 0),
        "excluded": outcome_counts.get("exclude", 0),
        "conflicts_open": conflicts_open,
        "conflicts_resolved": conflicts_resolved,
        "agreement": agreement_stats(db, config),
    }
