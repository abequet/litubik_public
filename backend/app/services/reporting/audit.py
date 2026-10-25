# SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The review's own audit trail, assembled as one structured dossier.

Everything here is READ from the tables the pipeline wrote as it ran: which
equation was frozen and when, how many reviewers screened each round under
which allocation rule, the κ actually obtained, which exclusion reasons were
recorded, how the full texts were obtained, how many snowballing iterations
ran. Nothing is typed in, and nothing is inferred.

This is the input of the Methods paragraph: a model asked to write "what was
done" from a dossier of measured facts cannot invent a threshold or a reviewer
count, which is the whole point of generating the paragraph here rather than
in a chat window.
"""
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.version import SOURCE_URL, __version__
from app.models import (
    AppraisalConsensus,
    Conflict,
    CustomDatabase, DedupPair, Equation, ExtractionColumn, ExtractionConfig,
    ExtractionValue, FullText, Import, JbiAppraisal, Project, ProjectMember,
    Protocol, Record, ReportSection, ResultsSynthesis, ScreeningConfig,
    SearchUpdatePlan, SearchUpdateRun, SnowballRun, Source, User,
)
from app.services import framing, registration
from app.services.appraisal import core as appraisal_core
from app.services.synthesis import core as synthesis_core
from app.services.synthesis import grade as grade_catalogue
from app.services.synthesis import methods as synthesis_methods
from app.services.prisma import prisma_counts
from app.services.reporting import deviations as deviations_service
from app.services.screening.anonymity import namer_for
from app.services.screening.core import agreement_stats, screening_outcomes
from app.services.screening.reasons import ft_prisma_outcomes, reason_labels

# dedup is parameterless for the user but not for the report: the Methods
# paragraph has to state the rule that was applied
from app.services.dedup.core import AUTO_THRESHOLD, UNCERTAIN_THRESHOLD

KEYWORD_CAP = 40  # per concept, so a 300-synonym block cannot flood the prompt


def _iso(value) -> str | None:
    return value.isoformat() if value else None


def _names(db: Session, user_ids) -> list[str]:
    if not user_ids:
        return []
    rows = db.query(User.id, User.display_name).filter(User.id.in_(user_ids))
    by_id = dict(rows)
    return [by_id.get(uid, "?") for uid in user_ids]


def _protocol(db: Session, project_id: int) -> dict:
    latest = (db.query(Protocol).filter_by(project_id=project_id)
              .order_by(Protocol.version.desc()).first())
    if latest is None:
        return {"imported": False}
    validated = (db.query(Protocol)
                 .filter(Protocol.project_id == project_id,
                         Protocol.validated_at.isnot(None))
                 .order_by(Protocol.version.desc()).first())
    current = validated or latest
    criteria = current.criteria or []
    return {
        "imported": True,
        "version": current.version,
        "source_filename": current.source_filename,
        "validated": validated is not None,
        "validated_at": _iso(current.validated_at),
        "ai_extracted": bool(current.generated_with),
        "generated_with": current.generated_with,
        # description included: the Methods section reports the criteria as a
        # Criterion/Description table, not as bare labels
        "criteria": [{"code": c.get("code", ""), "type": c.get("type", ""),
                      "label": c.get("label", ""),
                      "description": (c.get("description") or "")[:600]}
                     for c in criteria],
        "n_include": sum(1 for c in criteria if c.get("type") == "include"),
        "n_exclude": sum(1 for c in criteria if c.get("type") == "exclude"),
    }


def _search(db: Session, project_id: int) -> dict:
    equations = []
    for eq in (db.query(Equation).filter_by(project_id=project_id)
               .order_by(Equation.id)):
        structure = eq.structure or {}
        concepts = [
            {"name": c.get("name", ""),
             "keywords": [str(k) for k in (c.get("keywords") or [])][:KEYWORD_CAP],
             "n_keywords": len(c.get("keywords") or [])}
            for c in (structure.get("concepts") or [])]
        golden = eq.golden_results or {}
        # the query as actually run: a hand-edited override supersedes the
        # generated translation, and the manuscript must quote what was run
        translations = eq.translations or {}
        effective = dict(translations.get("auto") or {})
        effective.update({db_id: q for db_id, q
                          in (translations.get("overrides") or {}).items() if q})
        from app.services.equations.recall import latest_per_database
        equations.append({
            "label": eq.label,
            "mode": eq.mode,
            "status": eq.status,
            "frozen_at": _iso(eq.frozen_at),
            # golden-set recall per database, latest check each (the
            # protocol's acceptance test of the equation)
            "recall": [{"database": r.database_name, "method": r.method,
                        "found": r.found, "total": r.total,
                        "checked_at": _iso(r.checked_at)}
                       for r in latest_per_database(eq)],
            "params": eq.params or {},
            "concepts": concepts,
            "queries_per_database": effective,
            "hand_edited_queries": sorted(
                db_id for db_id, q in (translations.get("overrides") or {}).items()
                if q and db_id not in (translations.get("drafts") or {})),
            # queries the AI drafted from another database's text, and which
            # of them no human validated — the manuscript must say so
            "ai_drafted_queries": sorted(translations.get("drafts") or {}),
            "unreviewed_ai_queries": sorted(
                db_id for db_id, info in (translations.get("drafts") or {}).items()
                if not info.get("validated")),
            "counts": [{"database": c.database_name, "n": c.count,
                        "method": c.method, "noted_at": _iso(c.noted_at)}
                       for c in eq.counts],
            "golden": {"total": golden.get("total"), "found": golden.get("found"),
                       "database": golden.get("database"),
                       "checked_at": golden.get("checked_at")} if golden else None,
        })

    imports = []
    for imp, source, equation in (
            db.query(Import, Source, Equation)
            .join(Source, Source.id == Import.source_id)
            .outerjoin(Equation, Equation.id == Import.equation_id)
            .filter(Import.project_id == project_id)
            .order_by(Import.imported_at)):
        imports.append({
            "source": source.name, "type": source.type, "round": source.round,
            "n_records": imp.n_records, "filename": imp.filename,
            "imported_at": _iso(imp.imported_at),
            "searched_at": _iso(imp.searched_at),
            "declared_hits": imp.declared_hits,
            "date_restricted": imp.date_restricted,
            "discipline_restricted": imp.discipline_restricted,
            "disciplines": imp.disciplines or [],
            "doc_type_restricted": imp.doc_type_restricted,
            "doc_types": imp.doc_types or [],
            "search_fields": imp.search_fields or [],
            "equation": equation.label if equation else None,
        })
    # living review: the update passes (each is a round of its own) and the
    # plan, so the Methods draft can state the update dates and cadence
    update_runs = [{
        "round": r.round, "databases": list(r.databases or []),
        "since": _iso(r.since_at), "date": _iso(r.finished_at or r.started_at),
        "n_fetched": r.n_fetched, "n_new_unique": r.n_new_unique,
        "triggered_by": r.triggered_by,
    } for r in (db.query(SearchUpdateRun).filter_by(project_id=project_id)
                .order_by(SearchUpdateRun.round))]
    plan = db.query(SearchUpdatePlan).filter_by(project_id=project_id).first()
    return {
        "equations": equations,
        "frozen_equation": next((e["label"] for e in equations
                                 if e["status"] == "frozen"), None),
        "imports": imports,
        "living_review": {
            "update_passes": update_runs,
            "n_passes": len(update_runs),
            "plan": ({"enabled": plan.enabled, "interval_days": plan.interval_days,
                      "databases": list(plan.databases or [])}
                     if plan is not None else None),
            "method": ("living review: the frozen equation is re-run on the "
                       "API databases, restricted to records indexed since the "
                       "previous pass; each pass is deduplicated against the "
                       "corpus and screened as a round of its own, under the "
                       "same rules") if update_runs else None,
        },
        "custom_databases": [{"label": c.label, "syntax": c.syntax}
                             for c in db.query(CustomDatabase)
                             .filter_by(project_id=project_id)],
        "first_import_at": imports[0]["imported_at"] if imports else None,
        "last_import_at": imports[-1]["imported_at"] if imports else None,
    }


def _dedup(db: Session, project_id: int) -> dict:
    by_status = dict(db.query(Record.dedup_status, func.count(Record.id))
                     .filter_by(project_id=project_id)
                     .group_by(Record.dedup_status).all())
    pairs = dict(db.query(DedupPair.status, func.count(DedupPair.id))
                 .filter_by(project_id=project_id)
                 .group_by(DedupPair.status).all())
    return {
        "n_records": sum(by_status.values()),
        "n_duplicates": by_status.get("duplicate", 0),
        "n_unique": by_status.get("unique", 0),
        "n_unresolved": by_status.get("pending", 0) + by_status.get("uncertain", 0),
        "manual_pairs": {"merged": pairs.get("merged", 0),
                         "distinct": pairs.get("distinct", 0),
                         "pending": pairs.get("pending", 0)},
        "method": (f"exact DOI, then normalized title, then fuzzy title "
                   f"(rapidfuzz token_sort_ratio ≥ {AUTO_THRESHOLD:.0f} with a "
                   f"compatible year (±1) and matching first author for an "
                   f"automatic merge; ≥ {UNCERTAIN_THRESHOLD:.0f} queued for "
                   f"manual side-by-side arbitration)"),
    }


def _n_revealed_early(db: Session, config) -> int:
    """Reviewers' deliberate pre-vote reveals in this round that were then
    followed by their vote — the votes made with the suggestion in view."""
    from app.models import AiReveal, Vote
    return (db.query(AiReveal)
            .join(Vote, (Vote.record_id == AiReveal.record_id)
                  & (Vote.stage == AiReveal.stage)
                  & (Vote.round == AiReveal.round)
                  & (Vote.voter_user_id == AiReveal.user_id)
                  & (Vote.is_ai.is_(False)))
            .filter(AiReveal.project_id == config.project_id,
                    AiReveal.stage == config.stage,
                    AiReveal.round == config.round)
            .count())


def _screening(db: Session, project_id: int) -> dict:
    labels = reason_labels(db, project_id, "ft")
    out: dict[str, list] = {"ta": [], "ft": []}
    for config in (db.query(ScreeningConfig).filter_by(project_id=project_id)
                   .order_by(ScreeningConfig.stage, ScreeningConfig.round)):
        active = config.status == "active"
        outcomes = screening_outcomes(db, config) if active else {}
        stats = agreement_stats(db, config) if active else {}
        # the Methods section reports each phase as screened -> included ->
        # excluded -> conflicts -> resolution, so the disagreements count
        conflicts = dict(
            db.query(Conflict.status, func.count(Conflict.id))
            .filter_by(project_id=project_id, stage=config.stage,
                       round=config.round, origin="votes")
            .group_by(Conflict.status).all()) if active else {}
        n_auto_excluded = (
            db.query(func.count(Conflict.id))
            .filter_by(project_id=project_id, stage=config.stage,
                       round=config.round, origin="ai_triage",
                       status="resolved").scalar() or 0) if active else 0
        entry = {
            "round": config.round,
            "status": config.status,
            "started_at": _iso(config.started_at),
            "n_reviewers": len(config.reviewer_ids or []),
            "reviewers": _names(db, config.reviewer_ids or []),
            "allocation": config.allocation,
            "overlap_pct": (config.overlap_pct
                            if config.allocation == "single_overlap" else None),
            # allocation = lead: who screened the whole corpus
            "lead_reviewer": (namer_for(db, config)(config.lead_user_id)
                              if config.allocation == "lead"
                              and config.lead_user_id else None),
            "anonymous": bool(config.anonymous),
            "decision_rule": config.decision_rule,
            "maybe_policy": config.maybe_policy,
            "conflict_resolution": config.conflict_resolution,
            "blinding": "Reviewers cannot see each other's votes before their "
                        "own is cast (enforced server-side)",
            "ai": {"enabled": config.ai_enabled, "mode": config.ai_mode,
                   "triage": config.ai_triage, "batch": config.ai_batch,
                   # when reviewers saw the suggestion: always, or only after
                   # their own vote (with the number who chose to look first)
                   "reveal": config.ai_reveal,
                   "n_revealed_before_vote": _n_revealed_early(db, config)},
            "n_decided": len(outcomes),
            "n_included": sum(1 for d in outcomes.values() if d == "include"),
            "n_excluded": sum(1 for d in outcomes.values() if d == "exclude"),
            "conflicts": {"resolved": conflicts.get("resolved", 0),
                          "still_open": conflicts.get("open", 0)},
            # exclusions that came from validated AI title triage, reported
            # separately (PRISMA 2020 "excluded by automation tools")
            "n_excluded_by_validated_ai_triage": n_auto_excluded,
            "agreement": {"method": stats.get("method"),
                          "kappa": stats.get("kappa"),
                          "percent": stats.get("percent"),
                          "n_double_screened": stats.get("n_records"),
                          # T/A: κ and % computed on "include or maybe"
                          # (goes on to full text) vs "exclude"
                          "maybe_counted_as_include":
                              bool(stats.get("maybe_as_include"))},
        }
        if config.stage == "ft" and config.status == "active":
            ft = ft_prisma_outcomes(db, config)
            entry["excluded_by_reason"] = [
                {"code": r["code"], "label": labels.get(r["code"], r["code"]),
                 "n": r["n"]} for r in ft["by_reason"]]
            entry["n_not_retrieved"] = ft["not_retrieved"]
        out[config.stage].append(entry)
    return out


def _fulltext(db: Session, project_id: int) -> dict:
    rows = (db.query(FullText.status, FullText.via, func.count(FullText.id))
            .join(Record, Record.id == FullText.record_id)
            .filter(Record.project_id == project_id)
            .group_by(FullText.status, FullText.via).all())
    by_status: dict[str, int] = {}
    by_via: dict[str, int] = {}
    for status, via, n in rows:
        by_status[status] = by_status.get(status, 0) + n
        if status in ("retrieved", "manual") and via:
            by_via[via] = by_via.get(via, 0) + n
    return {
        "n_retrieved": by_status.get("retrieved", 0) + by_status.get("manual", 0),
        "n_uploaded_manually": by_status.get("manual", 0),
        "n_not_found": by_status.get("not_found", 0),
        "n_pending": by_status.get("pending", 0),
        "by_route": [{"route": via, "n": n}
                     for via, n in sorted(by_via.items(), key=lambda kv: -kv[1])],
    }


def _snowballing(db: Session, project_id: int) -> dict:
    runs = [{
        "round": r.round, "n_seeds": r.n_seeds, "n_backward": r.n_backward,
        "n_forward": r.n_forward, "n_new_records": r.n_new_records,
        "n_new_unique": r.n_new_unique, "created_at": _iso(r.created_at),
    } for r in (db.query(SnowballRun).filter_by(project_id=project_id)
                .order_by(SnowballRun.round))]
    return {"n_iterations": len(runs), "runs": runs,
            "method": "backward (references) and forward (citations) citation "
                      "searching, seeded by the full-text-included studies; "
                      "each iteration's new records go through the same "
                      "title/abstract and full-text screening rules"}


def _extraction(db: Session, project_id: int) -> dict:
    columns = (db.query(ExtractionColumn).filter_by(project_id=project_id)
               .order_by(ExtractionColumn.position, ExtractionColumn.id).all())
    config = (db.query(ExtractionConfig).filter_by(project_id=project_id)
              .first())
    values = (db.query(ExtractionValue.origin, ExtractionValue.validated,
                       func.count(ExtractionValue.id))
              .join(ExtractionColumn,
                    ExtractionColumn.id == ExtractionValue.column_id)
              .filter(ExtractionColumn.project_id == project_id)
              .group_by(ExtractionValue.origin, ExtractionValue.validated).all())
    n_ai = sum(n for origin, _, n in values if origin == "ai")
    n_ai_validated = sum(n for origin, validated, n in values
                         if origin == "ai" and validated)
    n_human = sum(n for origin, _, n in values if origin != "ai")
    from app.models import ExtractionStudy
    designs = dict(db.query(ExtractionStudy.study_design,
                            func.count(ExtractionStudy.id))
                   .join(Record, Record.id == ExtractionStudy.record_id)
                   .filter(Record.project_id == project_id,
                           ExtractionStudy.study_design.isnot(None))
                   .group_by(ExtractionStudy.study_design).all())
    n_appraised = (db.query(func.count(func.distinct(JbiAppraisal.study_id)))
                   .join(Record, Record.id == JbiAppraisal.record_id)
                   .filter(Record.project_id == project_id).scalar() or 0)
    appraisal = _appraisal(db, project_id, n_appraised, designs)
    return {
        "started": config is not None and config.status == "active",
        "n_extractors": config.n_extractors if config else 0,
        "double_extraction": bool(config and config.n_extractors >= 2),
        "extractors": _names(db, (config.extractor_ids or []) if config else []),
        "n_columns": len(columns),
        "columns": [{"name": c.name, "type": c.col_type} for c in columns],
        "cells": {"human": n_human, "ai_prefilled": n_ai,
                  "ai_prefilled_validated": n_ai_validated},
        # kept under its historical key so nothing downstream breaks; the
        # instrument is no longer necessarily JBI
        "jbi": appraisal,
        "appraisal": appraisal,
    }


def _appraisal(db: Session, project_id: int, n_appraised: int,
               designs: dict) -> dict:
    """How the studies were appraised — CREST_Triage domain 4 reads exactly
    this: which instrument, applied to how many studies, by how many assessors,
    and how their disagreements were settled."""
    config = appraisal_core.config_of(db, project_id)
    inst = appraisal_core.instrument_of(db, project_id)
    n_consensus = (db.query(func.count(AppraisalConsensus.id))
                   .filter_by(project_id=project_id).scalar() or 0)
    dual = appraisal_core.is_dual(config)
    return {
        "n_appraised": n_appraised,
        "designs": [{"design": d, "n": n} for d, n in designs.items()],
        "instrument": inst.label,
        "instrument_citation": inst.citation,
        "instrument_is_builtin": inst.builtin,
        "instrument_description": (
            f"{inst.label}, selected by the study design of each report"),
        "independent_assessors": config.n_assessors if dual else 1,
        "dual_assessment": dual,
        "conflict_scope": config.conflict_scope if dual else None,
        "conflict_resolution": config.conflict_resolution if dual else None,
        "n_resolved_by_consensus": n_consensus,
        # Stated rather than left to inference: an appraisal by a single
        # assessor is a limitation a reader is entitled to know about, and
        # CREST lists it among the problems it looks for.
        "note": ("Each report was appraised independently by "
                 f"{config.n_assessors} assessors; disagreements were settled "
                 f"by {config.conflict_resolution}." if dual else
                 "Reports were appraised by a single assessor; no independent "
                 "duplicate appraisal was performed."),
    }


def _synthesis(db: Session, project_id: int, narrative_generated: bool,
               review_type) -> dict:
    """What the review declared about its own synthesis — SWiM items 1 to 9 —
    and how certain it is of each result.

    The one subtlety worth spelling out: `method_declared` versus
    `method_default`. `ReviewType.synthesis_method` names a plausible method
    for the review *type* ("narrative synthesis (Popay et al., 2006)" for a
    systematic review), and the Methods prompt used to be told to cite it
    verbatim. A team that ran vote counting would then read its own manuscript
    naming a method it never used — which is the self-declared compliance
    editorial triage penalises. So the default is still carried, labelled as a
    default, and the declared methods win wherever they exist.
    """
    plan = synthesis_core.plan_of(db, project_id)
    outcomes = synthesis_core.outcomes_of(db, project_id)
    ratings = synthesis_core.effective_certainty(db, [o.id for o in outcomes])
    declared_methods = [o.synthesis_method for o in outcomes]
    framework = synthesis_core.certainty_framework(plan)
    return {
        "narrative_generated": narrative_generated,
        "declared": synthesis_core.is_enabled(plan),
        # SWiM review-level items (1a, 1b, 4, 5, 7, 9)
        "grouping": plan.grouping_md if plan else "",
        "grouping_changes": plan.grouping_changes_md if plan else "",
        "prioritisation": plan.prioritisation_md if plan else "",
        "heterogeneity": plan.heterogeneity_md if plan else "",
        "presentation": plan.presentation_md if plan else "",
        "limitations": plan.limitations_md if plan else "",
        "methods_declared": sorted({
            synthesis_methods.method(m).label for m in declared_methods}),
        "method_default": review_type.synthesis_method,
        "uses_meta_analysis": synthesis_methods.uses_meta_analysis(
            declared_methods),
        "swim_applies": synthesis_methods.swim_applies(declared_methods),
        "certainty_framework": framework,
        "certainty_framework_label": grade_catalogue.FRAMEWORKS.get(
            framework, {}).get("label", ""),
        "n_outcomes": len(outcomes),
        "n_outcomes_rated": sum(1 for o in outcomes
                                if (r := ratings.get(o.id)) and r.final),
        "outcomes": [{
            "label": o.label,
            "comparison": o.comparison,
            "intent": o.intent,
            "target": o.target,
            "thresholds": o.thresholds_md,
            "metric": o.metric,
            "metric_rationale": o.metric_rationale,
            "synthesis_method": synthesis_methods.method(
                o.synthesis_method).label,
            "question_the_method_answers": synthesis_methods.method(
                o.synthesis_method).question,
            "method_rationale": o.method_rationale,
            "n_contributing_studies": len(o.study_ids or []),
            "certainty": (ratings[o.id].final if o.id in ratings else ""),
            "certainty_statement": (ratings[o.id].statement_md
                                    if o.id in ratings else ""),
        } for o in outcomes],
    }


def review_dossier(db: Session, project_id: int) -> dict:
    """Everything the Methods paragraph is allowed to state, and nothing else."""
    project = db.get(Project, project_id)
    members = (db.query(ProjectMember, User)
               .join(User, User.id == ProjectMember.user_id)
               .filter(ProjectMember.project_id == project_id).all())
    narrative = (db.query(ResultsSynthesis).filter_by(project_id=project_id)
                 .first())
    review_type, framework = framing.resolve(project)
    return {
        "tool": {
            "name": "LitUbik", "version": __version__, "url": SOURCE_URL,
            "description": "an open-source, self-hosted application covering "
                           "the literature review pipeline from the registered "
                           "protocol to the PRISMA 2020 flow diagram",
        },
        "project": {
            "name": project.name if project else "",
            "research_question": (project.research_question or "") if project else "",
            "created_at": _iso(project.created_at) if project else None,
            "team": [{"name": u.display_name, "role": m.role}
                     for m, u in members],
        },
        # What this review claims to be. The Methods draft must take its type,
        # its question framework and its synthesis method from here rather than
        # assume a PICO systematic review with a narrative synthesis.
        "framing": {
            "review_type": review_type.key,
            "review_type_label": review_type.label,
            "review_type_citation": review_type.citation,
            "question_framework": framework.short,
            "question_framework_label": framework.label,
            "question_framework_citation": framework.citation,
            "question_framework_elements": framework.slot_labels(),
            "synthesis_method": review_type.synthesis_method,
            "tooling_note": review_type.tooling_note,
        },
        # PRISMA 24a/24b. `state` distinguishes "not registered" (an answer the
        # manuscript owes its readers) from "undeclared" (nobody said) — the
        # draft must not turn the second into the first.
        "registration": registration.audit_block(project),
        # PRISMA 24c: amendments to what was registered/planned. Only the
        # declared ones travel — a signal nobody answered is a question for the
        # team, not a fact about the review.
        "deviations": deviations_service.audit_block(db, project_id),
        "protocol": _protocol(db, project_id),
        "search": _search(db, project_id),
        "dedup": _dedup(db, project_id),
        "screening": _screening(db, project_id),
        "fulltext": _fulltext(db, project_id),
        "snowballing": _snowballing(db, project_id),
        "extraction": _extraction(db, project_id),
        "synthesis": _synthesis(db, project_id, narrative is not None,
                                review_type),
        "prisma": prisma_counts(db, project_id),
        "reporting_guidelines": review_type.guideline,
    }


def section_state(db: Session, project_id: int, kind: str) -> ReportSection | None:
    return (db.query(ReportSection)
            .filter_by(project_id=project_id, kind=kind).first())
