# SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Snowballing orchestration helpers: seed selection, round bookkeeping, status."""
from dataclasses import dataclass

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import (
    CitationEdge, Import, Record, ScreeningConfig, SearchUpdateRun, SnowballRun,
    Source,
)
from app.services.screening.core import screening_outcomes


@dataclass(frozen=True)
class Edge:
    citing_record_id: int
    cited_record_id: int
    direction: str
    round: int


def canonical_edges(db: Session, project_id: int) -> list[Edge]:
    """Citation edges between canonical records. A crawl remaps its edges
    when it creates them, but a record ruled a duplicate later (pair
    arbitration, a dedup re-run) keeps them: follow it to the record kept,
    drop the self-loops this makes and keep the earliest round of a pair."""
    canon = dict(db.query(Record.id, Record.canonical_id).filter(
        Record.project_id == project_id, Record.dedup_status == "duplicate",
        Record.canonical_id.isnot(None)))

    def root(rid: int) -> int:
        seen = set()
        while rid in canon and rid not in seen:
            seen.add(rid)
            rid = canon[rid]
        return rid

    out: dict[tuple[int, int], Edge] = {}
    for e in db.query(CitationEdge).filter_by(project_id=project_id):
        pair = (root(e.citing_record_id), root(e.cited_record_id))
        if pair[0] == pair[1]:
            continue
        if pair not in out or e.round < out[pair].round:
            out[pair] = Edge(pair[0], pair[1], e.direction, e.round)
    return list(out.values())


def ft_included_ids(db: Session, project_id: int) -> list[int]:
    """FT-included records across every round — the snowballing seed pool."""
    included: set[int] = set()
    for config in db.query(ScreeningConfig).filter_by(
            project_id=project_id, stage="ft", status="active"):
        outcomes = screening_outcomes(db, config)
        included |= {rid for rid, d in outcomes.items() if d == "include"}
    return sorted(included)


def crawled_seed_ids(db: Session, project_id: int) -> set[int]:
    seeds: set[int] = set()
    for run in db.query(SnowballRun).filter_by(project_id=project_id):
        seeds |= set(run.seed_record_ids or [])
    return seeds


def pending_seed_ids(db: Session, project_id: int) -> list[int]:
    """FT includes not crawled by a previous iteration (the next run's seeds)."""
    done = crawled_seed_ids(db, project_id)
    return [rid for rid in ft_included_ids(db, project_id) if rid not in done]


def next_round(db: Session, project_id: int) -> int:
    current = (db.query(func.max(Source.round))
               .filter(Source.project_id == project_id).scalar()) or 1
    return current + 1


def delete_iteration_round(db: Session, project_id: int, round_: int) -> None:
    """Completely reverse one snowballing round — as if it never ran.

    Mirrors delete_import's teardown: a bulk record delete lets the DB
    ON DELETE CASCADE clean votes/assignments/conflicts/fulltexts/tags/dedup
    pairs, and we explicitly remove the rows that do NOT cascade from records —
    the round's citation edges (a manual add can link two older records), its
    Source/Import rows, both round screening configs (ta + ft) and the
    SnowballRun audit row.

    The caller must ensure round_ is the latest iteration: its records always
    have the highest ids, so dedup makes them duplicates/uniques and never the
    canonical of an older record — nothing older is orphaned by their deletion.
    """
    # 1. citation edges of this round (incl. manual edges between older records)
    db.query(CitationEdge).filter_by(
        project_id=project_id, round=round_).delete(synchronize_session=False)
    # 2. the records this round imported + everything under them. Round R (>=2)
    #    sources are all snowballing; crawl and manual adds share one Source but
    #    a round can still hold several imports.
    sources = (db.query(Source)
               .filter_by(project_id=project_id, round=round_).all())
    if sources:
        src_ids = [s.id for s in sources]
        imp_ids = [i.id for i in db.query(Import.id)
                   .filter(Import.source_id.in_(src_ids))]
        if imp_ids:
            (db.query(Record).filter(Record.import_id.in_(imp_ids))
             .delete(synchronize_session=False))
            (db.query(Import).filter(Import.id.in_(imp_ids))
             .delete(synchronize_session=False))
        (db.query(Source).filter(Source.id.in_(src_ids))
         .delete(synchronize_session=False))
    # 3. the round's screening configs (ta + ft): assignments cascade via
    #    config_id, votes/conflicts already went with their records.
    db.query(ScreeningConfig).filter_by(
        project_id=project_id, round=round_).delete(synchronize_session=False)
    # 4. the audit row of the round — a snowballing iteration or a search
    #    update pass (living review), whichever owns it
    db.query(SnowballRun).filter_by(
        project_id=project_id, round=round_).delete(synchronize_session=False)
    db.query(SearchUpdateRun).filter_by(
        project_id=project_id, round=round_).delete(synchronize_session=False)
    db.commit()


