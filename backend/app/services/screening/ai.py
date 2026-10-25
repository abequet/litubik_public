# SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
# SPDX-License-Identifier: AGPL-3.0-or-later
"""On-click AI screening suggestion (never automatic, never a vote).

One suggestion per record/stage/round, cached as an is_ai Vote row so a second
reviewer's click costs nothing. The validated protocol.md is the system
context pack, per the master plan.
"""
from pathlib import Path

from sqlalchemy.orm import Session

from app.models import FullText, Record, ScreeningConfig, Vote
from app.services.llm import pricing
from app.services.llm.base import LLMError
from app.services.llm.credentials import open_provider_chain, resolve_model
from app.services.llm.prompts import resolve_prompt
from app.services.protocol.service import validated_protocol

# Rough scaffolding for cost estimates: the fixed instruction block (~), plus
# the analysis-first suggestion output is typically ~700 tokens.
_EST_PROMPT_CHARS = 6000
_EST_OUTPUT_TOKENS = 700


def _cost(provider, result) -> dict:
    """Actual cost of a completed call (attached to the returned suggestion)."""
    return pricing.call_cost(provider, result)


def estimate_suggestion_cost(db: Session, config: ScreeningConfig,
                             record: Record) -> dict | None:
    """Up-front per-record cost estimate for an AI suggestion (button hover).
    None when no API key is configured."""
    model = resolve_model(db, config.project_id, feature="screening_ta_suggest")
    if model is None:
        return None
    provider, model_id = model
    protocol = validated_protocol(db, config.project_id)
    chars = _EST_PROMPT_CHARS + len((protocol.protocol_md or "")[:12000]
                                    if protocol else "")
    if config.stage == "ft":
        ft = db.query(FullText).filter_by(record_id=record.id).first()
        if ft and ft.file_path:
            chars += min(round((ft.size_kb or 0) * 1024 * 0.35), FT_MAX_CHARS)
    else:
        chars += len(record.abstract or "") + 400
    tokens_in = pricing.chars_to_tokens(chars)
    return {**pricing.cost_breakdown(provider, model_id, tokens_in,
                                     _EST_OUTPUT_TOKENS),
            "estimated": True}

SUGGEST_SCHEMA = {
    "type": "object",
    "properties": {
        # generated FIRST on purpose: forces the model to reason before deciding
        "analysis": {
            "type": "string",
            "description": "Step-by-step assessment against each criterion, "
                           "quoting the abstract. For any numeric criterion "
                           "(sample size, dates, durations): list EVERY number "
                           "found in the abstract and write the arithmetic "
                           "explicitly (e.g. 'two groups of 9 -> total N = 18') "
                           "before concluding.",
        },
        "decision": {"type": "string", "enum": ["include", "exclude", "maybe"]},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "criteria": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "code": {"type": "string"},
                    "assessment": {"type": "string",
                                   "enum": ["met", "not_met", "unclear"]},
                    "note": {"type": "string"},
                },
                "required": ["code", "assessment"],
            },
        },
        "justification": {"type": "string",
                          "description": "2-3 sentences, grounded in the criteria"},
    },
    "required": ["analysis", "decision", "confidence", "justification"],
}


