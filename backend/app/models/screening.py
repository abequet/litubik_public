# SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Screening (title/abstract and full-text), full texts and data extraction."""
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.accounts import new_uuid, utcnow


class ScreeningConfig(Base):
    __tablename__ = "screening_configs"
    __table_args__ = (UniqueConstraint("project_id", "stage", "round"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    uuid: Mapped[str] = mapped_column(String(36), default=new_uuid, unique=True, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    stage: Mapped[str] = mapped_column(String(5))  # ta | ft
    round: Mapped[int] = mapped_column(Integer, default=1)
    n_reviewers: Mapped[int] = mapped_column(Integer, default=2)
    decision_rule: Mapped[str] = mapped_column(String(30), default="all")  # all | k_of_n
    maybe_policy: Mapped[str] = mapped_column(String(30), default="conflict")  # conflict | advance
    ai_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    ai_mode: Mapped[str] = mapped_column(String(20), default="suggestion")  # suggestion | reviewer
    # AI title triage (bulk exclusion proposals on titles only):
    # off | admin (validated list = global exclusion, admin only)
    #     | reviewers (validated list = MY exclude votes, any reviewer)
    ai_triage: Mapped[str] = mapped_column(String(12), default="off")
    # control sample of the title triage: this share (percent, 0 = off) of
    # every validated exclusion list is held back at random — the records
    # stay in the human queue, unmarked — so the dashboard can check that the
    # reviewers exclude them too (see TriageControl)
    triage_control_pct: Mapped[int] = mapped_column(Integer, default=0,
                                                    server_default="0")
    # batch AI suggestion (title+abstract vs I/E criteria): when on, a reviewer
    # can pre-compute the on-click suggestion for all their not-yet-voted records
    # of the round in one go (admin enables the button; every reviewer may run it)
    ai_batch: Mapped[bool] = mapped_column(Boolean, default=False)
    # when a reviewer gets to see the AI suggestion: always (as soon as one is
    # cached) | after_vote (hidden until their own vote is cast; a cached batch
    # suggestion can still be revealed on purpose, which is recorded — see
    # AiReveal). Enforced server-side like the blinding between reviewers.
    ai_reveal: Mapped[str] = mapped_column(String(12), default="always",
                                           server_default="always")
    # who screens what: all = everyone votes everything; dual = 2 votes per
    # record spread across reviewers (Covidence-style); single_overlap = 1 vote
    # per record + overlap_pct% double-screened for the agreement statistic;
    # lead = one lead reviewer screens every record, the other reviewers
    # share the corpus (equal or weighted shares) — 2 votes per record
    allocation: Mapped[str] = mapped_column(String(20), default="all")
    # allocation = lead: the reviewer who screens the whole corpus
    lead_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    overlap_pct: Mapped[int] = mapped_column(Integer, default=20)
    conflict_resolution: Mapped[str] = mapped_column(
        String(20), default="consensus")  # consensus | arbiter
    reviewer_ids: Mapped[list] = mapped_column(JSON, default=list)
    # allocation = lots / lead: each reviewer's share of the screening work,
    # in percent ({user_id: pct}, summing to 100; NULL = equal shares —
    # for lead, over the co-reviewers only), the
    # number of records per lot, and the 0–2 named arbiters — never paired
    # together on a lot, so that a conflict always has an arbiter who did
    # not vote on it (the arbitration rule itself comes with R2b)
    weights: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    lot_size: Mapped[int] = mapped_column(Integer, default=100,
                                          server_default="100")
    arbiter_ids: Mapped[list | None] = mapped_column(JSON, default=list,
                                                     nullable=True)
    # anonymous reviewers: while the round runs, nobody (admins included)
    # sees who voted what nor who is paired with whom — the names are
    # replaced by stable pseudonyms until the round is complete (see
    # services/screening/anonymity.py). Frozen at the start of the round.
    anonymous: Mapped[bool] = mapped_column(Boolean, default=False,
                                            server_default="0")
    status: Mapped[str] = mapped_column(String(20), default="draft")  # draft | active
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ScreeningLot(Base):
    """A lot of records screened by one pair of reviewers (allocation = lots).

    The corpus is cut into lots of `lot_size` records; each lot goes to one
    pair, chosen so that every reviewer ends up with their weighted share
    and the pairs rotate. Records that enter the round late (snowballing,
    update passes) form new lots on the remaining quotas. `user_ids` is the
    pair as validated by the admin before the start; `due_at` the deadline
    the team gave itself for that lot; `status` closes once every assignment
    of the lot has its vote. Published with the protocol as the allocation
    CSV."""

    __tablename__ = "screening_lots"
    __table_args__ = (UniqueConstraint("config_id", "index"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    uuid: Mapped[str] = mapped_column(String(36), default=new_uuid, unique=True,
                                      index=True)
    config_id: Mapped[int] = mapped_column(
        ForeignKey("screening_configs.id", ondelete="CASCADE"), index=True)
    index: Mapped[int] = mapped_column(Integer)  # 1-based, in corpus order
    user_ids: Mapped[list] = mapped_column(JSON, default=list)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(10), default="open")  # open | closed
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),
                                                 default=utcnow)


class Assignment(Base):
    __tablename__ = "assignments"
    __table_args__ = (UniqueConstraint("config_id", "record_id", "user_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    config_id: Mapped[int] = mapped_column(ForeignKey("screening_configs.id", ondelete="CASCADE"))
    record_id: Mapped[int] = mapped_column(ForeignKey("records.id", ondelete="CASCADE"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    # allocation = lots: the lot this assignment belongs to (NULL otherwise)
    lot_id: Mapped[int | None] = mapped_column(
        ForeignKey("screening_lots.id", ondelete="SET NULL"), nullable=True)
    # "decide later": a skipped record moves to the back of the reviewer's queue
    skipped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Vote(Base):
    __tablename__ = "votes"
    __table_args__ = (UniqueConstraint("record_id", "stage", "round", "voter_user_id", "is_ai"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    record_id: Mapped[int] = mapped_column(ForeignKey("records.id", ondelete="CASCADE"), index=True)
    stage: Mapped[str] = mapped_column(String(5))  # ta | ft
    round: Mapped[int] = mapped_column(Integer, default=1)
    voter_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    is_ai: Mapped[bool] = mapped_column(Boolean, default=False)
    decision: Mapped[str] = mapped_column(String(10))  # include | exclude | maybe
    # Exclusion reasons: list of protocol criteria codes; first item = primary reason (PRISMA).
    reasons: Mapped[list] = mapped_column(JSON, default=list)
    justification: Mapped[str] = mapped_column(Text, default="")
    criteria_eval: Mapped[dict] = mapped_column(JSON, default=dict)  # AI: per-criterion assessment
    confidence: Mapped[float | None] = mapped_column(Float)  # AI only
    # AI votes: email of the user whose instance generated the suggestion
    # (sync provenance; NULL = generated here / pre-sync history)
    generated_by: Mapped[str | None] = mapped_column(String(255))
    # sync: "author@email #seq" of the contribution package this row came from
    # (NULL = created directly on this instance) — ReviQ's source_file equivalent
    imported_from: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    # sync merge rule "newest wins" compares this across instances
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class AiReveal(Base):
    """A reviewer chose to see the cached AI suggestion BEFORE casting their
    vote, in a round whose `ai_reveal` setting hides it until the vote.

    Recorded so the paired human/AI corpus can tell blind votes from votes
    made with the suggestion in view, and so the AI disclosure can count them.
    Produced on whichever instance the reviewer works on: travels in
    contribution packages and snapshots."""

    __tablename__ = "ai_reveals"
    __table_args__ = (UniqueConstraint("record_id", "stage", "round", "user_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    record_id: Mapped[int] = mapped_column(
        ForeignKey("records.id", ondelete="CASCADE"), index=True)
    stage: Mapped[str] = mapped_column(String(5))  # ta | ft
    round: Mapped[int] = mapped_column(Integer, default=1)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    revealed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    # sync: "author@email #seq" of the package this row came from
    imported_from: Mapped[str | None] = mapped_column(String(255))


class Conflict(Base):
    __tablename__ = "conflicts"
    __table_args__ = (UniqueConstraint("record_id", "stage", "round"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    record_id: Mapped[int] = mapped_column(ForeignKey("records.id", ondelete="CASCADE"))
    stage: Mapped[str] = mapped_column(String(5))
    round: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(20), default="open")  # open | resolved
    resolution: Mapped[str] = mapped_column(String(10), default="")  # include | exclude
    resolution_note: Mapped[str] = mapped_column(Text, default="")
    # votes = a genuine reviewer disagreement; ai_triage = a pre-resolved row
    # recording a validated bulk title-triage exclusion (audit trail — these
    # never show in the Conflicts tab and are counted apart in the stats)
    origin: Mapped[str] = mapped_column(String(12), default="votes")
    # Full-text stage: the exclusion reasons recorded at resolution (first = primary,
    # PRISMA "reports excluded: reason (n)"). Empty at the title/abstract stage.
    reasons: Mapped[list] = mapped_column(JSON, default=list)
    resolved_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class TriageControl(Base):
    """A title the AI triage proposed for exclusion and the validator ticked,
    that was held back as a control instead of being excluded: no Conflict,
    no Vote — the record stays in the reviewers' queue with no visible mark,
    and the dashboard compares the humans' decision with the AI's. Rows are
    written on the coordinator only (the apply endpoint is coordinator-side)
    and do not travel in sync snapshots."""

    __tablename__ = "triage_controls"
    __table_args__ = (UniqueConstraint("record_id", "stage", "round", "held_by"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    record_id: Mapped[int] = mapped_column(ForeignKey("records.id", ondelete="CASCADE"), index=True)
    stage: Mapped[str] = mapped_column(String(5), default="ta")
    round: Mapped[int] = mapped_column(Integer, default=1)
    # who validated the list this control was drawn from (admin mode: the
    # admin; reviewers mode: the reviewer whose votes it would have cast)
    held_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    job_id: Mapped[int | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"))
    confidence: Mapped[float | None] = mapped_column(Float)
    reason: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PdfAnnotation(Base):
    """A highlight on a record's stored PDF, shared across reviewers (visible
    during full-text screening, conflict resolution and extraction). Coordinates
    are normalized (0..1) to the page box so they survive any render scale."""

    __tablename__ = "pdf_annotations"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    record_id: Mapped[int] = mapped_column(
        ForeignKey("records.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    page: Mapped[int] = mapped_column(Integer, default=1)  # 1-based
    # [{x, y, w, h}] normalized rects (one per highlighted text line)
    rects: Mapped[list] = mapped_column(JSON, default=list)
    quote: Mapped[str] = mapped_column(Text, default="")  # the highlighted text
    note: Mapped[str] = mapped_column(Text, default="")   # reviewer's comment
    color: Mapped[str] = mapped_column(String(20), default="yellow")
    imported_from: Mapped[str | None] = mapped_column(String(255))  # sync provenance
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class FullText(Base):
    __tablename__ = "fulltexts"

    id: Mapped[int] = mapped_column(primary_key=True)
    record_id: Mapped[int] = mapped_column(
        ForeignKey("records.id", ondelete="CASCADE"), unique=True
    )
    status: Mapped[str] = mapped_column(
        String(20), default="pending"
    )  # pending | retrieved | not_found | manual
    file_path: Mapped[str] = mapped_column(String(1000), default="")
    filename: Mapped[str] = mapped_column(String(500), default="")
    via: Mapped[str] = mapped_column(String(50), default="")  # unpaywall|europepmc|institution|upload...
    oa_url: Mapped[str] = mapped_column(Text, default="")  # publisher landing for manual retrieval
    error: Mapped[str] = mapped_column(Text, default="")
    size_kb: Mapped[int | None] = mapped_column(Integer)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class FulltextConfig(Base):
    """Per-project full-text retrieval settings (Unpaywall email, institutional
    EZProxy/CAS entries). Institution passwords are stored Fernet-encrypted in
    the JSON, decrypted only when a retrieval runs."""

    __tablename__ = "fulltext_configs"

    id: Mapped[int] = mapped_column(primary_key=True)
    # NULL = global config (institutions/email shared across every project)
    project_id: Mapped[int | None] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), unique=True, nullable=True)
    unpaywall_email: Mapped[str] = mapped_column(String(255), default="")
    # [{name, ezproxy_url, username, password_encrypted, scope, auth_type}]
    institutions: Mapped[list] = mapped_column(JSON, default=list)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class ExtractionConfig(Base):
    """M9: who extracts. n_extractors = 1 (records split between extractors)
    or 2 (each record extracted twice, for comparison)."""
    __tablename__ = "extraction_configs"
    __table_args__ = (UniqueConstraint("project_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    n_extractors: Mapped[int] = mapped_column(Integer, default=1)  # 1 | 2
    extractor_ids: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(20), default="draft")  # draft | active
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ExtractionAssignment(Base):
    __tablename__ = "extraction_assignments"
    __table_args__ = (UniqueConstraint("config_id", "record_id", "user_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    config_id: Mapped[int] = mapped_column(ForeignKey("extraction_configs.id", ondelete="CASCADE"))
    record_id: Mapped[int] = mapped_column(ForeignKey("records.id", ondelete="CASCADE"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))


class AppraisalConfig(Base):
    """Who appraises, with which instrument, and how two assessors are
    reconciled — the appraisal twin of ScreeningConfig.

    `status=draft` is the historical behaviour and stays the default: any
    member may appraise any record, nothing is allocated, no disagreement is
    computed. Activating it is what turns appraisal into a two-assessor process
    with an audit trail, which is what CREST_Triage looks for under
    "safeguards against reviewer error in the assessment process".
    """
    __tablename__ = "appraisal_configs"
    __table_args__ = (UniqueConstraint("project_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"))
    status: Mapped[str] = mapped_column(String(20), default="draft")  # draft | active
    # key into services/appraisal/instruments (built-in or project-declared)
    instrument: Mapped[str] = mapped_column(String(40), default="jbi")
    n_assessors: Mapped[int] = mapped_column(Integer, default=1)  # 1 | 2
    assessor_ids: Mapped[list] = mapped_column(JSON, default=list)
    # what counts as a disagreement: the overall judgement only, or any
    # individual question. Per-question is stricter and much noisier — the
    # choice belongs to the team, not to the app.
    conflict_scope: Mapped[str] = mapped_column(String(20), default="overall")
    # consensus = the assessors settle it · arbiter = a project admin does.
    # Same two modes and the same "arbiter == project admin" rule as
    # ScreeningConfig: a team that has run a dual screening round already
    # knows this setting, and a second mechanism would only be a second thing
    # to learn.
    conflict_resolution: Mapped[str] = mapped_column(
        String(20), default="consensus")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),
                                                 default=utcnow)


class AppraisalInstrument(Base):
    """An appraisal instrument a project declares for itself.

    LitUbik ships JBI and nothing else: embedding a third party's appraisal
    tool is a licensing decision. A team working outside health writes the
    instrument it uses here — checklists keyed by study design, each a list of
    domains and questions, in the same shape as the built-in catalogue.
    """
    __tablename__ = "appraisal_instruments"
    __table_args__ = (UniqueConstraint("project_id", "key"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    uuid: Mapped[str] = mapped_column(String(36), default=new_uuid,
                                      unique=True, index=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"))
    key: Mapped[str] = mapped_column(String(40))  # slug, unique in the project
    label: Mapped[str] = mapped_column(String(255))
    citation: Mapped[str] = mapped_column(Text, default="")
    url: Mapped[str] = mapped_column(String(500), default="")
    # {design_key: {options: "ynu"|"ynun", domains: [{label, questions:[{id,text}]}]}}
    checklists: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),
                                                 default=utcnow)


class ExtractionStudy(Base):
    """One study reported by an article (roadmap chantier 9).

    Every record that enters extraction has at least one — position 0, the
    default, created eagerly by the migration for records already touched and
    lazily otherwise. An article reporting several studies gets one row per
    study, and values, appraisals, consensus and synthesis outcomes are keyed
    by study. The design lives here: it is a property of the study, not of
    the report. `Record.study_design` mirrors the first study's for readers
    that still think per article.
    """
    __tablename__ = "extraction_studies"
    __table_args__ = (UniqueConstraint("record_id", "position",
                                       name="uq_extraction_studies_record_position"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    uuid: Mapped[str] = mapped_column(String(36), default=new_uuid, unique=True,
                                      index=True)
    record_id: Mapped[int] = mapped_column(
        ForeignKey("records.id", ondelete="CASCADE"), index=True)
    label: Mapped[str] = mapped_column(String(120), default="Study 1")
    position: Mapped[int] = mapped_column(Integer, default=0)
    study_design: Mapped[str | None] = mapped_column(String(40))
    design_origin: Mapped[str | None] = mapped_column(String(10))  # human | ai
    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow)


class JbiAppraisal(Base):
    """One assessor's critical appraisal of one study (checklist chosen by the
    study's qualified design). answers = {qid: {answer, comment}}.

    Table name kept from when JBI was the only instrument — the rows are
    instrument-agnostic and `instrument` records which one produced them.
    `record_id` is kept beside `study_id` so per-article queries stay cheap.
    """
    __tablename__ = "jbi_appraisals"
    __table_args__ = (UniqueConstraint("study_id", "user_id",
                                       name="uq_jbi_appraisals_study_user"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    record_id: Mapped[int] = mapped_column(ForeignKey("records.id", ondelete="CASCADE"))
    study_id: Mapped[int] = mapped_column(
        ForeignKey("extraction_studies.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    design: Mapped[str] = mapped_column(String(40))
    # Which instrument the answers belong to. Pre-existing rows are JBI by
    # construction, hence the server_default rather than a data migration.
    instrument: Mapped[str] = mapped_column(String(40), default="jbi",
                                            server_default="jbi")
    answers: Mapped[dict] = mapped_column(JSON, default=dict)
    overall: Mapped[str] = mapped_column(String(20), default="")  # include|exclude|seek_info
    comment: Mapped[str] = mapped_column(Text, default="")
    imported_from: Mapped[str | None] = mapped_column(String(255))  # sync provenance
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class AppraisalConsensus(Base):
    """The appraisal two assessors settled on, kept apart from what each of
    them said — the same separation as Conflict vs Vote.

    Overwriting one assessor's row with the agreed answers would destroy the
    evidence that they disagreed, which is precisely the thing a reader wants
    to see. The aggregates read this row when it exists.
    """
    __tablename__ = "appraisal_consensus"
    __table_args__ = (UniqueConstraint("study_id",
                                       name="uq_appraisal_consensus_study"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    record_id: Mapped[int] = mapped_column(
        ForeignKey("records.id", ondelete="CASCADE"))
    study_id: Mapped[int] = mapped_column(
        ForeignKey("extraction_studies.id", ondelete="CASCADE"), index=True)
    design: Mapped[str] = mapped_column(String(40))
    instrument: Mapped[str] = mapped_column(String(40), default="jbi")
    answers: Mapped[dict] = mapped_column(JSON, default=dict)
    overall: Mapped[str] = mapped_column(String(20), default="")
    comment: Mapped[str] = mapped_column(Text, default="")
    resolved_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    imported_from: Mapped[str | None] = mapped_column(String(255))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class ExtractionColumn(Base):
    __tablename__ = "extraction_columns"

    id: Mapped[int] = mapped_column(primary_key=True)
    uuid: Mapped[str] = mapped_column(String(36), default=new_uuid, unique=True, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(255))
    col_type: Mapped[str] = mapped_column(String(20), default="text")  # text|number|choice|bool|multi
    description: Mapped[str] = mapped_column(Text, default="")
    options: Mapped[list] = mapped_column(JSON, default=list)  # for choice/multi
    is_jbi: Mapped[bool] = mapped_column(Boolean, default=False)
    position: Mapped[int] = mapped_column(Integer, default=0)


class ExtractionValue(Base):
    """user_id: extractor who owns the cell — with double extraction each
    extractor has their own row per (study, column) and the grid compares."""
    __tablename__ = "extraction_values"
    __table_args__ = (UniqueConstraint("study_id", "column_id", "user_id",
                                       name="uq_extraction_values_study_column_user"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    record_id: Mapped[int] = mapped_column(ForeignKey("records.id", ondelete="CASCADE"))
    study_id: Mapped[int] = mapped_column(
        ForeignKey("extraction_studies.id", ondelete="CASCADE"), index=True)
    column_id: Mapped[int] = mapped_column(ForeignKey("extraction_columns.id", ondelete="CASCADE"))
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=True)
    value: Mapped[dict] = mapped_column(JSON, default=dict)  # {"v": <typed value>}
    origin: Mapped[str] = mapped_column(String(10), default="human")  # ai | human
    validated: Mapped[bool] = mapped_column(Boolean, default=False)
    imported_from: Mapped[str | None] = mapped_column(String(255))  # sync provenance
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
