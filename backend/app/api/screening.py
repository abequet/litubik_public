# SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
# SPDX-License-Identifier: AGPL-3.0-or-later
"""M5: title/abstract screening — config, blind voting, conflicts, stats.

Double blind is enforced HERE (server-side): queue payloads never contain
other reviewers' votes; votes are only exposed on records whose voting is
complete (conflict views).
"""
import csv
import io
import random
import unicodedata
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import func

from app.api.deps import (
    DbDep, ProjectMemberDep, SatelliteGuard, get_project, get_project_member,
    require_project_admin,
)
from app.core.csvsafe import safe_row
from app.models import (
    AiReveal, Assignment, Conflict, FullText, Job, Project, ProjectMember,
    Record, RecordTag, ScreeningConfig, ScreeningLot, Tag, TriageControl,
    User, Vote,
)
from app.services.llm.base import LLMError
from app.services.screening import generate_assignments, screening_stats
from app.services.screening.anonymity import (
    Namer, names_hidden, namer_for, project_namer,
)
from app.services.screening.ai import (
    estimate_ft_cost, estimate_suggestion_cost, get_or_create_ft_suggestion,
    get_or_create_suggestion, pdf_ai_block_reason,
)
from app.services.screening.core import (
    eligible_record_ids, ensure_conflict, human_votes, record_outcome,
    required_votes, sync_assignments,
)
from app.services.screening.lots import (
    allowed_pairs, lot_rows, preview_lots, weights_error,
)
from app.services.screening.reasons import (
    NOTFOUND_CODE, exclusion_reasons, ft_prisma_outcomes, primary_reason,
    reason_labels,
)
from app.services.translation import valid_translations

router = APIRouter(prefix="/api/projects/{project_id}/screening", tags=["screening"])


class ConfigIn(BaseModel):
    stage: str = Field(default="ta", pattern="^(ta|ft)$")
    allocation: str = Field(default="all",
                            pattern="^(all|dual|single_overlap|lots|lead)$")
    overlap_pct: int = Field(default=20, ge=0, le=100)
    # allocation = lead: the reviewer who screens every record; the others
    # share the corpus (weights over the co-reviewers, or equal shares)
    lead_user_id: int | None = None
    # allocation = lots: share of the work per reviewer in percent (sum 100;
    # empty = equal shares), records per lot, 0–2 named arbiters (never
    # paired together on a lot)
    weights: dict[str, float] | None = None
    lot_size: int = Field(default=100, ge=1, le=10000)
    arbiter_ids: list[int] = Field(default_factory=list, max_length=2)
    conflict_resolution: str = Field(default="consensus",
                                     pattern="^(consensus|arbiter)$")
    ai_enabled: bool = False
    # AI title triage: off | admin (validated list = global exclusion, admin
    # only) | reviewers (validated list = the reviewer's own exclude votes)
    ai_triage: str = Field(default="off", pattern="^(off|admin|reviewers)$")
    # control sample of the triage: this % of every validated exclusion list
    # is held back at random, unmarked, in the human queue (0 = off)
    triage_control_pct: int = Field(default=0, ge=0, le=50)
    # batch AI suggestion button on the screen tab (title+abstract vs I/E)
    ai_batch: bool = False
    # always: the suggestion shows as soon as it is cached | after_vote: hidden
    # until the reviewer's own vote (a cached one can be revealed on purpose,
    # which is recorded)
    ai_reveal: str = Field(default="always", pattern="^(always|after_vote)$")
    # anonymous reviewers: nobody (admins included) sees who voted what nor
    # who is paired with whom until the round is complete — frozen at start
    anonymous: bool = False
    reviewer_ids: list[int] = []


class ConfigOut(BaseModel):
    id: int
    stage: str
    round: int
    allocation: str
    overlap_pct: int
    conflict_resolution: str
    ai_enabled: bool
    ai_triage: str
    triage_control_pct: int = 0
    ai_batch: bool
    ai_reveal: str = "always"
    reviewer_ids: list
    lead_user_id: int | None = None
    weights: dict | None = None
    lot_size: int = 100
    arbiter_ids: list | None = None
    anonymous: bool = False
    status: str
    started_at: datetime | None

    model_config = {"from_attributes": True}


class LotIn(BaseModel):
    """One lot of the plan as edited by the admin before the start."""
    index: int
    user_ids: list[int]
    due_at: datetime | None = None


class StartIn(BaseModel):
    # allocation = lots: the previewed plan with the admin's edits
    lots: list[LotIn] | None = None


class VoteIn(BaseModel):
    record_id: int
    decision: str = Field(pattern="^(include|exclude|maybe)$")
    reasons: list[str] = []
    justification: str = ""


class ResolveIn(BaseModel):
    decision: str = Field(pattern="^(include|exclude)$")
    note: str = ""
    # Full-text: exclusion reasons recorded at resolution (first = primary).
    reasons: list[str] = []


def _rounds(project_id: int, stage: str, db) -> list[int]:
    return [r for (r,) in db.query(ScreeningConfig.round)
            .filter_by(project_id=project_id, stage=stage)
            .order_by(ScreeningConfig.round).all()]


def _resolve_round(project_id: int, stage: str, db, round_: int | None) -> int:
    """Explicit round if given; else the latest ACTIVE round, falling back to
    the latest configured one. Snowballing pre-creates the next round as a
    draft — defaulting to it would hide the finished rounds' decisions and
    exclusion reasons behind an empty screen."""
    if round_ is not None:
        return round_
    active = [r for (r,) in db.query(ScreeningConfig.round)
              .filter_by(project_id=project_id, stage=stage, status="active")
              .order_by(ScreeningConfig.round).all()]
    if active:
        return active[-1]
    rounds = _rounds(project_id, stage, db)
    return rounds[-1] if rounds else 1


def _get_config(project_id: int, stage: str, db,
                round_: int | None = None) -> ScreeningConfig | None:
    return (db.query(ScreeningConfig)
            .filter_by(project_id=project_id, stage=stage,
                       round=_resolve_round(project_id, stage, db, round_))
            .first())


def _require_active(project_id: int, stage: str, db,
                    round_: int | None = None) -> ScreeningConfig:
    config = _get_config(project_id, stage, db, round_)
    if config is None or config.status != "active":
        raise HTTPException(status_code=400,
                            detail="Screening has not been started yet")
    return config


@router.get("/config")
def get_config(project_id: int, member: ProjectMemberDep, db: DbDep,
               stage: str = "ta", round: int | None = None):
    get_project(project_id, db)
    resolved = _resolve_round(project_id, stage, db, round)
    config = _get_config(project_id, stage, db, resolved)
    members = (db.query(ProjectMember, User)
               .join(User, User.id == ProjectMember.user_id)
               .filter(ProjectMember.project_id == project_id).all())
    hidden = names_hidden(db, config)
    config_out = ConfigOut.model_validate(config).model_dump() if config else None
    if config_out and hidden and member.role != "admin":
        # the lead is every co-reviewer's pair: only the admin who picked
        # them keeps the name while the round is anonymous
        config_out["lead_user_id"] = None
    return {
        "config": config_out,
        # true while the reviewers of this round are anonymous: the front
        # shows the banner, every name in the payloads is already a pseudonym
        "names_hidden": hidden,
        "members": [{"user_id": u.id, "display_name": u.display_name,
                     "role": m.role,
                     "registered": u.password_hash != ""}
                    for m, u in members],
        "eligible_records": len(eligible_record_ids(db, project_id, stage,
                                                    resolved)),
        # what a reset of this round would delete — shown in its confirmation
        "n_votes": db.query(Vote).filter_by(project_id=project_id, stage=stage,
                                            round=resolved).count(),
        "me": member.user_id,
        "my_role": member.role,
        "round": resolved,
        "rounds": _rounds(project_id, stage, db) or [1],
    }


