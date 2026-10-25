# SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
# SPDX-License-Identifier: AGPL-3.0-or-later
"""M9 extraction: eligible rows, extractor allocation, columns, values, export.

Eligible records = the FT-included set across every round (the final corpus).
Allocation (user decision): 1 extractor per article (split between the chosen
extractors round-robin) or 2 per article (pairs rotate when >2 extractors).
Values are per-extractor rows so double extraction can be compared cell by
cell; single-extractor projects simply have one row per cell.
"""
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models import (
    ExtractionAssignment, ExtractionColumn, ExtractionConfig, ExtractionStudy,
    ExtractionValue, JbiAppraisal, Record,
)
from app.services.appraisal import core as appraisal_core
from app.services.appraisal import instruments
from app.services.extraction import studies as ext_studies
from app.services.snowballing.service import ft_included_ids

COLUMN_TYPES = ("text", "number", "bool", "choice", "multi")


@dataclass(frozen=True)
class Template:
    """A one-click set of starter columns. The right one for a project depends
    on its review type (services/framing.py), but any of them can be picked —
    a template only ever *adds* columns whose name is not already used."""
    key: str
    label: str
    description: str
    columns: list[dict]


TEMPLATES: dict[str, Template] = {
    # Standard evidence table. Unchanged since v1 — projects and tests rely on
    # these exact column names.
    "evidence_pico": Template(
        key="evidence_pico",
        label="Evidence table (PICO)",
        description="The standard evidence table of an effectiveness review: "
                    "population, intervention, comparator, outcomes.",
        columns=[
            {"name": "Country", "col_type": "text",
             "description": "Country/countries where the study was conducted"},
            {"name": "Aim", "col_type": "text",
             "description": "Stated aim or research question of the study"},
            {"name": "Population", "col_type": "text",
             "description": "Study population / participants characteristics"},
            {"name": "Sample size (N)", "col_type": "number",
             "description": "Total number of participants analysed"},
            {"name": "Setting", "col_type": "text",
             "description": "Context/setting of the study (field, lab, online...)"},
            {"name": "Intervention / Exposure", "col_type": "text",
             "description": "Intervention, exposure or phenomenon of interest"},
            {"name": "Comparator", "col_type": "text",
             "description": "Control or comparison condition, if any"},
            {"name": "Outcomes & measures", "col_type": "text",
             "description": "Outcomes and the instruments/measures used"},
            {"name": "Key findings", "col_type": "text",
             "description": "Main results relevant to the review question"},
            {"name": "Limitations", "col_type": "text",
             "description": "Limitations acknowledged or observed"},
            {"name": "Notes", "col_type": "text",
             "description": "Free notes for the review team"},
        ],
    ),
    "evidence_qualitative": Template(
        key="evidence_qualitative",
        label="Evidence table (qualitative / SPIDER)",
        description="For reviews of views, experiences and determinants: how "
                    "the sample was recruited, how the data were collected "
                    "and analysed, and what the study reports.",
        columns=[
            {"name": "Country", "col_type": "text",
             "description": "Country/countries where the study was conducted"},
            {"name": "Aim", "col_type": "text",
             "description": "Stated aim or research question of the study"},
            {"name": "Sample & recruitment", "col_type": "text",
             "description": "Who took part and how they were recruited"},
            {"name": "Sample size (N)", "col_type": "number",
             "description": "Total number of participants analysed"},
            {"name": "Setting", "col_type": "text",
             "description": "Context/setting of the study (field, lab, online...)"},
            {"name": "Phenomenon of interest", "col_type": "text",
             "description": "The behaviour, experience or determinant studied"},
            {"name": "Study design", "col_type": "text",
             "description": "Design and theoretical framing as the authors state them"},
            {"name": "Data collection method", "col_type": "text",
             "description": "Interviews, focus groups, observation, survey..."},
            {"name": "Analysis method", "col_type": "text",
             "description": "Thematic analysis, content analysis, statistics..."},
            {"name": "Key themes / findings", "col_type": "text",
             "description": "Main findings relevant to the review question"},
            {"name": "Illustrative quotes", "col_type": "text",
             "description": "Verbatim extracts supporting the findings, with their page"},
            {"name": "Limitations", "col_type": "text",
             "description": "Limitations acknowledged or observed"},
            {"name": "Notes", "col_type": "text",
             "description": "Free notes for the review team"},
        ],
    ),
    # The qualitative table plus the columns that keep a framework synthesis
    # auditable. LitUbik does not tool the a priori framework itself — these
    # columns are where the work done outside it gets recorded.
    "best_fit": Template(
        key="best_fit",
        label="“Best fit” framework synthesis",
        description="The qualitative evidence table plus the columns that "
                    "make the synthesis traceable: which a priori theme a "
                    "finding was coded against, what did not fit, and where "
                    "each finding came from.",
        columns=[
            {"name": "Country", "col_type": "text",
             "description": "Country/countries where the study was conducted"},
            {"name": "Aim", "col_type": "text",
             "description": "Stated aim or research question of the study"},
            {"name": "Sample & recruitment", "col_type": "text",
             "description": "Who took part and how they were recruited"},
            {"name": "Sample size (N)", "col_type": "number",
             "description": "Total number of participants analysed"},
            {"name": "Setting", "col_type": "text",
             "description": "Context/setting of the study (field, lab, online...)"},
            {"name": "Phenomenon of interest", "col_type": "text",
             "description": "The behaviour, experience or determinant studied"},
            {"name": "Study design", "col_type": "text",
             "description": "Design and theoretical framing as the authors state them"},
            {"name": "Data collection method", "col_type": "text",
             "description": "Interviews, focus groups, observation, survey..."},
            {"name": "Analysis method", "col_type": "text",
             "description": "Thematic analysis, content analysis, statistics..."},
            {"name": "Key themes / findings", "col_type": "text",
             "description": "Main findings relevant to the review question"},
            {"name": "Illustrative quotes", "col_type": "text",
             "description": "Verbatim extracts supporting the findings, with their page"},
            {"name": "A priori framework theme(s)", "col_type": "text",
             "description": "Theme(s) of the a priori framework this study's "
                            "findings were coded against"},
            {"name": "Fits the a priori framework", "col_type": "choice",
             "options": ["yes", "partly", "no"],
             "description": "Whether the framework accommodated the findings. "
                            "'partly' and 'no' are what the inductive analysis "
                            "then works on"},
            {"name": "New (emergent) theme", "col_type": "text",
             "description": "Theme created inductively for evidence the a "
                            "priori framework could not accommodate — left "
                            "empty when there is none"},
            {"name": "Source of the finding", "col_type": "text",
             "description": "Section and page the finding was taken from, so "
                            "the coding can be checked"},
            {"name": "Reviewer note on fit", "col_type": "text",
             "description": "Why the finding was coded there — the reasoning a "
                            "second reviewer needs to agree or disagree"},
            {"name": "Limitations", "col_type": "text",
             "description": "Limitations acknowledged or observed"},
            {"name": "Notes", "col_type": "text",
             "description": "Free notes for the review team"},
        ],
    ),
}

