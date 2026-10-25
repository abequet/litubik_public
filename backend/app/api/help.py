# SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
# SPDX-License-Identifier: AGPL-3.0-or-later
"""In-app help / FAQ, served from markdown files in docs/help/{en,fr}/.

Files are named NN-slug.md (the numeric prefix fixes the display order) and
their first `# ` heading is the topic title. French mirrors English file by
file; a missing French file silently falls back to the English one so a new
topic never 404s in the other language.
"""
import re
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.api.deps import CurrentUser
from app.core.paths import help_dir

router = APIRouter(prefix="/api/help", tags=["help"])

_LANGS = ("en", "fr")
_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")


class HelpTopic(BaseModel):
    slug: str
    title: str


class HelpPage(HelpTopic):
    content: str


def _lang_dir(lang: str) -> Path:
    if lang not in _LANGS:
        raise HTTPException(status_code=404, detail="Unknown language")
    return help_dir() / lang


def _title_of(path: Path) -> str:
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return path.stem


def _resolve(lang: str, slug: str) -> Path:
    if not _SLUG_RE.match(slug):
        raise HTTPException(status_code=404, detail="Unknown topic")
    for candidate in (_lang_dir(lang) / f"{slug}.md", _lang_dir("en") / f"{slug}.md"):
        if candidate.is_file():
            return candidate
    raise HTTPException(status_code=404, detail="Unknown topic")


@router.get("/{lang}", response_model=list[HelpTopic])
def list_topics(lang: str, user: CurrentUser):
    # English is the reference list; titles come from the requested language
    # when its file exists (per-file fallback to English otherwise).
    reference = _lang_dir("en")
    if not reference.is_dir():
        return []
    topics = []
    for en_file in sorted(reference.glob("*.md")):
        localized = _lang_dir(lang) / en_file.name
        topics.append(HelpTopic(
            slug=en_file.stem,
            title=_title_of(localized if localized.is_file() else en_file),
        ))
    return topics


@router.get("/{lang}/{slug}", response_model=HelpPage)
def get_topic(lang: str, slug: str, user: CurrentUser):
    path = _resolve(lang, slug)
    return HelpPage(slug=slug, title=_title_of(path),
                    content=path.read_text(encoding="utf-8"))