@router.put("/config", response_model=ConfigOut,
            dependencies=[Depends(require_project_admin), SatelliteGuard])
def upsert_config(project_id: int, payload: ConfigIn, db: DbDep,
                  round: int | None = None):
    get_project(project_id, db)
    resolved = _resolve_round(project_id, payload.stage, db, round)
    config = _get_config(project_id, payload.stage, db, resolved)
    if config is not None and config.status == "active":
        raise HTTPException(status_code=400,
                            detail="Screening already started — reset it to change "
                                   "the configuration")
    member_ids = {m.user_id for m in db.query(ProjectMember)
                  .filter_by(project_id=project_id)}
    reviewer_ids = [uid for uid in dict.fromkeys(payload.reviewer_ids)
                    if uid in member_ids]
    if config is None:
        config = ScreeningConfig(project_id=project_id, stage=payload.stage,
                                 round=resolved)
        db.add(config)
    config.allocation = payload.allocation
    config.overlap_pct = payload.overlap_pct
    config.conflict_resolution = payload.conflict_resolution
    config.ai_enabled = payload.ai_enabled
    config.ai_triage = payload.ai_triage
    config.triage_control_pct = payload.triage_control_pct
    config.ai_batch = payload.ai_batch
    config.ai_reveal = payload.ai_reveal
    config.anonymous = payload.anonymous
    config.reviewer_ids = reviewer_ids
    config.n_reviewers = len(reviewer_ids)
    config.lot_size = payload.lot_size
    config.weights = ({str(uid): float(pct) for uid, pct in payload.weights.items()
                       if uid.isdigit() and int(uid) in reviewer_ids}
                      if payload.weights else None) or None
    config.arbiter_ids = [uid for uid in dict.fromkeys(payload.arbiter_ids)
                          if uid in member_ids]
    config.lead_user_id = (payload.lead_user_id
                           if payload.lead_user_id in reviewer_ids else None)
    if payload.allocation == "lots":
        error = weights_error(reviewer_ids, config.weights)
        if error:
            raise HTTPException(status_code=400, detail=error)
    elif payload.allocation == "lead":
        # the lead takes everything: the shares are over the co-reviewers
        co = [uid for uid in reviewer_ids if uid != config.lead_user_id]
        config.weights = ({k: v for k, v in (config.weights or {}).items()
                           if int(k) in co}) or None
        error = weights_error(co, config.weights)
        if error:
            raise HTTPException(status_code=400, detail=error)
    db.commit()
    db.refresh(config)
    return config


def _lots_ready(config: ScreeningConfig) -> None:
    """What a lots round needs before its plan can be computed."""
    reviewers = list(config.reviewer_ids or [])
    if len(reviewers) < 2:
        raise HTTPException(status_code=400,
                            detail="'lots' needs at least 2 reviewers")
    error = weights_error(reviewers, config.weights)
    if error:
        raise HTTPException(status_code=400, detail=error)
    if not allowed_pairs(reviewers, config.arbiter_ids):
        raise HTTPException(
            status_code=400,
            detail="The two arbiters cannot be the only two reviewers: "
                   "they are never paired together")


def _lead_ready(config: ScreeningConfig) -> None:
    """What a lead-reviewer round needs: a lead among the reviewers and at
    least one co-reviewer with valid shares."""
    reviewers = list(config.reviewer_ids or [])
    if config.lead_user_id not in reviewers:
        raise HTTPException(status_code=400,
                            detail="Pick the lead reviewer among the reviewers")
    co = [uid for uid in reviewers if uid != config.lead_user_id]
    if not co:
        raise HTTPException(status_code=400,
                            detail="'lead' needs at least one other reviewer")
    error = weights_error(co, config.weights)
    if error:
        raise HTTPException(status_code=400, detail=error)


@router.post("/lots/preview",
             dependencies=[Depends(require_project_admin), SatelliteGuard])
def lots_preview(project_id: int, db: DbDep, stage: str = "ta",
                 round: int | None = None):
    """The lots /start would create — the admin reviews the pair of each
    lot, sets deadlines, then starts with the edited plan."""
    config = _get_config(project_id, stage, db, round)
    if config is None:
        raise HTTPException(status_code=400, detail="Configure screening first")
    if config.allocation != "lots":
        raise HTTPException(status_code=400,
                            detail="This round is not allocated in lots")
    _lots_ready(config)
    if not eligible_record_ids(db, project_id, stage, config.round):
        raise HTTPException(status_code=400,
                            detail="No record to screen yet")
    return preview_lots(db, config)


@router.get("/allocation.csv")
def allocation_csv(project_id: int, member: ProjectMemberDep, db: DbDep,
                   stage: str = "ta", round: int | None = None):
    """The published allocation: one line per lot — lot, size, reviewer A,
    reviewer B, deadline, status. Deposited with the protocol."""
    config = _get_config(project_id, stage, db, round)
    if config is None or config.allocation != "lots":
        raise HTTPException(status_code=404,
                            detail="This round is not allocated in lots")
    users = namer_for(db, config)  # pseudonyms while the round is anonymous
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(["Lot", "Size", "Reviewer A", "Reviewer B", "Due",
                     "Status"])
    for row in lot_rows(db, config):
        a, b = (row["user_ids"] + [None, None])[:2]
        writer.writerow(safe_row([
            row["index"], row["size"], users(a, ""), users(b, ""),
            (row["due_at"] or "")[:10], row["status"]]))
    db.commit()
    name = f"allocation_{stage}_r{config.round}.csv"
    return StreamingResponse(
        iter([buffer.getvalue().encode("utf-8-sig")]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{name}"'})


class TriageModeIn(BaseModel):
    ai_triage: str = Field(pattern="^(off|admin|reviewers)$")
    # optional: the control-sample share, changeable while the round runs too
    triage_control_pct: int | None = Field(default=None, ge=0, le=50)


@router.put("/config/triage-mode",
            dependencies=[Depends(require_project_admin), SatelliteGuard])
def set_triage_mode(project_id: int, payload: TriageModeIn, db: DbDep,
                    stage: str = "ta", round: int | None = None):
    """The triage mode is safe to change while a round runs (unlike the
    allocation/reviewers, locked once started)."""
    config = _get_config(project_id, stage, db, round)
    if config is None:
        raise HTTPException(status_code=404, detail="No screening configured")
    config.ai_triage = payload.ai_triage
    if payload.triage_control_pct is not None:
        config.triage_control_pct = payload.triage_control_pct
    db.commit()
    return {"ok": True, "ai_triage": config.ai_triage,
            "triage_control_pct": config.triage_control_pct}


class AiBatchModeIn(BaseModel):
    ai_batch: bool


@router.put("/config/ai-batch",
            dependencies=[Depends(require_project_admin), SatelliteGuard])
def set_ai_batch(project_id: int, payload: AiBatchModeIn, db: DbDep,
                 stage: str = "ta", round: int | None = None):
    """Admin toggles the batch-AI-suggestion button; safe while the round runs
    (only exposes the button — reviewers still trigger and review it)."""
    config = _get_config(project_id, stage, db, round)
    if config is None:
        raise HTTPException(status_code=404, detail="No screening configured")
    config.ai_batch = payload.ai_batch
    db.commit()
    return {"ok": True, "ai_batch": config.ai_batch}


class AiRevealModeIn(BaseModel):
    ai_reveal: str = Field(pattern="^(always|after_vote)$")


@router.put("/config/ai-reveal",
            dependencies=[Depends(require_project_admin), SatelliteGuard])
def set_ai_reveal(project_id: int, payload: AiRevealModeIn, db: DbDep,
                  stage: str = "ta", round: int | None = None):
    """When reviewers get to see the AI suggestion; safe to change while the
    round runs (it only gates what the screen shows, never a vote)."""
    config = _get_config(project_id, stage, db, round)
    if config is None:
        raise HTTPException(status_code=404, detail="No screening configured")
    config.ai_reveal = payload.ai_reveal
    db.commit()
    return {"ok": True, "ai_reveal": config.ai_reveal}


@router.post("/start",
             dependencies=[Depends(require_project_admin), SatelliteGuard])
def start(project_id: int, db: DbDep, stage: str = "ta",
          round: int | None = None, payload: StartIn | None = None):
    config = _get_config(project_id, stage, db, round)
    if config is None:
        raise HTTPException(status_code=400, detail="Configure screening first")
    if config.status == "active":
        raise HTTPException(status_code=400, detail="Already started")
    reviewers = list(config.reviewer_ids or [])
    if not reviewers:
        raise HTTPException(status_code=400, detail="Pick at least one reviewer")
    if config.allocation in ("dual", "single_overlap") and len(reviewers) < 2:
        raise HTTPException(status_code=400,
                            detail=f"'{config.allocation}' needs at least 2 reviewers")
    if config.allocation == "lots":
        _lots_ready(config)
    if config.allocation == "lead":
        _lead_ready(config)
    if not eligible_record_ids(db, project_id, stage, config.round):
        raise HTTPException(
            status_code=400,
            detail=("No record included at title/abstract to screen — finish "
                    "T/A screening first"
                    if stage == "ft"
                    else "No unique record to screen — run deduplication first"))
    lots = ([lot.model_dump() for lot in payload.lots]
            if payload and payload.lots else None)
    try:
        summary = generate_assignments(db, config, lots)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc))
    config.status = "active"
    config.started_at = datetime.now(timezone.utc)
    db.commit()
    return summary


