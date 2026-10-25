# SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
# SPDX-License-Identifier: AGPL-3.0-or-later
import secrets
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import (
    JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text,
    UniqueConstraint,
    false as sa_false,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_uuid() -> str:
    """Cross-instance identity: integer PKs mean nothing outside this instance,
    so every entity referenced by the sync layer carries a stable uuid
    (docs/SYNC_IMPLEMENTATION_PLAN.md, phase 0). Users are matched by email."""
    return str(uuid4())


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    display_name: Mapped[str] = mapped_column(String(120))
    is_admin: Mapped[bool] = mapped_column(default=False)  # app-level admin
    # M6 demo instances: full account (allowlisted email) vs sandbox account
    # (purged by the daily reset, open full-text sources only). Only consulted
    # when LITUBIK_DEMO is on — normal instances register everyone trusted.
    is_trusted: Mapped[bool] = mapped_column(Boolean, default=True)
    # M9: session-token epoch. Bumped on password change (and "log out
    # everywhere") so every JWT issued before then stops validating.
    token_version: Mapped[int] = mapped_column(Integer, default=0)
    # Random per account, carried in its session tokens. SQLite hands a deleted
    # account's id to the next one created, so without it a token kept from a
    # deleted account (a guest who ended their session) would open the next
    # account to take that id. NULL for accounts created before it existed:
    # their tokens carry none, and stay valid.
    session_salt: Mapped[str | None] = mapped_column(
        String(32), nullable=True, default=lambda: secrets.token_hex(16))
    # standalone "Download papers" module: opt-in per user, ticked by the
    # superadmin (who always has it). Off for everyone else by default.
    can_download_papers: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="0")
    # demo instances: a one-click guest session (no email, no known password).
    # Always a sandbox account, so purged with the others.
    is_guest: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="0")
    # demo instances: what this sandbox account has spent on the app-wide AI
    # key (USD). Goes away with the account; the monthly total that must
    # survive the purge lives in demo_ai_budget.
    demo_ai_spent_usd: Mapped[float] = mapped_column(
        Float, default=0.0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    memberships: Mapped[list["ProjectMember"]] = relationship(back_populates="user")


class TrustedEmail(Base):
    """M6 demo allowlist: emails that register as full (non-sandbox) accounts
    on a demo instance. Managed by the superadmin; seedable via the
    LITUBIK_TRUSTED_EMAILS env variable."""

    __tablename__ = "trusted_emails"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    added_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"))
    # "manual" (superadmin UI / env seed) or "invite" (auto-allowlisted when a
    # trusted project admin added this email as a project member)
    source: Mapped[str] = mapped_column(String(20), default="manual")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(primary_key=True)
    uuid: Mapped[str] = mapped_column(String(36), default=new_uuid, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text, default="")
    research_question: Mapped[str] = mapped_column(Text, default="")
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    # soft delete: archived projects are hidden from the main list and can be
    # restored or permanently deleted from the archive
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # T14: hand-curated highlight word lists for the screening screens —
    # {"green": [...], "red": [...]}, on top of the equations' keywords
    highlights: Mapped[dict] = mapped_column(JSON, default=dict)
    # How this review frames itself (app/services/framing.py). It drives the
    # vocabulary — protocol slots, concept-block labels, extraction template,
    # the framing given to the AI, what the Methods draft claims the review is
    # — and nothing in the pipeline. server_default keeps every pre-existing
    # project on the historical behaviour without a data migration.
    review_type: Mapped[str] = mapped_column(
        String(30), default="systematic", server_default="systematic")
    question_framework: Mapped[str] = mapped_column(
        String(20), default="picos", server_default="picos")
    # PRISMA 2020 item 24a: register name + registration number, OR an explicit
    # statement that the review was not registered. "" = the question has never
    # been answered (the Methods draft then flags the gap); "none" = answered,
    # and the manuscript must say so. Kept on the project rather than on a
    # Protocol version: a review is registered once, its protocol is versioned.
    registry: Mapped[str] = mapped_column(String(20), default="",
                                          server_default="")
    registration_id: Mapped[str] = mapped_column(String(120), default="",
                                                 server_default="")
    registration_url: Mapped[str] = mapped_column(String(500), default="",
                                                  server_default="")
    registered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True))
    # PRISMA 24b: where the protocol itself can be read, when it is public
    protocol_url: Mapped[str] = mapped_column(String(500), default="",
                                              server_default="")
    # Sync topology (hub-and-spoke): coordinator = this instance owns the
    # structural state (default, every locally created project); satellite =
    # imported from a snapshot, structural endpoints are locked here.
    sync_role: Mapped[str] = mapped_column(String(12), default="coordinator")
    coordinator_email: Mapped[str] = mapped_column(String(255), default="")
    coordinator_instance_id: Mapped[str | None] = mapped_column(String(36))
    # version of the last snapshot exported (coordinator) / imported (satellite)
    snapshot_version: Mapped[int] = mapped_column(Integer, default=0)
    # sync phase 3: passphrase protecting shared API keys in transit (PBKDF2 →
    # Fernet). Stored encrypted with the INSTANCE key; the same phrase must be
    # entered on every instance of the project (communicated out-of-band).
    sync_passphrase_encrypted: Mapped[str | None] = mapped_column(Text)
    # sync phase 4: local path of the shared folder (Nextcloud/Drive/...) this
    # project exchanges through; "" = file-based exchange only. auto_publish:
    # the coordinator's scans keep the folder's snapshot up to date.
    sync_dir: Mapped[str] = mapped_column(Text, default="")
    sync_auto_publish: Mapped[bool] = mapped_column(Boolean, default=False)
    # AI: open only the best-ranked key, never fall back to another provider.
    # Set by teams whose corpus must not leave a local model.
    llm_no_fallback: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=sa_false())
    # AI routing (provider/model/effort per task): editable by project
    # reviewers too, not only project admins
    llm_reviewers_can_route: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=sa_false())
    # The databases this review searches: registry ids (and declared
    # databases) the Equations and Search pages show, the counts run on, the
    # AI drafts translations for and PRISMA-S reports. None = every database
    # of the registry (the historical behaviour).
    databases: Mapped[list | None] = mapped_column(JSON)

    members: Mapped[list["ProjectMember"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )


class ProjectMember(Base):
    __tablename__ = "project_members"
    __table_args__ = (UniqueConstraint("project_id", "user_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    role: Mapped[str] = mapped_column(String(20), default="reviewer")  # admin | reviewer
    # M5: Ed25519 public key (hex) of the instance this member contributes from,
    # learned on their first signed contribution package and required to match on
    # every later one. Empty until they contribute. See services/sync/signing.py.
    sync_pubkey: Mapped[str] = mapped_column(String(64), default="")

    project: Mapped[Project] = relationship(back_populates="members")
    user: Mapped[User] = relationship(back_populates="memberships")


class ProjectInvitation(Base):
    """Membership granted to an email that has no account yet: converted to a
    real ProjectMember the moment that email registers (dev mode: no email is
    sent — the person just signs up with the invited address)."""

    __tablename__ = "project_invitations"
    __table_args__ = (UniqueConstraint("project_id", "email"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    email: Mapped[str] = mapped_column(String(255), index=True)
    role: Mapped[str] = mapped_column(String(20), default="reviewer")
    invited_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class LLMCredential(Base):
    """A stored third-party LLM API key. project_id NULL = global (app-wide) key."""

    __tablename__ = "llm_credentials"
    __table_args__ = (UniqueConstraint("project_id", "provider"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int | None] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=True
    )
    # one of services/llm/registry.PROVIDERS
    provider: Mapped[str] = mapped_column(String(20))
    # "local" needs no key: a placeholder is stored so the column stays NOT NULL
    api_key_encrypted: Mapped[str] = mapped_column(Text)
    default_model: Mapped[str] = mapped_column(String(120))
    # endpoint of a self-hosted / OpenAI-compatible server ("local" only);
    # NULL for the hosted providers, whose URL is fixed by the SDK
    base_url: Mapped[str | None] = mapped_column(String(300))
    # preferred credential of its scope (one per project, one global): jobs
    # without an explicit provider pick it first
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    # sync phase 3: who brought the key; shared = travels (encrypted with the
    # project passphrase) in snapshots/contribution packages so other
    # instances of the project can use it. Project-scoped keys only.
    owner_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"))
    shared: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class DatabaseCredential(Base):
    """A stored bibliographic-database API key (Scopus, IEEE) enabling the
    key-activated API connectors for counts and search. project_id NULL = global
    (app-wide); a project-scoped row overrides the global one."""

    __tablename__ = "database_credentials"
    __table_args__ = (UniqueConstraint("project_id", "provider"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int | None] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=True
    )
    provider: Mapped[str] = mapped_column(String(20))  # scopus | ieee
    api_key_encrypted: Mapped[str] = mapped_column(Text)
    # sync phase 3 (see LLMCredential): ownership + opt-in sharing
    owner_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"))
    shared: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
