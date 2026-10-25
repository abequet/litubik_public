# SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
# SPDX-License-Identifier: AGPL-3.0-or-later
"""M10 results: descriptive synthesis computed live from the extraction table.

Same principle as the PRISMA module: every number on the Results page is
computed from the tables, never typed in or stored. Corpus = the FT-included
set (eligible_ids); cell values go through the same consensus rule as the
extraction export (validated wins; a genuine disagreement between extractors
is excluded from the aggregates and counted as a conflict instead).
"""
import json
import statistics

from sqlalchemy.orm import Session

from app.models import (
    ExtractionColumn, ExtractionConfig, ExtractionStudy, ExtractionValue, Record,
)
from app.services.appraisal import core as appraisal_core
from app.services.appraisal import instruments
from app.services.appraisal import summary as appraisal_summary
from app.services.extraction import studies as ext_studies
from app.services.extraction.service import eligible_ids
from app.services.results.countries import (
    _norm, country_name, normalize_cell,
)

# Column names recognized as the country column (normalized comparison).
COUNTRY_COLUMN_NAMES = {"country", "countries", "pays", "country/countries",
                        "country of study", "study country"}


def consensus_cell(cell_values: list[ExtractionValue]) -> tuple[object, str]:
    """One value per study for the aggregates — the typed twin of the export's
    _export_cell: validated rows win; agreement yields the value; a real
    disagreement yields (None, "conflict")."""
    pool = [v for v in cell_values if v.validated] or list(cell_values)
    vals = [payload for v in pool
            if (payload := (v.value or {}).get("v")) not in (None, "", [])]
    if not vals:
        return None, "empty"
    if len({json.dumps(v, sort_keys=True) for v in vals}) == 1:
        return vals[0], "ok"
    return None, "conflict"


def first_author(record: Record) -> str:
    name = ((record.authors or [""])[0] or "").strip()
    return name.split(",")[0].strip() or name


def study_label(record: Record) -> str:
    author = first_author(record)
    if author and record.year:
        return f"{author} {record.year}"
    return author or (record.title or f"#{record.id}")[:40]


def find_country_column(columns: list[ExtractionColumn]) -> ExtractionColumn | None:
    return next((c for c in columns if _norm(c.name) in COUNTRY_COLUMN_NAMES),
                None)


def _load(db: Session, project_id: int):
    """One query pass shared by aggregates() and evidence_rows(). `studies`
    is the unit of every aggregate: (study, record, n studies of that
    record), in corpus order; `by_cell` is keyed by study id."""
    ids = eligible_ids(db, project_id)
    columns = (db.query(ExtractionColumn).filter_by(project_id=project_id)
               .order_by(ExtractionColumn.position, ExtractionColumn.id).all())
    by_id = {r.id: r for r in db.query(Record)
             .filter(Record.id.in_(ids))} if ids else {}
    records = [by_id[rid] for rid in ids if rid in by_id]
    by_record = ext_studies.studies_for_records(db, [r.id for r in records])
    studies = [(s, r, len(by_record[r.id])) for r in records
               for s in by_record.get(r.id, [])]
    by_cell: dict[int, dict[int, list[ExtractionValue]]] = {}
    study_ids = [s.id for s, _, _ in studies]
    if study_ids:
        for v in (db.query(ExtractionValue)
                  .filter(ExtractionValue.study_id.in_(study_ids))):
            by_cell.setdefault(v.study_id, {}).setdefault(
                v.column_id, []).append(v)
    return ids, columns, records, by_cell, studies


def _numeric_stats(values: list[float]) -> dict:
    q1 = q3 = values[0]
    if len(values) >= 2:
        q1, _, q3 = statistics.quantiles(values, n=4, method="inclusive")
    return {
        "n": len(values),
        "min": min(values), "max": max(values),
        "mean": round(statistics.fmean(values), 2),
        "median": statistics.median(values),
        "q1": round(q1, 2), "q3": round(q3, 2),
    }