@router.post("/reset",
             dependencies=[Depends(require_project_admin), SatelliteGuard])
def reset(project_id: int, db: DbDep, stage: str = "ta",
          round: int | None = None):
    """Wipe assignments, votes (human + AI) and conflicts for this stage/round."""
    config = _get_config(project_id, stage, db, round)
    if config is None:
        raise HTTPException(status_code=404, detail="No screening configured")
    db.query(Assignment).filter_by(config_id=config.id).delete()
    db.query(ScreeningLot).filter_by(config_id=config.id).delete()
    db.query(Vote).filter_by(project_id=project_id, stage=stage,
                             round=config.round).delete()
    db.query(Conflict).filter_by(project_id=project_id, stage=stage,
                                 round=config.round).delete()
    db.query(TriageControl).filter_by(project_id=project_id, stage=stage,
                                      round=config.round).delete()
    config.status = "draft"
    config.started_at = None
    db.commit()
    return {"ok": True}


@router.get("/queue")
def queue(project_id: int, member: ProjectMemberDep, db: DbDep,
          stage: str = "ta", limit: int = 10, round: int | None = None):
    """My next records to screen. Never contains anyone else's votes."""
    config = _require_active(project_id, stage, db, round)
    # records imported/ruled unique after /start join the round here
    sync_assignments(db, config)
    assigned = (db.query(Assignment.record_id)
                .filter_by(config_id=config.id, user_id=member.user_id))
    my_votes = (db.query(Vote.record_id)
                .filter_by(project_id=project_id, stage=stage,
                           round=config.round, voter_user_id=member.user_id,
                           is_ai=False))
    # records already decided without my vote (admin AI-triage exclusions
    # resolve the record globally) must leave my queue too
    resolved = (db.query(Conflict.record_id)
                .filter_by(project_id=project_id, stage=stage,
                           round=config.round, status="resolved"))
    # globally-resolved records I never voted on (admin triage) drop out of my
    # workload entirely, so they count in neither total nor done
    resolved_not_mine = (assigned
                         .filter(Assignment.record_id.in_(resolved.scalar_subquery()),
                                 Assignment.record_id.notin_(my_votes.scalar_subquery()))
                         .count())
    total = assigned.count() - resolved_not_mine
    done = my_votes.count()
    # skipped ("decide later") records sink to the back of the queue and come
    # around again once everything else is voted
    pending = (db.query(Record, Assignment.skipped_at)
               .join(Assignment, Assignment.record_id == Record.id)
               .filter(Assignment.config_id == config.id,
                       Assignment.user_id == member.user_id,
                       Record.id.notin_(my_votes.scalar_subquery()),
                       Record.id.notin_(resolved.scalar_subquery())))
    n_skipped = sum(1 for _, s in pending if s is not None)
    # lots: lot 1 before lot 2 (lot ids follow the lot order)
    rows = (pending.order_by(Assignment.skipped_at.isnot(None),
                             Assignment.lot_id, Record.id)
            .limit(min(max(limit, 1), 50)).all())
    records = [r for r, _ in rows]
    skipped_flags = {r.id: s is not None for r, s in rows}
    # full-text availability so the viewer can load the PDF (ft stage)
    fts = {ft.record_id: ft for ft in db.query(FullText)
           .filter(FullText.record_id.in_([r.id for r in records]))} if records else {}
    return {
        "total": total, "done": done, "skipped": n_skipped,
        "items": [{
            "id": r.id, "doi": r.doi, "title": r.title, "authors": r.authors,
            "year": r.year, "journal": r.journal, "abstract": r.abstract,
            "translations": valid_translations(r),
            "skipped": skipped_flags.get(r.id, False),
            "fulltext_status": (fts[r.id].status if r.id in fts else "pending"),
            "has_pdf": bool(r.id in fts and fts[r.id].file_path),
            "oa_url": (fts[r.id].oa_url if r.id in fts else ""),
        } for r in records],
    }


def _fold(text: str) -> str:
    """Lowercase + strip accents, for the list view's keyword search."""
    return "".join(c for c in unicodedata.normalize("NFKD", text.lower())
                   if not unicodedata.combining(c))


@router.get("/list")
def screening_list(project_id: int, member: ProjectMemberDep, db: DbDep,
                   stage: str = "ta", q: str = "", status: str = "pending",
                   offset: int = 0, limit: int = 30, round: int | None = None):
    """Ticket #8 — list view over MY assigned records: keyword search
    (title/abstract/authors/journal, accent-insensitive, AND of terms) and
    offset pagination for infinite scroll. Pending rows come first (skipped
    ones sink, like the queue); voted rows follow, most recent vote first.
    Double blind untouched: only my own votes appear."""
    config = _require_active(project_id, stage, db, round)
    sync_assignments(db, config)
    my_votes = {v.record_id: v for v in db.query(Vote).filter_by(
        project_id=project_id, stage=stage, round=config.round,
        voter_user_id=member.user_id, is_ai=False)}
    resolved = {c.record_id for c in db.query(Conflict).filter_by(
        project_id=project_id, stage=stage, round=config.round,
        status="resolved")}
    conflicted = {c.record_id for c in db.query(Conflict).filter_by(
        project_id=project_id, stage=stage, round=config.round)}
    from app.services.screening.core import screening_outcomes
    outcomes = screening_outcomes(db, config)

    rows = (db.query(Record, Assignment.skipped_at)
            .join(Assignment, Assignment.record_id == Record.id)
            .filter(Assignment.config_id == config.id,
                    Assignment.user_id == member.user_id).all())
    items = []
    for record, skipped_at in rows:
        vote_row = my_votes.get(record.id)
        # globally-resolved records I never voted on (admin triage) are not
        # part of my workload — same rule as the queue
        if vote_row is None and record.id in resolved:
            continue
        items.append({
            "id": record.id, "doi": record.doi, "title": record.title,
            "authors": record.authors, "year": record.year,
            "journal": record.journal, "abstract": record.abstract,
            "translations": valid_translations(record),
            "skipped": vote_row is None and skipped_at is not None,
            "decision": vote_row.decision if vote_row else None,
            "note": vote_row.justification if vote_row else "",
            "locked": vote_row is not None and (
                record.id in outcomes or record.id in conflicted),
            "_sort": ((0, int(skipped_at is not None), record.id)
                      if vote_row is None else (1, -vote_row.id, 0)),
        })
    if status in ("pending", "voted"):
        wanted = status == "voted"
        items = [it for it in items if (it["decision"] is not None) == wanted]
    terms = [_fold(term) for term in q.split() if term.strip()]
    if terms:
        items = [it for it in items
                 if all(term in _fold(" ".join(
                     [it["title"], it["abstract"] or "", it["journal"] or "",
                      " ".join(it["authors"] or [])])) for term in terms)]
    items.sort(key=lambda it: it["_sort"])
    total = len(items)
    offset = max(offset, 0)
    page = items[offset:offset + min(max(limit, 1), 100)]
    # the page's tags in one query, so each card's chips need no request
    tags: dict[int, list[dict]] = {it["id"]: [] for it in page}
    if tags:
        for record_id, tag in (db.query(RecordTag.record_id, Tag)
                               .join(Tag, Tag.id == RecordTag.tag_id)
                               .filter(Tag.project_id == project_id,
                                       RecordTag.record_id.in_(tags))
                               .order_by(func.lower(Tag.name))):
            tags[record_id].append({"id": tag.id, "name": tag.name})
    for it in page:
        del it["_sort"]
        it["tags"] = tags[it["id"]]
    return {"total": total, "items": page}