def canonical_id(record: Record) -> int:
    return record.canonical_id if (record.dedup_status == "duplicate"
                                   and record.canonical_id) else record.id


def snowball_status(db: Session, project_id: int) -> dict:
    """Everything the Snowballing page needs: seed pool, run history per round,
    where each round stands in screening, and the saturation verdict."""
    runs = (db.query(SnowballRun).filter_by(project_id=project_id)
            .order_by(SnowballRun.round).all())
    pending = pending_seed_ids(db, project_id)
    ft_includes = ft_included_ids(db, project_id)

    rounds = []
    for run in runs:
        # progress of that round's screening
        stats = {}
        for stage in ("ta", "ft"):
            config = (db.query(ScreeningConfig)
                      .filter_by(project_id=project_id, stage=stage,
                                 round=run.round).first())
            if config is None or config.status != "active":
                stats[stage] = None
                continue
            outcomes = screening_outcomes(db, config)
            stats[stage] = {
                "decided": len(outcomes),
                "included": sum(1 for d in outcomes.values() if d == "include"),
            }
        rounds.append({
            "round": run.round, "n_seeds": run.n_seeds,
            "n_backward": run.n_backward, "n_forward": run.n_forward,
            "n_new_records": run.n_new_records, "n_new_unique": run.n_new_unique,
            "created_at": run.created_at.isoformat() if run.created_at else "",
            "ta": stats["ta"], "ft": stats["ft"],
        })

    last = runs[-1] if runs else None
    # Saturation: at least one iteration ran, no new seed awaits crawling, and
    # the last iteration brought nothing new to screen (or everything new has
    # been screened without producing a single new include).
    saturated = bool(runs) and not pending and (
        (last.n_new_unique == 0) if last else False)
    if runs and not pending and last is not None and last.n_new_unique > 0:
        from app.services.screening.core import eligible_record_ids
        ft_cfg = (db.query(ScreeningConfig)
                  .filter_by(project_id=project_id, stage="ft",
                             round=last.round, status="active").first())
        if ft_cfg is not None:
            outcomes = screening_outcomes(db, ft_cfg)
            eligible_count = len(eligible_record_ids(db, project_id, "ft",
                                                     last.round))
            done = eligible_count > 0 and len(outcomes) >= eligible_count
            includes = sum(1 for d in outcomes.values() if d == "include")
            if done and includes == 0:
                saturated = True

    n_edges = db.query(CitationEdge).filter_by(project_id=project_id).count()
    missing_abstracts = (db.query(Record)
                         .filter(Record.project_id == project_id,
                                 Record.doi.isnot(None), Record.doi != "",
                                 Record.abstract == "")
                         .count())
    return {
        "runs": rounds,
        "pending_seeds": len(pending),
        "total_ft_included": len(ft_includes),
        "n_edges": n_edges,
        "saturated": saturated,
        "missing_abstracts": missing_abstracts,
    }


