# SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
# SPDX-License-Identifier: AGPL-3.0-or-later
"""LLM structured extraction of a pre-registered protocol + protocol.md rendering.

The LLM returns structured JSON; the markdown is rendered deterministically so
every project gets the same document shape. Criteria codes (I1…, E1…) are
assigned server-side — the model's own numbering is never trusted.
"""
from sqlalchemy.orm import Session

from app.models import Protocol
from app.services import framing

_BASE_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string", "description": "Title of the review/protocol"},
        "background": {
            "type": "string",
            "description": "Theoretical background and rationale, faithful summary "
                           "in markdown (2-5 paragraphs)",
        },
        "research_questions": {"type": "array", "items": {"type": "string"}},
        "objectives": {"type": "array", "items": {"type": "string"}},
        "scope": {
            "type": "string",
            "description": "Scope and perimeter the framing fields above do "
                           "not already cover: time span, languages, "
                           "disciplines, settings",
        },
        "search_concepts": {
            "type": "array",
            "description": "Search concepts (concept blocks) the protocol "
                           "itself names for its search strategy, with the "
                           "keywords/synonyms it lists for each. Copy them as "
                           "written; empty array if the protocol describes none.",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Concept name as stated"},
                    "keywords": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["name"],
            },
        },
        "search_strategy_notes": {
            "type": "string",
            "description": "What the protocol says about the search strategy "
                           "itself (databases, boolean equation, limits) — "
                           "empty if it says nothing",
        },
        "inclusion_criteria": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "label": {"type": "string", "description": "Short name (3-6 words)"},
                    "description": {"type": "string", "description": "Full criterion as stated"},
                },
                "required": ["label", "description"],
            },
        },
        "exclusion_criteria": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "label": {"type": "string"},
                    "description": {"type": "string"},
                },
                "required": ["label", "description"],
            },
        },
    },
    "required": ["background", "research_questions", "objectives",
                 "inclusion_criteria", "exclusion_criteria"],
}


def extraction_schema(framework_key: str | None = None) -> dict:
    """The extraction schema for a project's question framework.

    The framework's slots become the properties of a `framing` object — PICO's
    population/intervention/comparison/outcome, SPIDER's sample/phenomenon of
    interest/…, and so on. Nothing here is `required`: a protocol silent about
    its population must still extract. (The schema is instruction-only anyway —
    LLMProvider.generate_json serialises it into the system prompt and parses
    whatever comes back; see services/llm/base.py.)
    """
    fw = framing.framework(framework_key)
    schema = {**_BASE_SCHEMA, "properties": dict(_BASE_SCHEMA["properties"])}
    schema["properties"]["framing"] = {
        "type": "object",
        "description": f"How the protocol frames its question, following the "
                       f"{fw.short} framework. Fill only what the document "
                       f"actually states; leave a field out when it says "
                       f"nothing about it.",
        "properties": {s.key: {"type": "string", "description": s.hint}
                       for s in fw.slots},
    }
    return schema


# Kept for callers written before the framework became a project setting.
EXTRACTION_SCHEMA = extraction_schema(framing.DEFAULT_FRAMEWORK)

# The extraction instructions live in app/services/llm/prompts.py
# ("protocol_extract") — editable per project from the Settings page.


def build_extraction_messages(source_text: str) -> list[dict]:
    return [{
        "role": "user",
        "content": (
            "Extract the structure of the following review protocol document.\n"
            "<protocol_document>\n" + source_text + "\n</protocol_document>"
        ),
    }]


def normalize_criteria(structured: dict) -> list[dict]:
    """Flatten inclusion/exclusion lists into coded criteria.

    Codes are assigned sequentially (I1…, E1…) in document order; they are the
    stable identifiers later used as screening/exclusion reason codes.
    """
    criteria: list[dict] = []
    for kind, prefix in (("inclusion_criteria", "I"), ("exclusion_criteria", "E")):
        for i, item in enumerate(structured.get(kind) or [], start=1):
            label = str(item.get("label", "")).strip()
            description = str(item.get("description", "")).strip()
            if not label and not description:
                continue
            criteria.append({
                "code": f"{prefix}{i}",
                "type": "include" if prefix == "I" else "exclude",
                "label": label or description[:60],
                "description": description,
            })
    return criteria