@router.post("/skip")
def skip(project_id: int, payload: dict, member: ProjectMemberDep, db: DbDep,
         stage: str = "ta", round: int | None = None):
    """"Decide later": push one of my assigned, unvoted records to the back of
    my queue. Voting on it later is unchanged."""
    config = _require_active(project_id, stage, db, round)
    record_id = int(payload.get("record_id") or 0)
    assignment = (db.query(Assignment)
                  .filter_by(config_id=config.id, record_id=record_id,
                             user_id=member.user_id).first())
    if assignment is None:
        raise HTTPException(status_code=403,
                            detail="This record is not assigned to you")
    assignment.skipped_at = datetime.now(timezone.utc)
    db.commit()
    return {"ok": True}


@router.get("/my-votes")
def my_votes(project_id: int, member: ProjectMemberDep, db: DbDep,
             stage: str = "ta", limit: int = 500, round: int | None = None):
    """My screening history, most recent first — used to revisit past votes.
    `locked` = the record completed (my vote can no longer change).
    Only MY votes: the double blind is untouched."""
    config = _require_active(project_id, stage, db, round)
    votes = (db.query(Vote)
             .filter_by(project_id=project_id, stage=stage, round=config.round,
                        voter_user_id=member.user_id, is_ai=False)
             .order_by(Vote.id.desc())
             .limit(min(max(limit, 1), 1000)).all())
    from app.services.screening.core import screening_outcomes
    outcomes = screening_outcomes(db, config)
    conflicted = {c.record_id for c in db.query(Conflict).filter_by(
        project_id=project_id, stage=stage, round=config.round)}
    record_ids = [v.record_id for v in votes]
    records = {r.id: r for r in db.query(Record).filter(Record.id.in_(record_ids))}
    labels = reason_labels(db, project_id, stage) if stage == "ft" else {}
    fts = ({ft.record_id: ft for ft in db.query(FullText)
            .filter(FullText.record_id.in_(record_ids))}
           if stage == "ft" and record_ids else {})
    out = []
    for vote_row in votes:
        record = records.get(vote_row.record_id)
        if record is None:
            continue
        ft = fts.get(record.id)
        out.append({
            "record": {"id": record.id, "doi": record.doi, "title": record.title,
                       "authors": record.authors, "year": record.year,
                       "journal": record.journal, "abstract": record.abstract,
                       "fulltext_status": ft.status if ft else "pending",
                       "has_pdf": bool(ft and ft.file_path),
                       "oa_url": ft.oa_url if ft else ""},
            "decision": vote_row.decision,
            "reasons": vote_row.reasons or [],
            "reason_labels": [labels.get(c, c) for c in (vote_row.reasons or [])],
            "note": vote_row.justification,
            "locked": (record.id in outcomes) or (record.id in conflicted),
        })
    return out


@router.post("/vote")
def vote(project_id: int, payload: VoteIn, member: ProjectMemberDep, db: DbDep,
         stage: str = "ta", round: int | None = None):
    config = _require_active(project_id, stage, db, round)
    assignment = (db.query(Assignment)
                  .filter_by(config_id=config.id, record_id=payload.record_id,
                             user_id=member.user_id).first())
    if assignment is None:
        raise HTTPException(status_code=403,
                            detail="This record is not assigned to you")
    if record_outcome(db, config, payload.record_id) is not None:
        raise HTTPException(status_code=400,
                            detail="Voting on this record is closed")
    reasons = payload.reasons
    if stage == "ft" and payload.decision == "exclude":
        valid = {r["code"] for r in exclusion_reasons(db, project_id, "ft")}
        reasons = [c for c in dict.fromkeys(payload.reasons) if c in valid]
        if not reasons:
            raise HTTPException(
                status_code=400,
                detail="Pick a primary exclusion reason (full-text exclusions "
                       "must be justified by a protocol criterion)")
    existing = (db.query(Vote)
                .filter_by(project_id=project_id, record_id=payload.record_id,
                           stage=stage, round=config.round,
                           voter_user_id=member.user_id, is_ai=False).first())
    if existing is None:
        existing = Vote(project_id=project_id, record_id=payload.record_id,
                        stage=stage, round=config.round,
                        voter_user_id=member.user_id, is_ai=False,
                        decision=payload.decision)
        db.add(existing)
    existing.decision = payload.decision
    existing.reasons = reasons
    existing.justification = payload.justification
    db.flush()
    ensure_conflict(db, config, payload.record_id)
    db.commit()
    return {"ok": True, "outcome": record_outcome(db, config, payload.record_id)}


class VoteUndoIn(BaseModel):
    record_id: int
    # the vote this one replaced, to put back — None = I had not voted yet
    previous_decision: str | None = Field(default=None,
                                          pattern="^(include|exclude|maybe)$")
    previous_justification: str = ""


@router.post("/vote/undo")
def undo_vote(project_id: int, payload: VoteUndoIn, member: ProjectMemberDep,
              db: DbDep, stage: str = "ta", round: int | None = None):
    """Take back the vote I just cast (a misclick): restore the one it
    replaced, or remove it. Allowed while nobody has acted on the outcome it
    produced — an open conflict it opened is withdrawn, a resolved one keeps
    the vote. Title/abstract only: a full-text vote carries reasons."""
    if stage != "ta":
        raise HTTPException(status_code=400,
                            detail="Only title/abstract votes can be undone here")
    config = _require_active(project_id, stage, db, round)
    record_id = payload.record_id
    assignment = (db.query(Assignment)
                  .filter_by(config_id=config.id, record_id=record_id,
                             user_id=member.user_id).first())
    if assignment is None:
        raise HTTPException(status_code=403,
                            detail="This record is not assigned to you")
    vote_row = (db.query(Vote)
                .filter_by(project_id=project_id, record_id=record_id,
                           stage=stage, round=config.round,
                           voter_user_id=member.user_id, is_ai=False).first())
    if vote_row is None:
        raise HTTPException(status_code=400, detail="No vote to undo")
    conflict = (db.query(Conflict)
                .filter_by(project_id=project_id, record_id=record_id,
                           stage=stage, round=config.round).first())
    if conflict is not None and conflict.status == "resolved":
        raise HTTPException(status_code=400,
                            detail="This record's conflict is already resolved "
                                   "— its vote can no longer be undone")
    # an inclusion may already have reached full-text screening: take it back
    # out of the queues, unless someone voted on it there
    ft = _get_config(project_id, "ft", db, config.round)
    if ft is not None:
        if human_votes(db, ft, record_id):
            raise HTTPException(
                status_code=400,
                detail="This record already has full-text votes — its "
                       "title/abstract vote can no longer be undone")
        db.query(Assignment).filter_by(config_id=ft.id,
                                       record_id=record_id).delete()
    if conflict is not None:
        db.delete(conflict)
    if payload.previous_decision is None:
        db.delete(vote_row)
    else:
        vote_row.decision = payload.previous_decision
        vote_row.reasons = []
        vote_row.justification = payload.previous_justification
    db.flush()
    ensure_conflict(db, config, record_id)
    db.commit()
    return {"ok": True, "outcome": record_outcome(db, config, record_id)}


