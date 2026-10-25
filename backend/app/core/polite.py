# SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Identity LitUbik presents to the open scholarly APIs.

Crossref and OpenAlex route requests that carry a reachable contact address
(`mailto`) to their "polite pool"; NCBI E-utilities asks for `tool` and
`email`. A placeholder address is worse than none: it breaks their terms and
gets a User-Agent blocklisted for every instance that sends it. So the address
is the operator's, and when there is none the requests go out without one, to
the public pool.

Where the address comes from, first match wins:
1. `LITUBIK_CONTACT_EMAIL` (instance setting, see docs/DEPLOYMENT.md);
2. the instance-wide Unpaywall e-mail an admin entered in the Full text
   settings — Unpaywall requires one, and it is the same kind of contact;
3. nothing.
"""
import logging
import time

from app.core.config import get_settings
from app.core.version import HOMEPAGE, __version__

log = logging.getLogger(__name__)

_CACHE_SECONDS = 300
_cache: tuple[float, str] | None = None


def _global_unpaywall_email() -> str:
    from app.core.db import SessionLocal
    from app.models import FulltextConfig
    with SessionLocal() as db:
        cfg = db.query(FulltextConfig).filter_by(project_id=None).first()
        return (cfg.unpaywall_email or "").strip() if cfg else ""


def contact_email() -> str:
    """The operator's contact address, or "" when none is configured."""
    global _cache
    configured = (get_settings().contact_email or "").strip()
    if configured:
        return configured
    now = time.monotonic()
    if _cache and now - _cache[0] < _CACHE_SECONDS:
        return _cache[1]
    try:
        email = _global_unpaywall_email()
    except Exception:  # no table yet, locked database: never fail a request
        log.debug("contact e-mail lookup failed", exc_info=True)
        email = ""
    _cache = (now, email)
    return email


def reset_cache() -> None:
    global _cache
    _cache = None


def user_agent() -> str:
    email = contact_email()
    return (f"LitUbik/{__version__} (+{HOMEPAGE}"
            + (f"; mailto:{email})" if email else ")"))


def headers() -> dict[str, str]:
    return {"User-Agent": user_agent()}


def mailto() -> dict[str, str]:
    """Query parameter for Crossref / OpenAlex, empty without an address."""
    email = contact_email()
    return {"mailto": email} if email else {}


def ncbi_params() -> dict[str, str]:
    """`tool` (always) and `email` (when known) for NCBI E-utilities."""
    email = contact_email()
    return {"tool": "litubik", **({"email": email} if email else {})}
