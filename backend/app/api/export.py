# SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Reference export, usable at any stage of the review: pick a scope (all
unique records / included / excluded / undecided so far) and a format
(RIS, BibTeX, CSV). The decision basis is the current screening state —
title/abstract outcomes, overridden by full-text outcomes where they exist."""
import csv
import io
import re

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.api.deps import DbDep, ProjectMemberDep, get_project
from app.core.csvsafe import safe_row
from app.models import Record, ScreeningConfig
from app.services.ris.parse import to_ris
from app.services.screening.core import screening_outcomes

router = APIRouter(prefix="/api/projects/{project_id}/export", tags=["export"])

SCOPES = ("all", "included", "excluded", "undecided")
FORMATS = {"ris": ("ris", "application/x-research-info-systems"),
           "bibtex": ("bib", "application/x-bibtex"),
           "csv": ("csv", "text/csv")}


def current_decisions(db: Session, project_id: int) -> dict[int, str]:
    """Per-record decision as of now: T/A rounds in order, then FT rounds —
    a later stage's include/exclude overrides the earlier one."""
    decisions: dict[int, str] = {}
    for stage in ("ta", "ft"):
        for config in (db.query(ScreeningConfig)
                       .filter_by(project_id=project_id, stage=stage,
                                  status="active")
                       .order_by(ScreeningConfig.round)):
            decisions.update(screening_outcomes(db, config))
    return decisions


def _scoped_records(db: Session, project_id: int, scope: str) -> list[tuple[Record, str]]:
    records = (db.query(Record)
               .filter_by(project_id=project_id, dedup_status="unique")
               .order_by(Record.id).all())
    decisions = current_decisions(db, project_id)
    wanted = {"included": "include", "excluded": "exclude",
              "undecided": "undecided"}.get(scope)
    out = []
    for record in records:
        status = decisions.get(record.id, "undecided")
        if wanted is None or status == wanted:
            out.append((record, status))
    return out


@router.get("/references/summary")
def export_summary(project_id: int, member: ProjectMemberDep, db: DbDep):
    """Counts per scope, for the export dialog."""
    get_project(project_id, db)
    records = (db.query(Record.id)
               .filter_by(project_id=project_id, dedup_status="unique").all())
    ids = {rid for (rid,) in records}
    decisions = {rid: d for rid, d in current_decisions(db, project_id).items()
                 if rid in ids}
    included = sum(1 for d in decisions.values() if d == "include")
    excluded = sum(1 for d in decisions.values() if d == "exclude")
    return {"all": len(ids), "included": included, "excluded": excluded,
            "undecided": len(ids) - included - excluded}


def _bibtex_key(record: Record, seen: set[str]) -> str:
    author = (record.authors or ["anon"])[0]
    last = re.sub(r"[^A-Za-z]", "", str(author).split(",")[0].split()[-1]) or "anon"
    base = f"{last.lower()}{record.year or 'nd'}"
    key, i = base, 1
    while key in seen:
        i += 1
        key = f"{base}{chr(ord('a') + (i - 2) % 26)}"
    seen.add(key)
    return key


def _bibtex_escape(value: str) -> str:
    return str(value).replace("{", "").replace("}", "").strip()


def to_bibtex(records: list[Record]) -> str:
    seen: set[str] = set()
    chunks = []
    for r in records:
        fields = {
            "title": _bibtex_escape(r.title),
            "author": " and ".join(_bibtex_escape(a) for a in (r.authors or [])),
            "year": str(r.year) if r.year else "",
            "journal": _bibtex_escape(r.journal),
            "abstract": _bibtex_escape(r.abstract),
            "doi": r.doi or "",
        }
        body = ",\n".join(f"  {k} = {{{v}}}" for k, v in fields.items() if v)
        chunks.append(f"@article{{{_bibtex_key(r, seen)},\n{body}\n}}")
    return "\n\n".join(chunks) + ("\n" if chunks else "")


def _to_csv(rows: list[tuple[Record, str]]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(["doi", "title", "authors", "year", "journal",
                     "abstract", "screening_status"])
    for record, status in rows:
        writer.writerow(safe_row([record.doi or "", record.title,
                                  "; ".join(record.authors or []),
                                  record.year or "", record.journal,
                                  record.abstract, status]))
    return buffer.getvalue()


@router.get("/references")
def export_references(project_id: int, member: ProjectMemberDep, db: DbDep,
                      scope: str = "all", fmt: str = "ris"):
    get_project(project_id, db)
    if scope not in SCOPES:
        raise HTTPException(status_code=400,
                            detail=f"scope must be one of {SCOPES}")
    if fmt not in FORMATS:
        raise HTTPException(status_code=400,
                            detail=f"fmt must be one of {tuple(FORMATS)}")
    rows = _scoped_records(db, project_id, scope)
    if fmt == "ris":
        content = to_ris([{
            "doi": r.doi, "title": r.title, "authors": r.authors or [],
            "year": r.year, "journal": r.journal, "abstract": r.abstract,
        } for r, _ in rows])
    elif fmt == "bibtex":
        content = to_bibtex([r for r, _ in rows])
    else:
        content = _to_csv(rows)
    ext, media_type = FORMATS[fmt]
    data = content.encode("utf-8-sig" if fmt == "csv" else "utf-8")
    return StreamingResponse(
        iter([data]), media_type=media_type,
        headers={"Content-Disposition":
                 f'attachment; filename="references_{scope}.{ext}"'})
