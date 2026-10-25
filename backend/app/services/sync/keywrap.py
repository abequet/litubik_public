# SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Passphrase-based encryption for shared API keys in transit (sync phase 3).

The local Fernet (core/crypto) is derived from the INSTANCE secret and thus
useless on another machine. Shared keys therefore travel re-encrypted under a
per-project passphrase that every instance enters once (communicated
out-of-band): PBKDF2-HMAC-SHA256 (600k iterations, random salt per blob)
derives a Fernet key. Nothing is ever written in cleartext, at rest or in
transit.
"""
import base64
import json
import os

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

PBKDF2_ITERATIONS = 600_000


class WrongPassphrase(Exception):
    pass


def _fernet(passphrase: str, salt: bytes) -> Fernet:
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt,
                     iterations=PBKDF2_ITERATIONS)
    key = base64.urlsafe_b64encode(kdf.derive(passphrase.encode()))
    return Fernet(key)


def encrypt_blob(data: dict, passphrase: str) -> dict:
    """-> {"salt": b64, "token": fernet token} carrying `data` as JSON."""
    salt = os.urandom(16)
    token = _fernet(passphrase, salt).encrypt(
        json.dumps(data, ensure_ascii=False).encode())
    return {"salt": base64.b64encode(salt).decode(),
            "token": token.decode(),
            "kdf": f"pbkdf2-sha256:{PBKDF2_ITERATIONS}"}


def decrypt_blob(blob: dict, passphrase: str) -> dict:
    try:
        salt = base64.b64decode(blob["salt"])
        plaintext = _fernet(passphrase, salt).decrypt(blob["token"].encode())
    except (InvalidToken, KeyError, ValueError):
        raise WrongPassphrase("Phrase secrète incorrecte (ou blob corrompu)")
    return json.loads(plaintext)