DEFAULT_TEMPLATE = "evidence_pico"

# Kept as a module-level alias: callers and tests written before the catalogue
# existed import this name.
STANDARD_TEMPLATE: list[dict] = TEMPLATES[DEFAULT_TEMPLATE].columns


def eligible_ids(db: Session, project_id: int) -> list[int]:
    # FT-included records + records imported at the extraction stage (external
    # review import — screened on another platform, no FT round here).
    forced = {rid for (rid,) in db.query(Record.id).filter_by(
        project_id=project_id, ft_forced_included=True)}
    return sorted(set(ft_included_ids(db, project_id)) | forced)


def get_config(db: Session, project_id: int) -> ExtractionConfig | None:
    return db.query(ExtractionConfig).filter_by(project_id=project_id).first()


def generate_assignments(db: Session, config: ExtractionConfig) -> int:
    """(Re)build the record->extractor allocation for records not yet assigned.
    Never touches existing assignments (values may exist)."""
    extractors = [int(u) for u in (config.extractor_ids or [])]
    if not extractors:
        return 0
    records = eligible_ids(db, config.project_id)
    existing = {(a.record_id, a.user_id) for a in
                db.query(ExtractionAssignment).filter_by(config_id=config.id)}
    assigned_records = {r for r, _ in existing}
    n_per = 2 if config.n_extractors == 2 and len(extractors) >= 2 else 1
    created = 0
    todo = [r for r in records if r not in assigned_records]
    for i, record_id in enumerate(todo):
        for k in range(n_per):
            user_id = extractors[(i + k) % len(extractors)]
            if (record_id, user_id) in existing:
                continue
            db.add(ExtractionAssignment(config_id=config.id,
                                        record_id=record_id, user_id=user_id))
            existing.add((record_id, user_id))
            created += 1
    db.flush()
    return created


