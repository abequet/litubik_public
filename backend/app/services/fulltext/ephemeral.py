# SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
# SPDX-License-Identifier: AGPL-3.0-or-later
"""In-memory handoff of ephemeral institutional credentials (M4b).

Job params are persisted in the `jobs` table, so browser-held credentials must
never travel through them. The API stashes the institutions here under a
random token, puts only the token in the job params, and the handler pops the
token once. Process-local by design: a restart just loses the credentials
(the job runs without institutions), it never leaks them.
"""
import secrets
import threading

_lock = threading.Lock()
_stash: dict[str, list[dict]] = {}


def stash_institutions(institutions: list[dict]) -> str:
    token = secrets.token_urlsafe(16)
    with _lock:
        _stash[token] = institutions
    return token


def pop_institutions(token: str | None) -> list[dict]:
    if not token:
        return []
    with _lock:
        return _stash.pop(token, [])
