# SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Weighted lots and rotating pairs (allocation = "lots").

The corpus is cut, in corpus order, into lots of `lot_size` records. Each lot
is screened by one pair of reviewers. The pair of a lot is chosen so that:

- every reviewer ends up with their declared share of the work — a share in
  percent of the assignments (2 per record, so quota_u = pct_u × 2N);
- the pairs rotate: among the pairs that serve the quotas equally well, the
  one that was served least recently goes first, so with equal shares every
  pair gets a lot before any pair gets a second one;
- the two named arbiters are never paired together — a conflict then always
  has an arbiter who did not vote on the record (the arbitration rule itself
  belongs to R2b).

Records that enter the round after the start (snowballing, search update
passes, late imports) form new lots, numbered after the existing ones, on the
quotas that remain once the whole corpus is counted.

The planner is a pure function (`plan_lots`) so that it can be tested on
thousands of records without a database; the functions below it persist the
plan (`ScreeningLot` rows and `Assignment.lot_id`) and report on it.
"""
from datetime import datetime
from itertools import combinations

from sqlalchemy.orm import Session

from app.models import Assignment, Conflict, ScreeningConfig, ScreeningLot, Vote

# pairs whose quota sum lies within this fraction of a lot of the best one are
# treated as equally good, and the rotation decides between them
TIE_TOLERANCE = 0.25


# -- pure planning ---------------------------------------------------------------

def allowed_pairs(reviewers: list[int], arbiter_ids: list[int] | None
                  ) -> list[tuple[int, int]]:
    """Every unordered pair of reviewers, minus the pair of the two arbiters
    (when both of them screen)."""
    arbiters = set(arbiter_ids or [])
    return [(a, b) for a, b in combinations(reviewers, 2)
            if not (a in arbiters and b in arbiters)]


def effective_weights(reviewers: list[int], weights: dict | None
                      ) -> dict[int, float]:
    """{user_id: pct} over the reviewers. No weights (or none for any of the
    reviewers) = equal shares; a reviewer missing from a given weight map
    gets 0 % (and so no lot)."""
    if not reviewers:
        return {}
    given = {}
    for key, value in (weights or {}).items():
        try:
            uid, pct = int(key), float(value)
        except (TypeError, ValueError):
            continue
        if uid in reviewers and pct >= 0:
            given[uid] = pct
    if not given:
        return {u: 100 / len(reviewers) for u in reviewers}
    return {u: given.get(u, 0.0) for u in reviewers}


def weights_error(reviewers: list[int], weights: dict | None) -> str | None:
    """Why the weights cannot be used, or None. Only explicit weights are
    checked: no weights means equal shares."""
    if not weights:
        return None
    pct = effective_weights(reviewers, weights)
    total = sum(pct.values())
    if abs(total - 100) > 0.05:
        return f"The reviewers' shares must add up to 100 % (now {total:g} %)"
    return None


def chunk(record_ids: list[int], lot_size: int) -> list[list[int]]:
    size = max(int(lot_size or 1), 1)
    return [record_ids[i:i + size] for i in range(0, len(record_ids), size)]


def plan_pairs(lot_sizes: list[int], reviewers: list[int],
               weights: dict | None, arbiter_ids: list[int] | None,
               total_records: int | None = None,
               assigned: dict[int, int] | None = None,
               served: dict[tuple[int, int], int] | None = None,
               lot_size: int | None = None) -> list[tuple[int, int]]:
    """One pair per lot.

    `total_records` is the corpus the shares apply to (default: the sum of
    the lot sizes); `assigned` the assignments each reviewer already holds
    and `served` the sequence number at which each pair was last used — both
    carry the state of an already running round when late lots are planned.
    """
    pairs = allowed_pairs(reviewers, arbiter_ids)
    if not pairs:
        raise ValueError("No pair of reviewers can be formed")
    n_total = total_records if total_records is not None else sum(lot_sizes)
    pct = effective_weights(reviewers, weights)
    quota = {u: pct[u] / 100 * 2 * n_total - (assigned or {}).get(u, 0)
             for u in reviewers}
    last = dict(served or {})
    seq = max(last.values(), default=0)
    tolerance = TIE_TOLERANCE * (lot_size or (max(lot_sizes) if lot_sizes else 1))
    out: list[tuple[int, int]] = []
    for size in lot_sizes:
        best = max(quota[a] + quota[b] for a, b in pairs)
        candidates = [p for p in pairs if quota[p[0]] + quota[p[1]] >= best - tolerance]
        # rotation: never served first (in reviewer order), then least recent
        pair = min(candidates, key=lambda p: (last.get(p, 0), pairs.index(p)))
        seq += 1
        last[pair] = seq
        for u in pair:
            quota[u] -= size
        out.append(pair)
    return out


def plan_lots(record_ids: list[int], reviewers: list[int], weights: dict | None,
              lot_size: int, arbiter_ids: list[int] | None = None,
              first_index: int = 1, total_records: int | None = None,
              assigned: dict[int, int] | None = None,
              served: dict[tuple[int, int], int] | None = None) -> list[dict]:
    """[{index, record_ids, user_ids}] for the given records, in corpus order."""
    lots = chunk(sorted(record_ids), lot_size)
    pairs = plan_pairs([len(l) for l in lots], reviewers, weights, arbiter_ids,
                       total_records=total_records, assigned=assigned,
                       served=served, lot_size=lot_size)
    return [{"index": first_index + i, "record_ids": ids, "user_ids": list(pair)}
            for i, (ids, pair) in enumerate(zip(lots, pairs))]


def shares_from_counts(reviewers: list[int], weights: dict | None,
                       assigned: dict[int, int]) -> list[dict]:
    """Target vs effective share per reviewer."""
    pct = effective_weights(reviewers, weights)
    total = sum(assigned.get(u, 0) for u in reviewers)
    return [{"user_id": u, "target_pct": round(pct[u], 2),
             "assigned": assigned.get(u, 0),
             "effective_pct": round(100 * assigned.get(u, 0) / total, 2) if total else 0.0}
            for u in reviewers]


# -- validation of the admin's edited plan --------------------------------------

def validate_pairs(lots: list[dict], config: ScreeningConfig) -> str | None:
    """The admin may change the pair (and deadline) of each lot before the
    start; the pair still has to be two distinct reviewers of the round and
    not the two arbiters."""
    reviewers = set(config.reviewer_ids or [])
    arbiters = set(config.arbiter_ids or [])
    for lot in lots:
        users = list(lot.get("user_ids") or [])
        if len(users) != 2 or users[0] == users[1]:
            return f"Lot {lot.get('index')}: a lot needs two different reviewers"
        if not set(users) <= reviewers:
            return f"Lot {lot.get('index')}: both reviewers must screen this round"
        if set(users) <= arbiters and len(arbiters) == 2:
            return f"Lot {lot.get('index')}: the two arbiters cannot share a lot"
    return None


# -- persistence -------------------------------------------------------------------

def _state(db: Session, config: ScreeningConfig):
    """Assignments held per reviewer and the last sequence each pair served,
    from the lots already created."""
    existing = (db.query(ScreeningLot).filter_by(config_id=config.id)
                .order_by(ScreeningLot.index).all())
    served: dict[tuple[int, int], int] = {}
    for lot in existing:
        users = list(lot.user_ids or [])
        if len(users) == 2:
            served[tuple(sorted(users))] = lot.index  # type: ignore[assignment]
    assigned: dict[int, int] = {}
    for a in db.query(Assignment).filter_by(config_id=config.id):
        assigned[a.user_id] = assigned.get(a.user_id, 0) + 1
    next_index = (existing[-1].index + 1) if existing else 1
    return assigned, served, next_index


def _served_key(pair):
    return tuple(sorted(pair))


def preview_lots(db: Session, config: ScreeningConfig) -> dict:
    """The plan /start would apply, for the admin to review and edit."""
    from app.services.screening.core import eligible_record_ids
    reviewers = list(config.reviewer_ids or [])
    record_ids = eligible_record_ids(db, config.project_id, config.stage,
                                     config.round)
    plan = plan_lots(record_ids, reviewers, config.weights, config.lot_size,
                     config.arbiter_ids)
    counts: dict[int, int] = {}
    for lot in plan:
        for u in lot["user_ids"]:
            counts[u] = counts.get(u, 0) + len(lot["record_ids"])
    return {
        "n_records": len(record_ids),
        "lot_size": config.lot_size,
        "pairs": [list(p) for p in allowed_pairs(reviewers, config.arbiter_ids)],
        "lots": [{"index": lot["index"], "size": len(lot["record_ids"]),
                  "user_ids": lot["user_ids"], "due_at": None}
                 for lot in plan],
        "shares": shares_from_counts(reviewers, config.weights, counts),
    }


def _persist(db: Session, config: ScreeningConfig, plan: list[dict],
             due: dict[int, datetime | None] | None = None) -> int:
    n = 0
    for lot in plan:
        row = ScreeningLot(config_id=config.id, index=lot["index"],
                           user_ids=list(lot["user_ids"]),
                           due_at=(due or {}).get(lot["index"]))
        db.add(row)
        db.flush()
        for record_id in lot["record_ids"]:
            for user_id in lot["user_ids"]:
                db.add(Assignment(config_id=config.id, record_id=record_id,
                                  user_id=user_id, lot_id=row.id))
                n += 1
    return n


def create_lots(db: Session, config: ScreeningConfig, record_ids: list[int],
                validated: list[dict] | None = None) -> dict:
    """Cut the corpus into lots and create the assignments. `validated` is
    the admin's edited plan ([{index, user_ids, due_at}]): the records of
    each lot are regenerated identically, only the pairs and deadlines are
    taken from it."""
    reviewers = list(config.reviewer_ids or [])
    plan = plan_lots(record_ids, reviewers, config.weights, config.lot_size,
                     config.arbiter_ids)
    due: dict[int, datetime | None] = {}
    if validated:
        by_index = {int(lot["index"]): lot for lot in validated}
        if set(by_index) != {lot["index"] for lot in plan}:
            raise ValueError("The validated lots no longer match the corpus — "
                             "preview the lots again")
        error = validate_pairs(list(by_index.values()), config)
        if error:
            raise ValueError(error)
        for lot in plan:
            edited = by_index[lot["index"]]
            lot["user_ids"] = [int(u) for u in edited["user_ids"]]
            due[lot["index"]] = edited.get("due_at")
    n = _persist(db, config, plan, due)
    return {"records": len(record_ids), "reviewers": len(reviewers),
            "double_screened": len(record_ids), "lots": len(plan),
            "assignments": n}


def add_late_lots(db: Session, config: ScreeningConfig, missing: list[int],
                  total_records: int) -> int:
    """New lots for records that entered the round after the start, on the
    quotas that remain over the whole corpus."""
    reviewers = list(config.reviewer_ids or [])
    assigned, served, next_index = _state(db, config)
    try:
        plan = plan_lots(missing, reviewers, config.weights, config.lot_size,
                         config.arbiter_ids, first_index=next_index,
                         total_records=total_records, assigned=assigned,
                         served=served)
    except ValueError:
        return 0
    _persist(db, config, plan)
    return len(plan)


# -- reporting ---------------------------------------------------------------------

def lot_rows(db: Session, config: ScreeningConfig) -> list[dict]:
    """Every lot with its progress per reviewer; closes the lots whose
    assignments are all voted (or globally resolved)."""
    lots = (db.query(ScreeningLot).filter_by(config_id=config.id)
            .order_by(ScreeningLot.index).all())
    if not lots:
        return []
    by_lot: dict[int, list[Assignment]] = {}
    for a in db.query(Assignment).filter(Assignment.config_id == config.id,
                                         Assignment.lot_id.isnot(None)):
        by_lot.setdefault(a.lot_id, []).append(a)
    voted = {(v.record_id, v.voter_user_id) for v in
             db.query(Vote.record_id, Vote.voter_user_id)
             .filter_by(project_id=config.project_id, stage=config.stage,
                        round=config.round, is_ai=False)}
    resolved = {c.record_id for c in db.query(Conflict.record_id)
                .filter_by(project_id=config.project_id, stage=config.stage,
                           round=config.round, status="resolved")}
    rows = []
    for lot in lots:
        assignments = by_lot.get(lot.id, [])
        records = {a.record_id for a in assignments}
        done: dict[int, int] = {u: 0 for u in (lot.user_ids or [])}
        complete = True
        for a in assignments:
            if (a.record_id, a.user_id) in voted:
                done[a.user_id] = done.get(a.user_id, 0) + 1
            elif a.record_id not in resolved:
                complete = False
        if complete and assignments and lot.status != "closed":
            lot.status = "closed"
        rows.append({
            "id": lot.id, "index": lot.index, "size": len(records),
            "user_ids": list(lot.user_ids or []),
            "done": [{"user_id": u, "done": done.get(u, 0)}
                     for u in (lot.user_ids or [])],
            "due_at": lot.due_at.isoformat() if lot.due_at else None,
            "status": lot.status,
        })
    return rows


def shares(db: Session, config: ScreeningConfig) -> list[dict]:
    reviewers = list(config.reviewer_ids or [])
    assigned: dict[int, int] = {}
    for a in db.query(Assignment).filter_by(config_id=config.id):
        assigned[a.user_id] = assigned.get(a.user_id, 0) + 1
    return shares_from_counts(reviewers, config.weights, assigned)
