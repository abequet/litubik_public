# SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Local boolean post-filtering for providers whose API cannot do it.

Crossref's search is relevance ranking over a keyword soup — it returns items
that merely score on some tokens (or none visible at all). After fetching, we
re-apply the equation's own boolean structure locally: a record is kept only
if EVERY concept has at least one of its keywords present in the searched
fields (title, plus abstract unless the equation is title-only).
"""


def matches_structure(record: dict, structure: dict, fields: list | None = None) -> bool:
    searched = set(fields or ["title", "abstract"])
    haystack = record.get("title", "")
    if "abstract" in searched:
        haystack += " " + record.get("abstract", "")
    haystack = haystack.lower()
    for concept in structure.get("concepts", []):
        keywords = [str(k).lower() for k in concept.get("keywords", []) if str(k).strip()]
        if not keywords:
            continue
        if not any(k in haystack for k in keywords):
            return False
    return True
