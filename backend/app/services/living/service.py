# SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Living review orchestration: the plan, round kinds, the update pass
bookkeeping shared by the scheduled job and "fetch now", notifications."""
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import (
    Equation, Import, Notification, Project, ProjectMember, Record,
    ScreeningConfig, SearchUpdatePlan, SearchUpdateRun, SnowballRun, Source,
)
from app.models.accounts import utcnow
from app.models.living import UPDATE_INTERVALS
from app.services.screening.core import generate_assignments

logger = logging.getLogger(__name__)


def _utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


# -- plan ---------------------------------------------------------------------------

def get_plan(db: Session, project_id: int) -> SearchUpdatePlan | None:
    return db.query(SearchUpdatePlan).filter_by(project_id=project_id).first()


def plan_out(plan: SearchUpdatePlan | None, project_id: int) -> dict:
    if plan is None:
        return {"project_id": project_id, "enabled": False, "interval_days": 30,
                "databases": [], "equation_id": None, "last_run_at": None,
                "next_run_at": None}
    return {"project_id": project_id, "enabled": plan.enabled,
            "interval_days": plan.interval_days,
            "databases": list(plan.databases or []),
            "equation_id": plan.equation_id,
            "last_run_at": _utc(plan.last_run_at).isoformat() if plan.last_run_at else None,
            "next_run_at": _utc(plan.next_run_at).isoformat() if plan.next_run_at else None}


def upsert_plan(db: Session, project_id: int, *, enabled: bool, interval_days: int,
                databases: list[str], equation_id: int | None,
                user_id: int | None) -> SearchUpdatePlan:
    if interval_days not in UPDATE_INTERVALS:
        raise ValueError(f"interval_days must be one of {UPDATE_INTERVALS}")
    plan = get_plan(db, project_id)
    if plan is None:
        plan = SearchUpdatePlan(project_id=project_id, created_by=user_id)
        db.add(plan)
    plan.enabled = enabled
    plan.interval_days = interval_days
    plan.databases = list(dict.fromkeys(databases))
    plan.equation_id = equation_id
    now = utcnow()
    if enabled:
        base = _utc(plan.last_run_at) or now
        plan.next_run_at = base + timedelta(days=interval_days)
        if plan.next_run_at < now:  # a plan re-enabled long after its last run
            plan.next_run_at = now
    else:
        plan.next_run_at = None
    db.flush()
    return plan


def default_equation_id(db: Session, project_id: int) -> int | None:
    """The latest frozen equation, else the latest equation."""
    frozen = (db.query(Equation).filter_by(project_id=project_id, status="frozen")
              .order_by(Equation.frozen_at.desc(), Equation.id.desc()).first())
    if frozen is not None:
        return frozen.id
    latest = (db.query(Equation).filter_by(project_id=project_id)
              .order_by(Equation.id.desc()).first())
    return latest.id if latest else None


def default_since(db: Session, project_id: int) -> datetime | None:
    """What "since the previous pass" means with no plan history: the last
    import of the project (None on an empty project = full run)."""
    plan = get_plan(db, project_id)
    if plan is not None and plan.last_run_at:
        return _utc(plan.last_run_at)
    last = (db.query(func.max(Import.imported_at))
            .filter(Import.project_id == project_id).scalar())
    return _utc(last)


# -- rounds -------------------------------------------------------------------------

def latest_round(db: Session, project_id: int) -> int:
    return (db.query(func.max(Source.round))
            .filter(Source.project_id == project_id).scalar()) or 1


def round_kinds(db: Session, project_id: int) -> dict[int, dict]:
    """round -> {"kind": initial|snowballing|update, "n": ordinal within its
    kind, "label": English label}. A round owned by no run row (legacy data)
    counts as a snowballing iteration, which is what it used to mean."""
    kinds: dict[int, dict] = {1: {"kind": "initial", "n": 1, "label": "Initial search"}}
    updates = [r for (r,) in db.query(SearchUpdateRun.round)
               .filter_by(project_id=project_id).order_by(SearchUpdateRun.round)]
    for n, r in enumerate(dict.fromkeys(updates), start=1):
        kinds[r] = {"kind": "update", "n": n, "label": f"Search update {n}"}
    snowballs = [r for (r,) in db.query(SnowballRun.round)
                 .filter_by(project_id=project_id).order_by(SnowballRun.round)]
    n = 0
    present = [r for (r,) in db.query(Source.round)
               .filter(Source.project_id == project_id).distinct()
               .order_by(Source.round)]
    for r in present:
        if r in kinds:
            continue
        if r in snowballs or r not in kinds:
            n += 1
            kinds[r] = {"kind": "snowballing", "n": n,
                        "label": f"Snowballing iteration {n}"}
    return kinds


def round_label(kinds: dict[int, dict], round_: int) -> str:
    info = kinds.get(round_)
    if info is None:
        return f"Round {round_}"
    return info["label"]


# -- the pass bookkeeping (shared with "fetch now") -----------------------------------

def ta_round_active(db: Session, project_id: int) -> bool:
    return (db.query(ScreeningConfig.id)
            .filter_by(project_id=project_id, stage="ta", status="active")
            .first()) is not None


def open_next_screening_round(db: Session, project_id: int, round_: int) -> bool:
    """Copy the previous round's T/A rules onto the new round and start it
    (FT config copied as a draft). Returns True when a T/A round started."""
    from app.services.snowballing.jobs import _copy_config
    ta = _copy_config(db, project_id, "ta", round_)
    started = False
    if ta is not None and ta.status != "active" and ta.reviewer_ids:
        generate_assignments(db, ta)
        ta.status = "active"
        ta.started_at = utcnow()
        started = True
    _copy_config(db, project_id, "ft", round_)
    return started


def count_new_unique(db: Session, import_ids: list[int]) -> int:
    if not import_ids:
        return 0
    return (db.query(func.count(Record.id))
            .filter(Record.import_id.in_(import_ids),
                    Record.dedup_status == "unique").scalar()) or 0


def record_update_run(db: Session, project_id: int, *, round_: int,
                      databases: list[str], since_at: datetime | None,
                      n_fetched: int, n_new_unique: int, triggered_by: str,
                      errors: dict | None, user_id: int | None,
                      started_at: datetime | None = None) -> SearchUpdateRun:
    run = SearchUpdateRun(project_id=project_id, round=round_, databases=databases,
                          since_at=since_at, n_fetched=n_fetched,
                          n_new_unique=n_new_unique, triggered_by=triggered_by,
                          errors=errors or {}, created_by=user_id,
                          started_at=started_at or utcnow(), finished_at=utcnow())
    db.add(run)
    plan = get_plan(db, project_id)
    if plan is not None:
        plan.last_run_at = run.finished_at
        if plan.enabled:
            plan.next_run_at = run.finished_at + timedelta(days=plan.interval_days)
    db.flush()
    return run


def runs_out(db: Session, project_id: int) -> list[dict]:
    kinds = round_kinds(db, project_id)
    latest = latest_round(db, project_id)
    out = []
    for r in (db.query(SearchUpdateRun).filter_by(project_id=project_id)
              .order_by(SearchUpdateRun.round)):
        out.append({
            "id": r.id, "round": r.round, "label": round_label(kinds, r.round),
            "n": kinds.get(r.round, {}).get("n"),
            "databases": list(r.databases or []),
            "since_at": _utc(r.since_at).isoformat() if r.since_at else None,
            "n_fetched": r.n_fetched, "n_new_unique": r.n_new_unique,
            "triggered_by": r.triggered_by, "errors": r.errors or {},
            "started_at": _utc(r.started_at).isoformat() if r.started_at else None,
            "finished_at": _utc(r.finished_at).isoformat() if r.finished_at else None,
            "deletable": r.round == latest and r.round > 1,
        })
    return out


def delete_update_round(db: Session, project_id: int, round_: int) -> None:
    """Undo the latest update pass completely (records, screening, run row)."""
    from app.services.snowballing.service import delete_iteration_round
    if round_ != latest_round(db, project_id) or round_ <= 1:
        raise ValueError("Only the latest round can be deleted")
    if (db.query(SearchUpdateRun.id)
            .filter_by(project_id=project_id, round=round_).first()) is None:
        raise ValueError("This round is not a search update")
    delete_iteration_round(db, project_id, round_)


# -- notifications ------------------------------------------------------------------

def notify_members(db: Session, project_id: int, kind: str, payload: dict,
                   exclude_user: int | None = None) -> int:
    n = 0
    for (uid,) in db.query(ProjectMember.user_id).filter_by(project_id=project_id):
        if uid == exclude_user:
            continue
        db.add(Notification(user_id=uid, project_id=project_id, kind=kind,
                            payload=payload))
        n += 1
    db.flush()
    return n


# -- scheduler ----------------------------------------------------------------------

def due_plans(db: Session, now: datetime | None = None) -> list[SearchUpdatePlan]:
    now = now or utcnow()
    return [p for p in db.query(SearchUpdatePlan).filter_by(enabled=True)
            if p.next_run_at is not None and _utc(p.next_run_at) <= now]


def run_due_plans(now: datetime | None = None) -> list[int]:
    """Submit one `search_update` job per due plan (called hourly from
    main.py). A project with a pass already running is skipped; the plan's
    next_run_at is pushed first so a crash does not resubmit every hour."""
    from app.core.db import SessionLocal
    from app.models import Job
    from app.workers.runner import runner
    submitted: list[int] = []
    with SessionLocal() as db:
        for plan in due_plans(db, now):
            project = db.get(Project, plan.project_id)
            if project is None or project.archived_at is not None:
                continue
            if project.sync_role == "satellite":
                continue  # structural step, coordinator only
            running = (db.query(Job.id)
                       .filter(Job.project_id == plan.project_id,
                               Job.type == "search_update",
                               Job.status.in_(["queued", "running"])).first())
            if running is not None:
                continue
            plan.next_run_at = (now or utcnow()) + timedelta(days=plan.interval_days)
            db.commit()
            try:
                job = runner.submit("search_update",
                                    {"project_id": plan.project_id,
                                     "triggered_by": "schedule"},
                                    project_id=plan.project_id, user_id=None)
                submitted.append(job.id)
            except Exception:  # the runner is not started (tests) — keep going
                logger.exception("search update submit failed")
    return submitted
