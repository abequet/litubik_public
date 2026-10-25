# SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
# SPDX-License-Identifier: AGPL-3.0-or-later
"""M9 AI helpers — always on demand, per article (user decision): column
suggestion from the validated protocol, study-design qualification, and
row prefill from the stored PDF. AI output is never validated automatically."""
from sqlalchemy.orm import Session

from app.models import (
    ExtractionColumn, ExtractionValue, FullText, Project, Record,
)
from app.services import framing
from app.services.appraisal.instruments import DESIGNS
from app.services.extraction.service import COLUMN_TYPES, coerce_value
from app.services.llm import pricing
from app.services.llm.base import LLMError
from app.services.llm.credentials import open_provider_chain, resolve_model
from app.services.llm.prompts import resolve_prompt
from app.services.protocol.service import validated_protocol
from app.services.screening.ai import extract_pdf_text, pdf_ai_block_reason


def _cost(provider, result) -> dict:
    """What an on-demand extraction AI call actually cost (shown in the UI)."""
    return pricing.call_cost(provider, result)


def pdf_block_reason(db: Session, record: Record) -> str | None:
    """Why this record's stored PDF may not be sent to the AI (over the page
    limit), or None."""
    ft = db.query(FullText).filter_by(record_id=record.id).first()
    if ft is None or not ft.file_path:
        return None
    return pdf_ai_block_reason(ft.file_path)


def estimate_record_cost(db: Session, project_id: int, record: Record,
                         kind: str) -> dict | None:
    """Up-front cost estimate for a per-article AI button (fill / design /
    jbi), shown on hover. None when no API key is configured."""
    model = resolve_model(db, project_id, feature="extraction_prefill")
    if model is None:
        return None
    provider, model_id = model
    ft = db.query(FullText).filter_by(record_id=record.id).first()
    pdf_chars = 0
    # a PDF over the page limit is never sent (design falls back to the abstract)
    if ft is not None and ft.file_path \
            and pdf_ai_block_reason(ft.file_path) is None:
        pdf_chars = min(round((ft.size_kb or 0) * 1024 * 0.35), 60000)
    if kind == "design":
        chars = 2000 + len(record.title or "") + len(record.abstract or "") \
            + min(pdf_chars, 20000)
        out_tokens = 250
    elif kind == "jbi":
        chars = 3000 + pdf_chars           # checklist scaffolding + full text
        out_tokens = 700
    else:                                   # prefill
        n_cols = (db.query(ExtractionColumn)
                  .filter_by(project_id=project_id).count())
        protocol = validated_protocol(db, project_id)
        chars = (2000 + pdf_chars + n_cols * 60
                 + (len((protocol.protocol_md or "")[:6000]) if protocol else 0))
        out_tokens = max(n_cols, 1) * 80
    tokens_in = pricing.chars_to_tokens(chars)
    return {**pricing.cost_breakdown(provider, model_id, tokens_in, out_tokens),
            "estimated": True}

COLUMNS_SCHEMA = {
    "type": "object",
    "properties": {
        "columns": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "col_type": {"type": "string", "enum": list(COLUMN_TYPES)},
                    "description": {"type": "string"},
                    "options": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["name", "col_type", "description"],
            },
        },
    },
    "required": ["columns"],
}


def suggest_columns(db: Session, project_id: int,
                    user_id: int | None = None) -> dict:
    """Extraction columns tailored to the validated protocol (on demand).
    Returns {"columns": [...], "cost": {...}}."""
    protocol = validated_protocol(db, project_id)
    if protocol is None:
        raise LLMError("Validate the protocol first — the AI derives the "
                       "columns from it")
    provider = open_provider_chain(db, project_id,
                                   feature="extraction_columns",
                                   user_id=user_id)
    system = (
        resolve_prompt(db, project_id, "extraction_columns")
        + framing.review_context(db.get(Project, project_id))
        + "\n\nValidated protocol:\n" + protocol.protocol_md[:12000]
    )
    result = provider.generate_json(
        [{"role": "user", "content": "Propose the extraction columns."}],
        json_schema=COLUMNS_SCHEMA, system=system, max_tokens=3000)
    data = result.data if isinstance(result.data, dict) else {}
    out = []
    for c in data.get("columns", []):
        if not c.get("name") or c.get("col_type") not in COLUMN_TYPES:
            continue
        out.append({"name": str(c["name"])[:255],
                    "col_type": c["col_type"],
                    "description": str(c.get("description", "")),
                    "options": [str(o) for o in (c.get("options") or [])]})
    return {"columns": out, "cost": _cost(provider, result)}


DESIGN_SCHEMA = {
    "type": "object",
    "properties": {
        # the shared design vocabulary, not one instrument's — a study's
        # design does not change with the tool used to appraise it
        "design": {"type": "string", "enum": list(DESIGNS)},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "rationale": {"type": "string"},
    },
    "required": ["design", "confidence", "rationale"],
}


