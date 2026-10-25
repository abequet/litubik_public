# SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Generate the two manuscript write-ups from the project's own record.

Both follow the same contract as the Results narrative: on demand, priced
before the click, stored as a single per-project artifact, and editable — the
generated text is a draft, the authors sign the edited one.

The AI disclosure additionally goes through a form (see `ai_audit`): the author
sees the structured answers the journal produced, corrects them if needed, and
only then is a statement written from them. Separating "decide what to
disclose" from "phrase the disclosure" is DAISY's central design finding
(Ahmetoglu, Constantinides & Cox, CHIWORK '26) and the reason the form is not
skipped even when the journal already knows the answers.
"""
import json
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models import REPORT_KINDS, ReportSection
from app.services.llm import pricing
from app.services.llm.base import LLMError
from app.services.llm.credentials import open_provider_chain, resolve_model
from app.services.llm.prompts import resolve_prompt
from app.services.reporting import ai_audit, audit

LANGS = {"en": "English", "fr": "French"}

# Output ceiling, not a target. A PRISMA 2020 Methods section carries seven
# subsections and three tables, and a reasoning model spends part of the budget
# on hidden reasoning before emitting a single character — too tight a cap
# returns a truncated section, or no text at all. These are wide enough to
# absorb both, and stay under the output limit of every provider we support.
OUT_TOKENS = {"methods": 8000, "ai_disclosure": 3000}
# What the section actually costs to write, used for the price shown on hover:
# quoting the ceiling would over-quote by a factor of three.
EST_OUT_TOKENS = {"methods": 3000, "ai_disclosure": 800}
# the dossier is already compact (counts and settings, no record-level data),
# but a 300-variant equation history must not blow the context up
DOSSIER_BUDGET = 60_000

FEATURE_KEYS = {"methods": "reporting_methods",
                "ai_disclosure": "reporting_disclosure"}


def _dump(data: dict) -> str:
    text = json.dumps(data, separators=(",", ":"), ensure_ascii=False,
                      default=str)
    return text[:DOSSIER_BUDGET]


# The methods skeleton is written in English (the usual submission language);
# a French manuscript needs the established French terms rather than a literal
# translation, so the glossary travels with the language instruction.
FR_GLOSSARY = (
    "backward/forward snowballing → snowballing arrière/avant ; "
    "seed set → ensemble de départ ; screening → sélection/tri ; "
    "title and abstract screening → tri sur titres et résumés ; "
    "full-text screening → tri sur texte intégral ; "
    "eligibility criteria → critères d'éligibilité ; "
    "inter-rater reliability → accord inter-juges ; "
    "risk of bias → risque de biais ; "
    "narrative synthesis → synthèse narrative ; "
    "grey literature → littérature grise ; records → références/notices ; "
    "deduplication → déduplication ; living review → revue vivante ; "
    "search update → mise à jour de la recherche"
)


def _lang_clause(lang: str) -> str:
    clause = (f"\n\nWrite the text in {LANGS.get(lang, 'English')}. "
              "Keep tool names, model identifiers and database names as they "
              "are — do not translate them.")
    if lang == "fr":
        clause += (
            " Write the placeholder for missing data as "
            "**[À COMPLÉTER : ce qui manque]**, and use these French terms "
            "rather than literal translations: " + FR_GLOSSARY + ".")
    return clause


def _methods_prompt(db: Session, project_id: int, lang: str) -> tuple[str, str]:
    dossier = audit.review_dossier(db, project_id)
    if not dossier["search"]["imports"]:
        raise LLMError("Nothing to describe yet — import your search results "
                       "first; the Methods paragraph is written from what the "
                       "pipeline recorded")
    system = (resolve_prompt(db, project_id, "reporting_methods")
              + _lang_clause(lang)
              + "\n\nAudit trail of this review (authoritative — every number "
                "in your text must come from here):\n" + _dump(dossier))
    return system, ("Write the Methods section of this review now, following "
                    "the audit trail above.")


def _disclosure_prompt(db: Session, project_id: int, lang: str,
                       form: dict | None) -> tuple[str, str]:
    dossier = ai_audit.ai_dossier(db, project_id)
    # the author's reviewed answers win over the pre-filled ones
    dossier["form"] = form or dossier["form"]
    system = (resolve_prompt(db, project_id, "reporting_disclosure")
              + _lang_clause(lang)
              + "\n\nAI-use journal and disclosure form for this review "
                "(authoritative):\n" + _dump(dossier))
    return system, ("Write the AI disclosure statement for this review now, "
                    "following the journal and the form above.")


def _budget_exhausted(error: Exception) -> bool:
    """Did the call die on the output cap rather than on a real failure?

    Every provider words it differently ("no text", stop_reason=max_tokens,
    finish_reason=length), so match on what they have in common rather than on
    one vendor's phrasing."""
    message = str(error).lower()
    return "no text" in message or "length" in message or "max_tokens" in message


def build_prompt(db: Session, project_id: int, kind: str, lang: str = "en",
                 form: dict | None = None) -> tuple[str, str]:
    if kind not in REPORT_KINDS:
        raise LLMError(f"Unknown report section '{kind}'")
    if kind == "methods":
        return _methods_prompt(db, project_id, lang)
    return _disclosure_prompt(db, project_id, lang, form)


def estimate_cost(db: Session, project_id: int, kind: str,
                  lang: str = "en") -> dict | None:
    """Up-front estimate for the generate button (hover). None when no API key
    is configured or there is nothing to write about yet."""
    model = resolve_model(db, project_id, feature=FEATURE_KEYS[kind])
    if model is None:
        return None
    provider, model_id = model
    try:
        system, content = build_prompt(db, project_id, kind, lang)
    except LLMError:
        return None
    tokens_in = pricing.chars_to_tokens(len(system) + len(content))
    return {**pricing.cost_breakdown(provider, model_id, tokens_in,
                                     EST_OUT_TOKENS.get(kind, 1500)),
            "estimated": True}


def generate(db: Session, project_id: int, kind: str, user_id: int,
             lang: str = "en", form: dict | None = None) -> ReportSection:
    system, content = build_prompt(db, project_id, kind, lang, form)
    provider = open_provider_chain(db, project_id, feature=FEATURE_KEYS[kind],
                                   user_id=user_id)
    budget = OUT_TOKENS.get(kind, 2000)
    try:
        result = provider.generate([{"role": "user", "content": content}],
                                   system=system, max_tokens=budget)
    except LLMError as e:
        # A reasoning model can spend the whole budget thinking and return no
        # text at all. The user cannot raise max_tokens from the interface, so
        # retry once with a wider budget rather than handing them an error they
        # have no way to act on.
        if not _budget_exhausted(e):
            raise
        result = provider.generate([{"role": "user", "content": content}],
                                   system=system, max_tokens=budget * 2)
    text = (result.text or "").strip()
    if not text:
        raise LLMError("The model returned an empty text — try again")
    cost = pricing.call_cost(provider, result)
    row = (db.query(ReportSection)
           .filter_by(project_id=project_id, kind=kind).first())
    if row is None:
        row = ReportSection(project_id=project_id, kind=kind)
        db.add(row)
    row.lang = lang
    row.content_md = text
    if kind == "ai_disclosure":
        row.form = form or ai_audit.ai_dossier(db, project_id)["form"]
    row.provider = cost["provider"]
    row.model = cost["model"]
    row.tokens_in = result.tokens_input
    row.tokens_out = result.tokens_output
    row.cost_usd = cost["cost_usd"]
    row.generated_by = user_id
    row.created_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(row)
    return row


def save_edit(db: Session, project_id: int, kind: str,
              edited_md: str) -> ReportSection:
    """The author's own version, kept beside the generated one.

    Regenerating never touches it: the generated text is evidence of what the
    audit trail said, the edited text is what the authors put their name to.
    """
    if kind not in REPORT_KINDS:
        raise LLMError(f"Unknown report section '{kind}'")
    row = (db.query(ReportSection)
           .filter_by(project_id=project_id, kind=kind).first())
    if row is None:
        row = ReportSection(project_id=project_id, kind=kind)
        db.add(row)
    row.edited_md = edited_md
    db.commit()
    db.refresh(row)
    return row
