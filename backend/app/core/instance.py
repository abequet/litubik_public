# SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Stable instance identity, generated once at first startup."""
import os

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.crypto import decrypt_secret, encrypt_secret
from app.models.accounts import new_uuid
from app.models.instance import InstanceMeta


def _row(db: Session) -> InstanceMeta:
    row = db.get(InstanceMeta, 1)
    if row is None:
        row = InstanceMeta(id=1, instance_id=new_uuid())
        db.add(row)
        try:
            db.commit()
        except IntegrityError:  # concurrent first call created it
            db.rollback()
            row = db.get(InstanceMeta, 1)
            assert row is not None
    return row


def get_instance_id(db: Session) -> str:
    """The uuid of this LitUbik installation (created on first call)."""
    return _row(db).instance_id


def get_signing_key(db: Session) -> Ed25519PrivateKey:
    """This installation's Ed25519 signing key, created on first call.

    M5: identifies *which instance* produced a contribution package. The project
    passphrase cannot do that — every member holds it, so any of them could sign
    a package attributed to a colleague.
    """
    row = _row(db)
    seed = decrypt_secret(row.signing_key_encrypted) if row.signing_key_encrypted else None
    if not seed:
        raw = os.urandom(32)
        row.signing_key_encrypted = encrypt_secret(raw.hex())
        db.commit()
        return Ed25519PrivateKey.from_private_bytes(raw)
    return Ed25519PrivateKey.from_private_bytes(bytes.fromhex(seed))