def suggest_design(db: Session, project_id: int, record: Record,
                   user_id: int | None = None) -> dict:
    """Qualify the study design (per article, on demand) so the matching JBI
    checklist can be filled. Uses the stored PDF when available."""
    provider = open_provider_chain(db, project_id, feature="extraction_design",
                                   user_id=user_id)
    ft = db.query(FullText).filter_by(record_id=record.id).first()
    body = ""
    if ft is not None and ft.file_path:
        try:
            body = extract_pdf_text(ft.file_path, max_chars=20000)
        except LLMError:
            # unreadable, or over the page limit: title + abstract only
            body = ""
    designs = "\n".join(f"- {key}: {label}" for key, label in DESIGNS.items())
    system = (
        resolve_prompt(db, project_id, "extraction_design")
        + "\n\nDesign keys:\n" + designs
    )
    content = (f"Title: {record.title}\n"
               + (f"Abstract: {record.abstract}\n" if record.abstract else "")
               + (f"\nFull text (truncated):\n{body}" if body else ""))
    result = provider.generate_json([{"role": "user", "content": content}],
                                    json_schema=DESIGN_SCHEMA, system=system,
                                    max_tokens=1500)
    data = result.data if isinstance(result.data, dict) else {}
    return {"design": str(data.get("design", "other")),
            "confidence": float(data.get("confidence") or 0.0),
            "rationale": str(data.get("rationale", "")),
            "cost": _cost(provider, result)}


def suggest_jbi(db: Session, project_id: int, record: Record,
                user_id: int | None = None) -> dict:
    """Propose answers for the record's appraisal checklist from its stored PDF
    (on demand, per article). Returns suggestions only — nothing is saved;
    the UI prefill stays the assessor's to review, edit and save."""
    from app.services.appraisal import core as appraisal_core
    from app.services.appraisal import instruments

    design = record.study_design or ""
    inst = appraisal_core.instrument_of(db, project_id)
    checklist = instruments.checklist_for(inst, design)
    if checklist is None:
        raise LLMError("Set the study design first — it selects the "
                       "checklist the AI should fill")
    ft = db.query(FullText).filter_by(record_id=record.id).first()
    if ft is None or not ft.file_path:
        raise LLMError("No stored PDF for this record — the appraisal "
                       "reads the full text")
    body = extract_pdf_text(ft.file_path)
    provider = open_provider_chain(db, project_id, feature="extraction_jbi",
                                   user_id=user_id)

    options = checklist["options"]
    questions = [(q["id"], domain["label"], q["text"])
                 for domain in checklist["domains"]
                 for q in domain["questions"]]
    q_lines = "\n".join(f"- [{qid}] ({dom}) {text}"
                        for qid, dom, text in questions)
    schema = {
        "type": "object",
        "properties": {
            "answers": {
                "type": "object",
                "properties": {
                    qid: {
                        "type": "object",
                        "properties": {
                            "answer": {"type": "string", "enum": options},
                            "comment": {
                                "type": "string",
                                "description": "The deciding evidence, quoted "
                                               "or closely paraphrased from "
                                               "the report (1-2 sentences)"},
                        },
                        "required": ["answer", "comment"],
                    } for qid, _, _ in questions
                },
                "required": [qid for qid, _, _ in questions],
            },
        },
        "required": ["answers"],
    }
    # an instrument may spell an answer its own way (MMAT: "can't tell" is
    # stored as `unclear`) — the model answers with the stored value and is
    # told what it stands for
    labels = checklist.get("option_labels") or {}
    allowed = ", ".join(f"{o} (= {labels[o]})" if o in labels else o
                        for o in options)
    system = (
        resolve_prompt(db, project_id, "extraction_jbi")
        + f"\n\nInstrument: {inst.label}"
        + f"\nChecklist: {checklist['label']}"
        + f"\nAllowed answers: {allowed}"
        + "\n\nQuestions:\n" + q_lines
    )
    content = f"Title: {record.title}\n\nFull text (may be truncated):\n{body}"
    result = provider.generate_json([{"role": "user", "content": content}],
                                    json_schema=schema, system=system,
                                    max_tokens=4000)
    data = result.data if isinstance(result.data, dict) else {}
    raw = data.get("answers") or {}
    valid_ids = {qid for qid, _, _ in questions}
    answers = {}
    for qid, entry in raw.items():
        if qid not in valid_ids or not isinstance(entry, dict):
            continue
        if entry.get("answer") not in options:
            continue
        answers[qid] = {"answer": entry["answer"],
                        "comment": str(entry.get("comment", ""))}
    return {"design": design, "answers": answers,
            "cost": _cost(provider, result)}


