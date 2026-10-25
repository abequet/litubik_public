# SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
# SPDX-License-Identifier: AGPL-3.0-or-later
import secrets

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, EmailStr, Field

from app.api.deps import CurrentUser, DbDep
from app.core.config import get_settings
from app.core.ratelimit import (guest_daily, guest_global, guest_hourly,
                                login_throttle)
from app.core.security import AUTH_COOKIE_NAME, create_access_token, hash_password, verify_password
from app.models import ProjectInvitation, ProjectMember, User

router = APIRouter(prefix="/api/auth", tags=["auth"])


class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)
    display_name: str = Field(min_length=1, max_length=120)


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class UserOut(BaseModel):
    id: int
    email: str
    display_name: str
    is_admin: bool
    # M6: False only for sandbox accounts of a demo instance — the front uses
    # it to hide what a demo account cannot do (institutional access…)
    is_trusted: bool = True
    # standalone "Download papers" module, granted per user by the superadmin
    # (who has it regardless of this flag)
    can_download_papers: bool = False
    # demo instances: a one-click guest session (no e-mail, no password)
    is_guest: bool = False

    model_config = {"from_attributes": True}


def _set_auth_cookie(response: Response, request: Request, user: User):
    settings = get_settings()
    # H2: the JWT is a 12h bearer credential — it must never travel in clear.
    # `secure` is forced on as soon as the request itself arrived over HTTPS
    # (directly or through a reverse proxy that sets X-Forwarded-Proto), so a
    # deployment behind TLS is protected even if the operator forgot the
    # setting. Plain-HTTP LAN/desktop use keeps working.
    https = (request.url.scheme == "https"
             or request.headers.get("x-forwarded-proto", "").split(",")[0].strip()
             == "https")
    response.set_cookie(
        AUTH_COOKIE_NAME,
        create_access_token(user.id, user.token_version, user.session_salt),
        httponly=True,
        samesite="lax",
        secure=settings.session_cookie_secure or https,
        max_age=settings.access_token_expire_minutes * 60,
    )


def _registration_allowed(db: DbDep, email: str, existing: User | None,
                          is_first: bool) -> bool:
    """H1: who may create an account when signup is restricted.

    `allow_registration=True` is free signup (the old behaviour). Restricted
    mode — the default — is NOT a blanket 403: it still lets in the people a
    review team actually needs, so an admin never has to reopen the instance to
    onboard a reviewer.

    A demo instance is open to the public through its one-click guest session,
    so an e-mail account there is only for the allowlist (the superadmin's
    list, plus the members trusted accounts added to their projects) — and
    `allow_registration` does not reopen it. The first account must be on the
    list too when the operator provisioned one (LITUBIK_TRUSTED_EMAILS): a
    public instance must not hand its superadmin role to whoever registers
    first.
    """
    from app.core.demo import email_is_trusted
    settings = get_settings()
    if settings.demo_mode:
        if is_first and not settings.trusted_emails.strip():
            return True
        return email_is_trusted(db, email)
    if settings.allow_registration:
        return True
    if is_first:
        return True  # bootstrap: a fresh instance needs its first admin
    if existing is not None:
        # account already created for that email and awaiting its password: a
        # project admin added them to a team (api/projects.add_member), or a
        # snapshot import created their shadow account. Registering claims it.
        return True
    if email_is_trusted(db, email):
        return True
    return db.query(ProjectInvitation).filter_by(email=email).first() is not None


@router.post("/register", response_model=UserOut)
def register(payload: RegisterIn, request: Request, response: Response, db: DbDep):
    email = payload.email.lower()
    existing = db.query(User).filter_by(email=email).first()
    if existing is not None and existing.password_hash:
        raise HTTPException(status_code=409, detail="Email already registered")
    is_first = db.query(User).count() == 0
    if not _registration_allowed(db, email, existing, is_first):
        if get_settings().demo_mode:
            raise HTTPException(
                status_code=403,
                detail="On this demo, accounts are reserved for invited "
                       "collaborators — start a guest session instead.")
        raise HTTPException(
            status_code=403,
            detail="Registration is restricted on this instance — ask a project "
                   "admin to add you to the review team first.")
    # M6 demo instances: only allowlisted emails (and the first account, the
    # superadmin) register as full accounts — everyone else gets a sandbox
    # account, purged by the daily reset. Normal instances: always trusted.
    def _trusted(addr: str, first: bool) -> bool:
        from app.core.demo import email_is_trusted
        if not get_settings().demo_mode or first:
            return True
        return email_is_trusted(db, addr)

    if existing is not None:
        # account awaiting its password — created by a project admin
        # (projects.add_member) or by a snapshot import (sync). Registering with
        # that email claims it: memberships and contributions stay attached.
        existing.password_hash = hash_password(payload.password)
        existing.display_name = payload.display_name
        existing.is_trusted = _trusted(existing.email, first=False)
        user = existing
        db.flush()
    else:
        # First account becomes the app admin
        user = User(
            email=email,
            password_hash=hash_password(payload.password),
            display_name=payload.display_name,
            is_admin=is_first,
            is_trusted=_trusted(email, is_first),
        )
        db.add(user)
        db.flush()
    # pending project invitations for this email become real memberships
    invitations = db.query(ProjectInvitation).filter_by(email=user.email).all()
    for invitation in invitations:
        db.add(ProjectMember(project_id=invitation.project_id, user_id=user.id,
                             role=invitation.role))
        db.delete(invitation)
    db.commit()
    db.refresh(user)
    # M6 demo: a fresh sandbox account starts with its own copy of the
    # example review (never blocks registration on failure)
    if get_settings().demo_mode and not user.is_trusted:
        from app.services.demo_seed import seed_for_new_demo_account
        seed_for_new_demo_account(db, user.id)
    _set_auth_cookie(response, request, user)
    return user


