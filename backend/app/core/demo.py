# SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Public demo instance helpers (M6).

`is_demo_user(user)` is THE gate for every demo restriction: it is False for
everyone on a normal instance, and on a demo instance for the superadmin and
allowlisted ("trusted") accounts.
"""
import ipaddress
import shutil
from datetime import timedelta
from fnmatch import fnmatch

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import TrustedEmail, User

# sandbox guard-rails (demo accounts only — the daily reset does the rest)
DEMO_MAX_PROJECTS = 3
DEMO_MAX_IMPORT_RECORDS = 2000      # per uploaded file, per search, per snowball
DEMO_MAX_LIVE_GUESTS = 300          # sandbox accounts alive at the same time
DEMO_MAX_RETRIEVE_RECORDS = 100     # full texts fetched per retrieval run
DEMO_MAX_PDF_BYTES = 20 * 1024 * 1024
DEMO_MAX_PROJECT_STORAGE_BYTES = 100 * 1024 * 1024
DEMO_MIN_FREE_DISK_BYTES = 1024 ** 3
DEMO_MAX_TICKETS_PER_DAY = 5
DEMO_MAX_PROJECT_RECORDS = 5000     # references per sandbox project, all imports
DEMO_MAX_REQUEST_BYTES = 25 * 1024 * 1024  # one request body of a visitor
# background jobs: one at a time per visitor, a few for all visitors together
# (each full-text run alone keeps several downloads going)
DEMO_MAX_SANDBOX_JOBS = 4
# follow-ups a visitor's own job schedules for them: never refused
DEMO_JOB_EXEMPT = frozenset({"abstract_backfill"})
# a sandbox account younger than this survives the nightly purge, so a guest
# who arrives a few minutes before the reset does not lose their work at once
DEMO_PURGE_GRACE = timedelta(hours=1)
# guest accounts get an address under a reserved TLD (RFC 2606): never
# deliverable, so nothing can ever be sent to — or claimed through — it
GUEST_EMAIL_DOMAIN = "guest.invalid"


def is_demo_user(user: User) -> bool:
    if not get_settings().demo_mode:
        return False
    return not (user.is_admin or user.is_trusted)


def sandbox_owner(db: Session, project_id: int | None) -> User | None:
    """The sandbox account that created this project, on a demo instance —
    None for every project of a normal instance and for the projects of the
    superadmin and trusted accounts."""
    if not get_settings().demo_mode or project_id is None:
        return None
    from app.models import Project
    project = db.get(Project, project_id)
    if project is None or project.created_by is None:
        return None  # legacy/ownerless projects: behave as before
    owner = db.get(User, project.created_by)
    if owner is None or owner.is_admin or owner.is_trusted:
        return None
    return owner


def project_allows_global_keys(db: Session, project_id: int | None) -> bool:
    """Demo instances: the app-wide (global) database keys are reserved for
    projects created by trusted accounts. Always True on a normal instance.
    (The app-wide AI key is the exception: a sandbox reaches it through the
    capped demo budget, services/llm/demo_budget.py.)"""
    return sandbox_owner(db, project_id) is None


def guest_entry_for_host(host: str | None) -> bool:
    """Does this host name open the one-click guest entry? Only on a demo
    instance, and only for the hosts of LITUBIK_DEMO_GUEST_HOSTS (`demo.*` by
    default) — the same deployment then serves its full accounts an ordinary
    sign-in on its other names."""
    settings = get_settings()
    if not settings.demo_mode or not host:
        return False
    name = host.strip().lower()
    if not name.startswith("["):  # drop the port (an IPv6 literal never matches)
        name = name.split(":")[0]
    return any(fnmatch(name, pattern.strip().lower())
               for pattern in settings.demo_guest_hosts.split(",")
               if pattern.strip())


def rate_key(ip: str) -> str:
    """The key a per-address limit counts on. An IPv6 address is reduced to
    its /64: one connection usually owns the whole block, so counting single
    addresses would let anyone rotate through billions of them."""
    try:
        address = ipaddress.ip_address(ip)
    except ValueError:
        return ip
    if address.version == 4:
        return str(address)
    if address.ipv4_mapped is not None:
        return str(address.ipv4_mapped)
    return str(ipaddress.ip_network(f"{address}/64", strict=False))


def sandbox_records_room(db: Session, project_id: int) -> int | None:
    """How many more references a sandbox project may receive (None for any
    project that is not a visitor's): imports, searches and snowballing all
    stop at DEMO_MAX_PROJECT_RECORDS."""
    if sandbox_owner(db, project_id) is None:
        return None
    from app.models import Record
    held = db.query(Record).filter(Record.project_id == project_id).count()
    return max(0, DEMO_MAX_PROJECT_RECORDS - held)


def check_sandbox_job_quota(db: Session, user_id: int | None,
                            job_type: str) -> None:
    """Refuse a visitor's background job beyond the demo quotas: one running
    job per visitor, DEMO_MAX_SANDBOX_JOBS for all visitors together. A
    trusted account (or a normal instance) is never counted nor refused."""
    if (not get_settings().demo_mode or user_id is None
            or job_type in DEMO_JOB_EXEMPT):
        return
    user = db.get(User, user_id)
    if user is None or not is_demo_user(user):
        return
    from app.models import Job
    active = (db.query(Job)
              .join(User, Job.created_by == User.id)
              .filter(Job.status.in_(("queued", "running")),
                      Job.type.notin_(DEMO_JOB_EXEMPT),
                      User.is_trusted.is_(False), User.is_admin.is_(False)))
    if active.filter(Job.created_by == user_id).count() >= 1:
        raise HTTPException(
            status_code=429,
            detail="On the demo, one task runs at a time — wait for the "
                   "current one to finish")
    if active.count() >= DEMO_MAX_SANDBOX_JOBS:
        raise HTTPException(
            status_code=503,
            detail="The demo is busy with other visitors' tasks — try again "
                   "in a few minutes")


def sandbox_storage_error(project_id: int, incoming: int) -> str | None:
    """Why writing `incoming` more bytes for a sandbox project is refused, or
    None. Bounds what visitors can put on the volume: per project, and a floor
    of free space for the whole instance."""
    root = get_settings().storage_dir
    path = root / str(project_id)
    used = (sum(f.stat().st_size for f in path.rglob("*") if f.is_file())
            if path.exists() else 0)
    if used + incoming > DEMO_MAX_PROJECT_STORAGE_BYTES:
        return (f"Demo projects hold at most "
                f"{DEMO_MAX_PROJECT_STORAGE_BYTES // (1024 * 1024)} MB of files")
    try:
        free = shutil.disk_usage(root).free
    except OSError:
        return None
    if free - incoming < DEMO_MIN_FREE_DISK_BYTES:
        return "The demo instance is short of disk space — try again after the daily reset"
    return None


def email_is_trusted(db: Session, email: str) -> bool:
    return (db.query(TrustedEmail)
            .filter(TrustedEmail.email == email.lower()).first() is not None)


def seed_trusted_emails(db: Session) -> int:
    """Import the LITUBIK_TRUSTED_EMAILS env list (idempotent). Called at
    startup on demo instances so Railway can be provisioned without UI.

    Robust to a repeated email in the env list and to rows already present
    from a previous boot: the wanted emails are de-duplicated and checked
    against the table in one query (the session is autoflush=False, so we must
    not rely on a mid-loop query to surface pending inserts)."""
    wanted: list[str] = []
    seen: set[str] = set()
    for raw in get_settings().trusted_emails.split(","):
        email = raw.strip().lower()
        if email and "@" in email and email not in seen:
            seen.add(email)
            wanted.append(email)
    if not wanted:
        return 0
    existing = {e for (e,) in db.query(TrustedEmail.email)
                .filter(TrustedEmail.email.in_(wanted)).all()}
    added = 0
    for email in wanted:
        if email not in existing:
            db.add(TrustedEmail(email=email))
            added += 1
        # an already-registered account with that email is promoted
        user = db.query(User).filter_by(email=email).first()
        if user is not None and not user.is_trusted:
            user.is_trusted = True
    db.commit()
    return added
