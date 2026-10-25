# SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Personal third-party integrations (roadmap chantier 4): a per-user API key
for a reference manager, and the link between a LitUbik record and the item
it corresponds to in that manager's library, so a second export updates the
item instead of duplicating it.

Neither table travels in sync packages: the key is personal to one account on
one instance, and the links describe one person's library."""
from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.accounts import utcnow


class UserIntegration(Base):
    """One stored API key per (user, provider). `config` carries the
    provider-specific choices — for Zotero: library_type (user | group),
    library_id, library_name, username."""

    __tablename__ = "user_integrations"
    __table_args__ = (UniqueConstraint("user_id", "provider"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True)
    provider: Mapped[str] = mapped_column(String(20))  # zotero
    api_key_encrypted: Mapped[str] = mapped_column(Text)
    config: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class RecordExternalLink(Base):
    """A record's counterpart in an external library: `library` is the
    provider's library prefix ("users/123" or "groups/456" for Zotero) and
    `external_key` the item key there. Written on import (the item the record
    came from) and on export (the item created for it)."""

    __tablename__ = "record_external_links"
    __table_args__ = (UniqueConstraint("record_id", "provider", "library"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    record_id: Mapped[int] = mapped_column(
        ForeignKey("records.id", ondelete="CASCADE"), index=True)
    provider: Mapped[str] = mapped_column(String(20))
    library: Mapped[str] = mapped_column(String(60))
    external_key: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow)