class TriageRunIn(BaseModel):
    threshold: int = Field(default=95, ge=80, le=99)


class TriageApplyIn(BaseModel):
    record_ids: list[int] = Field(min_length=1, max_length=5000)


def _triage_config(project_id: int, db, round_: int | None,
                   member) -> ScreeningConfig:
    config = _require_active(project_id, "ta", db, round_)
    if config.ai_triage == "off":
        raise HTTPException(status_code=400,
                            detail="Enable AI title triage in the screening "
                                   "settings first")
    if config.ai_triage == "admin" and member.role != "admin":
        raise HTTPException(status_code=403,
                            detail="Title triage is admin-only on this project")
    if (config.ai_triage == "reviewers"
            and member.user_id not in (config.reviewer_ids or [])):
        raise HTTPException(status_code=403,
                            detail="Title triage casts YOUR votes — you are "
                                   "not a reviewer of this round")
    return config


@router.get("/triage/estimate")
def triage_estimate(project_id: int, member: ProjectMemberDep, db: DbDep,
                    round: int | None = None):
    """How many titles a triage would send, and roughly what it would cost."""
    from app.services.screening.triage import estimate_triage
    config = _triage_config(project_id, db, round, member)
    return estimate_triage(db, config, member.user_id)


@router.post("/triage")
def triage_run(project_id: int, payload: TriageRunIn, member: ProjectMemberDep,
               db: DbDep, round: int | None = None):
    """Send every not-yet-voted title of the round to the AI; it proposes
    exclusions above the confidence threshold. Proposals only — the human
    validates a checklist, then /triage/apply writes."""
    from app.services.screening.triage import candidate_ids
    from app.workers.runner import runner
    config = _triage_config(project_id, db, round, member)
    n = len(candidate_ids(db, config, member.user_id))
    if n == 0:
        raise HTTPException(status_code=400,
                            detail="No candidate — every record of this round "
                                   "already has a vote or a decision")
    job = runner.submit("ta_triage",
                        {"project_id": project_id, "round": config.round,
                         "user_id": member.user_id,
                         "threshold": payload.threshold},
                        project_id=project_id, user_id=member.user_id)
    return {"job_id": job.id, "candidates": n}


@router.get("/triage/latest")
def triage_latest(project_id: int, member: ProjectMemberDep, db: DbDep,
                  round: int | None = None):
    """The most recent completed triage for this round and caller, so the saved
    proposals reappear on return without re-running the AI. Proposals for records
    that have since been voted or decided are dropped (they are no longer
    candidates), so the list shrinks as it gets validated."""
    from app.services.screening.triage import candidate_ids
    config = _triage_config(project_id, db, round, member)
    latest = _latest_triage_job(db, project_id, config.round, member.user_id)
    if latest is None:
        return {"proposals": None}
    valid = set(candidate_ids(db, config, member.user_id))
    result = latest.result or {}
    proposals = [p for p in (result.get("proposals") or [])
                 if p.get("record_id") in valid]
    return {"proposals": proposals,
            "n_screened": result.get("n_screened", 0),
            "threshold": result.get("threshold", 95),
            "generated_at": latest.finished_at or latest.created_at,
            "job_id": latest.id}


def _latest_triage_job(db, project_id: int, round_: int,
                       user_id: int) -> Job | None:
    """The caller's most recent completed triage job for this round."""
    jobs = (db.query(Job)
            .filter(Job.project_id == project_id, Job.type == "ta_triage",
                    Job.status == "done", Job.created_by == user_id)
            .order_by(Job.created_at.desc()).limit(30).all())
    return next((j for j in jobs
                 if (j.params or {}).get("round") == round_), None)


@router.post("/triage/apply", dependencies=[SatelliteGuard])
def triage_apply(project_id: int, payload: TriageApplyIn,
                 member: ProjectMemberDep, db: DbDep,
                 round: int | None = None):
    """Write the exclusions the user ticked and validated. Depending on the
    config's mode: admin = global exclusion (audited ai_triage rows),
    reviewers = MY exclude votes. Records that gained a vote or a decision
    since the proposal are skipped, never overridden.

    Control sample: when the config asks for one, that share of the
    validated list is drawn at random and held back instead — no vote, no
    conflict, the records stay in the human queue unmarked — and recorded in
    `triage_controls` so the dashboard can check that the reviewers exclude
    them too."""
    from app.services.screening.triage import candidate_ids, control_sample_size
    config = _triage_config(project_id, db, round, member)
    valid = set(candidate_ids(db, config, member.user_id))
    user = db.get(User, member.user_id)
    name = user.display_name if user else "?"
    wanted = list(dict.fromkeys(payload.record_ids))
    to_apply = [rid for rid in wanted if rid in valid]
    skipped = len(wanted) - len(to_apply)
    controls: set[int] = set()
    n_ctrl = control_sample_size(len(to_apply), config.triage_control_pct or 0)
    if n_ctrl:
        controls = set(random.sample(to_apply, n_ctrl))
        latest = _latest_triage_job(db, project_id, config.round, member.user_id)
        proposals = {p.get("record_id"): p for p in
                     ((latest.result or {}).get("proposals") or [])} if latest else {}
        for record_id in controls:
            p = proposals.get(record_id) or {}
            db.add(TriageControl(
                project_id=project_id, record_id=record_id, stage="ta",
                round=config.round, held_by=member.user_id,
                job_id=latest.id if latest else None,
                confidence=p.get("confidence"), reason=p.get("reason") or ""))
    applied = 0
    for record_id in to_apply:
        if record_id in controls:
            continue
        if config.ai_triage == "admin":
            db.add(Conflict(
                project_id=project_id, record_id=record_id, stage="ta",
                round=config.round, status="resolved", resolution="exclude",
                origin="ai_triage",
                resolution_note=f"AI title triage — validated by {name}",
                resolved_by=member.user_id,
                resolved_at=datetime.now(timezone.utc)))
        else:  # reviewers: my own exclude vote, normal outcome rules
            db.add(Vote(project_id=project_id, record_id=record_id,
                        stage="ta", round=config.round,
                        voter_user_id=member.user_id, is_ai=False,
                        decision="exclude",
                        justification="AI title triage (validated by me)"))
            db.flush()
            ensure_conflict(db, config, record_id)
        applied += 1
    db.commit()
    return {"applied": applied, "skipped": skipped, "controls": len(controls),
            "mode": config.ai_triage}


@router.get("/triage-controls")
def triage_controls(project_id: int, member: ProjectMemberDep, db: DbDep,
                    round: int | None = None):
    """The control sample of the AI title triage and how the humans ruled on
    it. Blind-safe: undecided controls are only counted. A project admin sees
    every control of the round; in reviewers mode a reviewer sees the controls
    drawn from their own validated lists."""
    from app.services.screening.triage import control_report
    config = _get_config(project_id, "ta", db, round)
    if config is None:
        raise HTTPException(status_code=404, detail="No screening configured")
    if member.role == "admin":
        return control_report(db, config)
    if (config.ai_triage == "reviewers"
            and member.user_id in (config.reviewer_ids or [])):
        return control_report(db, config, held_by=member.user_id)
    raise HTTPException(status_code=403,
                        detail="The triage control sample is admin-only")


