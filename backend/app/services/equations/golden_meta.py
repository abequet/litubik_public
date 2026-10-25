# SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Golden-set enrichment: abstracts from OpenAlex (by DOI, best effort).

The abstract is the AI advisor's terminology mine: words used by the
must-find papers that the equation does not contain yet are prime synonym
candidates. Fetched once and cached on the GoldenRef row."""
import httpx


def _deinvert(inverted: dict | None) -> str:
    """OpenAlex stores abstracts as {word: [positions]} — rebuild the text."""
    if not inverted:
        return ""
    positions: list[tuple[int, str]] = []
    for word, indexes in inverted.items():
        for i in indexes:
            positions.append((i, word))
    return " ".join(word for _, word in sorted(positions))


def fetch_abstract(doi: str, timeout: float = 8.0) -> str:
    try:
        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            r = client.get(
                f"https://api.openalex.org/works/doi:{doi}",
                params={"select": "abstract_inverted_index"})
            if not r.is_success:
                return ""
            return _deinvert(r.json().get("abstract_inverted_index"))[:4000]
    except Exception:  # network/parse hiccups: the ref just has no abstract
        return ""
