# SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Protocol, search equations, sources, imports and bibliographic records."""
from datetime import datetime

from sqlalchemy import (
    JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models.accounts import new_uuid, utcnow


class Protocol(Base):
    __tablename__ = "protocols"

    id: Mapped[int] = mapped_column(primary_key=True)
    uuid: Mapped[str] = mapped_column(String(36), default=new_uuid, unique=True, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    version: Mapped[int] = mapped_column(default=1)
    source_filename: Mapped[str] = mapped_column(String(500), default="")
    source_text: Mapped[str] = mapped_column(Text, default="")  # extracted from the upload
    generated_with: Mapped[str] = mapped_column(String(120), default="")  # "provider:model"
    protocol_md: Mapped[str] = mapped_column(Text, default="")
    # [{code: "I1"|"E1"..., type: "include"|"exclude", label, description}]
    criteria: Mapped[list] = mapped_column(JSON, default=list)
    validated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Concept(Base):
    __tablename__ = "concepts"

    id: Mapped[int] = mapped_column(primary_key=True)
    uuid: Mapped[str] = mapped_column(String(36), default=new_uuid, unique=True, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text, default="")
    keywords: Mapped[list] = mapped_column(JSON, default=list)  # ["kw1", "kw2", ...]
    position: Mapped[int] = mapped_column(Integer, default=0)


class Equation(Base):
    __tablename__ = "equations"

    id: Mapped[int] = mapped_column(primary_key=True)
    uuid: Mapped[str] = mapped_column(String(36), default=new_uuid, unique=True, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    label: Mapped[str] = mapped_column(String(255))  # variant name (broad, narrow, ...)
    # concepts = generated from the concept blocks (structure + auto
    # translations); raw = typed by hand, one query per database, kept in
    # translations["overrides"] with an empty structure — a protocol whose
    # equation was built elsewhere is pasted as is, never rebuilt from concepts
    mode: Mapped[str] = mapped_column(String(10), default="concepts",
                                      server_default="concepts")
    structure: Mapped[dict] = mapped_column(JSON, default=dict)  # concepts/keywords tree
    translations: Mapped[dict] = mapped_column(JSON, default=dict)  # {database: query string}
    params: Mapped[dict] = mapped_column(JSON, default=dict)  # years, languages, doc types...
    status: Mapped[str] = mapped_column(String(20), default="draft")  # draft | frozen
    frozen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # latest golden-set check: {checked_at, database, total, found, missing:[doi]}
    golden_results: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    counts: Mapped[list["EquationCount"]] = relationship(cascade="all, delete-orphan")
    recalls: Mapped[list["EquationRecall"]] = relationship(cascade="all, delete-orphan")


class EquationCount(Base):
    __tablename__ = "equation_counts"

    id: Mapped[int] = mapped_column(primary_key=True)
    equation_id: Mapped[int] = mapped_column(ForeignKey("equations.id", ondelete="CASCADE"))
    database_name: Mapped[str] = mapped_column(String(100))
    count: Mapped[int] = mapped_column(Integer)
    method: Mapped[str] = mapped_column(String(20), default="api")  # api | manual
    noted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class EquationRecall(Base):
    """One golden-set check of one equation on one database.

    method = api: the database was asked whether its search for this
    equation retrieves each golden reference (PubMed, OpenAlex, Europe PMC,
    Scopus, WoS). method = import: the golden references were looked up among
    the records imported under that source for this equation — the only check
    possible for a database without an API (EBSCO, TRID, ACM…). A history is
    kept: a protocol reports the recall of every variant on every base."""

    __tablename__ = "equation_recalls"

    id: Mapped[int] = mapped_column(primary_key=True)
    equation_id: Mapped[int] = mapped_column(ForeignKey("equations.id", ondelete="CASCADE"))
    database_name: Mapped[str] = mapped_column(String(100))
    method: Mapped[str] = mapped_column(String(20), default="api")  # api | import
    total: Mapped[int] = mapped_column(Integer, default=0)
    found: Mapped[int] = mapped_column(Integer, default=0)
    # golden refs missed, as {"doi", "pmid", "citation"} dicts
    missing: Mapped[list] = mapped_column(JSON, default=list)
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class CustomDatabase(Base):
    """A bibliographic database declared by a project, on top of the built-in
    registry (`services/equations/translate.DATABASES`).

    Purely assisted-manual: the app shows the translated query (in the syntax
    of `syntax`, an existing registry id or "generic") plus the project's own
    instructions, and the export file is imported under `db_id` — no API
    connector exists for a hand-declared source."""

    __tablename__ = "custom_databases"
    __table_args__ = (UniqueConstraint("project_id", "db_id",
                                       name="uq_custom_db_project_slug"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    uuid: Mapped[str] = mapped_column(String(36), default=new_uuid, unique=True, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    db_id: Mapped[str] = mapped_column(String(50))  # slug: source name + translation key
    label: Mapped[str] = mapped_column(String(120))
    syntax: Mapped[str] = mapped_column(String(30), default="generic")
    instructions: Mapped[str] = mapped_column(Text, default="")
    url: Mapped[str] = mapped_column(String(500), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class GoldenRef(Base):
    """Reference article the final equation is expected to retrieve
    (signal/noise proxy for comparing equation variants)."""

    __tablename__ = "golden_refs"

    id: Mapped[int] = mapped_column(primary_key=True)
    uuid: Mapped[str] = mapped_column(String(36), default=new_uuid, unique=True, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    # a reference is identified by its DOI, its PMID, or both (one is enough:
    # the other is resolved through NCBI when it exists)
    doi: Mapped[str | None] = mapped_column(String(255))
    pmid: Mapped[str | None] = mapped_column(String(20))
    title: Mapped[str] = mapped_column(Text, default="")
    year: Mapped[int | None] = mapped_column(Integer)
    apa: Mapped[str] = mapped_column(Text, default="")  # APA-7 reference from Crossref
    # cached OpenAlex abstract: terminology source for the AI strategy advisor
    abstract: Mapped[str] = mapped_column(Text, default="")
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Source(Base):
    """Where records come from: a database search, a snowballing round, a manual import."""

    __tablename__ = "sources"

    id: Mapped[int] = mapped_column(primary_key=True)
    uuid: Mapped[str] = mapped_column(String(36), default=new_uuid, unique=True, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    type: Mapped[str] = mapped_column(String(20))  # database | snowballing | manual
    name: Mapped[str] = mapped_column(String(100))  # e.g. "PubMed", "WoS", "snowballing r2"
    round: Mapped[int] = mapped_column(Integer, default=1)


class Import(Base):
    __tablename__ = "imports"

    id: Mapped[int] = mapped_column(primary_key=True)
    uuid: Mapped[str] = mapped_column(String(36), default=new_uuid, unique=True, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id", ondelete="CASCADE"))
    equation_id: Mapped[int | None] = mapped_column(ForeignKey("equations.id", ondelete="SET NULL"))
    filename: Mapped[str] = mapped_column(String(500), default="")  # archived raw file
    n_records: Mapped[int] = mapped_column(Integer, default=0)  # persisted for PRISMA
    imported_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    imported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    # PRISMA-S: the day the search was actually run on the database (an export
    # is often uploaded days later) and the hit count the database displayed
    # (an export may be capped, or filtered, below it). Both declared by the
    # uploader; an API fetch sets searched_at itself.
    searched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    declared_hits: Mapped[int | None] = mapped_column(Integer)
    # PRISMA-S limits: whether the date range and the discipline/subject-area
    # restriction of the equation were applied when this search ran. NULL =
    # not declared. An API fetch sets them from the equation's parameters;
    # an uploader declares them with the file.
    date_restricted: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    discipline_restricted: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    # the disciplines / subject areas the search was limited to (free labels
    # typed by the uploader, or the equation's discipline labels for an API
    # fetch); empty when no discipline limit was applied
    disciplines: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # same for document types (free labels, or the equation's doc-type labels)
    doc_type_restricted: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    doc_types: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # PRISMA-S: the fields the query ran on (SEARCH_FIELD_IDS — title,
    # abstract, keywords, fulltext, all); NULL = not declared
    search_fields: Mapped[list | None] = mapped_column(JSON, nullable=True)


class Record(Base):
    __tablename__ = "records"

    id: Mapped[int] = mapped_column(primary_key=True)
    uuid: Mapped[str] = mapped_column(String(36), default=new_uuid, unique=True, index=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    import_id: Mapped[int] = mapped_column(ForeignKey("imports.id", ondelete="CASCADE"))
    doi: Mapped[str | None] = mapped_column(String(255), index=True)
    # PubMed identifier when the export carries one (.nbib, MEDLINE RIS, PubMed
    # fetch): an exact dedup key and what the golden-set recall is checked on
    pmid: Mapped[str | None] = mapped_column(String(20), index=True)
    title: Mapped[str] = mapped_column(Text, default="")
    authors: Mapped[list] = mapped_column(JSON, default=list)
    year: Mapped[int | None] = mapped_column(Integer)
    journal: Mapped[str] = mapped_column(Text, default="")
    abstract: Mapped[str] = mapped_column(Text, default="")
    raw_ris: Mapped[str] = mapped_column(Text, default="")
    # Duplicates point at their canonical record; provenance is merged onto the canonical one.
    canonical_id: Mapped[int | None] = mapped_column(
        ForeignKey("records.id", ondelete="SET NULL"), index=True
    )
    dedup_status: Mapped[str] = mapped_column(
        String(20), default="pending"
    )  # pending | unique | duplicate | uncertain
    # M9: study-design qualification (selects the JBI checklist). Key from
    # services/appraisal/instruments.py DESIGNS; origin = human | ai.
    study_design: Mapped[str | None] = mapped_column(String(40))
    # External-review import: the record entered the pipeline at the extraction
    # stage (already screened elsewhere) — counted in the extraction corpus
    # without any full-text screening round here.
    ft_forced_included: Mapped[bool] = mapped_column(default=False)
    design_origin: Mapped[str | None] = mapped_column(String(10))
    # T21: abstract edits are traced — the imported text is kept once, with
    # who last edited and when (the abstract is the screening's source data)
    abstract_original: Mapped[str | None] = mapped_column(Text)
    abstract_edited_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"))
    abstract_edited_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True))
    # AI reading aid: title+abstract translated per target language, shared by
    # the team so a text is paid for once — {"fr": {hash, same_language,
    # source_language, title, abstract, provider, model, at}}. `hash` ties an
    # entry to the text it was made from: an edited abstract orphans it. Never
    # replaces the abstract (services/translation.py).
    translations: Mapped[dict | None] = mapped_column(JSON)


class SnowballRun(Base):
    """One snowballing iteration: the FT-included seeds crawled and the round of
    records it created. Persisted at job completion (audit + which seeds are done)."""

    __tablename__ = "snowball_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    uuid: Mapped[str] = mapped_column(String(36), default=new_uuid, unique=True, index=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    round: Mapped[int] = mapped_column(Integer)  # round of the created records
    seed_record_ids: Mapped[list] = mapped_column(JSON, default=list)
    n_seeds: Mapped[int] = mapped_column(Integer, default=0)
    n_backward: Mapped[int] = mapped_column(Integer, default=0)
    n_forward: Mapped[int] = mapped_column(Integer, default=0)
    n_new_records: Mapped[int] = mapped_column(Integer, default=0)
    n_new_unique: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class CitationEdge(Base):
    """A citation link discovered by snowballing: citing_record cites
    cited_record. Both endpoints are canonical records (remapped after dedup);
    the graph view renders these."""

    __tablename__ = "citation_edges"
    __table_args__ = (UniqueConstraint("citing_record_id", "cited_record_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    citing_record_id: Mapped[int] = mapped_column(
        ForeignKey("records.id", ondelete="CASCADE"), index=True)
    cited_record_id: Mapped[int] = mapped_column(
        ForeignKey("records.id", ondelete="CASCADE"), index=True)
    direction: Mapped[str] = mapped_column(String(10))  # backward | forward
    round: Mapped[int] = mapped_column(Integer, default=2)  # discovering round
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class DedupPair(Base):
    """An uncertain duplicate candidate awaiting manual arbitration
    (fuzzy score in the uncertainty window), plus the audit of resolutions."""

    __tablename__ = "dedup_pairs"
    __table_args__ = (UniqueConstraint("record_id", "canonical_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    record_id: Mapped[int] = mapped_column(ForeignKey("records.id", ondelete="CASCADE"))
    canonical_id: Mapped[int] = mapped_column(ForeignKey("records.id", ondelete="CASCADE"))
    score: Mapped[float] = mapped_column(Float, default=0.0)
    reason: Mapped[str] = mapped_column(String(50), default="fuzzy_title")
    status: Mapped[str] = mapped_column(String(20), default="pending",
                                        index=True)  # pending | merged | distinct
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    resolved_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
