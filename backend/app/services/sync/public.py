# SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Public replication archive: the project archive cut down to what a team may
publish next to a paper (OSF, Zenodo, supplementary material).

A complete snapshot is a working copy for co-reviewers. It carries material
the team may hold but may not redistribute: full-text PDFs, abstracts (they
belong to the publishers, even when an open index serves them), the raw
exports of commercial databases (their terms forbid redistribution), AI
translations of those abstracts, and the passages quoted by PDF annotations.
It also carries the encrypted shared API keys.

It also carries operational traces that say more about the people than about
the review: when each reviewer worked (work sessions), whose institutional
access fetched which paper and why a retrieval failed (the diagnostics name the
institution, sometimes the account), and the occasional e-mail address that a
database left in an author field.

The public archive drops all of that and keeps everything the review's numbers
come from: bibliographic metadata, equations and counts, deduplication,
votes, conflicts and reasons, appraisal, extraction, the AI-use journal and
the deviations. Re-importing it reproduces the PRISMA counts and the agreement
statistics; whoever replicates the review fetches the full texts with their
own access.

Pseudonymisation is a separate choice, because journals differ: some want the
reviewers named, others want a blinded package. It replaces every e-mail
address the archive holds, in values and in keys, and the reviewers' display
names, by "Reviewer N". Names typed by hand in free-text notes (resolution
notes, deviations, comments) are not detected: the team rereads those.
"""
import re

from app.services.sync.serialize import collect_emails

PSEUDO_DOMAIN = "pseudonymized.invalid"

# what the public archive leaves out, reported in its manifest
REMOVED = ("pdfs", "abstracts", "abstract_translations", "raw_database_exports",
           "annotation_quotes", "shared_api_keys", "pending_invitations",
           "work_sessions", "retrieval_diagnostics", "institution_names",
           "emails_in_author_fields")

_EMAIL = re.compile(r"\s*[(<\[]?[\w.+-]+@[\w-]+(?:\.[\w-]+)+[)>\]]?")


def strip_for_publication(data: dict) -> None:
    """Blank, in place, the content of the serialized project that belongs to
    publishers or database vendors, and the operational traces listed in the
    module docstring."""
    for r in data.get("records", []):
        r["abstract"] = ""
        r["raw_ris"] = ""
        if r.get("abstract_original") is not None:
            r["abstract_original"] = ""
        r["translations"] = None
        if isinstance(r.get("authors"), list):
            r["authors"] = [_EMAIL.sub("", a).strip()
                            if isinstance(a, str) and "@" in a else a
                            for a in r["authors"]]
    for a in data.get("pdf_annotations", []):
        a["quote"] = ""
    # "institution (Université X)" -> "institution": the source type is what
    # the PRISMA reports-sought/retrieved figures need, not whose access it was
    for f in data.get("fulltexts", []):
        if isinstance(f.get("via"), str):
            f["via"] = re.sub(r"\s*\(.*\)\s*$", "", f["via"])
        f["error"] = ""
    data["work_sessions"] = []
    # fulltexts keep has_file: on import, a report whose PDF did not travel
    # goes back to "pending", so whoever replicates fetches it again
    # an invitation names someone who never took part in the review
    data["members"] = [m for m in data.get("members", [])
                       if m.get("status") != "invited"]


def pseudonym_map(data: dict, extra: tuple[str, ...] = ()) -> dict[str, str]:
    """email -> reviewer-N@pseudonymized.invalid. Members first, in the order
    the archive lists them, then anyone else the archive mentions."""
    order: list[str] = []
    for m in data.get("members", []):
        email = (m.get("email") or "").lower()
        if email and email not in order:
            order.append(email)
    for email in sorted(collect_emails(data)) + [e.lower() for e in extra]:
        if email and email not in order:
            order.append(email)
    return {email: f"reviewer-{i}@{PSEUDO_DOMAIN}"
            for i, email in enumerate(order, 1)}


def pseudonymize(data: dict, mapping: dict[str, str]) -> None:
    """Replace, in place, every mapped e-mail anywhere in the archive (values,
    dict keys, provenance strings such as "a@b.org #3") and give the members
    the display name "Reviewer N". Display names are not searched for in the
    text: a reviewer called Wang would otherwise vanish from author lists."""
    for m in data.get("members", []):
        email = (m.get("email") or "").lower()
        m["display_name"] = (f"Reviewer {mapping[email][len('reviewer-'):].split('@')[0]}"
                             if email in mapping else "")
    if not mapping:
        return
    email_re = re.compile("|".join(re.escape(e) for e in
                                   sorted(mapping, key=len, reverse=True)),
                          re.IGNORECASE)

    def fix(text: str) -> str:
        return email_re.sub(lambda m: mapping[m.group(0).lower()], text)

    def walk(obj):
        if isinstance(obj, dict):
            return {(fix(k) if isinstance(k, str) else k): walk(v)
                    for k, v in obj.items()}
        if isinstance(obj, list):
            return [walk(v) for v in obj]
        if isinstance(obj, str):
            return fix(obj)
        return obj

    cleaned = walk(data)
    data.clear()
    data.update(cleaned)


def readme(manifest: dict) -> str:
    """README.txt written at the root of a public archive, for whoever finds
    the zip in a repository without having used LitUbik."""
    info = manifest.get("public_replication") or {}
    pseudo = "yes" if info.get("pseudonymized") else "no"
    removed = "\n".join(f"  - {item}" for item in info.get("removed", REMOVED))
    return f"""LitUbik public replication archive
==================================

Project      : {manifest.get("project_name", "")}
Exported     : {manifest.get("exported_at", "")}
Format       : {manifest.get("format", "")} v{manifest.get("format_version", "")}
DB schema    : {manifest.get("schema_revision", "")}
Pseudonymised: {pseudo}

This archive is the state of a systematic review conducted in LitUbik
(https://github.com/abequet/litubik_public), cut down to what a team may
publish next to a paper.

Contents
  manifest.json      what this archive is and what was left out
  data.json          every table of the project: bibliographic metadata,
                     search equations and counts, deduplication, screening
                     votes, conflicts and reasons, AI suggestions, appraisal,
                     extraction, protocol deviations, the AI-use journal
  files/protocol/    the protocol documents the team uploaded, if any

Left out
{removed}

Reproducing the review
  Install LitUbik at a version whose database schema includes the revision
  above, then Projects -> Import a project -> choose this zip. The PRISMA
  counts and the agreement statistics are recomputed from the data. Full
  texts show as "to retrieve": fetch them with your own access.

Licence
  LitUbik does not set one. The team that publishes this archive states the
  licence of its own contribution (decisions, coding, protocol) next to it.
  Bibliographic metadata comes from the databases that were searched and
  remains subject to their terms.
"""
