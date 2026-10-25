# SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
# SPDX-License-Identifier: AGPL-3.0-or-later
"""M4b: institution → EZproxy/OpenAthens resolution for full-text access.

Serves the bundled ezproxy database (github.com/tom5760/ezproxy-db, plus the
BibCNRS portals) so the UI can auto-fill the proxy URL from an institution
name. `$@` in a URL is the placeholder for the target article URL.
Credentials themselves never transit through this API — they live in the
user's browser.
"""
import json
import logging
import re
import unicodedata
from functools import lru_cache

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.api.deps import CurrentUser
from app.core.paths import app_data_dir

router = APIRouter(prefix="/api/institution-proxies", tags=["institution-proxies"])

MAX_RESULTS = 20


class ProxyOut(BaseModel):
    name: str
    url: str
    country: str


def _fold(s: str) -> str:
    """Lowercase + strip accents, for tolerant matching."""
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()


def _terms(s: str) -> list[str]:
    """Words of a folded string, split on anything but letters/digits so
    'univ-eiffel' and 'univ eiffel' behave the same."""
    return [w for w in re.split(r"[^a-z0-9]+", _fold(s)) if w]


def _host(url: str) -> str:
    """The proxy host, matched too: many people know their institution by its
    domain (unistra, ucly, univ-eiffel…) rather than by its official name."""
    return _fold(url).split("//")[-1].split("/")[0]


@lru_cache(maxsize=1)
def _load_db() -> list[dict]:
    path = app_data_dir() / "ezproxy_db.json"
    try:
        with open(path, encoding="utf-8") as f:
            entries = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        logging.getLogger(__name__).warning(
            "EZproxy directory unreadable at %s — the institution typeahead "
            "will stay empty on this installation", path)
        return []
    out = []
    for e in entries:
        name = e.get("name", "")
        folded = _fold(name)
        haystack = _terms(name) + _terms(_host(e.get("url", "")))
        out.append({**e, "_folded": folded, "_terms": haystack,
                    "_initials": "".join(w[0] for w in _terms(name))})
    return out


def _score(entry: dict, words: list[str]) -> tuple:
    """Lower is better: entries whose words *start* with the typed terms come
    before mere substring matches, then the shortest name wins."""
    starts = sum(1 for w in words
                 if any(term.startswith(w) for term in entry["_terms"]))
    return (-starts, len(entry["_folded"]), entry["_folded"])


@router.get("", response_model=list[ProxyOut])
def search_proxies(user: CurrentUser, q: str = ""):
    """Institutions matching every word of `q` — accent-, case- and
    punctuation-insensitive, on the name, the proxy domain or the acronym of
    the name. Empty query returns nothing: the list is a typeahead."""
    words = _terms(q)
    if not words:
        return []
    directory = _load_db()
    if not directory:
        # a broken/absent data file must not read as "your institution is not
        # in the directory" — the UI shows this message instead
        raise HTTPException(
            status_code=503,
            detail="The proxy directory is missing from this installation — "
                   "paste your proxy login URL by hand (your library can give "
                   "it to you), or reinstall the app.")
    joined = "".join(words)
    matches = [e for e in directory
               if all(any(w in term for term in e["_terms"]) for w in words)
               or (len(joined) >= 2 and e["_initials"].startswith(joined))]
    matches.sort(key=lambda e: _score(e, words))
    return [ProxyOut(name=e["name"], url=e["url"], country=e.get("country", ""))
            for e in matches[:MAX_RESULTS]]
