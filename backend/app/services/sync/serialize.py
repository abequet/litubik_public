# SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Project state <-> plain dicts, keyed for cross-instance exchange.

Every foreign key is rewritten on export: rows are referenced by their `uuid`,
users by their `email`. Import resolves them back to local integer ids through
the maps built as tables are inserted (see snapshot.py for the orchestration).
Jobs never travel; credentials only as passphrase-encrypted blobs (phase 3);
support tickets only inside their author's contribution packages.
"""
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models import (
    AiReveal,
    AiUsage, AppraisalConfig, AppraisalConsensus, AppraisalInstrument,
    Assignment, CertaintyAssessment, ChecklistAnswer, CitationEdge,
    Concept, Conflict,
    CustomDatabase,
    DedupPair,
    Equation, EquationCount, EquationRecall, ExtractionAssignment, ExtractionColumn,
    ExtractionConfig,
    ExtractionValue, FullText, GoldenRef, Import, JbiAppraisal, PdfAnnotation,
    Project, ProjectInvitation, ProjectMember, Protocol, ProtocolDeviation,
    Record, RecordTag,
    ReportSection, ResultsSynthesis, ScreeningConfig, ScreeningLot, SnowballRun, Source,
    SynthesisOutcome, SynthesisPlan, Tag,
    SearchUpdatePlan, SearchUpdateRun,
    User, Vote, WorkSession,
)


def iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


def parse_dt(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def as_utc(dt: datetime | None) -> datetime | None:
    """Comparable form of a stored timestamp. Everything LitUbik writes is
    UTC, but the SQLite driver may hand naive datetimes back — comparing one
    with an aware package timestamp would raise."""
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

class ExportContext:
    """Lookup maps local-id -> portable key, built once per export."""

    def __init__(self, db: Session, project: Project):
        self.db = db
        self.project = project
        self.emails: dict[int, str] = {
            u.id: u.email for u in db.query(User).all()}
        self.record_uuids: dict[int, str] = {
            r.id: r.uuid for r in db.query(Record.id, Record.uuid)
            .filter(Record.project_id == project.id)}

    def email(self, user_id: int | None) -> str | None:
        return self.emails.get(user_id) if user_id else None

    def record(self, record_id: int | None) -> str | None:
        return self.record_uuids.get(record_id) if record_id else None


def serialize_project(db: Session, project: Project) -> dict:
    """The complete project state as one JSON-ready dict."""
    ctx = ExportContext(db, project)
    pid = project.id

    members = [
        {"email": u.email, "display_name": u.display_name, "role": m.role,
         "status": "member"}
        for m, u in db.query(ProjectMember, User)
        .join(User, User.id == ProjectMember.user_id)
        .filter(ProjectMember.project_id == pid)
    ] + [
        {"email": i.email, "display_name": "", "role": i.role,
         "status": "invited"}
        for i in db.query(ProjectInvitation).filter_by(project_id=pid)
    ]

    protocols = [
        {"uuid": p.uuid, "version": p.version,
         "source_filename": p.source_filename, "source_text": p.source_text,
         "generated_with": p.generated_with, "protocol_md": p.protocol_md,
         "criteria": p.criteria, "validated_at": iso(p.validated_at),
         "created_at": iso(p.created_at)}
        for p in db.query(Protocol).filter_by(project_id=pid)
    ]

    concepts = [
        {"uuid": c.uuid, "name": c.name, "description": c.description,
         "keywords": c.keywords, "position": c.position}
        for c in db.query(Concept).filter_by(project_id=pid)
    ]

    custom_databases = [
        {"uuid": c.uuid, "db_id": c.db_id, "label": c.label, "syntax": c.syntax,
         "instructions": c.instructions, "url": c.url,
         "created_at": iso(c.created_at)}
        for c in db.query(CustomDatabase).filter_by(project_id=pid)
    ]

    equations = []
    for e in db.query(Equation).filter_by(project_id=pid):
        counts = [
            {"database_name": c.database_name, "count": c.count,
             "method": c.method, "noted_at": iso(c.noted_at)}
            for c in db.query(EquationCount).filter_by(equation_id=e.id)
        ]
        recalls = [
            {"database_name": r.database_name, "method": r.method,
             "total": r.total, "found": r.found, "missing": r.missing,
             "checked_at": iso(r.checked_at)}
            for r in db.query(EquationRecall).filter_by(equation_id=e.id)
        ]
        equations.append(
            {"uuid": e.uuid, "label": e.label, "mode": e.mode,
             "structure": e.structure,
             "translations": e.translations, "params": e.params,
             "status": e.status, "frozen_at": iso(e.frozen_at),
             "golden_results": e.golden_results,
             "created_at": iso(e.created_at), "counts": counts,
             "recalls": recalls})
    equation_uuids = {e.id: e.uuid
                      for e in db.query(Equation).filter_by(project_id=pid)}

    golden_refs = [
        {"uuid": g.uuid, "doi": g.doi, "pmid": g.pmid, "title": g.title,
         "year": g.year, "apa": g.apa, "added_at": iso(g.added_at)}
        for g in db.query(GoldenRef).filter_by(project_id=pid)
    ]

    sources = [
        {"uuid": s.uuid, "type": s.type, "name": s.name, "round": s.round}
        for s in db.query(Source).filter_by(project_id=pid)
    ]
    source_uuids = {s.id: s.uuid
                    for s in db.query(Source).filter_by(project_id=pid)}

    imports = [
        {"uuid": i.uuid, "source": source_uuids.get(i.source_id),
         "equation": equation_uuids.get(i.equation_id),
         "filename": i.filename, "n_records": i.n_records,
         "imported_by": ctx.email(i.imported_by),
         "imported_at": iso(i.imported_at),
         "searched_at": iso(i.searched_at), "declared_hits": i.declared_hits,
         "date_restricted": i.date_restricted,
         "discipline_restricted": i.discipline_restricted,
         "disciplines": i.disciplines,
         "doc_type_restricted": i.doc_type_restricted,
         "doc_types": i.doc_types, "search_fields": i.search_fields}
        for i in db.query(Import).filter_by(project_id=pid)
    ]
    import_uuids = {i.id: i.uuid
                    for i in db.query(Import).filter_by(project_id=pid)}

    records = [
        {"uuid": r.uuid, "import": import_uuids.get(r.import_id),
         "doi": r.doi, "pmid": r.pmid, "title": r.title, "authors": r.authors,
         "year": r.year, "journal": r.journal, "abstract": r.abstract,
         "raw_ris": r.raw_ris, "canonical": ctx.record(r.canonical_id),
         "dedup_status": r.dedup_status, "study_design": r.study_design,
         "design_origin": r.design_origin,
         "abstract_original": r.abstract_original,
         "abstract_edited_by": ctx.email(r.abstract_edited_by),
         "abstract_edited_at": iso(r.abstract_edited_at),
         # cached AI translations travel: a satellite does not pay again
         "translations": r.translations}
        for r in db.query(Record).filter_by(project_id=pid)
    ]

    dedup_pairs = [
        {"record": ctx.record(d.record_id),
         "canonical": ctx.record(d.canonical_id), "score": d.score,
         "reason": d.reason, "status": d.status,
         "created_at": iso(d.created_at),
         "resolved_by": ctx.email(d.resolved_by),
         "resolved_at": iso(d.resolved_at)}
        for d in db.query(DedupPair).filter_by(project_id=pid)
    ]

    citation_edges = [
        {"citing": ctx.record(c.citing_record_id),
         "cited": ctx.record(c.cited_record_id),
         "direction": c.direction, "round": c.round,
         "created_at": iso(c.created_at)}
        for c in db.query(CitationEdge).filter_by(project_id=pid)
    ]

    snowball_runs = [
        {"uuid": s.uuid, "round": s.round,
         "seed_record_uuids": [ctx.record(rid) for rid in
                               (s.seed_record_ids or []) if ctx.record(rid)],
         "n_seeds": s.n_seeds, "n_backward": s.n_backward,
         "n_forward": s.n_forward, "n_new_records": s.n_new_records,
         "n_new_unique": s.n_new_unique, "created_at": iso(s.created_at)}
        for s in db.query(SnowballRun).filter_by(project_id=pid)
    ]

    # living review (chantier 5): the update passes own their rounds like
    # snowball_runs; the plan is project configuration (coordinator-side)
    search_update_runs = [
        {"uuid": r.uuid, "round": r.round, "databases": r.databases or [],
         "since_at": iso(r.since_at), "n_fetched": r.n_fetched,
         "n_new_unique": r.n_new_unique, "triggered_by": r.triggered_by,
         "errors": r.errors or {}, "created_by": ctx.email(r.created_by),
         "started_at": iso(r.started_at), "finished_at": iso(r.finished_at)}
        for r in db.query(SearchUpdateRun).filter_by(project_id=pid)
    ]
    plan_row = db.query(SearchUpdatePlan).filter_by(project_id=pid).first()
    search_update_plan = ({
        "uuid": plan_row.uuid, "enabled": plan_row.enabled,
        "interval_days": plan_row.interval_days,
        "databases": plan_row.databases or [],
        "equation": next((e.uuid for e in db.query(Equation)
                          .filter_by(id=plan_row.equation_id)), None)
        if plan_row.equation_id else None,
        "last_run_at": iso(plan_row.last_run_at),
        "next_run_at": iso(plan_row.next_run_at),
        "created_by": ctx.email(plan_row.created_by)}
        if plan_row is not None else None)

    screening_configs = [
        {"uuid": c.uuid, "stage": c.stage, "round": c.round,
         "n_reviewers": c.n_reviewers, "decision_rule": c.decision_rule,
         "maybe_policy": c.maybe_policy, "ai_enabled": c.ai_enabled,
         "ai_mode": c.ai_mode, "ai_triage": c.ai_triage,
         "ai_batch": c.ai_batch, "ai_reveal": c.ai_reveal,
         "allocation": c.allocation,
         "overlap_pct": c.overlap_pct,
         "conflict_resolution": c.conflict_resolution,
         "reviewer_emails": [ctx.email(uid) for uid in
                             (c.reviewer_ids or []) if ctx.email(uid)],
         # lots (R2a): shares keyed by e-mail, lot size, named arbiters
         "weights": {ctx.email(int(uid)): pct for uid, pct in
                     (c.weights or {}).items()
                     if str(uid).isdigit() and ctx.email(int(uid))} or None,
         "lot_size": c.lot_size,
         "arbiter_emails": [ctx.email(uid) for uid in
                            (c.arbiter_ids or []) if ctx.email(uid)],
         "lead_email": ctx.email(c.lead_user_id) if c.lead_user_id else None,
         "triage_control_pct": c.triage_control_pct,
         "anonymous": bool(c.anonymous),
         "status": c.status, "started_at": iso(c.started_at),
         "created_at": iso(c.created_at)}
        for c in db.query(ScreeningConfig).filter_by(project_id=pid)
    ]
    config_uuids = {c.id: c.uuid for c in
                    db.query(ScreeningConfig).filter_by(project_id=pid)}

    screening_lots = [
        {"uuid": lot.uuid, "config": config_uuids.get(lot.config_id),
         "index": lot.index,
         "emails": [ctx.email(uid) for uid in (lot.user_ids or [])
                    if ctx.email(uid)],
         "due_at": iso(lot.due_at), "status": lot.status,
         "created_at": iso(lot.created_at)}
        for lot in db.query(ScreeningLot)
        .join(ScreeningConfig, ScreeningConfig.id == ScreeningLot.config_id)
        .filter(ScreeningConfig.project_id == pid)
    ]
    lot_uuid_by_id = {lot.id: lot.uuid for lot in db.query(ScreeningLot)
                      .join(ScreeningConfig,
                            ScreeningConfig.id == ScreeningLot.config_id)
                      .filter(ScreeningConfig.project_id == pid)}

    assignments = [
        {"config": config_uuids.get(a.config_id),
         "record": ctx.record(a.record_id), "email": ctx.email(a.user_id),
         "lot": lot_uuid_by_id.get(a.lot_id) if a.lot_id else None,
         "skipped_at": iso(a.skipped_at)}
        for a in db.query(Assignment)
        .join(ScreeningConfig, ScreeningConfig.id == Assignment.config_id)
        .filter(ScreeningConfig.project_id == pid)
    ]

    votes = [
        {"record": ctx.record(v.record_id), "stage": v.stage,
         "round": v.round, "email": ctx.email(v.voter_user_id),
         "is_ai": v.is_ai, "decision": v.decision, "reasons": v.reasons,
         "justification": v.justification, "criteria_eval": v.criteria_eval,
         "confidence": v.confidence, "generated_by": v.generated_by,
         "imported_from": v.imported_from,
         "created_at": iso(v.created_at), "updated_at": iso(v.updated_at)}
        for v in db.query(Vote).filter_by(project_id=pid)
    ]

    ai_reveals = [
        {"record": ctx.record(r.record_id), "stage": r.stage, "round": r.round,
         "email": ctx.email(r.user_id), "revealed_at": iso(r.revealed_at),
         "imported_from": r.imported_from}
        for r in db.query(AiReveal).filter_by(project_id=pid)
    ]

    # reviewer work time (chantier 14): stage + duration, nothing else
    work_sessions = [
        {"uuid": s.uuid, "email": ctx.email(s.user_id), "stage": s.stage,
         "started_at": iso(s.started_at), "last_seen_at": iso(s.last_seen_at),
         "n_heartbeats": s.n_heartbeats, "instance_id": s.instance_id,
         "imported_from": s.imported_from}
        for s in db.query(WorkSession).filter_by(project_id=pid)
    ]

    conflicts = [
        {"record": ctx.record(c.record_id), "stage": c.stage,
         "round": c.round, "status": c.status, "resolution": c.resolution,
         "resolution_note": c.resolution_note, "origin": c.origin,
         "reasons": c.reasons, "resolved_by": ctx.email(c.resolved_by),
         "resolved_at": iso(c.resolved_at)}
        for c in db.query(Conflict).filter_by(project_id=pid)
    ]

    fulltexts = [
        {"record": ctx.record(f.record_id), "status": f.status,
         "filename": f.filename, "via": f.via, "oa_url": f.oa_url,
         "error": f.error, "size_kb": f.size_kb,
         "updated_at": iso(f.updated_at),
         "has_file": bool(f.file_path)}
        for f in db.query(FullText)
        .join(Record, Record.id == FullText.record_id)
        .filter(Record.project_id == pid)
    ]

    extraction_columns = [
        {"uuid": c.uuid, "name": c.name, "col_type": c.col_type,
         "description": c.description, "options": c.options,
         "is_jbi": c.is_jbi, "position": c.position}
        for c in db.query(ExtractionColumn).filter_by(project_id=pid)
    ]
    column_uuids = {c.id: c.uuid for c in
                    db.query(ExtractionColumn).filter_by(project_id=pid)}

    xconfig = db.query(ExtractionConfig).filter_by(project_id=pid).first()
    extraction_config = None
    extraction_assignments: list[dict] = []
    if xconfig:
        extraction_config = {
            "n_extractors": xconfig.n_extractors,
            "extractor_emails": [ctx.email(uid) for uid in
                                 (xconfig.extractor_ids or [])
                                 if ctx.email(uid)],
            "status": xconfig.status, "started_at": iso(xconfig.started_at),
            "created_at": iso(xconfig.created_at)}
        extraction_assignments = [
            {"record": ctx.record(a.record_id), "email": ctx.email(a.user_id)}
            for a in db.query(ExtractionAssignment)
            .filter_by(config_id=xconfig.id)
        ]

    # chantier 9: the studies each article reports — addressed by uuid, and
    # by (record, position) as a fallback so a default study created on two
    # instances independently still lands on the same row
    from app.models import ExtractionStudy
    study_rows = (db.query(ExtractionStudy)
                  .join(Record, Record.id == ExtractionStudy.record_id)
                  .filter(Record.project_id == pid).all())
    extraction_studies = [
        {"uuid": s.uuid, "record": ctx.record(s.record_id),
         "position": s.position, "label": s.label,
         "study_design": s.study_design, "design_origin": s.design_origin,
         "created_by": ctx.email(s.created_by), "created_at": iso(s.created_at)}
        for s in study_rows
    ]
    study_ref = {s.id: (s.uuid, s.position) for s in study_rows}

    def study_fields(study_id: int | None) -> dict:
        uuid, position = study_ref.get(study_id, (None, 0))
        return {"study": uuid, "study_position": position}

    extraction_values = [
        {"record": ctx.record(v.record_id),
         "column": column_uuids.get(v.column_id),
         "email": ctx.email(v.user_id), "value": v.value,
         "origin": v.origin, "validated": v.validated,
         "imported_from": v.imported_from,
         "updated_at": iso(v.updated_at), **study_fields(v.study_id)}
        for v in db.query(ExtractionValue)
        .join(Record, Record.id == ExtractionValue.record_id)
        .filter(Record.project_id == pid)
    ]

    jbi_appraisals = [
        {"record": ctx.record(j.record_id), "email": ctx.email(j.user_id),
         "design": j.design, "instrument": j.instrument,
         "answers": j.answers, "overall": j.overall,
         "comment": j.comment, "imported_from": j.imported_from,
         "updated_at": iso(j.updated_at), **study_fields(j.study_id)}
        for j in db.query(JbiAppraisal)
        .join(Record, Record.id == JbiAppraisal.record_id)
        .filter(Record.project_id == pid)
    ]

    # Structural: which instrument the project appraises with, whether two
    # assessors are required, and the instruments it declared for itself. A
    # satellite must appraise under the coordinator's rules, not its own.
    acfg = db.query(AppraisalConfig).filter_by(project_id=pid).first()
    appraisal_config = None if acfg is None else {
        "status": acfg.status, "instrument": acfg.instrument,
        "n_assessors": acfg.n_assessors,
        "assessor_emails": [e for e in (ctx.email(uid) for uid
                                        in (acfg.assessor_ids or [])) if e],
        "conflict_scope": acfg.conflict_scope,
        "conflict_resolution": acfg.conflict_resolution,
        "started_at": iso(acfg.started_at), "created_at": iso(acfg.created_at)}

    appraisal_instruments = [
        {"uuid": i.uuid, "key": i.key, "label": i.label,
         "citation": i.citation, "url": i.url, "checklists": i.checklists,
         "created_at": iso(i.created_at)}
        for i in db.query(AppraisalInstrument).filter_by(project_id=pid)
    ]

    appraisal_consensus = [
        {"record": ctx.record(c.record_id), "design": c.design,
         "instrument": c.instrument, "answers": c.answers,
         "overall": c.overall, "comment": c.comment,
         "resolved_by": ctx.email(c.resolved_by),
         "resolved_at": iso(c.resolved_at),
         "imported_from": c.imported_from, "updated_at": iso(c.updated_at),
         **study_fields(c.study_id)}
        for c in db.query(AppraisalConsensus).filter_by(project_id=pid)
    ]

    # Structural: what the review declares it synthesised and how. A satellite
    # reports the coordinator's synthesis, not one of its own.
    splan = db.query(SynthesisPlan).filter_by(project_id=pid).first()
    synthesis_plan = None if splan is None else {
        "enabled": splan.enabled,
        "certainty_framework": splan.certainty_framework,
        "grouping_md": splan.grouping_md,
        "grouping_changes_md": splan.grouping_changes_md,
        "prioritisation_md": splan.prioritisation_md,
        "heterogeneity_md": splan.heterogeneity_md,
        "presentation_md": splan.presentation_md,
        "limitations_md": splan.limitations_md,
        "updated_at": iso(splan.updated_at)}

    rec_of = {s.id: s.record_id for s in study_rows}
    synthesis_outcomes = []
    for o in db.query(SynthesisOutcome).filter_by(project_id=pid):
        assessments = [
            {"email": ctx.email(c.user_id), "is_consensus": c.is_consensus,
             "starting_point": c.starting_point,
             "starting_rationale": c.starting_rationale,
             "domains": c.domains, "upgrades": c.upgrades, "final": c.final,
             "statement_md": c.statement_md,
             "resolved_by": ctx.email(c.resolved_by),
             "imported_from": c.imported_from,
             "updated_at": iso(c.updated_at)}
            for c in db.query(CertaintyAssessment).filter_by(outcome_id=o.id)
        ]
        synthesis_outcomes.append({
            "uuid": o.uuid, "label": o.label, "comparison": o.comparison,
            "position": o.position, "intent": o.intent, "target": o.target,
            "thresholds_md": o.thresholds_md, "direction": o.direction,
            "metric": o.metric, "metric_rationale": o.metric_rationale,
            "synthesis_method": o.synthesis_method,
            "method_rationale": o.method_rationale,
            # contributing studies travel by study uuid (chantier 9), with
            # the (record, position) pair as fallback address
            "studies": [{"study": study_ref[sid][0], "record": ctx.record(rec_of[sid]),
                         "study_position": study_ref[sid][1]}
                        for sid in (o.study_ids or []) if sid in study_ref],
            "finding_md": o.finding_md,
            # the column mapping travels by column uuid (chantier 10)
            "effect_spec": ({"measure": (o.effect_spec or {}).get("measure"),
                             "mapping": {role: column_uuids.get(cid)
                                         for role, cid in
                                         ((o.effect_spec or {}).get("mapping") or {}).items()
                                         if column_uuids.get(cid)}}
                            if (o.effect_spec or {}).get("measure") else {}),
            "created_at": iso(o.created_at),
            "updated_at": iso(o.updated_at),
            "certainty_assessments": assessments,
        })

    # Structural: an amendment is a fact about the review, and a satellite
    # must report the same ones as the coordinator.
    protocol_deviations = [
        {"uuid": d.uuid, "stage": d.stage, "kind": d.kind, "signal": d.signal,
         "summary": d.summary, "rationale": d.rationale,
         "occurred_at": iso(d.occurred_at),
         "declared_by": ctx.email(d.declared_by),
         "dismissed_at": iso(d.dismissed_at), "dismiss_note": d.dismiss_note,
         "created_at": iso(d.created_at), "updated_at": iso(d.updated_at)}
        for d in db.query(ProtocolDeviation).filter_by(project_id=pid)
    ]

    pdf_annotations = [
        {"record": ctx.record(a.record_id), "email": ctx.email(a.user_id),
         "page": a.page, "rects": a.rects, "quote": a.quote, "note": a.note,
         "color": a.color, "imported_from": a.imported_from,
         "created_at": iso(a.created_at),
         "updated_at": iso(a.updated_at)}
        for a in db.query(PdfAnnotation).filter_by(project_id=pid)
    ]

    tags = [
        {"name": t.name, "created_by": ctx.email(t.created_by),
         "created_at": iso(t.created_at)}
        for t in db.query(Tag).filter_by(project_id=pid)
    ]
    tag_names = {t.id: t.name for t in db.query(Tag).filter_by(project_id=pid)}
    record_tags = [
        {"tag": tag_names.get(rt.tag_id), "record": ctx.record(rt.record_id),
         "created_by": ctx.email(rt.created_by),
         "created_at": iso(rt.created_at)}
        for rt in db.query(RecordTag)
        .join(Tag, Tag.id == RecordTag.tag_id)
        .filter(Tag.project_id == pid)
    ]

    synthesis = db.query(ResultsSynthesis).filter_by(project_id=pid).first()
    results_synthesis = None
    if synthesis:
        results_synthesis = {
            "content_md": synthesis.content_md, "provider": synthesis.provider,
            "model": synthesis.model, "tokens_in": synthesis.tokens_in,
            "tokens_out": synthesis.tokens_out, "cost_usd": synthesis.cost_usd,
            "generated_by": ctx.email(synthesis.generated_by),
            "created_at": iso(synthesis.created_at)}

    # the two manuscript write-ups (Methods, AI disclosure) travel with
    # the project — a satellite must be able to read what the coordinator
    # published about the review, including its AI disclosure.
    report_sections = [
        {"kind": s.kind, "lang": s.lang, "content_md": s.content_md,
         "edited_md": s.edited_md, "form": s.form,
         "provider": s.provider, "model": s.model, "tokens_in": s.tokens_in,
         "tokens_out": s.tokens_out, "cost_usd": s.cost_usd,
         "generated_by": ctx.email(s.generated_by),
         "created_at": iso(s.created_at), "updated_at": iso(s.updated_at)}
        for s in db.query(ReportSection).filter_by(project_id=pid)
    ]
    # the AI-use journal: aggregated per (feature, model, author, day), so the
    # coordinator's disclosure covers what satellites did too
    ai_usage = [
        {"feature": u.feature, "provider": u.provider, "model": u.model,
         "email": ctx.email(u.user_id), "day": u.day, "n_calls": u.n_calls,
         "tokens_in": u.tokens_in, "tokens_out": u.tokens_out,
         "cost_usd": u.cost_usd, "first_at": iso(u.first_at),
         "last_at": iso(u.last_at)}
        for u in db.query(AiUsage).filter_by(project_id=pid)
    ]

    return {
        "project": {
            "uuid": project.uuid, "name": project.name,
            "description": project.description,
            "research_question": project.research_question,
            "review_type": project.review_type,
            "question_framework": project.question_framework,
            "llm_no_fallback": project.llm_no_fallback,
            "databases": project.databases,
            "registry": project.registry,
            "registration_id": project.registration_id,
            "registration_url": project.registration_url,
            "registered_at": iso(project.registered_at),
            "protocol_url": project.protocol_url,
            "highlights": project.highlights,
            "created_at": iso(project.created_at)},
        "members": members,
        "protocols": protocols,
        "concepts": concepts,
        "custom_databases": custom_databases,
        "equations": equations,
        "golden_refs": golden_refs,
        "sources": sources,
        "imports": imports,
        "records": records,
        "dedup_pairs": dedup_pairs,
        "citation_edges": citation_edges,
        "snowball_runs": snowball_runs,
        "search_update_runs": search_update_runs,
        "search_update_plan": search_update_plan,
        "screening_configs": screening_configs,
        "screening_lots": screening_lots,
        "assignments": assignments,
        "votes": votes,
        "ai_reveals": ai_reveals,
        "work_sessions": work_sessions,
        "conflicts": conflicts,
        "fulltexts": fulltexts,
        "extraction_columns": extraction_columns,
        "extraction_config": extraction_config,
        "appraisal_config": appraisal_config,
        "appraisal_instruments": appraisal_instruments,
        "appraisal_consensus": appraisal_consensus,
        "extraction_studies": extraction_studies,
        "synthesis_plan": synthesis_plan,
        "synthesis_outcomes": synthesis_outcomes,
        "protocol_deviations": protocol_deviations,
        "checklist_answers": [
            {"checklist": a.checklist, "item": a.item,
             "page_ref": a.page_ref, "note": a.note,
             "status_override": a.status_override,
             "updated_at": iso(a.updated_at)}
            for a in db.query(ChecklistAnswer).filter_by(project_id=pid)],
        "extraction_assignments": extraction_assignments,
        "extraction_values": extraction_values,
        "jbi_appraisals": jbi_appraisals,
        "pdf_annotations": pdf_annotations,
        "tags": tags,
        "record_tags": record_tags,
        "results_synthesis": results_synthesis,
        "report_sections": report_sections,
        "ai_usage": ai_usage,
    }


def collect_emails(data: dict) -> set[str]:
    """Every email referenced anywhere in a serialized project (used to create
    shadow accounts for people who have no account on the importing instance)."""
    emails: set[str] = set()

    def _add(value):
        if value:
            emails.add(value.lower())

    for m in data.get("members", []):
        _add(m.get("email"))
    for i in data.get("imports", []):
        _add(i.get("imported_by"))
    for r in data.get("records", []):
        _add(r.get("abstract_edited_by"))
    for d in data.get("dedup_pairs", []):
        _add(d.get("resolved_by"))
    for c in data.get("screening_configs", []):
        for e in c.get("reviewer_emails", []):
            _add(e)
        for e in c.get("arbiter_emails", []):
            _add(e)
        for e in (c.get("weights") or {}):
            _add(e)
    for lot in data.get("screening_lots", []):
        for e in lot.get("emails", []):
            _add(e)
    for a in data.get("assignments", []):
        _add(a.get("email"))
    for v in data.get("votes", []):
        _add(v.get("email"))
        _add(v.get("generated_by"))
    for c in data.get("conflicts", []):
        _add(c.get("resolved_by"))
    xc = data.get("extraction_config")
    if xc:
        for e in xc.get("extractor_emails", []):
            _add(e)
    for a in data.get("extraction_assignments", []):
        _add(a.get("email"))
    for v in data.get("extraction_values", []):
        _add(v.get("email"))
    for j in data.get("jbi_appraisals", []):
        _add(j.get("email"))
    for a in data.get("pdf_annotations", []):
        _add(a.get("email"))
    for t in data.get("tags", []):
        _add(t.get("created_by"))
    for rt in data.get("record_tags", []):
        _add(rt.get("created_by"))
    rs = data.get("results_synthesis")
    if rs:
        _add(rs.get("generated_by"))
    for s in data.get("report_sections", []):
        _add(s.get("generated_by"))
    for u in data.get("ai_usage", []):
        _add(u.get("email"))
    return emails
