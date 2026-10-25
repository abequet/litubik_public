# SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Resolve stored bibliographic-database API keys (Scopus, IEEE, CORE, Lens,
Springer Nature, Web of Science Starter).

A project-scoped key overrides the global one. Keys are stored Fernet-encrypted;
decrypted only when a count/search actually runs."""
from sqlalchemy.orm import Session

from app.core.crypto import decrypt_secret
from app.models import DatabaseCredential

KEYED_PROVIDERS = ("scopus", "ieee", "core", "lens", "springer", "wos")
PROVIDER_PATTERN = "^(" + "|".join(KEYED_PROVIDERS) + ")$"


def resolve_db_key(db: Session, project_id: int | None, provider: str) -> str | None:
    row = None
    if project_id is not None:
        row = (db.query(DatabaseCredential)
               .filter_by(project_id=project_id, provider=provider).first())
    if row is None:
        # M6 demo: visitor sandboxes never fall back on the app-wide keys
        from app.core.demo import project_allows_global_keys
        if not project_allows_global_keys(db, project_id):
            return None
        row = (db.query(DatabaseCredential)
               .filter_by(project_id=None, provider=provider).first())
    if row is None:
        return None
    return decrypt_secret(row.api_key_encrypted) or None


def available_db_keys(db: Session, project_id: int | None) -> set[str]:
    """Which keyed providers have a usable key for this project (or globally)."""
    return {p for p in KEYED_PROVIDERS if resolve_db_key(db, project_id, p)}