def seed_contributions(db: Session, project_id: int) -> list[dict]:
    """Per crawled seed: the distinct papers its backward/forward crawl
    contributed to the citation graph (post-dedup, seed self-refs excluded) —
    counts plus the article lists, with the metadata and screening status the
    per-round audit table renders."""
    seed_round: dict[int, int] = {}
    for run in (db.query(SnowballRun).filter_by(project_id=project_id)
                .order_by(SnowballRun.round)):
        for rid in run.seed_record_ids or []:
            seed_round.setdefault(rid, run.round)
    if not seed_round:
        return []
    back: dict[int, list[int]] = {}
    fwd: dict[int, list[int]] = {}
    found_ids: set[int] = set()
    for e in canonical_edges(db, project_id):
        if e.direction == "backward" and e.citing_record_id in seed_round:
            back.setdefault(e.citing_record_id, []).append(e.cited_record_id)
            found_ids.add(e.cited_record_id)
        elif e.direction == "forward" and e.cited_record_id in seed_round:
            fwd.setdefault(e.cited_record_id, []).append(e.citing_record_id)
            found_ids.add(e.citing_record_id)
    records = {r.id: r for r in db.query(Record)
               .filter(Record.id.in_(set(seed_round) | found_ids))}

    # screening outcome of each discovered paper (same rule as the graph view)
    ta_out: dict[int, str] = {}
    ft_out: dict[int, str] = {}
    for config in db.query(ScreeningConfig).filter_by(project_id=project_id,
                                                      status="active"):
        target = ta_out if config.stage == "ta" else ft_out
        target.update(screening_outcomes(db, config))

    def status(rid: int) -> str:
        if rid in seed_round:
            return "seed"
        if ft_out.get(rid) == "include":
            return "included"
        if ft_out.get(rid) == "exclude" or ta_out.get(rid) == "exclude":
            return "excluded"
        return "pending"

    def article(rid: int) -> dict | None:
        record = records.get(rid)
        if record is None:
            return None
        return {"id": rid, "title": record.title, "authors": record.authors or [],
                "year": record.year, "doi": record.doi, "status": status(rid)}

    out = []
    for rid, round_ in sorted(seed_round.items(), key=lambda kv: (kv[1], kv[0])):
        record = records.get(rid)
        if record is None:
            continue
        backward = [a for a in (article(x) for x in back.get(rid, [])) if a]
        forward = [a for a in (article(x) for x in fwd.get(rid, [])) if a]
        out.append({
            "id": rid, "title": record.title, "doi": record.doi,
            "year": record.year, "author": (record.authors or [""])[0],
            "authors": record.authors or [],
            "round": round_,
            "n_backward": len(backward), "n_forward": len(forward),
            "backward": backward, "forward": forward,
        })
    return out


def record_card(db: Session, project_id: int, record_id: int) -> dict:
    """Everything the "paper card" modal shows about one article: metadata,
    provenance (sources across the dedup group), screening outcomes per
    stage/round with the FT exclusion reason, stored-PDF state, how snowballing
    discovered it, and — when it was crawled as a seed — what each of its own
    backward/forward crawls found (across every iteration)."""
    from app.models import FullText
    from app.services.screening.reasons import primary_reason, reason_labels

    record = db.get(Record, record_id)
    if record is None or record.project_id != project_id:
        raise ValueError("Record not found in this project")
    canon_id = canonical_id(record)
    canon = db.get(Record, canon_id) or record
    group_ids = [canon_id] + [
        r.id for r in db.query(Record)
        .filter_by(project_id=project_id, canonical_id=canon_id,
                   dedup_status="duplicate")]

    sources = [
        {"type": t, "name": n, "round": r}
        for t, n, r in (db.query(Source.type, Source.name, Source.round)
                        .join(Import, Import.source_id == Source.id)
                        .join(Record, Record.import_id == Import.id)
                        .filter(Record.id.in_(group_ids))
                        .distinct().order_by(Source.round, Source.name).all())]

    labels = reason_labels(db, project_id, "ft")
    screening = []
    for config in (db.query(ScreeningConfig)
                   .filter_by(project_id=project_id, status="active")
                   .order_by(ScreeningConfig.round, ScreeningConfig.stage)):
        outcome = screening_outcomes(db, config).get(canon_id)
        if outcome is None:
            continue
        entry = {"stage": config.stage, "round": config.round,
                 "outcome": outcome, "reason": None}
        if config.stage == "ft" and outcome == "exclude":
            code = primary_reason(db, config, canon_id)
            if code:
                entry["reason"] = {"code": code,
                                   "label": labels.get(code, code)}
        screening.append(entry)

    ft = db.query(FullText).filter_by(record_id=canon_id).first()

    # how snowballing found this paper (edges where it is the discovered end)
    records_cache: dict[int, Record] = {canon_id: canon}

    def meta(rid: int) -> dict | None:
        if rid not in records_cache:
            records_cache[rid] = db.get(Record, rid)
        r = records_cache[rid]
        if r is None:
            return None
        return {"id": r.id, "title": r.title, "authors": r.authors or [],
                "year": r.year, "doi": r.doi}

    discovered_by = []
    for e in canonical_edges(db, project_id):
        if e.direction == "backward" and e.cited_record_id == canon_id:
            seed = meta(e.citing_record_id)
            if seed:
                discovered_by.append({**seed, "direction": "backward",
                                      "round": e.round})
        elif e.direction == "forward" and e.citing_record_id == canon_id:
            seed = meta(e.cited_record_id)
            if seed:
                discovered_by.append({**seed, "direction": "forward",
                                      "round": e.round})

    # its own crawls, when it served as a seed (any iteration)
    as_seed = next((c for c in seed_contributions(db, project_id)
                    if c["id"] == canon_id), None)

    return {
        "id": canon_id,
        "requested_id": record_id,
        "is_duplicate_of": canon_id if canon_id != record_id else None,
        "title": canon.title, "authors": canon.authors or [],
        "year": canon.year, "journal": canon.journal, "doi": canon.doi,
        "abstract": canon.abstract,
        "sources": sources,
        "screening": screening,
        "has_pdf": bool(ft is not None and ft.file_path),
        "fulltext_status": ft.status if ft is not None else None,
        "discovered_by": discovered_by,
        "as_seed": None if as_seed is None else {
            "rounds": [as_seed["round"]],
            "n_backward": as_seed["n_backward"],
            "n_forward": as_seed["n_forward"],
            "backward": as_seed["backward"],
            "forward": as_seed["forward"],
        },
    }


