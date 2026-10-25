# SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Admin report of reviewer work time: sessions (measured or estimated)
aggregated by reviewer × stage, by ISO week, and a median time per screened
record — the figure comparable to the screening-tool literature.

Aggregates only: nothing here names a record."""
import csv
import io
from collections import defaultdict
from statistics import median

from sqlalchemy.orm import Session

from app.core.csvsafe import safe_row
from app.models import ProjectMember, User
from app.models.worktime import WORK_STAGES
from app.services.worktime.estimate import (
    DEFAULT_CAP_S, DEFAULT_GAP_S, activity_acts, estimate_sessions,
)
from app.services.worktime.sessions import measured_sessions

SOURCES = ("measured", "estimated")


def _members_first(db: Session, project_id: int, seen: set[int]) -> tuple[list[int], dict, dict]:
    members = (db.query(ProjectMember).filter_by(project_id=project_id)
               .order_by(ProjectMember.id).all())
    roles = {m.user_id: m.role for m in members}
    ordered = [m.user_id for m in members] + sorted(seen - set(roles))
    names = {u.id: u.display_name for u in db.query(User)
             .filter(User.id.in_(ordered))} if ordered else {}
    return ordered, roles, names


def build_report(db: Session, project_id: int, source: str = "measured",
                 gap_s: int = DEFAULT_GAP_S, cap_s: int = DEFAULT_CAP_S) -> dict:
    if source not in SOURCES:
        raise ValueError(f"unknown source {source!r}")
    acts = activity_acts(db, project_id)
    estimated = estimate_sessions(acts, gap_s, cap_s)
    sessions = measured_sessions(db, project_id) if source == "measured" else estimated

    # acts per (user, stage) give the denominator of "seconds per act" for
    # both sources; the time-per-record median always comes from the act
    # timestamps (a heartbeat does not know which record was on screen)
    n_acts: dict[tuple[int, str], int] = defaultdict(int)
    n_records: dict[tuple[int, str], int] = defaultdict(int)
    for a in acts:
        n_acts[(a.user_id, a.stage)] += 1
        if a.on_record:
            n_records[(a.user_id, a.stage)] += 1
    record_times: dict[tuple[int, str], list[float]] = defaultdict(list)
    for s in estimated:
        record_times[(s["user_id"], s["stage"])].extend(s.get("record_times", []))

    by_stage: dict[int, dict[str, dict]] = defaultdict(
        lambda: {st: {"seconds": 0, "n_sessions": 0} for st in WORK_STAGES})
    weeks: dict[str, dict[int, int]] = defaultdict(lambda: defaultdict(int))
    for s in sessions:
        cell = by_stage[s["user_id"]][s["stage"]]
        cell["seconds"] += s["seconds"]
        cell["n_sessions"] += 1
        iso = s["started_at"].isocalendar()
        weeks[f"{iso[0]}-W{iso[1]:02d}"][s["user_id"]] += s["seconds"]

    seen = set(by_stage) | {a.user_id for a in acts}
    ordered, roles, names = _members_first(db, project_id, seen)
    reviewers = []
    for uid in ordered:
        stages = {}
        for st in WORK_STAGES:
            cell = dict(by_stage[uid][st]) if uid in by_stage else {"seconds": 0, "n_sessions": 0}
            cell["n_acts"] = n_acts.get((uid, st), 0)
            cell["n_records"] = n_records.get((uid, st), 0)
            stages[st] = cell
        reviewers.append({
            "user_id": uid,
            "display_name": names.get(uid, "?"),
            "role": roles.get(uid),  # None = former member
            "total_seconds": sum(c["seconds"] for c in stages.values()),
            "by_stage": stages,
            "per_record": {
                st: (int(median(record_times[(uid, st)]))
                     if record_times.get((uid, st)) else None)
                for st in ("ta", "ft")},
        })
    return {
        "source": source,
        "gap_s": gap_s,
        "cap_s": cap_s,
        "stages": list(WORK_STAGES),
        "reviewers": reviewers,
        "weeks": [{"week": w, "by_user": {str(u): s for u, s in sorted(per.items())}}
                  for w, per in sorted(weeks.items())],
        "n_sessions": len(sessions),
        "total_seconds": sum(s["seconds"] for s in sessions),
    }


def my_total(db: Session, project_id: int, user_id: int) -> dict:
    """What a reviewer sees of their own measured time."""
    by_stage = {st: 0 for st in WORK_STAGES}
    for s in measured_sessions(db, project_id):
        if s["user_id"] == user_id:
            by_stage[s["stage"]] += s["seconds"]
    return {"total_seconds": sum(by_stage.values()), "by_stage": by_stage}


def export_csv(db: Session, project_id: int, source: str = "measured",
               gap_s: int = DEFAULT_GAP_S, cap_s: int = DEFAULT_CAP_S) -> str:
    """One row per reviewer × stage × day (seconds, sessions)."""
    if source not in SOURCES:
        raise ValueError(f"unknown source {source!r}")
    sessions = (measured_sessions(db, project_id) if source == "measured"
                else estimate_sessions(activity_acts(db, project_id), gap_s, cap_s))
    days: dict[tuple[int, str, str], list[int]] = defaultdict(lambda: [0, 0])
    for s in sessions:
        cell = days[(s["user_id"], s["stage"], s["started_at"].date().isoformat())]
        cell[0] += s["seconds"]
        cell[1] += 1
    ordered, _roles, names = _members_first(db, project_id, {k[0] for k in days})
    rank = {uid: i for i, uid in enumerate(ordered)}
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(["reviewer", "stage", "day", "seconds", "minutes", "sessions", "source"])
    for (uid, stage, day), (seconds, n) in sorted(
            days.items(), key=lambda kv: (rank.get(kv[0][0], 999), kv[0][2], kv[0][1])):
        # a display name is typed by its owner: neutralised like any cell
        writer.writerow(safe_row([names.get(uid, "?"), stage, day, seconds,
                                  round(seconds / 60, 1), n, source]))
    return buffer.getvalue()
