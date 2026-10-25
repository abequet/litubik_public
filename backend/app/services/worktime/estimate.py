# SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Estimated work time, reconstructed from the timestamps reviewers already
leave behind (votes, skips, reveals, conflict and duplicate rulings,
extracted cells, appraisals, annotations).

The method is the one the screening-tool literature uses for retrospective
telemetry: acts of one person on one stage are sorted in time; a gap longer
than `gap_s` closes a session; inside a session each act is credited the
time until the next act, capped at `cap_s` (reading a long paper is still
work, a lunch break is not); the last act of a session gets the session's
median act time. Zero infrastructure, available for projects older than
the heartbeat measure, and a sanity check on it.
"""
from collections import defaultdict
from datetime import datetime, timezone
from statistics import median

from sqlalchemy.orm import Session

from app.models import (
    AiReveal, AppraisalConsensus, Assignment, Conflict, DedupPair,
    ExtractionColumn, ExtractionValue, JbiAppraisal, PdfAnnotation, Record,
    ScreeningConfig, Vote,
)

DEFAULT_GAP_S = 600
DEFAULT_CAP_S = 300
# credit for an act with no neighbour to measure against (single-act session)
LONE_ACT_S = 60


def _utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


class Act:
    """One timestamped act of one person on one stage. `on_record` marks the
    acts that process one reference (a vote, a full-text decision), the
    denominator of the time-per-record figure."""
    __slots__ = ("user_id", "stage", "at", "on_record")

    def __init__(self, user_id: int, stage: str, at: datetime, on_record: bool = False):
        self.user_id, self.stage, self.at, self.on_record = user_id, stage, at, on_record


def activity_acts(db: Session, project_id: int) -> list[Act]:
    acts: list[Act] = []

    def add(user_id, stage, at, on_record=False):
        at = _utc(at)
        if user_id is not None and at is not None:
            acts.append(Act(user_id, stage, at, on_record))

    for v in (db.query(Vote).filter(Vote.project_id == project_id,
                                    Vote.is_ai.is_(False),
                                    Vote.voter_user_id.isnot(None))):
        add(v.voter_user_id, v.stage, v.created_at, on_record=True)
        if (v.updated_at and v.created_at
                and (_utc(v.updated_at) - _utc(v.created_at)).total_seconds() > 1):
            add(v.voter_user_id, v.stage, v.updated_at)
    for a, stage in (db.query(Assignment, ScreeningConfig.stage)
                     .join(ScreeningConfig, ScreeningConfig.id == Assignment.config_id)
                     .filter(ScreeningConfig.project_id == project_id,
                             Assignment.skipped_at.isnot(None))):
        add(a.user_id, stage, a.skipped_at)
    for r in db.query(AiReveal).filter_by(project_id=project_id):
        add(r.user_id, r.stage, r.revealed_at)
    for c in (db.query(Conflict)
              .filter(Conflict.project_id == project_id,
                      Conflict.resolved_by.isnot(None),
                      Conflict.resolved_at.isnot(None))):
        add(c.resolved_by, "conflicts", c.resolved_at)
    for d in (db.query(DedupPair)
              .filter(DedupPair.project_id == project_id,
                      DedupPair.resolved_by.isnot(None),
                      DedupPair.resolved_at.isnot(None))):
        add(d.resolved_by, "dedup", d.resolved_at)
    for v in (db.query(ExtractionValue)
              .join(ExtractionColumn, ExtractionColumn.id == ExtractionValue.column_id)
              .filter(ExtractionColumn.project_id == project_id,
                      ExtractionValue.user_id.isnot(None),
                      (ExtractionValue.origin == "human")
                      | ExtractionValue.validated.is_(True))):
        add(v.user_id, "extraction", v.updated_at)
    for j in (db.query(JbiAppraisal)
              .join(Record, Record.id == JbiAppraisal.record_id)
              .filter(Record.project_id == project_id)):
        add(j.user_id, "appraisal", j.updated_at)
    for c in (db.query(AppraisalConsensus)
              .filter(AppraisalConsensus.project_id == project_id,
                      AppraisalConsensus.resolved_by.isnot(None),
                      AppraisalConsensus.resolved_at.isnot(None))):
        add(c.resolved_by, "appraisal", c.resolved_at)
    for a in (db.query(PdfAnnotation)
              .filter(PdfAnnotation.project_id == project_id,
                      PdfAnnotation.user_id.isnot(None))):
        add(a.user_id, "ft", a.created_at)
    return acts


def estimate_sessions(acts: list[Act], gap_s: int = DEFAULT_GAP_S,
                      cap_s: int = DEFAULT_CAP_S) -> list[dict]:
    """Fold acts into sessions per (user, stage); see the module docstring.
    Each session dict also carries the capped time of its record acts, so the
    report can give a median time per screened record."""
    cap_s = max(1, min(cap_s, gap_s))
    by_key: dict[tuple[int, str], list[Act]] = defaultdict(list)
    for a in acts:
        by_key[(a.user_id, a.stage)].append(a)

    sessions: list[dict] = []
    for (user_id, stage), group in by_key.items():
        group.sort(key=lambda a: a.at)
        i = 0
        while i < len(group):
            j = i
            credits: list[float] = []
            record_times: list[float] = []
            while j + 1 < len(group):
                delta = (group[j + 1].at - group[j].at).total_seconds()
                if delta > gap_s:
                    break
                credited = min(delta, cap_s)
                credits.append(credited)
                if group[j].on_record:
                    record_times.append(credited)
                j += 1
            last_credit = min(cap_s, median(credits)) if credits else LONE_ACT_S
            if group[j].on_record:
                record_times.append(last_credit)
            sessions.append({
                "user_id": user_id, "stage": stage,
                "started_at": group[i].at, "ended_at": group[j].at,
                "seconds": int(sum(credits) + last_credit),
                "n_acts": j - i + 1,
                "record_times": record_times,
            })
            i = j + 1
    sessions.sort(key=lambda s: s["started_at"])
    return sessions