@router.get("/auto-excluded")
def auto_excluded_history(project_id: int, member: ProjectMemberDep, db: DbDep,
                          round: int | None = None):
    """#13: audit trail of the papers excluded through the AI title triage.
    Admin-mode validations are global exclusions (audited ai_triage
    resolutions); reviewer-mode validations are that reviewer's own exclude
    votes (tagged in their justification). The AI's per-title reason is
    recovered from the saved triage jobs. Reviewer-mode votes are listed
    only once their record is complete (blind), and under the reviewer's
    pseudonym while the round is anonymous."""
    users = project_namer(db, project_id)
    reasons: dict[int, str] = {}
    for job in (db.query(Job)
                .filter_by(project_id=project_id, type="ta_triage",
                           status="done").order_by(Job.created_at)):
        for p in (job.result or {}).get("proposals") or []:
            if p.get("record_id"):
                reasons[p["record_id"]] = p.get("reason", "")

    def row(record_id: int, kind: str, round_: int, who: int | None,
            when) -> dict | None:
        record = db.get(Record, record_id)
        if record is None:
            return None
        return {
            "record_id": record_id, "title": record.title,
            "authors": record.authors or [], "year": record.year,
            "round": round_, "kind": kind,
            "validated_by": users(who),
            "validated_at": when.isoformat() if when else "",
            "reason": reasons.get(record_id, ""),
        }

    out: list[dict] = []
    conflicts = (db.query(Conflict)
                 .filter_by(project_id=project_id, stage="ta",
                            origin="ai_triage", status="resolved"))
    if round is not None:
        conflicts = conflicts.filter(Conflict.round == round)
    for c in conflicts:
        if (r := row(c.record_id, "exclusion", c.round,
                     c.resolved_by, c.resolved_at)) is not None:
            out.append(r)
    votes = (db.query(Vote)
             .filter(Vote.project_id == project_id, Vote.stage == "ta",
                     Vote.is_ai.is_(False), Vote.decision == "exclude",
                     Vote.justification.like("AI title triage%")))
    if round is not None:
        votes = votes.filter(Vote.round == round)
    configs = {c.round: c for c in db.query(ScreeningConfig)
               .filter_by(project_id=project_id, stage="ta")}
    for v in votes:
        config = configs.get(v.round)
        # blind: a reviewer's exclude vote stays theirs until the record is
        # complete — unless it is the caller's own
        if (v.voter_user_id != member.user_id and config is not None
                and record_outcome(db, config, v.record_id) is None):
            continue
        if (r := row(v.record_id, "vote", v.round,
                     v.voter_user_id, v.created_at)) is not None:
            out.append(r)
    out.sort(key=lambda x: x["validated_at"], reverse=True)
    return out


@router.get("/conflicts")
def conflicts(project_id: int, member: ProjectMemberDep, db: DbDep,
              stage: str = "ta", status: str = "open",
              round: int | None = None):
    """Votes are revealed here only because these records are complete."""
    config = _require_active(project_id, stage, db, round)
    query = (db.query(Conflict)
             .filter_by(project_id=project_id, stage=stage, round=config.round,
                        origin="votes"))  # triage audit rows are not conflicts
    if status in ("open", "resolved"):
        query = query.filter(Conflict.status == status)
    rows = query.order_by(Conflict.id).all()
    users = namer_for(db, config)  # pseudonyms while the round is anonymous
    labels = reason_labels(db, project_id, stage) if stage == "ft" else {}
    fts = ({ft.record_id: ft for ft in db.query(FullText)
            .filter(FullText.record_id.in_([c.record_id for c in rows]))}
           if stage == "ft" and rows else {})
    out = []
    for conflict in rows:
        record = db.get(Record, conflict.record_id)
        if record is None:
            continue
        votes = human_votes(db, config, conflict.record_id)
        ft = fts.get(conflict.record_id)
        out.append({
            "id": conflict.id, "status": conflict.status,
            "resolution": conflict.resolution,
            "resolution_note": conflict.resolution_note,
            "resolution_reasons": [{"code": c, "label": labels.get(c, c)}
                                   for c in (conflict.reasons or [])],
            "resolved_by": users.name(conflict.resolved_by),
            "has_pdf": bool(ft and ft.file_path),
            "record": {"id": record.id, "doi": record.doi, "title": record.title,
                       "authors": record.authors, "year": record.year,
                       "journal": record.journal, "abstract": record.abstract},
            "votes": [{"reviewer": users(v.voter_user_id),
                       # the caller's own vote — labelled "you" when anonymous
                       "mine": v.voter_user_id == member.user_id,
                       "decision": v.decision, "reasons": v.reasons,
                       "reason_labels": [labels.get(c, c) for c in (v.reasons or [])],
                       "justification": v.justification} for v in votes],
        })
    return out


def _member_ids(config: ScreeningConfig) -> set[int]:
    from sqlalchemy.orm import object_session
    return {uid for (uid,) in object_session(config).query(ProjectMember.user_id)
            .filter_by(project_id=config.project_id)}


def _require_resolver(config: ScreeningConfig, member) -> None:
    """Who may settle (or reopen) a conflict, per the round's resolution mode."""
    if config.conflict_resolution == "arbiter":
        # the arbiters named for the round (admin or not); any project admin
        # when none was named or none of them is still a member, so that a
        # departure never leaves a round with nobody allowed to settle it
        named = set(config.arbiter_ids or []) & _member_ids(config)
        if named:
            if member.user_id not in named:
                raise HTTPException(
                    status_code=403,
                    detail="Arbiter mode: only the round's arbiters resolve")
        elif member.role != "admin":
            raise HTTPException(status_code=403,
                                detail="Arbiter mode: only a project admin resolves")
    else:  # consensus: participating reviewers (or admin)
        if member.role != "admin" and member.user_id not in (config.reviewer_ids or []):
            raise HTTPException(status_code=403,
                                detail="Consensus mode: only the reviewers resolve")


@router.post("/conflicts/{conflict_id}/resolve",
             dependencies=[SatelliteGuard])
def resolve_conflict(project_id: int, conflict_id: int, payload: ResolveIn,
                     member: ProjectMemberDep, db: DbDep, stage: str = "ta",
                     round: int | None = None):
    config = _require_active(project_id, stage, db, round)
    conflict = db.get(Conflict, conflict_id)
    if conflict is None or conflict.project_id != project_id:
        raise HTTPException(status_code=404, detail="Conflict not found")
    if conflict.status == "resolved":
        raise HTTPException(status_code=400, detail="Already resolved")
    _require_resolver(config, member)
    reasons: list[str] = []
    if stage == "ft" and payload.decision == "exclude":
        valid = {r["code"] for r in exclusion_reasons(db, project_id, "ft")}
        reasons = [c for c in dict.fromkeys(payload.reasons) if c in valid]
        if not reasons:
            raise HTTPException(
                status_code=400,
                detail="Record the primary exclusion reason for this full-text "
                       "exclusion")
    conflict.status = "resolved"
    conflict.resolution = payload.decision
    conflict.resolution_note = payload.note
    conflict.reasons = reasons
    conflict.resolved_by = member.user_id
    conflict.resolved_at = datetime.now(timezone.utc)
    db.commit()
    return {"ok": True}


@router.post("/conflicts/{conflict_id}/reopen",
             dependencies=[SatelliteGuard])
