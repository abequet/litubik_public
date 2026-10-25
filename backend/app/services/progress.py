# SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Where a project stands in the review pipeline.

Feeds the pipeline menu: the first step with outstanding work is highlighted
("you are here"), and the snowballing rounds are listed so the menu can show
them as indented sub-steps (5.1, 5.2, ...) of the screening stages."""
from sqlalchemy.orm import Session

from app.models import (
    Equation, FullText, Import, Protocol, Record, ScreeningConfig, SnowballRun,
)
from app.services.screening.core import eligible_record_ids, screening_outcomes


def _stage_rounds(db: Session, project_id: int, stage: str) -> list[dict]:
    """Every configured round of a stage with its completion state."""
    out = []
    for config in (db.query(ScreeningConfig)
                   .filter_by(project_id=project_id, stage=stage)
                   .order_by(ScreeningConfig.round)):
        eligible = len(eligible_record_ids(db, project_id, stage, config.round))
        decided = (len(screening_outcomes(db, config))
                   if config.status == "active" else 0)
        out.append({
            "round": config.round,
            "status": config.status,
            "eligible": eligible,
            "decided": decided,
            "done": config.status == "active" and eligible > 0
                    and decided >= eligible,
        })
    return out


def project_progress(db: Session, project_id: int) -> dict:
    """{current, done: [step ids], rounds: {ta: [...], ft: [...]}}."""
    has_validated_protocol = (db.query(Protocol)
                              .filter(Protocol.project_id == project_id,
                                      Protocol.validated_at.isnot(None))
                              .count() > 0)
    has_frozen_equation = (db.query(Equation)
                           .filter_by(project_id=project_id, status="frozen")
                           .count() > 0)
    n_imports = db.query(Import).filter_by(project_id=project_id).count()
    n_records = db.query(Record).filter_by(project_id=project_id).count()
    n_undeduped = (db.query(Record)
                   .filter(Record.project_id == project_id,
                           Record.dedup_status.in_(["pending", "uncertain"]))
                   .count())

    ta_rounds = _stage_rounds(db, project_id, "ta")
    ft_rounds = _stage_rounds(db, project_id, "ft")
    ta_done = bool(ta_rounds) and all(r["done"] for r in ta_rounds)
    ft_done = bool(ft_rounds) and all(r["done"] for r in ft_rounds)

    # retrieval: every T/A include has a final full-text status
    ta_included: set[int] = set()
    for config in (db.query(ScreeningConfig)
                   .filter_by(project_id=project_id, stage="ta", status="active")):
        ta_included |= {rid for rid, d in screening_outcomes(db, config).items()
                        if d == "include"}
    retrieval_done = False
    if ta_included:
        settled = (db.query(FullText)
                   .filter(FullText.record_id.in_(ta_included),
                           FullText.status.in_(["retrieved", "manual", "not_found"]))
                   .count())
        retrieval_done = settled >= len(ta_included)

    # snowballing: at least one run and no FT include left to crawl
    runs = db.query(SnowballRun).filter_by(project_id=project_id).count()
    crawled: set[int] = set()
    for run in db.query(SnowballRun).filter_by(project_id=project_id):
        crawled |= set(run.seed_record_ids or [])
    ft_included: set[int] = set()
    for config in (db.query(ScreeningConfig)
                   .filter_by(project_id=project_id, stage="ft", status="active")):
        ft_included |= {rid for rid, d in screening_outcomes(db, config).items()
                        if d == "include"}
    snowballing_done = runs > 0 and not (ft_included - crawled) and ft_done

    # extraction (M9): active and every included record has >= 1 validated cell
    extraction_done = False
    if ft_included:
        from app.models import ExtractionConfig, ExtractionValue
        ext_cfg = (db.query(ExtractionConfig)
                   .filter_by(project_id=project_id, status="active").first())
        if ext_cfg is not None:
            from app.models import ExtractionStudy
            validated_studies = {
                v.study_id for v in db.query(ExtractionValue)
                .filter(ExtractionValue.record_id.in_(ft_included),
                        ExtractionValue.validated.is_(True))}
            studies_of: dict[int, set[int]] = {}
            for s in (db.query(ExtractionStudy)
                      .filter(ExtractionStudy.record_id.in_(ft_included))):
                studies_of.setdefault(s.record_id, set()).add(s.id)
            # an article is extracted when each of its studies has a
            # validated cell (an article with no study row yet has none)
            extraction_done = all(
                studies_of.get(rid) and studies_of[rid] <= validated_studies
                for rid in ft_included)

    # results (M10): the stage's one deliverable is the stored narrative
    # synthesis (the charts are always computed live and have no "done" state)
    from app.models import ResultsSynthesis
    results_done = (db.query(ResultsSynthesis)
                    .filter_by(project_id=project_id).count() > 0)

    # reporting: the stage delivers the Methods paragraph and the AI
    # disclosure statement — done once both exist in some form (generated or
    # written by the author)
    from app.models import ReportSection
    sections = {r.kind for r in db.query(ReportSection)
                .filter_by(project_id=project_id)
                if (r.content_md or r.edited_md)}
    reporting_done = {"methods", "ai_disclosure"} <= sections

    done: list[str] = []
    if has_validated_protocol:
        done.append("protocol")
    if has_frozen_equation:
        done.append("equations")
    if n_imports:
        done.append("search")
    if n_records and not n_undeduped:
        done.append("dedup")
    if ta_done:
        done.append("screening")
    if retrieval_done:
        done.append("fulltext")
    if ft_done:
        done.append("ft-screening")
    if snowballing_done:
        done.append("snowballing")
    if extraction_done:
        done.append("extraction")
    if results_done:
        done.append("results")
    # the PRISMA flow is a live diagram, so "done" can only mean "final": every
    # snowballing iteration has been through full-text screening and no further
    # record can enter the counts
    if snowballing_done:
        done.append("prisma")
    if reporting_done:
        done.append("reporting")

    # current = where the work is. protocol/equations are only "current" before
    # the first import (they can be skipped); from search on, the first
    # incomplete step wins — snowballing rounds legitimately reopen screening.
    if not n_imports:
        current = ("protocol" if not has_validated_protocol
                   else "equations" if not has_frozen_equation else "search")
    else:
        seq = ["dedup", "screening", "fulltext", "ft-screening",
               "snowballing", "extraction", "results", "prisma", "reporting"]
        current = next((s for s in seq if s not in done), "reporting")
    return {
        "current": current,
        "done": done,
        "rounds": {"ta": ta_rounds, "ft": ft_rounds},
    }