def start(db: Session, config: ExtractionConfig) -> int:
    created = generate_assignments(db, config)
    config.status = "active"
    if config.started_at is None:
        config.started_at = datetime.now(timezone.utc)
    db.commit()
    return created


def coerce_value(col: ExtractionColumn, raw) -> dict:
    """Validate/coerce a submitted value against the column type; returns the
    stored payload {"v": value}. Raises ValueError on a bad value."""
    if raw is None or raw == "":
        return {"v": None}
    if col.col_type == "number":
        try:
            value = float(raw)
        except (TypeError, ValueError):
            raise ValueError("Expected a number")
        return {"v": int(value) if value == int(value) else value}
    if col.col_type == "bool":
        if isinstance(raw, bool):
            return {"v": raw}
        if str(raw).lower() in ("true", "yes", "1"):
            return {"v": True}
        if str(raw).lower() in ("false", "no", "0"):
            return {"v": False}
        raise ValueError("Expected true/false")
    if col.col_type == "choice":
        value = str(raw)
        if col.options and value not in col.options:
            raise ValueError(f"Must be one of: {', '.join(col.options)}")
        return {"v": value}
    if col.col_type == "multi":
        values = raw if isinstance(raw, list) else [raw]
        values = [str(v) for v in values]
        bad = [v for v in values if col.options and v not in col.options]
        if bad:
            raise ValueError(f"Not in options: {', '.join(bad)}")
        return {"v": values}
    return {"v": str(raw)}


def table_data(db: Session, project_id: int, me: int) -> dict:
    """Everything the grid needs: columns, rows (record meta + my assignment
    + PDF state) each carrying its studies (design + per-extractor cells +
    JBI state per study). The row also mirrors its first study's design,
    cells and JBI block for readers that still think per article."""
    config = get_config(db, project_id)
    columns = (db.query(ExtractionColumn).filter_by(project_id=project_id)
               .order_by(ExtractionColumn.position, ExtractionColumn.id).all())
    ids = eligible_ids(db, project_id)
    records = {r.id: r for r in db.query(Record).filter(Record.id.in_(ids))} \
        if ids else {}
    # me=0 is an export, not a person: a study created on the way has no author
    studies_by_record = ext_studies.studies_for_records(db, ids,
                                                        user_id=me or None)
    study_ids = [s.id for ss in studies_by_record.values() for s in ss]
    values = (db.query(ExtractionValue)
              .filter(ExtractionValue.study_id.in_(study_ids)).all()) if study_ids else []
    by_cell: dict[int, dict[int, list[ExtractionValue]]] = {}
    for v in values:
        by_cell.setdefault(v.study_id, {}).setdefault(v.column_id, []).append(v)
    assignments: dict[int, list[int]] = {}
    if config is not None:
        for a in db.query(ExtractionAssignment).filter_by(config_id=config.id):
            assignments.setdefault(a.record_id, []).append(a.user_id)
    appraisals: dict[int, list[JbiAppraisal]] = {}
    for ap in (db.query(JbiAppraisal)
               .filter(JbiAppraisal.study_id.in_(study_ids)).all()) if study_ids else []:
        appraisals.setdefault(ap.study_id, []).append(ap)
    inst = appraisal_core.instrument_of(db, project_id)
    from app.models import FullText
    pdf_ids = {ft.record_id for ft in
               db.query(FullText).filter(FullText.record_id.in_(ids))
               if ft.file_path} if ids else set()

    def study_block(s: ExtractionStudy) -> dict:
        cells = {}
        for col in columns:
            cell_values = by_cell.get(s.id, {}).get(col.id, [])
            cells[str(col.id)] = [{
                "user_id": v.user_id, "value": v.value.get("v"),
                "origin": v.origin, "validated": v.validated,
            } for v in cell_values]
        my_appraisal = next((a for a in appraisals.get(s.id, [])
                             if a.user_id == me), None)

        def done(a: JbiAppraisal) -> bool:
            return instruments.is_complete(inst, s.study_design, a.answers,
                                           a.overall)
        return {
            **ext_studies.study_dict(s),
            "cells": cells,
            "jbi": {
                "mine_done": bool(my_appraisal and done(my_appraisal)),
                "n_appraisals": sum(1 for a in appraisals.get(s.id, [])
                                    if done(a)),
                # criteria met / answered over the design's checklist, per
                # assessor; whether "met" is worth showing is the
                # instrument's call (`instrument.score`)
                "scores": [
                    {"user_id": a.user_id, "overall": a.overall, **sc}
                    for a in appraisals.get(s.id, [])
                    if (sc := instruments.score(inst, s.study_design,
                                                a.answers))
                    and sc["n_answered"] > 0
                ],
            },
        }

    rows = []
    for rid in ids:
        record = records.get(rid)
        if record is None:
            continue
        blocks = [study_block(s) for s in studies_by_record.get(rid, [])]
        first = blocks[0]
        rows.append({
            "record_id": rid, "title": record.title, "doi": record.doi,
            "authors": record.authors or [], "year": record.year,
            "journal": record.journal,
            "study_design": first["study_design"],
            "design_origin": first["design_origin"],
            "assigned_to": sorted(assignments.get(rid, [])),
            "assigned_to_me": me in assignments.get(rid, []),
            "has_pdf": rid in pdf_ids,
            "cells": first["cells"],
            "jbi": first["jbi"],
            "studies": blocks,
        })
    return {
        "config": None if config is None else {
            "n_extractors": config.n_extractors,
            "extractor_ids": config.extractor_ids or [],
            "status": config.status,
        },
        "columns": [{
            "id": c.id, "name": c.name, "col_type": c.col_type,
            "description": c.description, "options": c.options or [],
            "position": c.position,
        } for c in columns],
        "rows": rows,
        # how to read the per-study appraisal blocks
        "instrument": instruments.summary(inst),
    }


