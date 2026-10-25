# SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
# SPDX-License-Identifier: AGPL-3.0-or-later
"""AI translation of a record's title + abstract — a reading aid.

The translation never replaces the abstract (the screening's source data): it
is cached next to it, per target language, and shown on demand with its AI
provenance. One entry per language, shared by the whole team, so a text is
translated — and paid for — once. An entry carries the hash of the text it was
made from: editing the abstract orphans it and the next request redoes it.
"""
import hashlib
import re
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models import Record
from app.services.llm import LLMError  # noqa: F401 — re-exported for callers
from app.services.llm.credentials import open_provider_chain
from app.services.llm.prompts import resolve_prompt

# target languages = the UI languages
LANGUAGES = {"en": "English", "fr": "French"}

SCHEMA = {
    "type": "object",
    "properties": {
        "source_language": {
            "type": "string",
            "description": "ISO 639-1 code of the language the record is "
                           "written in (e.g. en, fr, es, de, pt, zh)"},
        "same_language": {
            "type": "boolean",
            "description": "true when the record is already written in the "
                           "target language — title and abstract are then "
                           "returned empty"},
        "title": {"type": "string"},
        "abstract": {"type": "string"},
    },
    "required": ["source_language", "same_language", "title", "abstract"],
}

# Function words are enough to tell the two target languages apart, and doing
# it locally means an abstract already in the reader's language costs no call.
_STOPWORDS = {
    "en": frozenset("the of and in to a is for that with was were on as by "
                    "this are from an be at which these we it has have their "
                    "or not between than been our".split()),
    "fr": frozenset("le la les de des du et en un une dans pour que qui est "
                    "sur par au aux avec ont été cette ces nous sont plus ce "
                    "se ne pas entre leur leurs chez d l".split()),
}


def already_in(text: str, lang: str) -> bool:
    """Confidently written in `lang`? Conservative: a doubt means 'no', and
    the model then decides."""
    words = re.findall(r"[a-zàâçéèêëîïôûùüÿœ]+", (text or "").lower())
    if len(words) < 12:
        return False
    share = {code: sum(w in stop for w in words) / len(words)
             for code, stop in _STOPWORDS.items()}
    other = max(v for code, v in share.items() if code != lang)
    return share[lang] >= 0.15 and share[lang] >= 3 * other


def source_hash(record: Record) -> str:
    text = f"{record.title or ''}\n{record.abstract or ''}"
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]


def valid_translations(record: Record) -> dict:
    """The cached entries still matching the record's current text, in the
    shape sent to the front."""
    current = source_hash(record)
    return {
        lang: {k: entry.get(k) for k in (
            "same_language", "source_language", "title", "abstract",
            "provider", "model", "at")}
        for lang, entry in (record.translations or {}).items()
        if entry.get("hash") == current
    }


def translate_record(db: Session, project_id: int, record: Record, lang: str,
                     user_id: int | None) -> dict:
    """Cached entry for `lang`, translating first if needed. Raises LLMError
    (no key configured, provider failure)."""
    cached = valid_translations(record).get(lang)
    if cached is not None:
        return cached

    entry = {"hash": source_hash(record), "same_language": True,
             "source_language": lang, "title": "", "abstract": "",
             "provider": "", "model": "",
             "at": datetime.now(timezone.utc).isoformat()}
    if not already_in(record.abstract or record.title, lang):
        provider = open_provider_chain(db, project_id,
                                       feature="translate_abstract",
                                       user_id=user_id)
        system = (resolve_prompt(db, project_id, "translate_abstract")
                  + f"\n\nTarget language: {LANGUAGES[lang]} ({lang}).")
        prompt = (f"TITLE:\n{record.title or ''}\n\n"
                  f"ABSTRACT:\n{record.abstract or ''}")
        result = provider.generate_json(
            [{"role": "user", "content": prompt}],
            json_schema=SCHEMA, system=system, max_tokens=4096)
        data = result.data or {}
        same = bool(data.get("same_language"))
        entry.update(
            same_language=same,
            source_language=str(data.get("source_language") or "")[:8].lower(),
            title="" if same else str(data.get("title") or ""),
            abstract="" if same else str(data.get("abstract") or ""),
            provider=provider.name, model=provider.model)

    # reassign: an in-place change to a JSON column is not detected
    record.translations = {**(record.translations or {}), lang: entry}
    db.commit()
    return valid_translations(record)[lang]