def _distribution(consensus: list, col: ExtractionColumn) -> list[dict]:
    """Counts per bucket. Options keep their declared order; stray values
    (legacy options, off-list entries) follow, most frequent first."""
    counts: dict[str, int] = {}
    for value in consensus:
        buckets = value if isinstance(value, list) else [value]
        for b in {("yes" if b else "no") if isinstance(b, bool) else str(b)
                  for b in buckets}:
            counts[b] = counts.get(b, 0) + 1
    declared = (["yes", "no"] if col.col_type == "bool" else col.options or [])
    out = [{"value": o, "n": counts.pop(o)} for o in declared if o in counts]
    out += [{"value": v, "n": n}
            for v, n in sorted(counts.items(), key=lambda kv: -kv[1])]
    return out


def study_rows(studies: list[tuple[ExtractionStudy, Record, int]],
               columns: list[ExtractionColumn],
               by_cell: dict, country_col: ExtractionColumn | None) -> list[dict]:
    """Per-study consensus shipped to the client so the Results charts can be
    cross-filtered (year range, designs, countries) without re-fetching:
    metadata + normalized countries + one {v, s} per chartable column
    (s: ok | conflict | empty). One row per study — an article reporting
    several studies yields several rows, told apart by their label."""
    rows = []
    for s, r, n_studies in studies:
        values: dict[int, dict] = {}
        countries: list[str] = []
        unmatched: list[str] = []
        for col in columns:
            if col.col_type == "text" and col is not country_col:
                continue
            value, status = consensus_cell(by_cell.get(s.id, {}).get(col.id, []))
            if col is country_col:
                if status == "ok":
                    text = "; ".join(str(v) for v in value) \
                        if isinstance(value, list) else str(value)
                    countries, unmatched = normalize_cell(text)
                continue
            values[col.id] = {"v": value if status == "ok" else None,
                              "s": status}
        rows.append({"record_id": r.id, "study_id": s.id,
                     "label": ext_studies.display_label(study_label(r), s, n_studies),
                     "year": r.year, "design": s.study_design,
                     "countries": countries,
                     "countries_unmatched": unmatched, "values": values})
    return rows