def manual_add(db: Session, project_id: int, seed_record_id: int,
               direction: str, dois: list[str], user_id: int | None) -> dict:
    """Manually attach missed backward/forward articles to a crawled seed.

    The crawl APIs miss references (bad Crossref metadata, unindexed venues):
    the user pastes the DOIs, we hydrate metadata via OpenAlex, import them
    under the seed's snowballing round (same source as the crawl), dedup
    against the whole base and add the citation edges. New unique records join
    the round's T/A screening automatically (late-assignment sync)."""
    from app.services.connectors.jobs import (
        archive_raw, get_or_create_source, store_import,
    )
    from app.services.dedup.core import run_dedup
    from app.services.ris.parse import normalize_doi, to_ris
    from app.services.snowballing.core import (
        fetch_abstracts, make_client, openalex_resolve_dois,
    )

    seed = db.get(Record, seed_record_id)
    if seed is None or seed.project_id != project_id:
        raise ValueError("Seed record not found in this project")
    round_ = None
    for run in (db.query(SnowballRun).filter_by(project_id=project_id)
                .order_by(SnowballRun.round)):
        if seed_record_id in (run.seed_record_ids or []):
            round_ = run.round
            break
    if round_ is None:  # seed not crawled yet -> attach to the latest iteration
        round_ = (db.query(func.max(SnowballRun.round))
                  .filter_by(project_id=project_id).scalar())
    if round_ is None:
        raise ValueError("Run a snowballing iteration first — manual additions "
                         "complete an existing crawl")

    seed_doi = normalize_doi(seed.doi)
    wanted = [d for d in dict.fromkeys(normalize_doi(x) for x in dois)
              if d and d != seed_doi]
    if not wanted:
        raise ValueError("No valid DOI to add")

    # already in the base? just link them (on their canonical record)
    by_doi: dict[str, Record] = {}
    for record in (db.query(Record)
                   .filter(Record.project_id == project_id,
                           Record.doi.isnot(None), Record.doi != "")):
        by_doi.setdefault(normalize_doi(record.doi) or "", record)
    existing = {d: by_doi[d] for d in wanted if d in by_doi}
    missing = [d for d in wanted if d not in existing]

    n_created = 0
    unresolved: list[str] = []
    if missing:
        with make_client() as client:
            refs = {r["doi"]: r for r in openalex_resolve_dois(client, missing)
                    if r.get("doi")}
            abstracts = fetch_abstracts(client, missing, scrape_cap=0)
        payload = []
        for doi in missing:
            ref = refs.get(doi)
            if ref is None:
                unresolved.append(doi)
            payload.append({
                "doi": doi,
                "title": (ref or {}).get("title") or f"[metadata not found] {doi}",
                "authors": (ref or {}).get("authors") or [],
                "year": (ref or {}).get("year"),
                "journal": "", "abstract": abstracts.get(doi, ""), "raw": "",
            })
        filename = archive_raw(project_id, f"snowballing_r{round_}_manual.ris",
                               to_ris(payload).encode("utf-8"))
        source = get_or_create_source(db, project_id, "snowballing",
                                      f"snowballing r{round_}", round_)
        imp = store_import(db, project_id=project_id, source_id=source.id,
                           equation_id=None, filename=filename,
                           records=payload, user_id=user_id)
        db.flush()
        created = (db.query(Record).filter_by(import_id=imp.id)
                   .order_by(Record.id).all())
        n_created = len(created)
        db.commit()
        run_dedup(db, project_id)  # commits; may fold a new record onto an old one
        n_new_unique = 0
        for record in created:
            db.refresh(record)
            existing[normalize_doi(record.doi) or ""] = record
            if record.dedup_status == "unique":
                n_new_unique += 1

        # make sure the round's T/A screening exists so the additions get
        # screened (same auto-config as the crawl job; an already-active
        # round picks them up via the late-assignment sync)
        if n_new_unique:
            from datetime import datetime, timezone

            from app.services.screening.core import generate_assignments
            from app.services.snowballing.jobs import _copy_config
            ta = _copy_config(db, project_id, "ta", round_)
            if ta is not None and ta.status != "active" and ta.reviewer_ids:
                generate_assignments(db, ta)
                ta.status = "active"
                ta.started_at = datetime.now(timezone.utc)
            _copy_config(db, project_id, "ft", round_)
            db.commit()

    # citation edges on canonical records
    existing_pairs = {(e.citing_record_id, e.cited_record_id)
                      for e in db.query(CitationEdge)
                      .filter_by(project_id=project_id)}
    n_edges = 0
    for doi in wanted:
        record = existing.get(doi)
        if record is None:
            continue
        other = canonical_id(record)
        pair = ((seed_record_id, other) if direction == "backward"
                else (other, seed_record_id))
        if pair[0] == pair[1] or pair in existing_pairs:
            continue
        existing_pairs.add(pair)
        db.add(CitationEdge(project_id=project_id, citing_record_id=pair[0],
                            cited_record_id=pair[1], direction=direction,
                            round=round_))
        n_edges += 1
    db.commit()
    return {"round": round_, "requested": len(wanted),
            "already_known": len(wanted) - len(missing), "created": n_created,
            "edges_added": n_edges, "unresolved": unresolved}


