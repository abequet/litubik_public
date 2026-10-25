# SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Last-resort abstract tier: read the publisher's landing page.

Elsevier/Springer/APA/Wiley withhold abstracts from the open APIs but display
them publicly on the article page — so we read them where they are public.
Plain httpx first (Springer, T&F, SAGE...); a Playwright pass (same
launcher as the M6 downloader) covers the JS-relay/bot-protected publishers
(ScienceDirect, psycnet, Wiley). Best-effort like every other tier.
"""
import json
import re
import time

import httpx

from app.core.httpcap import ResponseTooLarge, get_capped
from app.core.ssrf import SSRFError, block_private_redirects, is_public_url

BROWSER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
MIN_LEN = 150          # anything shorter is a tagline, not an abstract
PAGE_DELAY = 1.0       # polite pause between page fetches

# CSS selectors per publisher family, tried in order after the generic metas
_SELECTORS = [
    "div.abstract.author .u-margin-s-bottom", "div.Abstracts",
    "div.abstract.author",            # ScienceDirect
    "div#Abs1-content", "section[data-title='Abstract']",  # Springer
    "div.abstract-group .article-section__content",        # Wiley
    "div.abstract-content",           # APA PsycNet
    "div.abstractSection", "div.hlFld-Abstract",           # Taylor & Francis
    "div#abstract", "section#abstract", "div.abstract", "section.abstract",
]

# JATS/JSON abstract embedded in a page <script> (ScienceDirect, some others)
_JSON_ABS = re.compile(r'"(?:abstract|abstractText|description)"\s*:\s*"'
                       r'((?:[^"\\]|\\.){150,}?)"')

_WS = re.compile(r"\s+")
_PREFIX = re.compile(r"^\s*(abstract|résumé|summary)\s*[:.]?\s*", re.I)


def _clean(text: str) -> str:
    text = _WS.sub(" ", str(text or "")).strip()
    return _PREFIX.sub("", text)


def extract_abstract(html: str) -> str:
    """Best-effort abstract from an article landing page."""
    from bs4 import BeautifulSoup

    try:
        soup = BeautifulSoup(html, "html.parser")
    except Exception:
        return ""
    # 1) bibliographic metas (authoritative when present)
    for name in ("citation_abstract", "dcterms.abstract", "dc.description",
                 "eprints.abstract"):
        tag = soup.find("meta", attrs={"name": re.compile(f"^{name}$", re.I)})
        if tag and len(_clean(tag.get("content", ""))) >= MIN_LEN:
            return _clean(tag["content"])
    # 2) JSON-LD description (Springer et al.)
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
        except (ValueError, TypeError):
            continue
        for node in (data if isinstance(data, list) else [data]):
            if not isinstance(node, dict):
                continue
            graph = node.get("@graph")
            candidates = graph if isinstance(graph, list) else [node]
            for c in candidates:
                if isinstance(c, dict) and len(_clean(c.get("description", ""))) >= MIN_LEN:
                    return _clean(c["description"])
    # 3) publisher abstract containers
    for selector in _SELECTORS:
        el = soup.select_one(selector)
        if el and len(_clean(el.get_text(" "))) >= MIN_LEN:
            return _clean(el.get_text(" "))
    # 4) JATS/JSON abstract embedded in a <script> (ScienceDirect Redux blob)
    for script in soup.find_all("script"):
        raw = script.string or ""
        if '"abstract' not in raw and '"description"' not in raw:
            continue
        m = _JSON_ABS.search(raw)
        if m:
            try:
                decoded = json.loads(f'"{m.group(1)}"')
            except ValueError:
                decoded = m.group(1)
            text = _clean(re.sub(r"<[^>]+>", " ", decoded))
            if len(text) >= MIN_LEN:
                return text
    # 5) og:description as a guarded fallback (often truncated with an ellipsis)
    og = soup.find("meta", attrs={"property": "og:description"})
    if og:
        text = _clean(og.get("content", ""))
        if len(text) >= 300 and not text.endswith(("…", "...")):
            return text
    return ""


def _httpx_pass(dois: list[str]) -> tuple[dict[str, str], list[str]]:
    """Plain fetch of doi.org/{doi}. Returns (found, needs_browser)."""
    found: dict[str, str] = {}
    retry: list[str] = []
    with httpx.Client(timeout=30, follow_redirects=True,
                      headers={"User-Agent": BROWSER_UA,
                               "Accept": "text/html"},
                      event_hooks={"response": [block_private_redirects]}) \
            as client:
        for doi in dois:
            try:
                status, body, _headers, _url = get_capped(
                    client, f"https://doi.org/{doi}")
            except SSRFError:
                # M10: the DOI resolved/redirected to an internal host — drop it
                continue
            except (httpx.HTTPError, ResponseTooLarge):
                retry.append(doi)
                continue
            is_success = 200 <= status < 300
            text = body.decode(errors="replace")
            abstract = extract_abstract(text) if is_success else ""
            if abstract:
                found[doi] = abstract
            elif not is_success or len(text) < 20_000:
                # 403 or a tiny JS relay page -> worth a real browser
                retry.append(doi)
            time.sleep(PAGE_DELAY)
    return found, retry


def _playwright_pass(dois: list[str], progress=None) -> dict[str, str]:
    """Headless-browser fetch for publishers that build the page in JS. Reuses
    the M6 downloader's hardened launcher; skipped when Playwright is absent."""
    from app.services.fulltext import doibatch

    if not dois or not doibatch._ensure_playwright():
        return {}
    try:
        from playwright.sync_api import sync_playwright
        from playwright.sync_api import TimeoutError as _PWTimeout
    except ImportError:
        return {}
    found: dict[str, str] = {}
    try:
        with sync_playwright() as pw:
            browser, ctx = doibatch._pw_launch(pw, accept_downloads=False)
            page = ctx.new_page()
            for n, doi in enumerate(dois):
                # per-page tick: this pass is sequential (~30 s/page), so without
                # it a long browser pass looks frozen to the caller
                if progress:
                    progress(f"Browser pass — page {n + 1}/{len(dois)}...")
                try:
                    page.goto(f"https://doi.org/{doi}",
                              wait_until="domcontentloaded", timeout=30_000)
                    try:
                        page.wait_for_load_state("networkidle", timeout=8_000)
                    except _PWTimeout:
                        pass
                    # M10: a redirect may have landed on an internal host —
                    # never read/store the content of a private page
                    if not is_public_url(page.url):
                        continue
                    abstract = extract_abstract(page.content())
                    if abstract:
                        found[doi] = abstract
                except Exception:
                    continue
            browser.close()
    except Exception:
        pass
    return found


def page_abstracts(dois: list[str], cap: int = 150,
                   progress=None) -> dict[str, str]:
    """{doi: abstract} read from the publisher pages, capped to `cap` DOIs."""
    todo = list(dict.fromkeys(dois))[:cap]
    if not todo:
        return {}
    if progress:
        progress(f"Reading {len(todo)} publisher pages...")
    found, retry = _httpx_pass(todo)
    if retry:
        if progress:
            progress(f"Browser pass on {len(retry)} protected pages...")
        found.update(_playwright_pass(retry, progress=progress))
    return found