def _framing_lines(structured: dict, framework_key: str | None) -> list[str]:
    """The question-framing section: one line per slot the document filled.

    Falls back to the pre-framework shape (`population` / `scope` at the top
    level) so protocols extracted by an earlier version — and a model that
    answers in the old form — still render.
    """
    fw = framing.framework(framework_key)
    values = structured.get("framing")
    if not isinstance(values, dict):
        values = {}
    pairs = [(s.label, str(values.get(s.key, "")).strip()) for s in fw.slots]
    pairs = [(label, value) for label, value in pairs if value]
    if not pairs and structured.get("population"):
        pairs = [("Population", str(structured["population"]).strip())]

    scope = (structured.get("scope") or "").strip()
    if not pairs and not scope:
        return []

    # PICO/PICOS keep the historical heading: those protocols are the existing
    # corpus and the section is the same thing under a different name.
    heading = ("## Population & scope" if fw.key in ("pico", "picos")
               else f"## Question framing ({fw.short})")
    lines = ["", heading, ""]
    body = [f"**{label}:** {value}" for label, value in pairs]
    if scope:
        body.append(f"**Scope:** {scope}")
    lines += "\n\n".join(body).split("\n")
    return lines


def render_protocol_md(structured: dict, criteria: list[dict],
                       framework_key: str | None = None) -> str:
    """Deterministic protocol.md — the validated version becomes the context
    pack injected into every AI prompt of the pipeline."""
    lines: list[str] = []
    title = (structured.get("title") or "").strip()
    lines.append(f"# {title}" if title else "# Review protocol")

    background = (structured.get("background") or "").strip()
    if background:
        lines += ["", "## Background", "", background]

    questions = [q.strip() for q in structured.get("research_questions") or [] if q.strip()]
    if questions:
        lines += ["", "## Research questions", ""]
        lines += [f"{i}. {q}" for i, q in enumerate(questions, start=1)]

    objectives = [o.strip() for o in structured.get("objectives") or [] if o.strip()]
    if objectives:
        lines += ["", "## Objectives", ""]
        lines += [f"- {o}" for o in objectives]

    lines += _framing_lines(structured, framework_key)

    # The structured extraction is not persisted — protocol_md is the only
    # durable channel, so what the protocol says about its own search concepts
    # has to be rendered here or it never reaches the equation builder.
    search_concepts = []
    for item in structured.get("search_concepts") or []:
        name = str(item.get("name", "")).strip()
        keywords = [str(k).strip() for k in item.get("keywords") or [] if str(k).strip()]
        if name:
            search_concepts.append((name, keywords))
    notes = (structured.get("search_strategy_notes") or "").strip()
    if search_concepts or notes:
        lines += ["", "## Search concepts", ""]
        lines += [f"- **{name}**: {', '.join(keywords) if keywords else '—'}"
                  for name, keywords in search_concepts]
        if notes:
            lines += ["", f"**Search strategy:** {notes}"]

    for kind, heading in (("include", "## Inclusion criteria"),
                          ("exclude", "## Exclusion criteria")):
        subset = [c for c in criteria if c["type"] == kind]
        if subset:
            lines += ["", heading, ""]
            lines += [f"- **{c['code']} — {c['label']}**: {c['description']}"
                      for c in subset]

    return "\n".join(lines).strip() + "\n"


def validated_protocol(db: Session, project_id: int) -> Protocol | None:
    """Context pack for the AI modules: the most recently validated version."""
    return (
        db.query(Protocol)
        .filter(Protocol.project_id == project_id, Protocol.validated_at.isnot(None))
        .order_by(Protocol.validated_at.desc())
        .first()
    )