def reopen_conflict(project_id: int, conflict_id: int,
                    member: ProjectMemberDep, db: DbDep, stage: str = "ta",
                    round: int | None = None):
    """Undo a resolution (a misclick, a decision recorded on the wrong card):
    the conflict goes back to "to resolve" with the reviewers' votes intact.
    Open to whoever may resolve. A title/abstract inclusion that full-text
    screening has already voted on stays put — undoing it would orphan those
    votes."""
    config = _require_active(project_id, stage, db, round)
    conflict = db.get(Conflict, conflict_id)
    # triage audit rows share the table but are not conflicts: never reopened
    if (conflict is None or conflict.project_id != project_id
            or conflict.origin != "votes" or conflict.stage != config.stage
            or conflict.round != config.round):
        raise HTTPException(status_code=404, detail="Conflict not found")
    if conflict.status != "resolved":
        raise HTTPException(status_code=400, detail="This conflict is not resolved")
    _require_resolver(config, member)
    if conflict.stage == "ta" and conflict.resolution == "include":
        # the inclusion sent the record to full-text screening: take it back
        # out of the reviewers' queues — unless they already voted on it
        ft = _get_config(project_id, "ft", db, conflict.round)
        if ft is not None:
            if human_votes(db, ft, conflict.record_id):
                raise HTTPException(
                    status_code=400,
                    detail="This record already has full-text votes — its "
                           "title/abstract decision can no longer be undone")
            db.query(Assignment).filter_by(
                config_id=ft.id, record_id=conflict.record_id).delete()
    conflict.status = "open"
    conflict.resolution = ""
    conflict.resolution_note = ""
    conflict.reasons = []
    conflict.resolved_by = None
    conflict.resolved_at = None
    db.commit()
    return {"ok": True}


def _name_stats(data: dict, users: Namer) -> None:
    """Attach the reviewers' names to the stats payload — pseudonyms, and
    opaque ids everywhere a user id appears, while the round is anonymous
    (the front keys its cards on these ids; nothing may map them back on
    the project roster)."""
    for entry in data["per_reviewer"]:
        entry["display_name"] = users(entry["user_id"])
        entry["user_id"] = users.ident(entry["user_id"])
    matrix = (data.get("agreement") or {}).get("matrix")
    if matrix:
        matrix["rows_name"] = users.name(matrix.get("rows_user_id"))
        matrix["cols_name"] = users.name(matrix.get("cols_user_id"))
        matrix["rows_user_id"] = users.ident(matrix.get("rows_user_id"))
        matrix["cols_user_id"] = users.ident(matrix.get("cols_user_id"))
    for pair in (data.get("agreement") or {}).get("pairs") or []:
        pair["rows_name"] = users(pair["rows_user_id"])
        pair["cols_name"] = users(pair["cols_user_id"])
        pair["rows_user_id"] = users.ident(pair["rows_user_id"])
        pair["cols_user_id"] = users.ident(pair["cols_user_id"])
    if not users.hidden:
        return
    for share in data.get("shares") or []:
        share["user_id"] = users.ident(share["user_id"])
    for lot in data.get("lots") or []:
        lot["user_ids"] = [users.ident(u) for u in lot["user_ids"]]
        for d in lot["done"]:
            d["user_id"] = users.ident(d["user_id"])
    if data.get("lead_user_id") is not None:
        data["lead_user_id"] = users.ident(data["lead_user_id"])


@router.get("/stats")
def stats(project_id: int, member: ProjectMemberDep, db: DbDep, stage: str = "ta",
          round: int | None = None):
    config = _get_config(project_id, stage, db, round)
    if config is None:
        return {"status": "unconfigured"}
    sync_assignments(db, config)  # late-imported records join the round
    data = screening_stats(db, config)
    users = namer_for(db, config)
    _name_stats(data, users)
    data["names_hidden"] = users.hidden
    data["status"] = config.status
    data["conflict_resolution"] = config.conflict_resolution
    data["allocation"] = config.allocation
    if stage == "ft":
        from app.services.screening.core import screening_outcomes
        ft = ft_prisma_outcomes(db, config)
        labels = reason_labels(db, project_id, "ft")
        # group the excluded reports (with metadata) under their primary reason
        outcomes = screening_outcomes(db, config)
        excluded_ids = [rid for rid, d in outcomes.items() if d == "exclude"]
        included_ids = [rid for rid, d in outcomes.items() if d == "include"]
        recs = {r.id: r for r in db.query(Record).filter(
            Record.id.in_(excluded_ids + included_ids))} if outcomes else {}
        pdf_ids = {ft.record_id for ft in db.query(FullText).filter(
            FullText.record_id.in_(excluded_ids + included_ids))
            if ft.file_path} if outcomes else set()

        def meta(rid: int) -> dict | None:
            r = recs.get(rid)
            if r is None:
                return None
            return {"id": r.id, "title": r.title, "authors": r.authors,
                    "year": r.year, "journal": r.journal, "doi": r.doi,
                    "has_pdf": rid in pdf_ids}

        by_reason: dict[str, list] = {}
        for rid in excluded_ids:
            code = primary_reason(db, config, rid) or ""
            if code == NOTFOUND_CODE:
                continue  # counted under 'not retrievable', not a content reason
            m = meta(rid)
            if m is not None:
                by_reason.setdefault(code, []).append(m)
        data["ft"] = {
            "assessed": ft["assessed"], "not_retrieved": ft["not_retrieved"],
            "excluded_by_reason": [
                {"code": r["code"], "label": labels.get(r["code"], r["code"]),
                 "n": r["n"], "records": by_reason.get(r["code"], [])}
                for r in ft["by_reason"]],
            "included_records": [m for m in (meta(rid) for rid in
                                             sorted(included_ids)) if m],
        }
    return data


# ---- AI reveal gating ------------------------------------------------------------
#
# `ai_reveal == "after_vote"`: the suggestion is withheld from a reviewer until
# their own vote exists. Enforced here, not in the UI, for the same reason the
# blinding between reviewers is: a client must not be able to peek. The one
# sanctioned way round it is POST /reveal, which leaves an AiReveal row.

VOTE_FIRST = ("Vote first — in this round the AI suggestion is shown after your "
              "vote. A suggestion already computed in batch can be revealed "
              "before voting with the dedicated button; that choice is recorded.")


def _has_voted(db, project_id: int, record_id: int, stage: str, round_: int,
               user_id: int) -> bool:
    return (db.query(Vote.id)
            .filter_by(project_id=project_id, record_id=record_id, stage=stage,
                       round=round_, voter_user_id=user_id, is_ai=False)
            .first()) is not None


def _reveal_row(db, record_id: int, stage: str, round_: int,
                user_id: int) -> AiReveal | None:
    return (db.query(AiReveal)
            .filter_by(record_id=record_id, stage=stage, round=round_,
                       user_id=user_id).first())


def _withheld(db, config: ScreeningConfig, record_id: int, user_id: int) -> bool:
    """True when this requester may not see the suggestion yet."""
    if config.ai_reveal != "after_vote":
        return False
    if _has_voted(db, config.project_id, record_id, config.stage, config.round,
                  user_id):
        return False
    return _reveal_row(db, record_id, config.stage, config.round, user_id) is None


def _cached_ai_vote(db, config: ScreeningConfig, record_id: int) -> Vote | None:
    return (db.query(Vote)
            .filter_by(project_id=config.project_id, record_id=record_id,
                       stage=config.stage, round=config.round, is_ai=True)
            .first())


def _suggestion_payload(vote: Vote, cost=None, revealed_early: bool = False) -> dict:
    return {
        "decision": vote.decision,
        "confidence": vote.confidence,
        "criteria": (vote.criteria_eval or {}).get("criteria", []),
        "reasons": vote.reasons or [],
        "justification": vote.justification,
        "warning": (vote.criteria_eval or {}).get("warning", ""),
        "analysis": (vote.criteria_eval or {}).get("analysis", ""),
        # present only when a fresh LLM call was made (None on a cache hit)
        "cost": cost,
        # this reviewer chose to see it before voting (after_vote rounds)
        "revealed_early": revealed_early,
    }


