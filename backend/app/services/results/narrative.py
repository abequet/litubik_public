# SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
# SPDX-License-Identifier: AGPL-3.0-or-later
"""M10 AI narrative synthesis: a Results-section draft written from the
computed aggregates + the consensus evidence table, grounded by the validated
protocol. On demand only; the one stored artifact of the Results stage."""
from datetime import datetime, timezone

import json

from sqlalchemy.orm import Session

from app.models import Project, ResultsSynthesis
from app.services import framing
from app.services.llm import pricing
from app.services.llm.base import LLMError
from app.services.llm.credentials import open_provider_chain, resolve_model
from app.services.llm.prompts import resolve_prompt
from app.services.protocol.service import validated_protocol
from app.services.results import compute
from app.services.synthesis import core as synthesis_core
from app.services.synthesis import methods as synthesis_methods

# The evidence block is capped so any provider's context fits: per-row text
# truncation shrinks first (never below the floor), then text columns other
# than the key-findings-like ones are dropped — studies are never dropped.
EVIDENCE_BUDGET = 60_000
TEXT_TRUNC = 250
TEXT_TRUNC_FLOOR = 80
OUT_TOKENS = 4000


def _fmt(v) -> str:
    if isinstance(v, list):
        return "; ".join(str(x) for x in v)
    if isinstance(v, bool):
        return "yes" if v else "no"
    return str(v)


def _evidence_block(columns, rows) -> str:
    def build(trunc: int, cols) -> str:
        lines = []
        for row in rows:
            head = f"[{row['label']}]"
            meta = "; ".join(str(x) for x in (row["design"], row["year"]) if x)
            parts = [f"{head} ({meta})" if meta else head]
            for c in cols:
                value = row["values"].get(c.id)
                if value in (None, "", []):
                    continue
                text = _fmt(value)
                if c.col_type == "text":
                    text = text[:trunc]
                parts.append(f"{c.name}: {text}")
            lines.append(" | ".join(parts))
        return "\n".join(lines)

    block = build(TEXT_TRUNC, columns)
    if len(block) <= EVIDENCE_BUDGET:
        return block
    trunc = max(TEXT_TRUNC_FLOOR,
                int(TEXT_TRUNC * EVIDENCE_BUDGET / len(block)))
    block = build(trunc, columns)
    if len(block) <= EVIDENCE_BUDGET:
        return block
    keep = [c for c in columns
            if c.col_type != "text" or "finding" in c.name.lower()]
    return build(TEXT_TRUNC_FLOOR, keep)[:EVIDENCE_BUDGET]


def _synthesis_block(db: Session, project_id: int) -> str:
    """The synthesis the team declared, appended to the instructions.

    Without it the draft names no method and hedges no conclusion — exactly the
    two failures SWiM was written to fix (items 3 and 8: describe and justify
    the synthesis method; report each finding *with its certainty*, saying
    which studies contribute). With it, the model has to write within what the
    declared method can actually support, and cannot upgrade a vote count into
    an average effect.
    """
    plan = synthesis_core.plan_of(db, project_id)
    if not synthesis_core.is_enabled(plan):
        return ""
    outcomes = synthesis_core.outcomes_of(db, project_id)
    ratings = synthesis_core.effective_certainty(db, [o.id for o in outcomes])
    block = {
        "grouping": plan.grouping_md,
        "grouping_changes": plan.grouping_changes_md,
        "prioritisation": plan.prioritisation_md,
        "heterogeneity": plan.heterogeneity_md,
        "presentation": plan.presentation_md,
        "limitations": plan.limitations_md,
        "certainty_framework": plan.certainty_framework,
        "outcomes": [{
            "label": o.label, "comparison": o.comparison,
            "metric": o.metric,
            "synthesis_method": synthesis_methods.method(
                o.synthesis_method).label,
            "question_the_method_answers": synthesis_methods.method(
                o.synthesis_method).question,
            "n_contributing_studies": len(o.study_ids or []),
            "finding": o.finding_md,
            "certainty": ratings[o.id].final if o.id in ratings else "",
            "certainty_statement": (ratings[o.id].statement_md
                                    if o.id in ratings else ""),
        } for o in outcomes],
    }
    return (
        "\n\nThe synthesis this review declared (SWiM items 1 to 9, "
        "authoritative):\n"
        + json.dumps(block, separators=(",", ":"), ensure_ascii=False)
        + "\n\nWrite within it: structure the section by these groups and "
          "outcomes, name the synthesis method used for each, and state each "
          "finding with its certainty in the words of `certainty_statement` "
          "where one is given. Never claim more than the method supports — "
          "`question_the_method_answers` says what each one can answer. An "
          "outcome with no certainty rating is reported without one, never as "
          "if it were certain."
    )


def build_prompt(db: Session, project_id: int) -> tuple[str, str]:
    data = compute.aggregates(db, project_id)
    if data["n_included"] == 0:
        raise LLMError("No included studies yet — finish full-text screening "
                       "first")
    # the raw numeric value arrays add tokens without adding meaning
    data["columns"] = [{k: v for k, v in c.items() if k != "values"}
                       for c in data["columns"]]
    protocol = validated_protocol(db, project_id)
    system = (
        resolve_prompt(db, project_id, "results_narrative")
        + framing.review_context(db.get(Project, project_id))
        + "\n\nComputed aggregates (authoritative numbers):\n"
        + json.dumps(data, separators=(",", ":"), ensure_ascii=False)
        + _synthesis_block(db, project_id)
        + ("\n\nValidated protocol (context):\n"
           + protocol.protocol_md[:8000] if protocol else "")
    )
    columns, rows = compute.evidence_rows(db, project_id)
    content = ("Evidence table — one line per included study; field values "
               "may be truncated:\n" + _evidence_block(columns, rows)
               + "\n\nWrite the Results section now.")
    return system, content


def estimate_cost(db: Session, project_id: int) -> dict | None:
    """Up-front cost estimate for the generate button (hover), same contract
    as the extraction ai-estimate. None when no API key or nothing to write."""
    model = resolve_model(db, project_id, feature="results_narrative")
    if model is None:
        return None
    provider, model_id = model
    try:
        system, content = build_prompt(db, project_id)
    except LLMError:
        return None
    tokens_in = pricing.chars_to_tokens(len(system) + len(content))
    return {**pricing.cost_breakdown(provider, model_id, tokens_in, OUT_TOKENS),
            "estimated": True}


def generate(db: Session, project_id: int, user_id: int) -> ResultsSynthesis:
    system, content = build_prompt(db, project_id)
    provider = open_provider_chain(db, project_id, feature="results_narrative",
                                   user_id=user_id)
    result = provider.generate([{"role": "user", "content": content}],
                               system=system, max_tokens=OUT_TOKENS)
    text = (result.text or "").strip()
    if not text:
        raise LLMError("The model returned an empty synthesis — try again")
    cost = pricing.call_cost(provider, result)
    row = db.query(ResultsSynthesis).filter_by(project_id=project_id).first()
    if row is None:
        row = ResultsSynthesis(project_id=project_id)
        db.add(row)
    row.content_md = text
    row.provider = cost["provider"]
    row.model = cost["model"]
    row.tokens_in = result.tokens_input
    row.tokens_out = result.tokens_output
    row.cost_usd = cost["cost_usd"]
    row.generated_by = user_id
    row.created_at = datetime.now(timezone.utc)
    db.commit()
    return row