def export_rows(db: Session, project_id: int) -> tuple[list[str], list[list]]:
    """Header + data rows for CSV/XLSX. One line per study (an article
    reporting several studies spans several lines, told apart by the Study
    column); with double extraction a cell shows the validated/consensus
    value, or both values marked by extractor when they disagree."""
    from app.models import User
    data = table_data(db, project_id, me=0)
    names = {u.id: u.display_name for u in db.query(User)}
    # JBI keeps its historical column; an instrument without a score (MMAT)
    # reports how far each appraisal got instead, under a header that says so
    scored = data["instrument"]["score"]
    header = ["Record ID", "Study", "First author", "Year", "Title", "Journal",
              "DOI", "Study design",
              ("JBI score" if data["instrument"]["key"] == "jbi"
               else "Appraisal score" if scored else "Appraisal (answered)")]
    header += [c["name"] for c in data["columns"]]
    out = []
    for row in data["rows"]:
        for study in row["studies"]:
            scores = study["jbi"]["scores"]
            jbi_score = " | ".join(
                (f"{names.get(s['user_id'], '?')}: " if len(scores) > 1 else "")
                + (f"{s['n_yes']}/{s['n_questions']}" if scored
                   else f"{s['n_answered']}/{s['n_questions']}")
                for s in scores)
            line = [row["record_id"], study["label"],
                    (row["authors"] or [""])[0], row["year"],
                    row["title"], row["journal"], row["doi"] or "",
                    study["study_design"] or "", jbi_score]
            for col in data["columns"]:
                cell_values = study["cells"].get(str(col["id"]), [])
                line.append(_export_cell(cell_values, names))
            out.append(line)
    return header, out


def instrument_question_columns(inst: instruments.Instrument) -> list[str]:
    """Every question id the instrument uses, once, in catalogue order — the
    wide columns of the appraisal table. JBI numbers q1..q13 across designs,
    MMAT names its criteria S1, 1.1 … 5.5: the ids are the instrument's own,
    which is what lets a reader match a column back to the published tool."""
    seen: list[str] = []
    # catalogue order, not alphabetical: JBI opens on the RCT tool (q1..q13),
    # MMAT on category 1 (S1, S2, 1.1 ... 5.5)
    for design in inst.checklists:
        for qid in instruments.question_ids(inst, design):
            if qid not in seen:
                seen.append(qid)
    return seen