def get_or_create_suggestion(db: Session, config: ScreeningConfig,
                             record: Record, force: bool = False,
                             generated_by: str | None = None,
                             user_id: int | None = None) -> Vote:
    existing = (db.query(Vote)
                .filter_by(project_id=config.project_id, record_id=record.id,
                           stage=config.stage, round=config.round, is_ai=True)
                .first())
    if existing is not None:
        if not force:
            return existing
        db.delete(existing)
        db.flush()

    protocol = validated_protocol(db, config.project_id)
    if protocol is None:
        raise LLMError("Validate the protocol first — it is the context the AI "
                       "screens against")
    provider = open_provider_chain(db, config.project_id,
                                   feature="screening_ta_suggest",
                                   user_id=user_id)

    system = (
        resolve_prompt(db, config.project_id, "screening_ta_suggest")
        + "\n\nReview protocol (validated):\n" + protocol.protocol_md[:12000]
    )
    # full bibliographic context — year matters for period criteria
    meta_lines = [f"Title: {record.title}"]
    if record.authors:
        meta_lines.append("Authors: " + "; ".join(map(str, record.authors[:10])))
    if record.year:
        meta_lines.append(f"Publication year: {record.year}")
    if record.journal:
        meta_lines.append(f"Journal/venue: {record.journal}")
    if record.doi:
        meta_lines.append(f"DOI: {record.doi}")
    content = "\n".join(meta_lines) + f"\n\nAbstract: {record.abstract or '(none)'}"
    # generous budget: the analysis-first output is long, and some models spend
    # part of it on internal reasoning blocks before any text
    result = provider.generate_json([{"role": "user", "content": content}],
                                    json_schema=SUGGEST_SCHEMA, system=system,
                                    max_tokens=4000)
    data = result.data if isinstance(result.data, dict) else {}
    criteria = data.get("criteria", [])
    decision = str(data.get("decision", "maybe"))
    # server-side consistency check: the model sometimes argues one way and
    # concludes another — surface it instead of trusting the decision field
    warning = ""
    exclusion_met = [c.get("code", "?") for c in criteria
                     if str(c.get("code", "")).upper().startswith("E")
                     and c.get("assessment") == "met"]
    if exclusion_met and decision == "include":
        warning = ("Inconsistent output: exclusion criteria "
                   f"{', '.join(exclusion_met)} assessed as met but the model "
                   "answered 'include'. Treat with extra care.")
    suggestion = Vote(
        project_id=config.project_id, record_id=record.id, stage=config.stage,
        round=config.round, voter_user_id=None, is_ai=True,
        decision=decision,
        justification=str(data.get("justification", "")),
        criteria_eval={"criteria": criteria, "warning": warning,
                       "analysis": str(data.get("analysis", ""))},
        confidence=float(data.get("confidence") or 0.0),
        generated_by=generated_by,  # sync: whose instance produced it
    )
    db.add(suggestion)
    db.commit()
    db.refresh(suggestion)
    suggestion.last_cost = _cost(provider, result)
    return suggestion


# -- full-text suggestion (M7) ----------------------------------------------------

FT_MAX_CHARS = 60000  # keep the prompt bounded; cost estimate is shown up-front

FT_SUGGEST_SCHEMA = {
    "type": "object",
    "properties": {
        "analysis": {
            "type": "string",
            "description": "Step-by-step assessment against each criterion, "
                           "quoting the full text. Do the arithmetic explicitly "
                           "for any numeric criterion.",
        },
        "decision": {"type": "string", "enum": ["include", "exclude", "maybe"]},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "criteria": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "code": {"type": "string"},
                    "assessment": {"type": "string",
                                   "enum": ["met", "not_met", "unclear"]},
                    "note": {"type": "string"},
                },
                "required": ["code", "assessment"],
            },
        },
        "reasons": {
            "type": "array",
            "description": "If decision is 'exclude': the exclusion criteria codes "
                           "(E*) that justify it, most important first. Empty otherwise.",
            "items": {"type": "string"},
        },
        "justification": {"type": "string",
                          "description": "2-3 sentences, grounded in the criteria"},
    },
    "required": ["analysis", "decision", "confidence", "justification"],
}


# A stored file longer than this is a book, a thesis or a whole proceedings
# volume rather than a report: the truncated prompt would show the model its
# front matter only, and the answer would look as confident as any other.
# Such a PDF is never sent to the AI — it is assessed by hand.
AI_PDF_MAX_PAGES = 45


def _too_long_message(n_pages: int) -> str:
    return (f"This PDF has {n_pages} pages — over the {AI_PDF_MAX_PAGES}-page "
            "limit for AI analysis (a book, a thesis or a proceedings volume "
            "rather than a single report?). Assess it manually, or replace "
            "the file with the report itself.")


def pdf_ai_block_reason(file_path: str) -> str | None:
    """Why the AI buttons must refuse this stored PDF, or None when it may be
    sent. Lets the UI disable the button up-front; a missing or unreadable
    file is not reported here — the call itself surfaces that."""
    import pymupdf

    try:
        with pymupdf.open(file_path) as doc:
            n_pages = doc.page_count
    except Exception:
        return None
    return _too_long_message(n_pages) if n_pages > AI_PDF_MAX_PAGES else None


def extract_pdf_text(file_path: str, max_chars: int = FT_MAX_CHARS) -> str:
    import pymupdf

    path = Path(file_path)
    if not path.exists():
        raise LLMError("The stored PDF is missing on disk")
    try:
        with pymupdf.open(path) as doc:
            n_pages = doc.page_count
            text = ("" if n_pages > AI_PDF_MAX_PAGES
                    else "\n\n".join(page.get_text() for page in doc))
    except Exception as e:  # pymupdf.FileDataError et al.
        raise LLMError(f"Could not read the PDF: {e}") from e
    if n_pages > AI_PDF_MAX_PAGES:
        raise LLMError(_too_long_message(n_pages))
    text = text.strip()
    if not text:
        raise LLMError("No text could be extracted from this PDF "
                       "(scanned without OCR?) — screen it manually")
    return text[:max_chars]


