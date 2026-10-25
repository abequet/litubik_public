# SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
# SPDX-License-Identifier: AGPL-3.0-or-later
"""HMAC authentication of sync artifacts (H3 / M6).

The shared-folder transport moves files that arrive attributed to a named
author and are (for contribution packages) auto-applied by the background scan.
Nothing cryptographically bound the artifact to someone who actually holds the
project's secret, so anyone with WRITE access to the shared folder could forge a
package (votes/decisions attributed to a victim) or tamper with a snapshot.

Every instance of a project already shares one secret out-of-band: the project
passphrase (also used to wrap shared API keys). We reuse it as an HMAC key. A
deterministic PBKDF2 derivation (salted by the project uuid, identical on every
instance) lets both sides sign and verify without exchanging anything new.

Policy enforced by the callers:
- Contribution packages imported from the shared folder MUST carry a valid
  signature (folder scan refuses unsigned/forged packages). The explicit
  admin-only upload endpoint stays usable for unsigned legacy files (a human is
  vouching), but still rejects a *present-but-invalid* signature.
- Snapshots are signed too; import verifies when a signature is present and
  refuses a tampered one, surfacing verified provenance to the admin.

M5 — what the project HMAC does NOT prove
-----------------------------------------
The passphrase is shared by every member of the project, so the HMAC only says
"produced by someone holding the project secret". It cannot distinguish one
member from another: a satellite reviewer could craft a package declaring a
colleague as its author, sign it validly, and have their votes accepted.

So contribution packages carry a *second*, asymmetric signature made with the
exporting installation's Ed25519 key (`core.instance.get_signing_key`). The
coordinator binds an author to the public key seen on their first signed package
(`ProjectMember.sync_pubkey`) and refuses any later package for that author
signed by a different key — trust on first use, as SSH does for host keys.

Residual limitation, deliberately not papered over: the *first* package for a
given author establishes the binding, so it cannot itself be authenticated. An
admin who wants certainty compares the fingerprint out of band; re-binding is an
explicit admin action, never automatic.
"""
import hashlib
import hmac
import json

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from app.core.crypto import decrypt_secret

ALG = "hmac-sha256-pbkdf2"
_PBKDF2_ITERATIONS = 200_000


def _passphrase(project) -> str | None:
    enc = getattr(project, "sync_passphrase_encrypted", None)
    if not enc:
        return None
    phrase = decrypt_secret(enc)
    return phrase or None


def project_key(project) -> bytes | None:
    """Deterministic per-project HMAC key, or None if no passphrase is set.
    Reproducible on any instance: same passphrase + same project uuid."""
    phrase = _passphrase(project)
    if not phrase:
        return None
    salt = ("litubik-sync-sign:" + (project.uuid or "")).encode()
    return hashlib.pbkdf2_hmac("sha256", phrase.encode(), salt,
                               _PBKDF2_ITERATIONS)


def _canonical(payload: dict) -> bytes:
    body = {k: v for k, v in payload.items()
            if k not in ("signature", "author_signature")}
    return json.dumps(body, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":")).encode()


# --- M5: per-instance author signature ---------------------------------------
AUTHOR_ALG = "ed25519"


def public_key_hex(private_key) -> str:
    """The hex fingerprint an author's package is bound to."""
    from cryptography.hazmat.primitives.serialization import (
        Encoding, PublicFormat)
    return private_key.public_key().public_bytes(
        Encoding.Raw, PublicFormat.Raw).hex()


def sign_author(private_key, payload: dict) -> dict:
    """Attach payload['author_signature'] — an Ed25519 signature over the same
    canonical bytes the project HMAC covers, made with the exporting
    installation's key."""
    payload["author_signature"] = {
        "alg": AUTHOR_ALG,
        "pubkey": public_key_hex(private_key),
        "value": private_key.sign(_canonical(payload)).hex(),
    }
    return payload


def verify_author(payload: dict) -> tuple[bool | None, str]:
    """Check the author signature against the public key it declares.

    Returns (verdict, pubkey_hex): verdict is None when the package carries no
    author signature (legacy), True/False otherwise. A True verdict only says
    "signed by whoever holds this key" — binding that key to an author is the
    caller's job (see `bind_author_key`).
    """
    sig = payload.get("author_signature")
    if not isinstance(sig, dict) or not sig.get("value") or not sig.get("pubkey"):
        return None, ""
    pubkey = str(sig["pubkey"])
    try:
        key = Ed25519PublicKey.from_public_bytes(bytes.fromhex(pubkey))
        key.verify(bytes.fromhex(str(sig["value"])), _canonical(payload))
    except (InvalidSignature, ValueError):
        return False, pubkey
    return True, pubkey


def bind_author_key(member, pubkey: str) -> tuple[bool, str]:
    """Trust-on-first-use binding of an author to the key that signs for them.

    Returns (accepted, note). Refuses a key that differs from the one recorded
    on this member — that is the forgery case M5 is about.
    """
    if not pubkey:
        return True, ""
    known = (member.sync_pubkey or "").strip()
    if not known:
        member.sync_pubkey = pubkey
        return True, f"clé d'auteur enregistrée ({pubkey[:16]}…)"
    if known != pubkey:
        return False, (
            f"paquet signé par une autre installation que celle enregistrée "
            f"pour cet auteur (attendue {known[:16]}…, reçue {pubkey[:16]}…). "
            f"Si le co-relecteur a changé de machine, un admin doit réinitialiser "
            f"sa clé depuis la page Synchronisation.")
    return True, ""


def sign_dict(project, payload: dict) -> dict:
    """Attach payload['signature'] in place (no-op without a passphrase)."""
    key = project_key(project)
    if key is None:
        return payload
    mac = hmac.new(key, _canonical(payload), hashlib.sha256).hexdigest()
    payload["signature"] = {"alg": ALG, "value": mac}
    return payload


def verify_dict(project, payload: dict) -> bool | None:
    """True/False when a signature is present; None when the payload is
    unsigned. False also when signed but no local passphrase can check it."""
    sig = payload.get("signature")
    if not isinstance(sig, dict) or not sig.get("value"):
        return None
    key = project_key(project)
    if key is None:
        return False
    expected = hmac.new(key, _canonical(payload), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, str(sig.get("value", "")))


def snapshot_blob(manifest: dict, data_bytes: bytes) -> bytes:
    """The bytes a snapshot signature covers: its manifest (minus the signature
    field) plus the exact data.json bytes — so both provenance (coordinator
    email/instance in the manifest) and content are bound."""
    return _canonical(manifest) + b"\x00" + data_bytes


def sign_bytes(project, blob: bytes) -> dict | None:
    """Detached signature over raw bytes (snapshot content). None without a
    passphrase."""
    key = project_key(project)
    if key is None:
        return None
    return {"alg": ALG,
            "value": hmac.new(key, blob, hashlib.sha256).hexdigest()}


def verify_bytes(project, blob: bytes, signature: dict | None) -> bool | None:
    """True/False when `signature` is present; None when it is absent."""
    if not isinstance(signature, dict) or not signature.get("value"):
        return None
    key = project_key(project)
    if key is None:
        return False
    expected = hmac.new(key, blob, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, str(signature.get("value", "")))
