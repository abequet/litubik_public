# SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Identity of this LitUbik installation (sync provenance)."""
from datetime import datetime

from sqlalchemy import DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.accounts import utcnow


class InstanceMeta(Base):
    """Single row (id=1), created at first startup: the stable identifier of
    this installation, stamped on everything the sync layer exports so the
    origin of any imported row can be traced back to an instance."""

    __tablename__ = "instance_meta"

    id: Mapped[int] = mapped_column(primary_key=True)  # always 1
    instance_id: Mapped[str] = mapped_column(String(36), unique=True)
    # M5: Ed25519 signing seed of this installation (Fernet-encrypted), created
    # on first use. It signs outbound contribution packages so a coordinator can
    # tell one reviewer's instance from another's — the project passphrase
    # cannot, since every member of the project holds it.
    signing_key_encrypted: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
