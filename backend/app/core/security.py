# SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
# SPDX-License-Identifier: AGPL-3.0-or-later
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from app.core.config import get_settings

JWT_ALGORITHM = "HS256"
AUTH_COOKIE_NAME = "litubik_token"


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode(), hashed.encode())
    except ValueError:
        return False


def create_access_token(user_id: int, token_version: int = 0,
                        session_salt: str | None = None) -> str:
    settings = get_settings()
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.access_token_expire_minutes)
    # M9: `tv` binds the token to the user's current token version; changing the
    # password bumps that version and all previously issued tokens stop
    # decoding (see api/deps.get_current_user).
    payload = {"sub": str(user_id), "tv": token_version, "exp": expire}
    # `sid` binds it to this account rather than to its id, which SQLite reuses
    # once the account is deleted (User.session_salt)
    if session_salt:
        payload["sid"] = session_salt
    return jwt.encode(payload, settings.secret_key, algorithm=JWT_ALGORITHM)


def session_user(db, payload: dict | None):
    """The account a decoded session token designates, or None when the token
    no longer matches it: password changed since (M9, `tv`), or the id now
    belongs to another account (`sid`). The one check behind every use of the
    session cookie."""
    from app.models import User
    if not payload:
        return None
    try:
        user = db.get(User, int(payload["sub"]))
    except (KeyError, ValueError, TypeError):
        return None
    if user is None or payload.get("tv", 0) != user.token_version:
        return None
    if (user.session_salt is not None
            and payload.get("sid") != user.session_salt):
        return None
    return user


def decode_access_token(token: str) -> dict | None:
    """Return the token payload ({"sub", "tv", "exp"}, plus "sid"), or None if
    invalid/expired."""
    try:
        return jwt.decode(token, get_settings().secret_key,
                          algorithms=[JWT_ALGORITHM])
    except jwt.InvalidTokenError:
        return None