def graph_data(db: Session, project_id: int, included_only: bool = False) -> dict:
    """Nodes + edges for the network view. Node status: seed | included |
    excluded | pending (screening not finished). Each node also carries how it
    was discovered (origin: backward | forward | both — the shape code in the
    UI), whether its PDF is stored (open in the viewer), the primary exclusion
    reason for excluded papers, and per-seed crawl contributions (hover).
    included_only keeps only the FT-included papers."""
    from app.models import FullText
    from app.services.screening.reasons import primary_reason, reason_labels

    edges = canonical_edges(db, project_id)
    if not edges:
        return {"nodes": [], "edges": []}
    node_ids = {e.citing_record_id for e in edges} | {e.cited_record_id for e in edges}
    records = {r.id: r for r in db.query(Record).filter(Record.id.in_(node_ids))}

    # outcome per record across every round/stage (keep the config that decided
    # each record so excluded nodes can surface their primary reason)
    ta_out: dict[int, str] = {}
    ft_out: dict[int, str] = {}
    decided_by: dict[int, ScreeningConfig] = {}
    for config in db.query(ScreeningConfig).filter_by(project_id=project_id,
                                                      status="active"):
        outcomes = screening_outcomes(db, config)
        target = ta_out if config.stage == "ta" else ft_out
        target.update(outcomes)
        if config.stage == "ft":
            for rid, d in outcomes.items():
                if d == "exclude":
                    decided_by[rid] = config
    seed_ids = crawled_seed_ids(db, project_id)

    def status(rid: int) -> str:
        if rid in seed_ids:
            return "seed"
        if ft_out.get(rid) == "include":
            return "included"
        if ft_out.get(rid) == "exclude" or ta_out.get(rid) == "exclude":
            return "excluded"
        return "pending"

    # discovery origin per node + per-seed contribution counts
    origin: dict[int, set] = {}
    seed_back: dict[int, int] = {}
    seed_fwd: dict[int, int] = {}
    for e in edges:
        if e.direction == "backward":
            origin.setdefault(e.cited_record_id, set()).add("backward")
            if e.citing_record_id in seed_ids:
                seed_back[e.citing_record_id] = seed_back.get(e.citing_record_id, 0) + 1
        else:
            origin.setdefault(e.citing_record_id, set()).add("forward")
            if e.cited_record_id in seed_ids:
                seed_fwd[e.cited_record_id] = seed_fwd.get(e.cited_record_id, 0) + 1

    pdf_ids = {ft.record_id for ft in
               db.query(FullText).filter(FullText.record_id.in_(node_ids))
               if ft.file_path}
    labels = reason_labels(db, project_id, "ft")

    # round each node entered the corpus (1 = initial corpus, N = discovered by
    # the round-N crawl). A record crawled as seed in round R existed in round
    # R-1 at the latest — this beats any edge that "rediscovers" an early seed;
    # so does the round of the source it was imported from (a crawl that finds
    # an initial-corpus paper again did not discover it).
    source_round = dict(
        db.query(Record.id, Source.round)
        .join(Import, Record.import_id == Import.id)
        .join(Source, Import.source_id == Source.id)
        .filter(Record.id.in_(node_ids)))
    seed_since: dict[int, int] = {}
    for run in db.query(SnowballRun).filter_by(project_id=project_id):
        for rid in run.seed_record_ids or []:
            seed_since[rid] = min(seed_since.get(rid, run.round), run.round)
    disc_round: dict[int, int] = {}
    for e in edges:
        target = (e.cited_record_id if e.direction == "backward"
                  else e.citing_record_id)
        disc_round[target] = min(disc_round.get(target, e.round), e.round)

    def node_round(rid: int) -> int:
        candidates = []
        if rid in seed_since:
            candidates.append(seed_since[rid] - 1)
        if rid in disc_round:
            candidates.append(disc_round[rid])
        if source_round.get(rid):
            candidates.append(source_round[rid])
        return max(min(candidates), 1) if candidates else 1

    def node_origin(rid: int) -> str:
        kinds = origin.get(rid, set()) - {None}
        if rid in seed_ids and not kinds:
            return "seed"      # initial seed, not itself discovered by a crawl
        if kinds == {"backward"}:
            return "backward"
        if kinds == {"forward"}:
            return "forward"
        return "both" if kinds else "seed"

    nodes = []
    keep: set[int] = set()
    for rid in sorted(node_ids):
        record = records.get(rid)
        if record is None:
            continue
        st = status(rid)
        if included_only and st not in ("seed", "included"):
            continue
        keep.add(rid)
        first_author = (record.authors or [""])[0]
        reason_code = None
        if st == "excluded" and rid in decided_by:
            reason_code = primary_reason(db, decided_by[rid], rid)
        nodes.append({
            "id": rid, "title": record.title, "doi": record.doi,
            "year": record.year, "author": first_author, "status": st,
            "origin": node_origin(rid), "round": node_round(rid),
            "has_pdf": rid in pdf_ids,
            "reason": ({"code": reason_code,
                        "label": labels.get(reason_code, reason_code)}
                       if reason_code else None),
            "n_backward": seed_back.get(rid, 0),
            "n_forward": seed_fwd.get(rid, 0),
        })
    out_edges = [
        {"citing": e.citing_record_id, "cited": e.cited_record_id,
         "direction": e.direction, "round": e.round}
        for e in edges
        if e.citing_record_id in keep and e.cited_record_id in keep
    ]
    return {"nodes": nodes, "edges": out_edges}
