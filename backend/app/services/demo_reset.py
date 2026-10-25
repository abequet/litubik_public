# SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Demo instance — the daily selective purge.

NOT a database wipe: only sandbox accounts (is_trusted=False, never admins)
and the projects they created are removed — superadmin, allowlisted accounts,
the shared demo co-reviewer and their data all survive. Project rows cascade
at the DB level; per-project storage (PDFs, archived imports) is removed from
disk like the regular project delete does.

Scheduling: an in-process ticker (started from the FastAPI lifespan when
LITUBIK_DEMO is on) fires once per day after LITUBIK_DEMO_RESET_HOUR UTC.
The last run date is kept in a marker file under data_dir, so restarts never
double-run nor skip a due purge.
"""
import logging
import shutil
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.demo import DEMO_PURGE_GRACE
from app.models import Project, User

logger = logging.getLogger(__name__)

CHECK_INTERVAL_S = 15 * 60


def _marker_path():
    return get_settings().data_dir / "demo_last_reset"


def _last_reset_date() -> str:
    try:
        return _marker_path().read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return ""


def reset_due(now: datetime | None = None) -> bool:
    """True when today's purge has not run yet and the reset hour has passed."""
    settings = get_settings()
    if not settings.demo_mode or settings.demo_reset_hour < 0:
        return False
    now = now or datetime.now(timezone.utc)
    return (now.hour >= settings.demo_reset_hour
            and _last_reset_date() != now.date().isoformat())


def purge_sandbox_users(db: Session, users: list[User]) -> dict:
    """Delete these sandbox accounts and every project they created, files
    included. Shared by the nightly purge and a guest ending their session."""
    user_ids = [u.id for u in users]
    projects = (db.query(Project)
                .filter(Project.created_by.in_(user_ids)).all()
                if user_ids else [])
    storage_root = get_settings().storage_dir
    project_ids = [p.id for p in projects]
    for project in projects:
        db.delete(project)  # project-scoped tables cascade at the DB level
    db.flush()
    for user in users:
        db.delete(user)  # votes/memberships cascade
    db.commit()
    for project_id in project_ids:
        path = storage_root / str(project_id)
        if path.exists():
            shutil.rmtree(path, ignore_errors=True)
    return {"users": len(users), "projects": len(projects)}


def run_demo_reset(db: Session, grace: bool = True) -> dict:
    """Purge sandbox accounts and their projects. Returns the counts.

    `grace` spares the accounts opened during the last hour (nightly run): a
    guest who started five minutes before the reset keeps their session until
    the next one. The superadmin's "reset now" button purges everything."""
    query = db.query(User).filter(User.is_trusted.is_(False),
                                  User.is_admin.is_(False))
    if grace:
        cutoff = datetime.now(timezone.utc) - DEMO_PURGE_GRACE
        query = query.filter(User.created_at < cutoff)
    result = purge_sandbox_users(db, query.all())
    from app.services.llm.demo_budget import prune_days
    prune_days(db)
    _marker_path().write_text(datetime.now(timezone.utc).date().isoformat(),
                              encoding="utf-8")
    logger.info("Demo reset: removed %(users)s sandbox accounts and "
                "%(projects)s projects", result)
    return result


def tick() -> dict | None:
    """One scheduler beat: purge if due. Runs in a worker thread."""
    if not reset_due():
        return None
    from app.core.db import SessionLocal
    with SessionLocal() as db:
        return run_demo_reset(db)
