# SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Full-text exclusion reasons and the per-reason PRISMA breakdown.

A record excluded at full text carries an ordered list of reasons: the first is
the PRIMARY reason (the one PRISMA counts under "reports excluded: reason (n)"),
any others are secondary. Reasons are the protocol's exclusion criteria (E*)
plus one built-in reason, "full text not retrievable" (the user's explicit
"article introuvable"), which feeds the PRISMA "reports not retrieved" box
rather than the content-exclusion tally.
"""
from collections import Counter

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import Conflict, ScreeningConfig, User, Vote
from app.services.protocol.service import validated_protocol
from app.services.screening.core import screening_outcomes

# Built-in reason: the full text could not be obtained. Not a protocol criterion.
NOTFOUND_CODE = "NOTFOUND"
NOTFOUND_LABEL = "Full text not retrievable"


def exclusion_reasons(db: Session, project_id: int, stage: str = "ft") -> list[dict]:
    """The exclusion reasons a reviewer may pick from, in display order:
    the validated protocol's E* criteria, then the built-in "not retrievable"."""
    protocol = validated_protocol(db, project_id)
    reasons: list[dict] = []
    for c in (protocol.criteria if protocol else []) or []:
        if str(c.get("type")) == "exclude" or str(c.get("code", "")).upper().startswith("E"):
            reasons.append({"code": c.get("code", ""), "label": c.get("label", ""),
                            "description": c.get("description", ""), "kind": "criterion"})
    if stage == "ft":
        reasons.append({"code": NOTFOUND_CODE, "label": NOTFOUND_LABEL,
                        "description": "The full text could not be obtained, so the "
                                       "report was not assessed on its content.",
                        "kind": "builtin"})
    return reasons


def reason_labels(db: Session, project_id: int, stage: str = "ft") -> dict[str, str]:
    return {r["code"]: r["label"] for r in exclusion_reasons(db, project_id, stage)}


def primary_reason(db: Session, config: ScreeningConfig, record_id: int) -> str | None:
    """The single primary exclusion reason recorded for an excluded record.

    A resolved conflict's recorded reasons win; otherwise the modal primary
    reason across the human exclude-votes. A tie goes to the reviewer whose
    e-mail sorts first: local account ids differ between a coordinator and
    its satellites, an e-mail does not, so every instance reports the same
    PRISMA breakdown."""
    conflict = (db.query(Conflict)
                .filter_by(project_id=config.project_id, record_id=record_id,
                           stage=config.stage, round=config.round,
                           status="resolved").first())
    if conflict is not None and conflict.resolution == "exclude" and conflict.reasons:
        return conflict.reasons[0]
    votes = (db.query(Vote)
             .join(User, User.id == Vote.voter_user_id)
             .filter(Vote.project_id == config.project_id,
                     Vote.record_id == record_id, Vote.stage == config.stage,
                     Vote.round == config.round, Vote.is_ai.is_(False))
             .order_by(func.lower(User.email), Vote.id)
             .all())
    primaries = [v.reasons[0] for v in votes
                 if v.decision == "exclude" and v.reasons]
    if not primaries:
        return None
    counts = Counter(primaries)
    top = max(counts.values())
    for code in primaries:  # first-occurrence tiebreak, deterministic
        if counts[code] == top:
            return code
    return primaries[0]


def ft_prisma_outcomes(db: Session, config: ScreeningConfig,
                       only: set[int] | None = None) -> dict:
    """Full-text screening counters for the PRISMA flow.

    - assessed      : reports whose full text was assessed on its content
                      (completed FT records excluding the "not retrievable" ones)
    - not_retrieved : records excluded with the built-in NOTFOUND reason
    - included      : FT includes (studies carried forward)
    - excluded      : content exclusions (reason != NOTFOUND)
    - by_reason     : [{code, n}] for content exclusions, primary reason

    `only` restricts the tally to a subset of record ids (used by the PRISMA
    2020 split between "via databases" and "via other methods").
    """
    outcomes = screening_outcomes(db, config)
    if only is not None:
        outcomes = {rid: d for rid, d in outcomes.items() if rid in only}
    included = [rid for rid, d in outcomes.items() if d == "include"]
    excluded = [rid for rid, d in outcomes.items() if d == "exclude"]
    not_retrieved = 0
    by_reason: Counter = Counter()
    for rid in excluded:
        code = primary_reason(db, config, rid) or ""
        if code == NOTFOUND_CODE:
            not_retrieved += 1
        else:
            by_reason[code] += 1
    content_excluded = sum(by_reason.values())
    return {
        "assessed": len(included) + content_excluded,
        "not_retrieved": not_retrieved,
        "included": len(included),
        "excluded": content_excluded,
        "by_reason": [{"code": code, "n": n} for code, n in by_reason.most_common()],
    }
