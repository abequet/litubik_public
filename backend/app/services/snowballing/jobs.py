# SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Background job: one snowballing iteration.

Seeds (FT-included records not yet crawled) -> backward + forward crawl via the
public APIs (+ DOIs from the stored PDFs) -> one import of the discovered
articles under a `snowballing r{N}` source -> deduplication against the whole
base -> citation edges remapped onto canonical records -> the next round's T/A
screening auto-configured (same reviewers/rules as the previous round, per user
decision) and started.
"""
from app.core.db import SessionLocal
from app.models import (
    CitationEdge, FullText, Record, ScreeningConfig, SnowballRun, Source,
)
from app.services.connectors.jobs import (
    archive_raw, get_or_create_source, store_import,
)
from app.services.dedup.core import run_dedup
from app.services.ris.parse import normalize_doi, to_ris
from app.services.screening.core import generate_assignments
from app.services.snowballing.core import (
    backward_refs, fetch_abstracts, forward_refs, make_client, union_refs,
    _norm_title,
)
from app.services.snowballing.service import next_round, pending_seed_ids
from app.workers.runner import register_handler


def _ref_key(ref: dict) -> str:
    doi = normalize_doi(ref.get("doi"))
    return f"doi:{doi}" if doi else f"title:{_norm_title(ref.get('title'))}"


def _copy_config(db, project_id: int, stage: str, round_: int) -> ScreeningConfig | None:
    """New round's screening config = copy of the latest existing config for the
    stage (same reviewers/rules, per user decision). None if no previous config."""
    prev = (db.query(ScreeningConfig)
            .filter_by(project_id=project_id, stage=stage)
            .order_by(ScreeningConfig.round.desc()).first())
    if prev is None:
        return None
    existing = (db.query(ScreeningConfig)
                .filter_by(project_id=project_id, stage=stage, round=round_)
                .first())
    if existing is not None:
        return existing
    config = ScreeningConfig(
        project_id=project_id, stage=stage, round=round_,
        n_reviewers=prev.n_reviewers, decision_rule=prev.decision_rule,
        maybe_policy=prev.maybe_policy, ai_enabled=prev.ai_enabled,
        ai_mode=prev.ai_mode, ai_triage=prev.ai_triage,
        ai_batch=prev.ai_batch, ai_reveal=prev.ai_reveal,
        allocation=prev.allocation,
        overlap_pct=prev.overlap_pct,
        conflict_resolution=prev.conflict_resolution,
        reviewer_ids=list(prev.reviewer_ids or []),
        weights=dict(prev.weights) if prev.weights else None,
        lot_size=prev.lot_size,
        arbiter_ids=list(prev.arbiter_ids or []),
        lead_user_id=prev.lead_user_id,
        triage_control_pct=prev.triage_control_pct,
        anonymous=prev.anonymous)
    db.add(config)
    db.flush()
    return config


@register_handler("snowball_run")
def snowball_run_handler(job_id: int, params: dict, progress) -> dict:
    project_id = params["project_id"]
    cap = int(params.get("cap") or 5000)

    with SessionLocal() as db:
        from app.core import demo
        room = demo.sandbox_records_room(db, project_id)
        if room is not None:
            if room == 0:
                raise ValueError(f"Demo projects hold at most {demo.DEMO_MAX_PROJECT_RECORDS} references — this one is full")
            cap = min(cap, demo.DEMO_MAX_IMPORT_RECORDS, room)
        seed_ids = params.get("record_ids") or pending_seed_ids(db, project_id)
        if not seed_ids:
            raise ValueError("No new full-text-included article to snowball — "
                             "finish full-text screening first")
        seeds = (db.query(Record).filter(Record.id.in_(seed_ids),
                                         Record.project_id == project_id)
                 .order_by(Record.id).all())
        if not seeds:
            raise ValueError("None of the requested seeds belongs to this project")
        pdf_paths = {ft.record_id: ft.file_path for ft in
                     db.query(FullText).filter(FullText.record_id.in_(seed_ids))
                     if ft.file_path}
        round_ = next_round(db, project_id)

    # -- crawl each seed -------------------------------------------------------
    per_seed: list[tuple[int, list[dict], list[dict]]] = []
    n_backward = n_forward = 0
    with make_client() as client:
        for i, seed in enumerate(seeds):
            progress(i, len(seeds),
                     f"Snowballing {i + 1}/{len(seeds)}: {seed.title[:60]}...")
            back: list[dict] = []
            fwd: list[dict] = []
            if seed.doi or pdf_paths.get(seed.id):
                back = backward_refs(client, seed.doi or "",
                                     pdf_path=pdf_paths.get(seed.id))
            if seed.doi:
                fwd = forward_refs(client, seed.doi)
            n_backward += len(back)
            n_forward += len(fwd)
            per_seed.append((seed.id, back, fwd))

    progress(len(seeds), len(seeds), "Merging the discovered articles...")
    merged = union_refs([refs for _, b, f in per_seed for refs in (b, f)])
    # drop articles that are themselves seeds (self-references across the pool)
    seed_dois = {normalize_doi(s.doi) for s in seeds if s.doi}
    merged = [r for r in merged if normalize_doi(r.get("doi")) not in seed_dois]
    merged = merged[:cap]

    result = {"round": round_, "n_seeds": len(seeds), "n_backward": n_backward,
              "n_forward": n_forward, "n_discovered": len(merged)}

    key_to_record: dict[str, int] = {}
    n_new_unique = 0
    if merged:
        # abstracts so the next T/A screening round has something to screen on.
        # Only the fast API tiers here (OpenAlex/S2/PubMed): the Playwright
        # publisher-scrape tier is sequential (~30 s/page) and would freeze the
        # run for many minutes with no feedback. The remaining abstracts are
        # backfilled afterwards by the `abstract_enrich` job (visible progress
        # + banner), which is the designed path for the withheld-abstract
        # publishers.
        progress(len(seeds), len(seeds), "Fetching abstracts...")
        with make_client() as client:
            abstracts = fetch_abstracts(
                client, [r["doi"] for r in merged if r.get("doi")],
                scrape_cap=0,
                progress=lambda msg: progress(len(seeds), len(seeds), msg))
        records_payload = [
            {"doi": r.get("doi"), "title": r.get("title", ""),
             "authors": r.get("authors", []), "year": r.get("year"),
             "journal": "",
             "abstract": abstracts.get(normalize_doi(r.get("doi")) or "", ""),
             "raw": ""}
            for r in merged]
        result["n_abstracts"] = sum(1 for r in records_payload if r["abstract"])
        progress(len(seeds), len(seeds), "Importing and archiving...")
        with SessionLocal() as db:
            filename = archive_raw(project_id, f"snowballing_r{round_}.ris",
                                   to_ris(records_payload).encode("utf-8"))
            source = get_or_create_source(db, project_id, "snowballing",
                                          f"snowballing r{round_}", round_)
            imp = store_import(db, project_id=project_id, source_id=source.id,
                               equation_id=None, filename=filename,
                               records=records_payload,
                               user_id=params.get("user_id"))
            db.flush()
            created = (db.query(Record).filter_by(import_id=imp.id)
                       .order_by(Record.id).all())
            for ref, record in zip(merged, created):
                key_to_record[_ref_key(ref)] = record.id
            db.commit()

        # -- dedup against the whole base --------------------------------------
        def dedup_progress(done: int, total: int):
            progress(done, total, f"Deduplicating ({done}/{total})...")

        with SessionLocal() as db:
            run_dedup(db, project_id, dedup_progress)

        with SessionLocal() as db:
            created = {r.id: r for r in db.query(Record).filter(
                Record.id.in_(list(key_to_record.values())))}
            n_new_unique = sum(1 for r in created.values()
                               if r.dedup_status == "unique")

            # -- citation edges on canonical records ---------------------------
            def canon(rid: int) -> int:
                r = created.get(rid)
                if r is not None and r.dedup_status == "duplicate" and r.canonical_id:
                    return r.canonical_id
                return rid

            existing_pairs = {(e.citing_record_id, e.cited_record_id)
                              for e in db.query(CitationEdge)
                              .filter_by(project_id=project_id)}
            n_edges = 0
            for seed_id, back, fwd in per_seed:
                for direction, refs in (("backward", back), ("forward", fwd)):
                    for ref in refs:
                        target = key_to_record.get(_ref_key(ref))
                        if target is None:  # dropped (seed self-ref / cap)
                            continue
                        other = canon(target)
                        pair = ((seed_id, other) if direction == "backward"
                                else (other, seed_id))
                        if pair[0] == pair[1] or pair in existing_pairs:
                            continue
                        existing_pairs.add(pair)
                        db.add(CitationEdge(
                            project_id=project_id, citing_record_id=pair[0],
                            cited_record_id=pair[1], direction=direction,
                            round=round_))
                        n_edges += 1
            db.commit()
            result["n_edges"] = n_edges

        # -- auto-configure the next round's screening -------------------------
        if n_new_unique:
            with SessionLocal() as db:
                ta = _copy_config(db, project_id, "ta", round_)
                if ta is not None and ta.status != "active" and ta.reviewer_ids:
                    generate_assignments(db, ta)
                    ta.status = "active"
                    from datetime import datetime, timezone
                    ta.started_at = datetime.now(timezone.utc)
                    result["ta_round_started"] = True
                _copy_config(db, project_id, "ft", round_)  # draft, started later
                db.commit()

    result["n_new_unique"] = n_new_unique
    with SessionLocal() as db:
        db.add(SnowballRun(
            project_id=project_id, round=round_,
            seed_record_ids=[s.id for s in seeds], n_seeds=len(seeds),
            n_backward=n_backward, n_forward=n_forward,
            n_new_records=len(merged), n_new_unique=n_new_unique))
        db.commit()

    progress(len(seeds), len(seeds), "Done")
    return result


@register_handler("abstract_enrich")
def abstract_enrich_handler(job_id: int, params: dict, progress) -> dict:
    """Backfill missing abstracts (records with a DOI and no abstract) from
    OpenAlex/Semantic Scholar/PubMed, then the publisher pages — the manual,
    whole-project pass of the Snowballing page. The silent per-import pass
    that follows every search or upload lives in connectors/abstracts.py."""
    from app.services.connectors.abstracts import fill_abstracts, missing_abstract_rows
    project_id = params["project_id"]
    with SessionLocal() as db:
        rows = missing_abstract_rows(db, project_id)
    if not rows:
        return {"targets": 0, "filled": 0}
    filled = fill_abstracts(rows, scrape_cap=300, progress=progress)
    return {"targets": len(rows), "filled": filled}
