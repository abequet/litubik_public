# SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
# SPDX-License-Identifier: AGPL-3.0-or-later
"""What the review did that its protocol did not say it would.

CREST_Triage asks editors, for a review that references a protocol, to "check
for consistency between planned and applied methods"; SWiM item 1b asks authors
to report changes made after the protocol *and their reason*; PRISMA item 24c
asks for amendments to the registered information. All three want the same
thing, and all three are usually answered from memory months later.

LitUbik wrote down when each stage happened, so some of those changes are
visible in its own tables: eligibility criteria edited once screening had
begun, a protocol version validated after the records were in, an equation
frozen after imports, a screening round restarted over existing votes. This
module finds those and stops there — a change no timestamp can witness is
declared by the team, not guessed at.

**A detected signal is not a deviation.** Amending a protocol is legitimate;
what a reader needs is the amendment *and its reason*, and only the team has
the reason. So a signal surfaces as a question — "this happened, why?" — that a
human turns into a declared deviation or dismisses with a note. Nothing is ever
promoted automatically, and a dismissed signal stays dismissed rather than
reappearing at every page load.
"""
from datetime import datetime

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import (
    Equation, Import, Protocol, ProtocolDeviation, ScreeningConfig, Vote,
)

# Stages a deviation can belong to, in pipeline order.
STAGES: dict[str, str] = {
    "protocol": "Protocol and eligibility criteria",
    "search": "Search strategy",
    "screening": "Screening",
    "appraisal": "Critical appraisal",
    "extraction": "Data extraction",
    "synthesis": "Synthesis",
}


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _criteria_signature(protocol: Protocol) -> set[tuple[str, str]]:
    """A protocol's criteria as a comparable set: (code, description).

    The label alone is too weak — rewording a description changes what a
    screener applies while leaving the label intact.
    """
    return {(c.get("code", ""), (c.get("description") or "").strip())
            for c in (protocol.criteria or [])}


def detect(db: Session, project_id: int) -> list[dict]:
    """Signals the tables carry, each with the date it happened.

    `signal` is a stable machine key so a dismissal sticks across reloads;
    `summary` is what the card says.
    """
    out: list[dict] = []

    protocols = (db.query(Protocol).filter_by(project_id=project_id)
                 .order_by(Protocol.version).all())
    first_vote = db.query(func.min(Vote.created_at)).filter_by(
        project_id=project_id).scalar()
    first_import = db.query(func.min(Import.imported_at)).filter_by(
        project_id=project_id).scalar()

    # -- eligibility criteria changed after screening had started ------------
    # The strongest signal there is: records were judged against one set of
    # criteria and the review reports another.
    for previous, current in zip(protocols, protocols[1:]):
        if current.validated_at is None:
            continue
        before, after = _criteria_signature(previous), _criteria_signature(current)
        if before == after:
            continue
        if first_vote and current.validated_at > _as_naive_safe(first_vote,
                                                                current.validated_at):
            added = len(after - before)
            removed = len(before - after)
            out.append({
                "signal": f"criteria_changed_v{current.version}",
                "stage": "protocol",
                "occurred_at": _iso(current.validated_at),
                "summary": (
                    f"The eligibility criteria changed in protocol version "
                    f"{current.version}, validated after screening had begun "
                    f"({added} added or reworded, {removed} removed). Records "
                    f"screened before that date were judged against the "
                    f"previous criteria."),
            })

    # -- a protocol version validated after the search results were in -------
    for protocol in protocols:
        if (protocol.validated_at and first_import
                and protocol.version > 1
                and protocol.validated_at > _as_naive_safe(first_import,
                                                           protocol.validated_at)):
            out.append({
                "signal": f"protocol_after_import_v{protocol.version}",
                "stage": "protocol",
                "occurred_at": _iso(protocol.validated_at),
                "summary": (
                    f"Protocol version {protocol.version} was validated after "
                    f"records had already been imported."),
            })

    # -- an equation frozen after records were already imported --------------
    for equation in db.query(Equation).filter_by(project_id=project_id):
        if (equation.frozen_at and first_import
                and equation.frozen_at > _as_naive_safe(first_import,
                                                        equation.frozen_at)):
            out.append({
                "signal": f"equation_frozen_after_import_{equation.id}",
                "stage": "search",
                "occurred_at": _iso(equation.frozen_at),
                "summary": (
                    f"The search equation “{equation.label}” was frozen after "
                    f"records had already been imported — the query reported "
                    f"may not be the one that produced every record."),
            })

    # -- a screening round activated when votes already existed --------------
    for config in (db.query(ScreeningConfig).filter_by(project_id=project_id)
                   .order_by(ScreeningConfig.stage, ScreeningConfig.round)):
        if config.status != "active" or config.started_at is None:
            continue
        earlier = (db.query(func.min(Vote.created_at))
                   .filter_by(project_id=project_id, stage=config.stage,
                              round=config.round).scalar())
        if earlier and _as_naive_safe(earlier, config.started_at) < config.started_at:
            out.append({
                "signal": f"screening_restarted_{config.stage}_{config.round}",
                "stage": "screening",
                "occurred_at": _iso(config.started_at),
                "summary": (
                    f"The {config.stage.upper()} screening round "
                    f"{config.round} was (re)started after votes had already "
                    f"been cast in it — its allocation or decision rule may "
                    f"not be the one under which those votes were made."),
            })

    # Extraction columns added mid-extraction would belong here, and do not:
    # ExtractionColumn carries no timestamp, so the only "signal" available
    # would fire for every project that ever started extracting, whether or not
    # anything changed. A register that cries wolf is a register nobody reads,
    # so that change is declared rather than detected.

    out.sort(key=lambda d: d["occurred_at"] or "")
    return out