def _prefill_schema(columns: list[ExtractionColumn]) -> dict:
    props = {}
    for col in columns:
        desc = f"{col.description or col.name}"
        if col.col_type == "number":
            spec = {"type": ["number", "null"], "description": desc}
        elif col.col_type == "bool":
            spec = {"type": ["boolean", "null"], "description": desc}
        elif col.col_type == "choice":
            spec = {"type": ["string", "null"],
                    "enum": (col.options or []) + [None], "description": desc}
        elif col.col_type == "multi":
            spec = {"type": "array", "items": {"type": "string",
                                               "enum": col.options or []},
                    "description": desc}
        else:
            spec = {"type": ["string", "null"], "description": desc}
        props[str(col.id)] = spec
    study = {"type": "object",
             "properties": {"label": {"type": "string",
                                      "description": "Short name of the study as "
                                                     "the paper calls it (e.g. "
                                                     "'Study 2', 'Experiment B')"},
                            "fields": {"type": "object", "properties": props}},
             "required": ["label", "fields"]}
    return {"type": "object",
            "properties": {"studies": {"type": "array", "items": study,
                                       "description": "One entry per distinct "
                                                      "study the paper reports; "
                                                      "most papers report one"},
                           "notes": {"type": "string"}},
            "required": ["studies"]}


def prefill_record(db: Session, project_id: int, record: Record,
                   user_id: int) -> dict:
    """Fill this record's row(s) from its stored PDF (on demand, per article).
    The model answers one entry per study the paper reports: entries map onto
    the article's existing studies in order (by label when one matches), and
    extra entries create new studies — never the other way round. Only cells
    the extractor has not already filled by hand are written; everything
    lands as origin='ai', validated=False."""
    from app.services.extraction import studies as ext_studies
    columns = (db.query(ExtractionColumn).filter_by(project_id=project_id)
               .order_by(ExtractionColumn.position, ExtractionColumn.id).all())
    if not columns:
        raise LLMError("Define extraction columns first")
    ft = db.query(FullText).filter_by(record_id=record.id).first()
    if ft is None or not ft.file_path:
        raise LLMError("No stored PDF for this record — the AI prefill reads "
                       "the full text")
    body = extract_pdf_text(ft.file_path)
    provider = open_provider_chain(db, project_id,
                                   feature="extraction_prefill",
                                   user_id=user_id)
    protocol = validated_protocol(db, project_id)
    col_lines = "\n".join(
        f"- [{c.id}] {c.name} ({c.col_type}"
        + (f", options: {', '.join(c.options)}" if c.options else "") + "): "
        + (c.description or "") for c in columns)
    existing_studies = ext_studies.studies_for_records(db, [record.id],
                                                       user_id)[record.id]
    system = (
        resolve_prompt(db, project_id, "extraction_prefill")
        + "\n\nFields (key = column id):\n" + col_lines
        + "\n\nReturn one entry in `studies` per distinct study the paper "
          "reports (separate samples, experiments or trials with their own "
          "results). Most papers report a single study: then return exactly "
          "one entry. Studies already declared for this paper, in order: "
        + "; ".join(s.label for s in existing_studies)
        + ("\n\nReview protocol for context:\n" + protocol.protocol_md[:6000]
           if protocol else "")
    )
    content = (f"Title: {record.title}\n\nFull text (may be truncated):\n{body}")
    result = provider.generate_json([{"role": "user", "content": content}],
                                    json_schema=_prefill_schema(columns),
                                    system=system, max_tokens=6000)
    data = result.data if isinstance(result.data, dict) else {}
    entries = data.get("studies")
    if not isinstance(entries, list) or not entries:
        # tolerate the flat pre-study answer shape
        entries = [{"label": "", "fields": data.get("fields") or {}}]
    by_id = {str(c.id): c for c in columns}
    written, skipped, created = 0, 0, 0
    used: set[int] = set()
    for i, entry in enumerate(entries[:ext_studies.MAX_STUDIES]):
        if not isinstance(entry, dict):
            continue
        label = str(entry.get("label") or "").strip()
        target = next((s for s in existing_studies
                       if label and s.label.strip().lower() == label.lower()
                       and s.id not in used), None)
        if target is None:
            target = next((s for s in existing_studies if s.id not in used), None)
        if target is None:
            target = ext_studies.add_study(db, record, label or f"Study {i + 1}",
                                           user_id)
            existing_studies.append(target)
            created += 1
        used.add(target.id)
        for key, raw in (entry.get("fields") or {}).items():
            col = by_id.get(str(key))
            if col is None or raw is None or raw == "" or raw == []:
                continue
            try:
                payload = coerce_value(col, raw)
            except ValueError:
                continue
            existing = (db.query(ExtractionValue)
                        .filter_by(study_id=target.id, column_id=col.id,
                                   user_id=user_id).first())
            if existing is not None and (existing.origin == "human"
                                         or existing.validated):
                skipped += 1  # never overwrite human work
                continue
            if existing is None:
                existing = ExtractionValue(record_id=record.id, study_id=target.id,
                                           column_id=col.id, user_id=user_id)
                db.add(existing)
            existing.value = payload
            existing.origin = "ai"
            existing.validated = False
            written += 1
    db.commit()
    return {"written": written, "skipped_human": skipped,
            "studies_created": created,
            "notes": str(data.get("notes", "")),
            "cost": _cost(provider, result)}
