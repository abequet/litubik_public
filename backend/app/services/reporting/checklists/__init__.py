# SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Reporting checklists, pre-filled from the review's own audit trail.

Three files, three purposes:

- `prisma2020.py` — the 42-row checklist journals ask for as a supplementary
  file, with each item resolved to what the pipeline recorded;
- `swim.py` — the nine SWiM items, offered only when the review declared a
  synthesis method other than meta-analysis;
- `crest.py` — the problems editorial triage looks for, without its scores.

None of them judges the review. They say what happened, and where nothing
happened they say that too — which is the whole difference between a filled
checklist and a claimed one.
"""
from sqlalchemy.orm import Session

from app.models import ChecklistAnswer
from app.services.reporting import audit
from app.services.reporting.checklists import crest, prisma2020, swim

CHECKLISTS = {"prisma2020": prisma2020, "swim": swim}


def _answers(db: Session, project_id: int) -> dict[tuple[str, str], ChecklistAnswer]:
    return {(a.checklist, a.item): a
            for a in db.query(ChecklistAnswer).filter_by(project_id=project_id)}


def report(db: Session, project_id: int) -> dict:
    """Every checklist this review needs, plus the triage triggers."""
    dossier = audit.review_dossier(db, project_id)
    answers = _answers(db, project_id)

    def rows(key: str, module) -> list[dict]:
        out = []
        for row in module.evaluate(dossier):
            answer = answers.get((key, row["number"]))
            out.append({**row,
                        "page_ref": answer.page_ref if answer else "",
                        "note": answer.note if answer else "",
                        # the author's word wins: only they know whether an
                        # item is genuinely not applicable to their review
                        "status": (answer.status_override
                                   if answer and answer.status_override
                                   else row["status"]),
                        "overridden": bool(answer and answer.status_override)})
        return out

    checklists = [{
        "key": "prisma2020", "label": "PRISMA 2020",
        "citation": prisma2020.CITATION,
        "rows": rows("prisma2020", prisma2020),
    }]
    if swim.applies(dossier):
        checklists.append({
            "key": "swim", "label": "SWiM",
            "citation": swim.CITATION,
            "rows": rows("swim", swim),
        })
    return {
        "checklists": checklists,
        "triggers": crest.evaluate(dossier),
        "triggers_citation": crest.CITATION,
        "statuses": [prisma2020.EVIDENCED, prisma2020.AUTHOR,
                     prisma2020.NOT_DONE, prisma2020.NOT_APPLICABLE],
    }


def export_rows(db: Session, project_id: int,
                checklist: str) -> tuple[list[str], list[list]]:
    """The filled checklist as the supplementary file a journal asks for."""
    data = report(db, project_id)
    block = next((c for c in data["checklists"] if c["key"] == checklist), None)
    if block is None:
        raise KeyError(checklist)
    header = ["Section", "Item #", "Checklist item", "Status",
              "What this review recorded", "Location where item is reported"]
    body = [[r["section"], r["number"], r["text"], r["status"],
             " ".join(x for x in (r["fact"], r["note"]) if x).strip(),
             r["page_ref"]]
            for r in block["rows"]]
    return header, body