@router.post("/records/{record_id}/suggest")
def suggest(project_id: int, record_id: int, member: ProjectMemberDep, db: DbDep,
            stage: str = "ta", force: bool = False, round: int | None = None):
    """On-click AI suggestion (cached; force=true regenerates — new LLM call).
    In an after_vote round, only once the requester has voted."""
    config = _require_active(project_id, stage, db, round)
    if not config.ai_enabled:
        raise HTTPException(status_code=400, detail="AI suggestions are disabled")
    record = db.get(Record, record_id)
    if record is None or record.project_id != project_id:
        raise HTTPException(status_code=404, detail="Record not found")
    if (config.ai_reveal == "after_vote"
            and not _has_voted(db, project_id, record_id, stage, config.round,
                               member.user_id)):
        raise HTTPException(status_code=409, detail=VOTE_FIRST)
    requester = db.get(User, member.user_id)
    generated_by = requester.email if requester else None
    try:
        if stage == "ft":
            suggestion = get_or_create_ft_suggestion(
                db, config, record, force=force, generated_by=generated_by,
                user_id=member.user_id)
        else:
            suggestion = get_or_create_suggestion(
                db, config, record, force=force, generated_by=generated_by,
                user_id=member.user_id)
    except LLMError as e:
        raise HTTPException(status_code=400, detail=str(e))
    revealed = _reveal_row(db, record_id, stage, config.round,
                           member.user_id) is not None
    return _suggestion_payload(suggestion, getattr(suggestion, "last_cost", None),
                               revealed_early=revealed)


@router.post("/records/{record_id}/reveal")
def reveal_suggestion(project_id: int, record_id: int, member: ProjectMemberDep,
                      db: DbDep, stage: str = "ta", round: int | None = None):
    """Show me the suggestion already computed for this record (by a batch run
    of mine or a co-reviewer's) although I have not voted yet. Never calls the
    model. In an after_vote round the choice is recorded — the AI disclosure
    and the paired human/AI corpus tell blind votes from informed ones."""
    config = _require_active(project_id, stage, db, round)
    if not config.ai_enabled:
        raise HTTPException(status_code=400, detail="AI suggestions are disabled")
    record = db.get(Record, record_id)
    if record is None or record.project_id != project_id:
        raise HTTPException(status_code=404, detail="Record not found")
    vote = _cached_ai_vote(db, config, record_id)
    if vote is None:
        raise HTTPException(status_code=409,
                            detail="No AI suggestion has been computed for this "
                                   "record yet — nothing to reveal")
    revealed = _reveal_row(db, record_id, stage, config.round, member.user_id)
    if (config.ai_reveal == "after_vote" and revealed is None
            and not _has_voted(db, project_id, record_id, stage, config.round,
                               member.user_id)):
        revealed = AiReveal(project_id=project_id, record_id=record_id,
                            stage=stage, round=config.round,
                            user_id=member.user_id)
        db.add(revealed)
        db.commit()
    return {"suggestion": _suggestion_payload(
        vote, revealed_early=revealed is not None)}


@router.get("/records/{record_id}/ai-estimate")
def record_ai_estimate(project_id: int, record_id: int, member: ProjectMemberDep,
                       db: DbDep, stage: str = "ta", round: int | None = None):
    """Up-front cost estimate for one record's AI suggestion (button hover)."""
    config = _get_config(project_id, stage, db, round)
    if config is None:
        return {"cost": None}
    record = db.get(Record, record_id)
    if record is None or record.project_id != project_id:
        raise HTTPException(status_code=404, detail="Record not found")
    # full text: a PDF over the page limit is refused before any call
    blocked = None
    if stage == "ft":
        ft = db.query(FullText).filter_by(record_id=record.id).first()
        if ft is not None and ft.file_path:
            blocked = pdf_ai_block_reason(ft.file_path)
    return {"cost": (None if blocked
                     else estimate_suggestion_cost(db, config, record)),
            "blocked": blocked}


@router.get("/records/{record_id}/suggestion")
def cached_suggestion(project_id: int, record_id: int, member: ProjectMemberDep,
                      db: DbDep, stage: str = "ta", round: int | None = None):
    """The AI suggestion already cached for this record, or null — never makes
    an LLM call. Lets the screen tab show a batch-generated (or previously
    requested) recommendation under the article without a click."""
    config = _get_config(project_id, stage, db, round)
    if config is None:
        return {"suggestion": None}
    vote = _cached_ai_vote(db, config, record_id)
    if _withheld(db, config, record_id, member.user_id):
        # after_vote round, not voted, not revealed: say whether there IS one
        # to reveal, never what it says
        return {"suggestion": None, "withheld": True,
                "available": vote is not None}
    if vote is None:
        return {"suggestion": None}
    revealed = _reveal_row(db, record_id, stage, config.round,
                           member.user_id) is not None
    return {"suggestion": _suggestion_payload(vote, revealed_early=revealed)}


def _ai_batch_config(project_id: int, db, round_: int | None) -> ScreeningConfig:
    config = _require_active(project_id, "ta", db, round_)
    if not config.ai_enabled:
        raise HTTPException(status_code=400,
                            detail="Enable AI suggestions for this round first")
    if not config.ai_batch:
        raise HTTPException(status_code=400,
                            detail="Batch AI suggestion is off — an admin enables "
                                   "it in the screening settings")
    return config


@router.get("/ai-batch/estimate")
def ai_batch_estimate(project_id: int, member: ProjectMemberDep, db: DbDep,
                      round: int | None = None):
    """How many of MY still-to-vote records lack a suggestion + rough cost."""
    from app.services.screening.ai_batch import estimate_batch
    config = _ai_batch_config(project_id, db, round)
    sync_assignments(db, config)
    return estimate_batch(db, config, member.user_id)


@router.post("/ai-batch")
def ai_batch_run(project_id: int, member: ProjectMemberDep, db: DbDep,
                 round: int | None = None):
    """Pre-compute the title/abstract AI suggestion for every record I still
    have to vote on that has none yet. Proposals only — cached as is_ai votes,
    shown under each article; nothing is voted automatically."""
    from app.services.screening.ai_batch import (
        batch_candidate_ids, needs_suggestion)
    from app.workers.runner import runner
    config = _ai_batch_config(project_id, db, round)
    sync_assignments(db, config)
    todo = needs_suggestion(
        db, config, batch_candidate_ids(db, config, member.user_id))
    if not todo:
        raise HTTPException(status_code=400,
                            detail="Nothing to AI-screen — every record you still "
                                   "have to vote on already has a suggestion")
    job = runner.submit("ta_ai_batch",
                        {"project_id": project_id, "round": config.round,
                         "user_id": member.user_id},
                        project_id=project_id, user_id=member.user_id)
    return {"job_id": job.id, "n": len(todo)}


@router.get("/reasons")
def list_reasons(project_id: int, member: ProjectMemberDep, db: DbDep,
                 stage: str = "ft"):
    """Exclusion reasons a reviewer may pick from: the protocol's E* criteria
    plus the built-in 'full text not retrievable'."""
    get_project(project_id, db)
    return {"reasons": exclusion_reasons(db, project_id, stage),
            "notfound_code": NOTFOUND_CODE}


@router.get("/ai-estimate")
def ai_estimate(project_id: int, member: ProjectMemberDep, db: DbDep,
                stage: str = "ft", round: int | None = None):
    """Rough token/char budget for AI-screening every eligible full-text record
    (shown before running any AI, per plan). One record per suggestion, but this
    gives the methodologist the batch order of magnitude."""
    config = _get_config(project_id, stage, db, round)
    if config is None:
        return {"records_with_pdf": 0, "records_without_pdf": 0,
                "approx_input_chars": 0, "approx_input_tokens": 0}
    ids = eligible_record_ids(db, project_id, stage, config.round)
    return estimate_ft_cost(db, config, ids)