def aggregates(db: Session, project_id: int) -> dict:
    ids, columns, records, by_cell, study_units = _load(db, project_id)
    config = db.query(ExtractionConfig).filter_by(project_id=project_id).first()

    # -- corpus KPIs (per article: an article counts once however many
    # studies it reports) ---------------------------------------------------
    n_with_any_value = 0
    n_fully_validated = 0  # >=1 cell and nothing left unvalidated
    for r in records:
        rows = [v for s, rr, _ in study_units if rr.id == r.id
                for cells in by_cell.get(s.id, {}).values() for v in cells
                if (v.value or {}).get("v") not in (None, "", [])]
        if rows:
            n_with_any_value += 1
            if all(v.validated for v in rows):
                n_fully_validated += 1

    # -- per-study consensus rows (single source for every aggregate below,
    # and shipped to the client for cross-filtering) --------------------------
    country_col = find_country_column(columns)
    studies = study_rows(study_units, columns, by_cell, country_col)

    # -- publication years ---------------------------------------------------
    year_counts: dict[int, int] = {}
    for s in studies:
        if s["year"]:
            year_counts[s["year"]] = year_counts.get(s["year"], 0) + 1
    years = {
        "counts": [{"year": y, "n": n} for y, n in sorted(year_counts.items())],
        "unknown": sum(1 for s in studies if not s["year"]),
        "min": min(year_counts) if year_counts else None,
        "max": max(year_counts) if year_counts else None,
    }

    # -- study designs -------------------------------------------------------
    design_counts: dict[str | None, int] = {}
    for s in studies:
        design_counts[s["design"] or None] = \
            design_counts.get(s["design"] or None, 0) + 1
    designs = [{"design": d, "n": n} for d, n in
               sorted(design_counts.items(),
                      key=lambda kv: (kv[0] is None, -kv[1]))]

    # -- countries (free-text extraction column, normalized) -----------------
    country_counts: dict[str, int] = {}
    unmatched_counts: dict[str, int] = {}
    n_studies_with_country = n_multi_country = country_missing = 0
    if country_col is not None:
        for s in studies:
            matched, unmatched = s["countries"], s["countries_unmatched"]
            if not matched and not unmatched:  # no consensus or empty cell
                country_missing += 1
                continue
            for iso3 in matched:
                country_counts[iso3] = country_counts.get(iso3, 0) + 1
            for raw in unmatched:
                unmatched_counts[raw] = unmatched_counts.get(raw, 0) + 1
            if matched:
                n_studies_with_country += 1
                if len(matched) > 1:
                    n_multi_country += 1
    countries = {
        "column_id": country_col.id if country_col else None,
        "column_name": country_col.name if country_col else None,
        "counts": [{"iso3": iso3, "name": country_name(iso3), "n": n}
                   for iso3, n in sorted(country_counts.items(),
                                         key=lambda kv: -kv[1])],
        "n_studies_with_country": n_studies_with_country,
        "n_multi_country": n_multi_country,
        "unmatched": [{"value": v, "n": n}
                      for v, n in sorted(unmatched_counts.items(),
                                         key=lambda kv: -kv[1])],
        "missing": country_missing,
    }

    # -- per-column distributions / numeric stats ----------------------------
    col_blocks = []
    for col in columns:
        if col.col_type == "text" or col is country_col:
            continue
        consensus, n_missing, n_conflicts = [], 0, 0
        for s in studies:
            cell = s["values"][col.id]
            if cell["s"] == "ok":
                consensus.append(cell["v"])
            elif cell["s"] == "conflict":
                n_conflicts += 1
            else:
                n_missing += 1
        block = {"id": col.id, "name": col.name, "col_type": col.col_type,
                 "options": col.options or [],
                 "n_missing": n_missing, "n_conflicts": n_conflicts}
        if col.col_type == "number":
            numbers = sorted(float(v) for v in consensus
                             if isinstance(v, (int, float)))
            block["stats"] = _numeric_stats(numbers) if numbers else None
            block["values"] = numbers
        else:
            block["distribution"] = _distribution(consensus, col)
        col_blocks.append(block)

    # -- critical appraisal --------------------------------------------------
    # The headline is the per-domain view (see services/appraisal/summary.py);
    # what follows is the per-study detail behind it. One appraisal counts per
    # study: the consensus row when two assessors settled one, their pooled
    # answers otherwise — the same precedence as consensus_cell() above.
    inst = appraisal_core.instrument_of(db, project_id)
    config = appraisal_core.config_of(db, project_id)
    study_ids = [s.id for s, _, _ in study_units]
    effective = appraisal_core.effective_appraisals(db, study_ids)
    domain_rows = appraisal_summary.per_study(
        db, project_id, study_ids, {s.id: s.study_design for s, _, _ in study_units})
    per_study = []
    for s, r, n_studies in study_units:
        entry = effective.get(s.id)
        if entry is None:
            continue
        counts = {"yes": 0, "no": 0, "unclear": 0, "na": 0}
        # a consensus has one set of answers; individual appraisals are pooled
        for answers in entry.get("all_answers") or [entry["answers"]]:
            for cell in (answers or {}).values():
                answer = (cell or {}).get("answer", "")
                if answer in counts:
                    counts[answer] += 1
        answered = sum(counts.values())
        if not answered:
            continue
        per_study.append({
            "record_id": r.id, "study_id": s.id,
            "label": ext_studies.display_label(study_label(r), s, n_studies),
            "design": s.study_design, "n_assessors": entry["n_assessors"],
            "source": entry["source"], "overall": entry["overall"],
            "answers": counts,
            "n_questions": len(instruments.question_ids(inst, entry["design"])),
            "pct_yes": round(counts["yes"] / answered, 3),
            # shipped per study so the client can re-fold the domain view over
            # a cross-filtered subset without another round trip
            "domains": domain_rows.get(s.id),
        })
    per_study.sort(key=lambda s: -s["pct_yes"])
    by_design: dict[str | None, list[float]] = {}
    for s in per_study:
        by_design.setdefault(s["design"], []).append(s["pct_yes"])
    jbi = {
        "instrument": instruments.summary(inst),
        "dual": appraisal_core.is_dual(config),
        "by_domain": appraisal_summary.fold(list(domain_rows.values())),
        "per_study": per_study,
        "n_from_consensus": sum(1 for s in per_study
                                if s["source"] == "consensus"),
        # Kept, and kept secondary: a single "% of criteria met" is the
        # composite quality score JBI and the Cochrane Handbook advise against
        # reading as a quality ranking. It says how complete an appraisal is,
        # not how good a study is.
        "avg_pct_yes": round(statistics.fmean(
            [s["pct_yes"] for s in per_study]), 3) if per_study else None,
        "by_design": [{"design": d, "n_studies": len(v),
                       "avg_pct_yes": round(statistics.fmean(v), 3)}
                      for d, v in sorted(by_design.items(),
                                         key=lambda kv: -len(kv[1]))],
        "n_appraised": len(per_study),
    }

    return {
        "n_included": len(ids),
        # studies reported by those articles (chantier 9) — the unit of the
        # rows below; equals n_included until an article declares a second one
        "n_studies": len(study_units),
        "n_with_any_value": n_with_any_value,
        "n_fully_validated": n_fully_validated,
        "extraction_started": bool(config and config.status == "active"),
        "years": years,
        "designs": designs,
        "countries": countries,
        "columns": col_blocks,
        "jbi": jbi,
        "studies": studies,
    }


