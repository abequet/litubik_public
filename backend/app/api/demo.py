# SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
# SPDX-License-Identifier: AGPL-3.0-or-later
"""M6 demo administration: the superadmin's email allowlist.

Emails on the list register as full accounts on a demo instance; adding an
email that already has an account promotes it immediately. Removing an entry
does NOT demote an existing account (documented choice — simple and safe).
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, EmailStr

from app.api.deps import CurrentUser, DbDep
from app.models import TrustedEmail, User

router = APIRouter(prefix="/api/admin/trusted-emails", tags=["demo-admin"])


class TrustedEmailIn(BaseModel):
    email: EmailStr


class TrustedEmailOut(BaseModel):
    id: int
    email: str
    registered: bool  # an account with this email already exists
    source: str = "manual"  # "invite" = auto-allowlisted by a project invite


def _require_app_admin(user: CurrentUser):
    if not user.is_admin:
        raise HTTPException(status_code=403,
                            detail="Only an application admin manages demo access")


@router.get("", response_model=list[TrustedEmailOut])
def list_trusted(user: CurrentUser, db: DbDep):
    _require_app_admin(user)
    registered = {email for (email,) in db.query(User.email).all()}
    return [TrustedEmailOut(id=t.id, email=t.email,
                            registered=t.email in registered, source=t.source)
            for t in db.query(TrustedEmail).order_by(TrustedEmail.email)]


@router.post("", response_model=TrustedEmailOut)
def add_trusted(payload: TrustedEmailIn, user: CurrentUser, db: DbDep):
    _require_app_admin(user)
    email = payload.email.lower()
    row = db.query(TrustedEmail).filter_by(email=email).first()
    if row is None:
        row = TrustedEmail(email=email, added_by=user.id)
        db.add(row)
    # promote an already-registered account on the spot
    existing = db.query(User).filter_by(email=email).first()
    if existing is not None:
        existing.is_trusted = True
    db.commit()
    db.refresh(row)
    return TrustedEmailOut(id=row.id, email=row.email,
                           registered=existing is not None, source=row.source)


@router.delete("/{entry_id}")
def remove_trusted(entry_id: int, user: CurrentUser, db: DbDep):
    _require_app_admin(user)
    row = db.get(TrustedEmail, entry_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Not in the allowlist")
    db.delete(row)
    db.commit()
    return {"ok": True}


reset_router = APIRouter(prefix="/api/admin/demo-reset", tags=["demo-admin"])


@reset_router.post("")
def reset_now(user: CurrentUser, db: DbDep):
    """Run the selective purge immediately (test/troubleshooting button)."""
    from app.core.config import get_settings
    from app.services.demo_reset import run_demo_reset
    _require_app_admin(user)
    if not get_settings().demo_mode:
        raise HTTPException(status_code=400,
                            detail="This instance is not in demo mode")
    return run_demo_reset(db, grace=False)


budget_router = APIRouter(tags=["demo"])


@budget_router.get("/api/demo/ai-budget")
def ai_budget(user: CurrentUser, db: DbDep):
    """What the demo AI budget has left — for a visitor, their own share and
    the month's; for the superadmin, the month's spending and the number of
    visitor accounts alive. `applies` is False for everyone the budget does not
    concern (normal instances, trusted accounts)."""
    from app.core.config import get_settings
    from app.core.demo import is_demo_user
    from app.services.llm.demo_budget import budget_status
    if not get_settings().demo_mode:
        return {"applies": False, "enabled": False}
    visitor = is_demo_user(user)
    status = budget_status(db, user.id if visitor else None)
    status["applies"] = visitor
    if user.is_admin:
        status["live_visitors"] = (db.query(User)
                                   .filter(User.is_trusted.is_(False),
                                           User.is_admin.is_(False)).count())
    return status


@budget_router.post("/api/admin/demo-ai-budget/reset")
def reset_ai_budget(user: CurrentUser, db: DbDep):
    """Start this month's visitor AI spending from zero again (per-account
    spending is not touched: it goes with the accounts at the nightly reset)."""
    from app.services.llm.demo_budget import reset_month
    _require_app_admin(user)
    reset_month(db)
    return {"ok": True}