def _as_naive_safe(value: datetime, reference: datetime) -> datetime:
    """Compare two timestamps that may disagree about tzinfo.

    Everything LitUbik writes is UTC, but the SQLite driver hands some columns
    back naive; comparing one with an aware one raises. Same problem, and the
    same fix, as sync/serialize.as_utc.
    """
    if (value.tzinfo is None) == (reference.tzinfo is None):
        return value
    if reference.tzinfo is None:
        return value.replace(tzinfo=None)
    from datetime import timezone
    return value.replace(tzinfo=timezone.utc)


def register(db: Session, project_id: int) -> dict:
    """Detected signals and declared deviations, side by side.

    A signal the team already answered — declared or dismissed — is not offered
    again; a signal is matched to its answer by its machine key.
    """
    rows = (db.query(ProtocolDeviation).filter_by(project_id=project_id)
            .order_by(ProtocolDeviation.occurred_at,
                      ProtocolDeviation.id).all())
    answered = {r.signal for r in rows if r.signal}
    signals = [s for s in detect(db, project_id) if s["signal"] not in answered]
    return {
        "signals": signals,
        "deviations": [{
            "id": r.id, "uuid": r.uuid, "stage": r.stage,
            "stage_label": STAGES.get(r.stage, r.stage),
            "kind": r.kind, "signal": r.signal,
            "summary": r.summary, "rationale": r.rationale,
            "occurred_at": _iso(r.occurred_at),
            "dismissed": r.dismissed_at is not None,
            "dismiss_note": r.dismiss_note,
            "declared_at": _iso(r.created_at),
        } for r in rows],
        "stages": [{"key": k, "label": v} for k, v in STAGES.items()],
        "n_undeclared_signals": len(signals),
    }


def audit_block(db: Session, project_id: int) -> dict:
    """What the Methods draft may say about amendments (PRISMA 24c)."""
    data = register(db, project_id)
    # a detected signal the team answered with a rationale is a declared
    # deviation like any other; only the dismissed ones stay out
    declared = [d for d in data["deviations"] if not d["dismissed"]]
    return {
        "n_declared": len(declared),
        "n_detected_unanswered": data["n_undeclared_signals"],
        "deviations": [{"stage": d["stage_label"], "what": d["summary"],
                        "why": d["rationale"], "when": d["occurred_at"]}
                       for d in declared],
    }