def evidence_rows(db: Session, project_id: int) -> tuple[list[ExtractionColumn],
                                                         list[dict]]:
    """Condensed per-study consensus for the narrative prompt: one entry per
    included record with its metadata and one value per column (conflicts and
    empties are None)."""
    _, columns, records, by_cell, study_units = _load(db, project_id)
    rows = []
    for s, r, n_studies in study_units:
        values = {}
        for col in columns:
            value, status = consensus_cell(by_cell.get(s.id, {}).get(col.id, []))
            values[col.id] = value if status == "ok" else None
        rows.append({"label": ext_studies.display_label(study_label(r), s, n_studies),
                     "year": r.year, "design": s.study_design,
                     "journal": r.journal, "values": values})
    return columns, rows


def export_rows(db: Session, project_id: int) -> tuple[list[str], list[list]]:
    """The aggregates flattened to one long-format table (Section / Item /
    Detail / N) — a single CSV importable anywhere, same numbers as the page."""
    data = aggregates(db, project_id)
    rows: list[list] = []
    rows.append(["summary", "included articles", "", data["n_included"]])
    rows.append(["summary", "included studies", "", data["n_studies"]])
    rows.append(["summary", "with extraction data", "",
                 data["n_with_any_value"]])
    rows.append(["summary", "fully validated", "", data["n_fully_validated"]])
    rows.append(["summary", "appraised (JBI)", "", data["jbi"]["n_appraised"]])
    for item in data["years"]["counts"]:
        rows.append(["studies per year", item["year"], "", item["n"]])
    if data["years"]["unknown"]:
        rows.append(["studies per year", "(unknown)", "",
                     data["years"]["unknown"]])
    for item in data["designs"]:
        rows.append(["study designs", item["design"] or "(not qualified)", "",
                     item["n"]])
    for item in data["countries"]["counts"]:
        rows.append(["countries", item["name"], item["iso3"], item["n"]])
    for item in data["countries"]["unmatched"]:
        rows.append(["countries (unrecognized)", item["value"], "", item["n"]])
    if data["countries"]["missing"]:
        rows.append(["countries", "(missing)", "",
                     data["countries"]["missing"]])
    for col in data["columns"]:
        section = f"column: {col['name']}"
        if col["col_type"] == "number":
            for key, value in (col["stats"] or {}).items():
                rows.append([section, key, value, ""])
        else:
            for item in col["distribution"]:
                rows.append([section, item["value"], "", item["n"]])
        if col["n_missing"]:
            rows.append([section, "(missing)", "", col["n_missing"]])
        if col["n_conflicts"]:
            rows.append([section, "(conflicting)", "", col["n_conflicts"]])
    for s in data["jbi"]["per_study"]:
        rows.append(["jbi (% yes)", s["label"],
                     f"{s['answers']['yes']}/{sum(s['answers'].values())}",
                     round(s["pct_yes"] * 100)])
    return ["Section", "Item", "Detail", "N"], rows
