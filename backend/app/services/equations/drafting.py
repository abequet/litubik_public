# SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
# SPDX-License-Identifier: AGPL-3.0-or-later
"""AI drafts of a raw equation's other syntaxes.

A raw variant is typed for one database — the protocol's PubMed string,
say. The other databases the review searches are drafted from it by the
model, one call per target, and stored as overrides flagged in
`translations["drafts"]`:

    {db_id: {"from_db", "provider", "model", "at", "notes": [...],
             "validated": bool, "validated_by", "validated_at"}}

A draft is usable at once (counts, fetches, the Search page) but stays
marked "AI draft, not reviewed" until a human validates it or edits the
text — the search report and the audit say which queries were run
unreviewed. An override saved by hand drops the flag: the text is then the
human's.
"""
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models import Equation
from app.services.equations.recall import effective_query
from app.services.llm import pricing
from app.services.llm.base import LLMError
from app.services.llm.credentials import open_provider_chain
from app.services.llm.prompts import resolve_prompt

PROMPT_KEY = "equation_translate"


def _prompt(src: dict, dst: dict, source: str) -> str:
    return (f"Source database: {src['label']}.\n"
            f"Target database: {dst['label']} ({dst.get('syntax') or dst['id']} "
            f"syntax). Target syntax notes: {dst.get('instructions', '')}\n\n"
            f"Query to translate:\n{source}")


def _split(text: str) -> tuple[str, list[str]]:
    """The model's reply -> (query, comment lines)."""
    text = (text or "").strip()
    if text.startswith("```"):
        text = text.strip("`").strip()
        first, _, rest = text.partition("\n")
        if rest and not first.strip().startswith("("):
            text = rest  # a language hint line
    query = "\n".join(ln for ln in text.splitlines() if not ln.lstrip().startswith("#"))
    notes = [ln.lstrip("# ").strip() for ln in text.splitlines()
             if ln.lstrip().startswith("#")]
    return query.strip(), notes


def draft_query(db: Session, project_id: int, equation: Equation, registry: dict,
                from_db: str, to_db: str, user_id: int | None) -> dict:
    """One LLM call: the `to_db` syntax of the query typed for `from_db`.
    Returns {query, notes, provider, model, cost}; raises ValueError when
    there is nothing to translate, LLMError when the model fails."""
    source = effective_query(equation, from_db)
    if not source.strip():
        raise ValueError(f"No {registry[from_db]['label']} query to translate from")
    provider = open_provider_chain(db, project_id, feature=PROMPT_KEY, user_id=user_id)
    system = resolve_prompt(db, project_id, PROMPT_KEY)
    result = provider.generate(
        [{"role": "user", "content": _prompt(registry[from_db], registry[to_db], source)}],
        system=system, max_tokens=4096)
    query, notes = _split(result.text)
    return {"query": query, "notes": notes,
            "provider": getattr(provider, "name", ""),
            "model": getattr(provider, "model", ""),
            "cost": pricing.call_cost(provider, result)}


def store_draft(equation: Equation, to_db: str, from_db: str, drafted: dict) -> None:
    """Keep a drafted query as the database's override, flagged as an
    unreviewed AI draft (the previous flag, if any, is replaced)."""
    translations = dict(equation.translations or {})
    overrides = dict(translations.get("overrides") or {})
    overrides[to_db] = drafted["query"]
    drafts = dict(translations.get("drafts") or {})
    drafts[to_db] = {"from_db": from_db, "provider": drafted.get("provider", ""),
                     "model": drafted.get("model", ""),
                     "at": datetime.now(timezone.utc).isoformat(),
                     "notes": list(drafted.get("notes") or []),
                     "validated": False, "validated_by": None, "validated_at": None}
    translations["overrides"] = overrides
    translations["drafts"] = drafts
    equation.translations = translations


def drop_draft(equation: Equation, db_id: str) -> None:
    """A human typed the query: it is no longer an AI draft."""
    translations = dict(equation.translations or {})
    drafts = dict(translations.get("drafts") or {})
    if db_id in drafts:
        del drafts[db_id]
        translations["drafts"] = drafts
        equation.translations = translations


def validate_draft(equation: Equation, db_id: str, user_id: int | None) -> bool:
    """Mark a draft as reviewed by a human. False when there is no draft."""
    translations = dict(equation.translations or {})
    drafts = dict(translations.get("drafts") or {})
    if db_id not in drafts:
        return False
    drafts[db_id] = {**drafts[db_id], "validated": True, "validated_by": user_id,
                     "validated_at": datetime.now(timezone.utc).isoformat()}
    translations["drafts"] = drafts
    equation.translations = translations
    return True


def unreviewed(equation: Equation) -> list[str]:
    """Database ids whose query is an AI draft nobody validated."""
    drafts = (equation.translations or {}).get("drafts") or {}
    return sorted(d for d, info in drafts.items() if not info.get("validated"))


def targets(equation: Equation, registry: dict, from_db: str, mode: str) -> list[str]:
    """Databases to draft: `missing` = no query yet; `unreviewed` = missing
    plus the AI drafts nobody validated (after the source was edited)."""
    drafts = (equation.translations or {}).get("drafts") or {}
    out = []
    for db_id in registry:
        if db_id == from_db:
            continue
        has_query = bool(effective_query(equation, db_id).strip())
        if not has_query:
            out.append(db_id)
        elif mode == "unreviewed" and db_id in drafts and not drafts[db_id].get("validated"):
            out.append(db_id)
    return out


def estimate(db: Session, project_id: int, n_targets: int, source_chars: int,
             user_id: int | None) -> dict:
    """What drafting `n_targets` databases would cost, from the provider the
    chain would open and rough token counts (prompt ≈ instructions + source,
    reply ≈ the source again)."""
    try:
        provider = open_provider_chain(db, project_id, feature=PROMPT_KEY,
                                       user_id=user_id)
    except LLMError as e:
        return {"n_targets": n_targets, "available": False, "reason": str(e)}
    system_chars = len(resolve_prompt(db, project_id, PROMPT_KEY))
    tokens_in = pricing.chars_to_tokens(system_chars + source_chars + 400)
    tokens_out = pricing.chars_to_tokens(int(source_chars * 1.2) + 100)
    one = pricing.cost_breakdown(getattr(provider, "name", ""),
                                 getattr(provider, "model", ""), tokens_in, tokens_out)
    total = pricing.cost_breakdown(one["provider"], one["model"],
                                   tokens_in * n_targets, tokens_out * n_targets)
    return {"n_targets": n_targets, "available": True,
            "provider": one["provider"], "model": one["model"],
            "cost_label": total["cost_label"], "cost_usd": total["cost_usd"],
            "free": total["free"]}