def estimate_ft_cost(db: Session, config: ScreeningConfig,
                     record_ids: list[int]) -> dict:
    """Rough token/char budget for a batch full-text AI pass (shown before any
    call). Counts only records with a stored PDF."""
    fts = {ft.record_id: ft for ft in db.query(FullText)
           .filter(FullText.record_id.in_(record_ids))} if record_ids else {}
    n_pdf = 0
    chars = 0
    for rid in record_ids:
        ft = fts.get(rid)
        if ft and ft.file_path and Path(ft.file_path).exists():
            n_pdf += 1
            # protocol + instruction scaffolding is re-sent per record
            chars += (_EST_PROMPT_CHARS
                      + min(round((ft.size_kb or 0) * 1024 * 0.35), FT_MAX_CHARS))
    tokens_in = pricing.chars_to_tokens(chars)
    out = {"records_with_pdf": n_pdf,
           "records_without_pdf": len(record_ids) - n_pdf,
           "approx_input_chars": chars, "approx_input_tokens": tokens_in}
    model = resolve_model(db, config.project_id, feature="screening_ft_suggest")
    if model is not None:
        provider, model_id = model
        out["cost"] = {**pricing.cost_breakdown(
            provider, model_id, tokens_in, _EST_OUTPUT_TOKENS * n_pdf),
            "estimated": True}
    return out


def get_or_create_ft_suggestion(db: Session, config: ScreeningConfig,
                                record: Record, force: bool = False,
                                generated_by: str | None = None,
                                user_id: int | None = None) -> Vote:
    """On-click AI suggestion for a full-text record: reads the stored PDF and
    screens it against the validated protocol. Cached as an is_ai Vote."""
    existing = (db.query(Vote)
                .filter_by(project_id=config.project_id, record_id=record.id,
                           stage=config.stage, round=config.round, is_ai=True)
                .first())
    if existing is not None:
        if not force:
            return existing
        db.delete(existing)
        db.flush()

    protocol = validated_protocol(db, config.project_id)
    if protocol is None:
        raise LLMError("Validate the protocol first — it is the context the AI "
                       "screens against")
    ft = db.query(FullText).filter_by(record_id=record.id).first()
    if ft is None or not ft.file_path:
        raise LLMError("No full text stored for this record — retrieve or upload "
                       "the PDF first")
    body = extract_pdf_text(ft.file_path)

    provider = open_provider_chain(db, config.project_id,
                                   feature="screening_ft_suggest",
                                   user_id=user_id)

    system = (
        resolve_prompt(db, config.project_id, "screening_ft_suggest")
        + "\n\nReview protocol (validated):\n" + protocol.protocol_md[:12000]
    )
    meta_lines = [f"Title: {record.title}"]
    if record.year:
        meta_lines.append(f"Publication year: {record.year}")
    if record.journal:
        meta_lines.append(f"Journal/venue: {record.journal}")
    content = ("\n".join(meta_lines)
               + "\n\nFull text (may be truncated):\n" + body)
    result = provider.generate_json([{"role": "user", "content": content}],
                                    json_schema=FT_SUGGEST_SCHEMA, system=system,
                                    max_tokens=4000)
    data = result.data if isinstance(result.data, dict) else {}
    criteria = data.get("criteria", [])
    decision = str(data.get("decision", "maybe"))
    reasons = [str(c) for c in (data.get("reasons") or [])]
    warning = ""
    exclusion_met = [c.get("code", "?") for c in criteria
                     if str(c.get("code", "")).upper().startswith("E")
                     and c.get("assessment") == "met"]
    if exclusion_met and decision == "include":
        warning = ("Inconsistent output: exclusion criteria "
                   f"{', '.join(exclusion_met)} assessed as met but the model "
                   "answered 'include'. Treat with extra care.")
    # sensible fallback: if excluding but no reasons proposed, use the met E-codes
    if decision == "exclude" and not reasons and exclusion_met:
        reasons = exclusion_met
    suggestion = Vote(
        project_id=config.project_id, record_id=record.id, stage=config.stage,
        round=config.round, voter_user_id=None, is_ai=True, decision=decision,
        reasons=reasons,
        justification=str(data.get("justification", "")),
        criteria_eval={"criteria": criteria, "warning": warning,
                       "analysis": str(data.get("analysis", ""))},
        confidence=float(data.get("confidence") or 0.0),
        generated_by=generated_by,  # sync: whose instance produced it
    )
    db.add(suggestion)
    db.commit()
    db.refresh(suggestion)
    suggestion.last_cost = _cost(provider, result)
    return suggestion
