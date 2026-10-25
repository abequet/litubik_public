# SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
# SPDX-License-Identifier: AGPL-3.0-or-later
"""arXiv Atom feed parsing (shared by the count and the fetch connectors).

The export API answers Atom XML: one `<entry>` per paper, the total in
`<opensearch:totalResults>`. Papers rarely carry a publisher DOI in the
feed; every arXiv paper has a DataCite DOI `10.48550/arXiv.<id>`, which the
record gets so that dedup and full-text retrieval have something to key on.
"""
import re
import xml.etree.ElementTree as ET

from app.services.ris.parse import _record

NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "opensearch": "http://a9.com/-/spec/opensearch/1.1/",
    "arxiv": "http://arxiv.org/schemas/atom",
}


def arxiv_id(entry_id: str) -> str:
    """`http://arxiv.org/abs/2301.01234v2` -> `2301.01234` (version dropped,
    old-style `math/0601001` kept as is)."""
    ident = entry_id.rsplit("/abs/", 1)[-1].strip()
    return re.sub(r"v\d+$", "", ident)


def parse_arxiv_feed(text: str) -> tuple[int, list[dict]]:
    """(total results, normalized records) of one API page."""
    root = ET.fromstring(text)
    total_el = root.find("opensearch:totalResults", NS)
    total = int(total_el.text) if total_el is not None and total_el.text else 0
    records: list[dict] = []
    for entry in root.findall("atom:entry", NS):
        ident = arxiv_id(entry.findtext("atom:id", "", NS))
        doi_el = entry.find("arxiv:doi", NS)
        doi = (doi_el.text or "").strip() if doi_el is not None else ""
        if not doi and ident:
            doi = f"10.48550/arXiv.{ident}"
        published = entry.findtext("atom:published", "", NS)
        journal_ref = entry.findtext("arxiv:journal_ref", "", NS)
        records.append(_record(
            doi=doi or None,
            title=entry.findtext("atom:title", "", NS),
            authors=[a.findtext("atom:name", "", NS)
                     for a in entry.findall("atom:author", NS)],
            year=published[:4] if published[:4].isdigit() else None,
            journal=journal_ref.strip() if journal_ref else "arXiv",
            abstract=entry.findtext("atom:summary", "", NS),
        ))
    return total, records
