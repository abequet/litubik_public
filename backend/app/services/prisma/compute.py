# SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Live PRISMA 2020 counters.

Principle (plan): numbers are NEVER typed in — always computed from the
tables. Boxes for stages not implemented yet return None so the diagram can
render them greyed; they will fill in as the pipeline modules land
(M5 screening, M6/M7 full text, M9 inclusion).

Two levels are produced:
- the aggregate flow (all rounds folded), used for the 2020 diagram totals —
  the review's final numbers only exist once the snowballing loop is done;
- a per-round breakdown (`rounds`): round 1 = the initial database search,
  rounds >= 2 = one snowballing iteration each, so the flow of every
  iteration stays auditable on its own.
"""
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import (
    Conflict, FullText, Import, Record, ScreeningConfig, Source,
)
from app.services.screening import screening_outcomes
from app.services.screening.reasons import ft_prisma_outcomes, reason_labels


def _auto_excluded_ids(db: Session, project_id: int,
                       rounds: list[int]) -> set[int]:
    """Records excluded through the validated AI title triage (admin mode
    writes an audited ai_triage resolution). PRISMA 2020 reports these under
    an explicit "excluded by automation tools" mention (#12); reviewer-mode
    triage produces ordinary human votes and stays in the reviewer tally."""
    if not rounds:
        return set()
    return {rid for (rid,) in db.query(Conflict.record_id)
            .filter(Conflict.project_id == project_id,
                    Conflict.stage == "ta",
                    Conflict.status == "resolved",
                    Conflict.resolution == "exclude",
                    Conflict.origin == "ai_triage",
                    Conflict.round.in_(rounds))}


def _round_counts(db: Session, project_id: int, round_: int,
                  labels: dict[str, str], kinds: dict[int, dict] | None = None) -> dict:
    """One round's own flow: identified -> dedup -> T/A -> retrieval -> FT."""
    per_source = (
        db.query(Source.type, Source.name, func.count(Record.id))
        .join(Import, Import.source_id == Source.id)
        .join(Record, Record.import_id == Import.id)
        .filter(Record.project_id == project_id, Source.round == round_)
        .group_by(Source.type, Source.name)
        .order_by(Source.name).all()
    )
    sources = [{"source": name, "type": type_, "n": n}
               for type_, name, n in per_source]
    by_status = dict(
        db.query(Record.dedup_status, func.count(Record.id))
        .join(Import, Import.id == Record.import_id)
        .join(Source, Source.id == Import.source_id)
        .filter(Record.project_id == project_id, Source.round == round_)
        .group_by(Record.dedup_status).all()
    )

    ta_excluded = ta_included = ta_excluded_auto = None
    included_ids: list[int] = []
    ta = (db.query(ScreeningConfig)
          .filter_by(project_id=project_id, stage="ta", round=round_,
                     status="active").first())
    if ta is not None:
        outcomes = screening_outcomes(db, ta)
        ta_excluded = sum(1 for d in outcomes.values() if d == "exclude")
        auto_ids = _auto_excluded_ids(db, project_id, [round_])
        ta_excluded_auto = sum(1 for rid, d in outcomes.items()
                               if d == "exclude" and rid in auto_ids)
        included_ids = sorted(rid for rid, d in outcomes.items()
                              if d == "include")
        ta_included = len(included_ids)

    not_retrieved = None
    if included_ids:
        fts = dict(db.query(FullText.status, func.count(FullText.id))
                   .filter(FullText.record_id.in_(included_ids))
                   .group_by(FullText.status).all())
        not_retrieved = fts.get("not_found", 0)

    assessed = excluded = included = None
    by_reason: list[dict] = []
    ft_cfg = (db.query(ScreeningConfig)
              .filter_by(project_id=project_id, stage="ft", round=round_,
                         status="active").first())
    if ft_cfg is not None:
        ft = ft_prisma_outcomes(db, ft_cfg)
        assessed, excluded, included = ft["assessed"], ft["excluded"], ft["included"]
        by_reason = [{"code": r["code"], "label": labels.get(r["code"], r["code"]),
                      "n": r["n"]} for r in ft["by_reason"]]
        if ft["not_retrieved"]:
            not_retrieved = ft["not_retrieved"]

    info = (kinds or {}).get(round_) or {
        "kind": "initial" if round_ == 1 else "snowballing",
        "n": 1 if round_ == 1 else round_ - 1,
        "label": ("Initial search" if round_ == 1
                  else f"Snowballing iteration {round_ - 1}")}
    return {
        "round": round_,
        "label": info["label"],
        "kind": info["kind"],
        "n": info["n"],
        "sources": sources,
        "identified": sum(s["n"] for s in sources),
        "duplicates_removed": by_status.get("duplicate", 0),
        "records_screened": by_status.get("unique", 0),
        "records_excluded": ta_excluded,
        "records_excluded_auto": ta_excluded_auto,
        "reports_sought": ta_included,
        "reports_not_retrieved": not_retrieved,
        "reports_assessed": assessed,
        "reports_excluded": excluded,
        "reports_excluded_by_reason": by_reason,
        "studies_included": included,
    }


def _column_flow(db: Session, ids: set[int], status_by_id: dict[int, str],
                 ta_configs, ft_configs, labels: dict[str, str],
                 auto_ids: set[int]) -> dict:
    """One PRISMA 2020 identification column (via databases / via other
    methods): the full chain restricted to the records of that origin."""
    duplicates = sum(1 for r in ids if status_by_id.get(r) == "duplicate")
    unresolved = sum(1 for r in ids
                     if status_by_id.get(r) in ("pending", "uncertain"))
    screened = sum(1 for r in ids if status_by_id.get(r) == "unique")

    ta_excluded = ta_included = ta_excluded_auto = None
    included_ids: list[int] = []
    if ta_configs:
        ta_excluded = ta_excluded_auto = 0
        included: set[int] = set()
        for ta_config in ta_configs:
            outcomes = screening_outcomes(db, ta_config)
            ta_excluded += sum(1 for rid, d in outcomes.items()
                               if d == "exclude" and rid in ids)
            ta_excluded_auto += sum(1 for rid, d in outcomes.items()
                                    if d == "exclude" and rid in ids
                                    and rid in auto_ids)
            included |= {rid for rid, d in outcomes.items()
                         if d == "include" and rid in ids}
        included_ids = sorted(included)
        ta_included = len(included_ids)

    not_retrieved = None
    if included_ids:
        fts = dict(db.query(FullText.status, func.count(FullText.id))
                   .filter(FullText.record_id.in_(included_ids))
                   .group_by(FullText.status).all())
        not_retrieved = fts.get("not_found", 0)

    assessed = excluded = studies_included = None
    by_reason_out: list[dict] = []
    if ft_configs:
        assessed = excluded = studies_included = 0
        ft_not_retrieved = 0
        by_reason: dict[str, int] = {}
        for ft_config in ft_configs:
            ft = ft_prisma_outcomes(db, ft_config, only=ids)
            assessed += ft["assessed"]
            excluded += ft["excluded"]
            studies_included += ft["included"]
            ft_not_retrieved += ft["not_retrieved"]
            for r in ft["by_reason"]:
                by_reason[r["code"]] = by_reason.get(r["code"], 0) + r["n"]
        by_reason_out = [
            {"code": code, "label": labels.get(code, code), "n": n}
            for code, n in sorted(by_reason.items(), key=lambda kv: -kv[1])]
        if ft_not_retrieved:
            not_retrieved = ft_not_retrieved

    return {
        "identified": len(ids),
        "duplicates_removed": duplicates,
        "dedup_unresolved": unresolved,
        "records_screened": screened,
        "records_excluded": ta_excluded,
        "records_excluded_auto": ta_excluded_auto,
        "reports_sought": ta_included,
        "reports_not_retrieved": not_retrieved,
        "reports_assessed": assessed,
        "reports_excluded": excluded,
        "reports_excluded_by_reason": by_reason_out,
        "studies_included": studies_included,
    }


def prisma_counts(db: Session, project_id: int) -> dict:
    per_source = (
        db.query(Source.type, Source.name, func.count(Record.id))
        .join(Import, Import.source_id == Source.id)
        .join(Record, Record.import_id == Import.id)
        .filter(Record.project_id == project_id)
        .group_by(Source.type, Source.name)
        .order_by(Source.name).all()
    )
    databases = [{"source": name, "n": n}
                 for type_, name, n in per_source if type_ == "database"]
    others = [{"source": name, "n": n}
              for type_, name, n in per_source if type_ != "database"]

    by_status = dict(
        db.query(Record.dedup_status, func.count(Record.id))
        .filter_by(project_id=project_id)
        .group_by(Record.dedup_status).all()
    )
    duplicates = by_status.get("duplicate", 0)
    unresolved = by_status.get("pending", 0) + by_status.get("uncertain", 0)
    screened = by_status.get("unique", 0)

    # title/abstract screening outcomes, aggregated across rounds (snowballing
    # rounds run their own T/A pass; PRISMA counts the union)
    ta_excluded = ta_included = ta_excluded_auto = None
    ta_configs = (db.query(ScreeningConfig)
                  .filter_by(project_id=project_id, stage="ta", status="active")
                  .order_by(ScreeningConfig.round).all())
    auto_ids = _auto_excluded_ids(db, project_id,
                                  [c.round for c in ta_configs])
    included_ids: list[int] = []
    if ta_configs:
        ta_excluded = ta_excluded_auto = 0
        included: set[int] = set()
        for ta_config in ta_configs:
            outcomes = screening_outcomes(db, ta_config)
            ta_excluded += sum(1 for d in outcomes.values() if d == "exclude")
            ta_excluded_auto += sum(1 for rid, d in outcomes.items()
                                    if d == "exclude" and rid in auto_ids)
            included |= {rid for rid, d in outcomes.items() if d == "include"}
        included_ids = sorted(included)
        ta_included = len(included_ids)

    # full-text retrieval among the T/A-included records (M6)
    reports_not_retrieved = None
    if included_ids:
        fts = dict(db.query(FullText.status, func.count(FullText.id))
                   .filter(FullText.record_id.in_(included_ids))
                   .group_by(FullText.status).all())
        reports_not_retrieved = fts.get("not_found", 0)

    # full-text screening outcomes (M7), aggregated across rounds
    reports_assessed = reports_excluded = studies_included = None
    reports_excluded_by_reason: list[dict] = []
    labels = reason_labels(db, project_id, "ft")
    ft_configs = (db.query(ScreeningConfig)
                  .filter_by(project_id=project_id, stage="ft", status="active")
                  .order_by(ScreeningConfig.round).all())
    if ft_configs:
        reports_assessed = reports_excluded = studies_included = 0
        ft_not_retrieved = 0
        by_reason: dict[str, int] = {}
        for ft_config in ft_configs:
            ft = ft_prisma_outcomes(db, ft_config)
            reports_assessed += ft["assessed"]
            reports_excluded += ft["excluded"]
            studies_included += ft["included"]
            ft_not_retrieved += ft["not_retrieved"]
            for r in ft["by_reason"]:
                by_reason[r["code"]] = by_reason.get(r["code"], 0) + r["n"]
        reports_excluded_by_reason = [
            {"code": code, "label": labels.get(code, code), "n": n}
            for code, n in sorted(by_reason.items(), key=lambda kv: -kv[1])]
        # reviewers can flag "full text not retrievable" explicitly; once they do,
        # that supersedes the raw M6 not-found tally
        if ft_not_retrieved:
            reports_not_retrieved = ft_not_retrieved

    # PRISMA 2020 dual identification columns (#15): "via databases and
    # registers" vs "via other methods" (citation searching = snowballing,
    # manual imports). Each column carries the full chain restricted to the
    # records of that origin; the totals above stay the union of both.
    origin_rows = (
        db.query(Record.id, Record.dedup_status, Source.type)
        .join(Import, Import.id == Record.import_id)
        .join(Source, Source.id == Import.source_id)
        .filter(Record.project_id == project_id).all()
    )
    status_by_id = {rid: status for rid, status, _ in origin_rows}
    db_ids = {rid for rid, _, type_ in origin_rows if type_ == "database"}
    other_ids = {rid for rid, _, type_ in origin_rows if type_ != "database"}
    via_databases = _column_flow(db, db_ids, status_by_id,
                                 ta_configs, ft_configs, labels, auto_ids)
    via_other = _column_flow(db, other_ids, status_by_id,
                             ta_configs, ft_configs, labels, auto_ids)
    via_other["sources"] = [
        {"source": name, "type": type_, "n": n}
        for type_, name, n in per_source if type_ != "database"]

    # per-round breakdown: initial search + one entry per snowballing iteration
    rounds_present = sorted({r for (r,) in db.query(Source.round)
                             .filter(Source.project_id == project_id)
                             .distinct().all()})
    # a round is labelled by the run row that owns it (snowballing iteration
    # or search-update pass), not by arithmetic on its number
    from app.services.living.service import round_kinds
    kinds = round_kinds(db, project_id)
    rounds = [_round_counts(db, project_id, r, labels, kinds)
              for r in rounds_present]
    loop_done = bool(rounds) and all(
        r["studies_included"] is not None for r in rounds)

    # PRISMA 2020 tells "reports of included studies" from "studies included":
    # the full-text includes are reports; the studies are what those reports
    # describe (chantier 9 — an article may report several). Until a second
    # study is declared the two numbers coincide.
    reports_included = studies_included
    if studies_included:
        from app.models import ExtractionStudy
        from app.services.snowballing.service import ft_included_ids
        ft_ids = set(ft_included_ids(db, project_id))
        per_record: dict[int, int] = {}
        for s in (db.query(ExtractionStudy)
                  .filter(ExtractionStudy.record_id.in_(ft_ids))) if ft_ids else []:
            per_record[s.record_id] = per_record.get(s.record_id, 0) + 1
        studies_included = sum(max(1, per_record.get(rid, 1)) for rid in ft_ids) \
            if ft_ids else studies_included

    return {
        "identified_databases": databases,
        "n_databases": sum(d["n"] for d in databases),
        "identified_other": others,
        "n_other": sum(d["n"] for d in others),
        "duplicates_removed": duplicates,
        "dedup_unresolved": unresolved,  # pending + uncertain, shown as a warning
        "records_screened": screened,
        "records_excluded": ta_excluded,  # M5 title/abstract screening
        # of which via validated AI title triage — reported as the explicit
        # PRISMA 2020 "excluded by automation tools" mention (#12)
        "records_excluded_auto": ta_excluded_auto,
        "reports_sought": ta_included,    # includes after T/A (M6 retrieves them)
        "reports_not_retrieved": reports_not_retrieved,   # M6 / M7
        "reports_assessed": reports_assessed,        # M7 full-text screening
        "reports_excluded": reports_excluded,        # M7 total content exclusions
        "reports_excluded_by_reason": reports_excluded_by_reason,  # M7 per reason
        "studies_included": studies_included,        # studies the included reports describe
        "reports_included": reports_included,        # M7 includes (all rounds)
        # PRISMA 2020 identification columns: same chain split by origin
        "via_databases": via_databases,
        "via_other": via_other,
        "rounds": rounds,                 # per-iteration detail (initial + snowballing)
        # the review's final tally only stands once every iteration finished FT
        "final_total_ready": loop_done,
    }