def _export_answer(checklist: dict | None, answer: str) -> str:
    """An answer as the instrument spells it (MMAT stores "can't tell" as
    `unclear`; a spreadsheet reader should see the tool's own word)."""
    labels = (checklist or {}).get("option_labels") or {}
    return labels.get(answer, answer)


def appraisal_export_rows(db: Session, project_id: int) -> tuple[list[str], list[list]]:
    """The dedicated appraisal table: one line per study × assessor — study
    metadata, design, the per-question answers laid out wide (a blank cell
    means the design's checklist has no such question) and, when the
    instrument has them, the score (criteria met) and the overall judgement.

    Reads the instrument the project appraises with, not one catalogue:
    appraisals recorded under another instrument (the project switched) are
    still exported, under the ids they were answered with, in an extra block
    of columns so nothing is silently dropped.
    """
    from app.models import User
    names = {u.id: u.display_name for u in db.query(User)}
    inst = appraisal_core.instrument_of(db, project_id)
    appraisals = (db.query(JbiAppraisal, Record, ExtractionStudy)
                  .join(Record, Record.id == JbiAppraisal.record_id)
                  .join(ExtractionStudy, ExtractionStudy.id == JbiAppraisal.study_id)
                  .filter(Record.project_id == project_id)
                  .order_by(Record.id, ExtractionStudy.position,
                            JbiAppraisal.user_id).all())
    qids = instrument_question_columns(inst)
    # answers keyed by ids the instrument does not know (another instrument's)
    extra: list[str] = []
    for appraisal, _, _ in appraisals:
        for qid in (appraisal.answers or {}):
            if qid not in qids and qid not in extra:
                extra.append(qid)
    header = ["Record ID", "Study", "First author", "Year", "Title", "DOI",
              "Design", "Instrument", "Assessor"]
    if inst.score:
        header += ["Score (yes)", "Out of", "Answered"]
    else:
        header += ["Answered", "Out of"]
    if inst.overall:
        header += ["Overall appraisal"]
    header += ["Overall comment"] + qids + extra
    out = []
    for appraisal, record, study in appraisals:
        checklist = instruments.checklist_for(inst, appraisal.design)
        s = instruments.score(inst, appraisal.design, appraisal.answers)
        answers = appraisal.answers or {}
        if s is None:
            # the design has no checklist in this instrument: the answers
            # were given under another one — report what was answered
            s = {"n_yes": sum(1 for e in answers.values()
                              if (e or {}).get("answer") == "yes"),
                 "n_questions": len(answers),
                 "n_answered": sum(1 for e in answers.values()
                                   if (e or {}).get("answer"))}
        design_qids = (set(instruments.question_ids(inst, appraisal.design))
                       if checklist else set(answers))
        line = [record.id, study.label, (record.authors or [""])[0], record.year,
                record.title, record.doi or "", appraisal.design,
                appraisal.instrument, names.get(appraisal.user_id, "?")]
        if inst.score:
            line += [s["n_yes"], s["n_questions"], s["n_answered"]]
        else:
            line += [s["n_answered"], s["n_questions"]]
        if inst.overall:
            line.append(appraisal.overall)
        line.append(appraisal.comment)
        for qid in qids + extra:
            line.append(_export_answer(checklist,
                                       (answers.get(qid) or {}).get("answer", ""))
                        if qid in design_qids or qid in extra else "")
        out.append(line)
    return header, out


# kept for callers that still think "JBI"
jbi_export_rows = appraisal_export_rows


def _fmt(v) -> str:
    if v is None:
        return ""
    if isinstance(v, list):
        return "; ".join(str(x) for x in v)
    if isinstance(v, bool):
        return "yes" if v else "no"
    return str(v)


def _export_cell(cell_values: list[dict], names: dict[int, str]) -> str:
    if not cell_values:
        return ""
    validated = [c for c in cell_values if c["validated"]]
    if validated:
        distinct = {_fmt(c["value"]) for c in validated}
        if len(distinct) == 1:
            return distinct.pop()
        cell_values = validated
    distinct = {_fmt(c["value"]) for c in cell_values}
    if len(distinct) == 1:
        return distinct.pop()
    return " | ".join(
        f"{names.get(c['user_id'], 'AI' if c['origin'] == 'ai' else '?')}: "
        f"{_fmt(c['value'])}" for c in cell_values)
