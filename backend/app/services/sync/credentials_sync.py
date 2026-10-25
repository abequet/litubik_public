# SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Shared API keys in sync exchanges (phase 3).

What travels: PROJECT-scoped LLM and bibliographic-database credentials whose
owner opted in (`shared=True`) — encrypted under the project passphrase
(keywrap). Global instance keys and full-text institutional logins (personal
EZProxy/CAS credentials) never travel.

Full-set semantics per exchange: a package carries its author's complete
shared set, a snapshot the project's complete shared set — so un-sharing a
key removes it on the other instances at the next exchange, without
tombstones. Owners are identified by email; their rows on the receiving
instance are replaced, other people's rows are never touched.
"""
from sqlalchemy.orm import Session

from app.core.crypto import decrypt_secret, encrypt_secret
from app.models import DatabaseCredential, LLMCredential, Project, User
from app.services.sync.keywrap import (
    WrongPassphrase, decrypt_blob, encrypt_blob,
)


def project_passphrase(db: Session, project: Project) -> str | None:
    if not project.sync_passphrase_encrypted:
        return None
    return decrypt_secret(project.sync_passphrase_encrypted)


def collect_shared(db: Session, project: Project,
                   owner: User | None = None) -> dict:
    """Plaintext shared credentials of the project (or of one owner), ready
    for keywrap. Never returned by any API — only written encrypted."""
    emails = {u.id: u.email for u in db.query(User).all()}

    def rows(model):
        query = db.query(model).filter_by(project_id=project.id, shared=True)
        if owner is not None:
            query = query.filter_by(owner_user_id=owner.id)
        return query.all()

    llm = []
    for c in rows(LLMCredential):
        key = decrypt_secret(c.api_key_encrypted)
        if key:
            llm.append({"provider": c.provider, "api_key": key,
                        "default_model": c.default_model,
                        "base_url": c.base_url,
                        "owner": emails.get(c.owner_user_id)})
    database = []
    for c in rows(DatabaseCredential):
        key = decrypt_secret(c.api_key_encrypted)
        if key:
            database.append({"provider": c.provider, "api_key": key,
                             "owner": emails.get(c.owner_user_id)})
    return {"llm": llm, "database": database}


def build_credentials_blob(db: Session, project: Project,
                           owner: User | None = None) -> tuple[dict | None,
                                                               int, str]:
    """(encrypted blob | None, n_keys, note). With a passphrase set the blob
    is ALWAYS included — an empty set is the signal that propagates the
    un-sharing of a last key (full-set semantics). Without a passphrase,
    nothing can travel: None, plus a note when keys would have."""
    data = collect_shared(db, project, owner)
    n = len(data["llm"]) + len(data["database"])
    passphrase = project_passphrase(db, project)
    if not passphrase:
        if n == 0:
            return None, 0, ""
        return None, n, (f"{n} clé(s) partagée(s) non incluse(s) : définissez "
                         "la phrase secrète du projet (page Synchronisation)")
    return encrypt_blob(data, passphrase), n, ""


def apply_credentials_blob(db: Session, project: Project, blob: dict | None,
                           replace_owner_emails: set[str] | None,
                           warnings: list[str]) -> dict:
    """Decrypt and merge a received blob. replace_owner_emails limits the
    full-set replacement to those owners (a contribution package speaks only
    for its author); None = the blob is authoritative for every shared row
    coming from elsewhere (snapshot). Returns counts for the report."""
    counts = {"applied": 0, "removed": 0, "skipped": 0}
    if blob is None:
        return counts
    passphrase = project_passphrase(db, project)
    if not passphrase:
        warnings.append("Des clés partagées accompagnent cet échange mais la "
                        "phrase secrète du projet n'est pas définie ici — "
                        "clés ignorées")
        return counts
    try:
        data = decrypt_blob(blob, passphrase)
    except WrongPassphrase:
        warnings.append("Phrase secrète différente de celle de l'expéditeur — "
                        "clés partagées ignorées")
        return counts

    users = {u.email: u for u in db.query(User).all()}

    def uid(email):
        user = users.get((email or "").lower())
        return user.id if user else None

    for model, entries in ((LLMCredential, data.get("llm", [])),
                           (DatabaseCredential, data.get("database", []))):
        seen: set[str] = set()
        for e in entries:
            owner_id = uid(e.get("owner"))
            row = (db.query(model)
                   .filter_by(project_id=project.id,
                              provider=e["provider"]).first())
            if row is not None and row.owner_user_id \
                    and row.owner_user_id != owner_id:
                # someone else's key already fills the (project, provider)
                # slot — theirs wins locally, note it
                counts["skipped"] += 1
                warnings.append(
                    f"Clé {e['provider']} de {e.get('owner')} ignorée : une "
                    "clé d'un autre propriétaire existe déjà sur ce projet")
                continue
            if row is None:
                row = model(project_id=project.id, provider=e["provider"])
                db.add(row)
            row.api_key_encrypted = encrypt_secret(e["api_key"])
            row.owner_user_id = owner_id
            row.shared = True
            if model is LLMCredential:
                row.default_model = e.get("default_model", "")
                row.base_url = e.get("base_url") or None
            seen.add(e["provider"])
            counts["applied"] += 1

        # full-set removal: shared rows of the concerned owners that the
        # sender no longer shares
        query = db.query(model).filter_by(project_id=project.id, shared=True)
        if seen:
            query = query.filter(model.provider.notin_(seen))
        for row in query.all():
            owner_email = next((em for em, u in users.items()
                                if u.id == row.owner_user_id), None)
            if replace_owner_emails is not None \
                    and owner_email not in replace_owner_emails:
                continue
            if replace_owner_emails is None and owner_email in users \
                    and users[owner_email].password_hash != "":
                continue  # snapshot: local real users keep their own keys
            db.delete(row)
            counts["removed"] += 1
    db.flush()
    return counts