class GuestIn(BaseModel):
    accept_terms: bool = False


@router.post("/guest", response_model=UserOut)
def start_guest(payload: GuestIn, request: Request, response: Response,
                db: DbDep):
    """Demo instances: open a guest session in one click. The account has a
    random identifier under a reserved domain and a password nobody knows, so
    a visitor — a journal reviewer, say — tries LitUbik without giving any
    personal data. It is a sandbox account like the others: its own copy of
    the example review, the demo caps, and the nightly purge.

    Only served on the guest host names (LITUBIK_DEMO_GUEST_HOSTS), so the
    same deployment keeps an ordinary sign-in for its full accounts."""
    from app.core.demo import (DEMO_MAX_LIVE_GUESTS, GUEST_EMAIL_DOMAIN,
                               guest_entry_for_host, rate_key)
    if not guest_entry_for_host(request.headers.get("host")):
        raise HTTPException(status_code=404, detail="Not Found")
    if not payload.accept_terms:
        raise HTTPException(
            status_code=422,
            detail="Accept the terms of use to start a guest session")
    if db.query(User).count() == 0:
        # the first account becomes the superadmin: never a guest
        raise HTTPException(status_code=503,
                            detail="This instance is not set up yet")
    live = db.query(User).filter(User.is_trusted.is_(False),
                                 User.is_admin.is_(False)).count()
    if live >= DEMO_MAX_LIVE_GUESTS:
        raise HTTPException(
            status_code=503,
            detail="The demo is full right now — please come back after the "
                   "daily reset")
    key = rate_key(request.client.host if request.client else "unknown")
    if not (guest_daily.hit(key) and guest_hourly.hit(key)):
        raise HTTPException(
            status_code=429,
            detail="Too many guest sessions from this address — try again later")
    if not guest_global.hit("instance"):
        raise HTTPException(
            status_code=503,
            detail="Many visitors are opening sessions right now — please try "
                   "again in a few minutes")
    tag = secrets.token_hex(6)
    user = User(email=f"guest-{tag}@{GUEST_EMAIL_DOMAIN}",
                password_hash=hash_password(secrets.token_urlsafe(32)),
                display_name=f"Guest {tag[:4].upper()}",
                is_admin=False, is_trusted=False, is_guest=True)
    db.add(user)
    db.commit()
    db.refresh(user)
    from app.services.demo_seed import seed_for_new_demo_account
    seed_for_new_demo_account(db, user.id)
    _set_auth_cookie(response, request, user)
    return user


@router.delete("/guest")
def end_guest(response: Response, user: CurrentUser, db: DbDep):
    """A demo visitor ends their session: the account and every project it
    created are deleted now rather than at the nightly reset."""
    from app.core.demo import is_demo_user
    if not is_demo_user(user):
        raise HTTPException(
            status_code=403,
            detail="Only a demo visitor's account can be deleted this way")
    from app.services.demo_reset import purge_sandbox_users
    purge_sandbox_users(db, [user])
    response.delete_cookie(AUTH_COOKIE_NAME)
    return {"ok": True}


@router.post("/login", response_model=UserOut)
def login(payload: LoginIn, request: Request, response: Response, db: DbDep):
    # L2: throttle online brute-force — 3 failed attempts per (IP, account)
    # then a 10-minute cooldown.
    ip = request.client.host if request.client else "unknown"
    throttle_key = f"{ip}:{payload.email.lower()}"
    wait = login_throttle.retry_after(throttle_key)
    if wait:
        raise HTTPException(
            status_code=429,
            detail=f"Trop de tentatives de connexion — réessayez dans "
                   f"{wait // 60 + 1} min",
            headers={"Retry-After": str(wait)})
    user = db.query(User).filter_by(email=payload.email.lower()).first()
    if user is None or not verify_password(payload.password, user.password_hash):
        login_throttle.record_failure(throttle_key)
        raise HTTPException(status_code=401, detail="Invalid email or password")
    login_throttle.reset(throttle_key)
    _set_auth_cookie(response, request, user)
    return user


@router.post("/logout")
def logout(response: Response):
    response.delete_cookie(AUTH_COOKIE_NAME)
    return {"ok": True}


@router.get("/me", response_model=UserOut)
def me(user: CurrentUser):
    return user


class ChangePasswordIn(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8)


@router.post("/change-password")
def change_password(payload: ChangePasswordIn, request: Request,
                    response: Response, user: CurrentUser, db: DbDep):
    if not verify_password(payload.current_password, user.password_hash):
        raise HTTPException(status_code=401, detail="Current password is incorrect")
    user.password_hash = hash_password(payload.new_password)
    # M9: invalidate every token issued before this change (a stolen 12h JWT
    # must not survive a password reset), then re-issue one for this session.
    user.token_version = (user.token_version or 0) + 1
    db.commit()
    _set_auth_cookie(response, request, user)
    return {"ok": True}
