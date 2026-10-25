# SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Request body size limits, enforced before the body is read.

FastAPI reads a request's whole body (spooling uploads to disk) before any
dependency runs, so an authorization check cannot stop a gigabyte sent by an
anonymous client, and an endpoint's own size check only runs once the file is
already in memory. This ASGI middleware refuses an oversized body up front,
from its Content-Length, and cuts off a body sent without one as soon as it
crosses the limit:

- without a valid session: 64 KB — signing in, registering or opening a guest
  session needs a few hundred bytes. A signed token is not enough: it must
  still designate a live account (a deleted guest's cookie stays signed);
- a demo visitor (sandbox account): DEMO_MAX_REQUEST_BYTES (25 MB);
- everyone else: the largest upload the app accepts (a 1 GiB sync snapshot).
"""
import json

from starlette.concurrency import run_in_threadpool

from app.core.config import get_settings
from app.core.security import AUTH_COOKIE_NAME, decode_access_token, session_user

ANONYMOUS_MAX_BYTES = 64 * 1024
MAX_BYTES = 1024 ** 3 + 1024 ** 2  # snapshot cap + multipart overhead
_BODYLESS = {"GET", "HEAD", "OPTIONS"}


def _header(scope, name: bytes) -> str | None:
    for key, value in scope.get("headers", ()):
        if key == name:
            return value.decode("latin-1")
    return None


def _session_payload(scope) -> dict | None:
    cookies = _header(scope, b"cookie") or ""
    for part in cookies.split(";"):
        key, _, value = part.strip().partition("=")
        if key == AUTH_COOKIE_NAME and value:
            return decode_access_token(value)
    return None


def _account(payload: dict) -> tuple[bool, bool]:
    """(the token designates a live account, that account is a demo sandbox)"""
    from app.core.db import SessionLocal
    from app.core.demo import is_demo_user
    with SessionLocal() as db:
        user = session_user(db, payload)
        return user is not None, user is not None and is_demo_user(user)


def _human(limit: int) -> str:
    if limit >= 1024 ** 2:
        return f"{limit // 1024 ** 2} MB"
    return f"{limit // 1024} KB"


class BodySizeLimit:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] in _BODYLESS:
            return await self.app(scope, receive, send)
        raw_length = _header(scope, b"content-length")
        length = int(raw_length) if raw_length and raw_length.isdigit() else None
        limit = await self._limit(scope, length)
        if length is not None and length > limit:
            return await self._too_large(send, limit)
        if length is None:
            # streamed without a length: count, and stop reading past the limit
            received = 0

            async def limited_receive():
                nonlocal received
                message = await receive()
                if message["type"] == "http.request":
                    received += len(message.get("body", b""))
                    if received > limit:
                        return {"type": "http.disconnect"}
                return message

            return await self.app(scope, limited_receive, send)
        return await self.app(scope, receive, send)

    async def _limit(self, scope, length: int | None) -> int:
        payload = _session_payload(scope)
        if payload is None:
            return ANONYMOUS_MAX_BYTES
        from app.core import demo
        if (length is not None
                and length <= min(ANONYMOUS_MAX_BYTES,
                                  demo.DEMO_MAX_REQUEST_BYTES)):
            return MAX_BYTES  # within every limit: no need to look the account up
        live, sandbox = await run_in_threadpool(_account, payload)
        if not live:
            return ANONYMOUS_MAX_BYTES
        if sandbox:
            return demo.DEMO_MAX_REQUEST_BYTES
        return MAX_BYTES

    @staticmethod
    async def _too_large(send, limit: int) -> None:
        body = json.dumps(
            {"detail": f"Request too large (max {_human(limit)})"}).encode()
        await send({"type": "http.response.start", "status": 413,
                    "headers": [(b"content-type", b"application/json"),
                                (b"content-length", str(len(body)).encode())]})
        await send({"type": "http.response.body", "body": body})
