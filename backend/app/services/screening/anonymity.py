# SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Anonymous reviewers (optional, per round).

While an anonymous round runs, nobody — the project admins included — sees
which reviewer cast which vote or who is paired with whom: every name that
a screening payload would carry is replaced by a stable pseudonym
("Reviewer 1", "Reviewer 2", …), the same for everyone, and the user ids
that go with it by opaque negative ids so that the front cannot map them
back on the project roster. The names come back once the round is
complete: every assignment voted (or settled) and no open conflict.

The option is frozen at the start of the round: it is part of the
configuration that `/start` locks, so an admin cannot lift the veil for a
moment and put it back.

The pseudonyms are seeded by the project uuid and the user's e-mail, so
they are the same on every synced instance and across the rounds of a
project (a reviewer keeps the same number in title/abstract and full text).
"""
from __future__ import annotations

import hashlib

from sqlalchemy.orm import Session

from app.models import Assignment, Conflict, Project, ProjectMember, User, Vote
from app.models.screening import ScreeningConfig


def round_complete(db: Session, config: ScreeningConfig) -> bool:
    """Every assignment of the round has its vote (or its record was settled
    without it — a validated AI triage exclusion) and no conflict is open."""
    if (db.query(Conflict)
            .filter_by(project_id=config.project_id, stage=config.stage,
                       round=config.round, status="open").count()):
        return False
    voted = {(v.record_id, v.voter_user_id) for v in
             db.query(Vote.record_id, Vote.voter_user_id)
             .filter_by(project_id=config.project_id, stage=config.stage,
                        round=config.round, is_ai=False)}
    settled = {c.record_id for c in db.query(Conflict.record_id)
               .filter_by(project_id=config.project_id, stage=config.stage,
                          round=config.round, status="resolved")}
    for a in (db.query(Assignment.record_id, Assignment.user_id)
              .filter_by(config_id=config.id)):
        if (a.record_id, a.user_id) not in voted and a.record_id not in settled:
            return False
    return True


def names_hidden(db: Session, config: ScreeningConfig | None) -> bool:
    """True while the reviewers of this round must stay anonymous."""
    return bool(config is not None and config.anonymous
                and config.status == "active"
                and not round_complete(db, config))


def project_names_hidden(db: Session, project_id: int) -> bool:
    """True while any round of the project keeps its reviewers anonymous —
    the project-wide views (notes, PRISMA activity, annotations) follow the
    strictest round."""
    configs = (db.query(ScreeningConfig)
               .filter_by(project_id=project_id, status="active")
               .filter(ScreeningConfig.anonymous.is_(True)).all())
    return any(not round_complete(db, c) for c in configs)


def pseudonyms(db: Session, project_id: int) -> dict[int, str]:
    """Stable "Reviewer n" per project member, in an order that nothing on
    the roster (membership order, name, id) lets anyone reconstruct."""
    project = db.get(Project, project_id)
    seed = project.uuid if project is not None else str(project_id)
    rows = (db.query(User.id, User.email)
            .join(ProjectMember, ProjectMember.user_id == User.id)
            .filter(ProjectMember.project_id == project_id).all())
    ordered = sorted(rows, key=lambda r: hashlib.sha256(
        f"{seed}|{r.email}".encode()).hexdigest())
    return {uid: f"Reviewer {i}" for i, (uid, _) in enumerate(ordered, start=1)}


class Namer:
    """Resolves a user id to what the caller may see: the display name, or
    the pseudonym while the names are hidden. `ident` does the same for the
    id itself (the negative pseudonym rank when hidden), so that payloads
    keyed by user id stay usable by the front without naming anyone."""

    def __init__(self, db: Session, project_id: int, hidden: bool):
        self.hidden = hidden
        self._names = {u.id: u.display_name for u in db.query(User)}
        self._alias = pseudonyms(db, project_id) if hidden else {}

    def __call__(self, user_id: int | None, default: str = "?") -> str:
        if user_id is None:
            return default
        if self.hidden:
            return self._alias.get(user_id, "Reviewer ?")
        return self._names.get(user_id, default)

    def name(self, user_id: int | None) -> str | None:
        return self(user_id) if user_id is not None else None

    def ident(self, user_id: int | None) -> int | None:
        if user_id is None or not self.hidden:
            return user_id
        alias = self._alias.get(user_id)
        return -int(alias.split()[-1]) if alias else -9999


def namer_for(db: Session, config: ScreeningConfig | None,
              project_id: int | None = None) -> Namer:
    """Namer for one round's payloads."""
    pid = config.project_id if config is not None else project_id
    return Namer(db, pid, names_hidden(db, config))


def project_namer(db: Session, project_id: int) -> Namer:
    """Namer for the project-wide views (strictest round wins)."""
    return Namer(db, project_id, project_names_hidden(db, project_id))
