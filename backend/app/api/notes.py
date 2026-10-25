# SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
# SPDX-License-Identifier: AGPL-3.0-or-later
"""T15: read-only aggregation of every note written during screening —
vote justifications (T/A and full-text) and conflict resolution notes —
one list + CSV export. No new model: it reads votes.justification and
conflicts.resolution_note."""
import csv
import io

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from app.api.deps import DbDep, ProjectMemberDep, get_project
from app.core.csvsafe import safe_row
from app.models import Conflict, Record, ScreeningConfig, Vote
from app.services.screening.anonymity import project_namer
from app.services.screening.core import record_outcome

router = APIRouter(prefix="/api/projects/{project_id}/notes", tags=["notes"])


def _rows(db, project_id: int, me: int) -> list[dict]:
    """Blind: a vote justification is listed once its record is complete
    for that stage and round, or when it is the caller's own. Authors are
    pseudonyms while a round keeps its reviewers anonymous."""
    users = project_namer(db, project_id)
    configs = {(c.stage, c.round): c for c in
               db.query(ScreeningConfig).filter_by(project_id=project_id)}
    out: list[dict] = []
    votes = (db.query(Vote)
             .filter(Vote.project_id == project_id,
                     Vote.is_ai.is_(False),
                     Vote.justification != ""))
    for v in votes:
        config = configs.get((v.stage, v.round))
        if (v.voter_user_id != me and config is not None
                and record_outcome(db, config, v.record_id) is None):
            continue
        out.append({
            "record_id": v.record_id, "stage": v.stage, "round": v.round,
            "kind": "vote", "author": users(v.voter_user_id),
            "decision": v.decision, "note": v.justification,
            "at": v.created_at.isoformat() if v.created_at else "",
        })
    conflicts = (db.query(Conflict)
                 .filter(Conflict.project_id == project_id,
                         Conflict.origin == "votes",
                         Conflict.resolution_note != ""))
    for c in conflicts:
        out.append({
            "record_id": c.record_id, "stage": c.stage, "round": c.round,
            "kind": "resolution", "author": users(c.resolved_by),
            "decision": c.resolution or "", "note": c.resolution_note,
            "at": c.resolved_at.isoformat() if c.resolved_at else "",
        })
    records = {r.id: r for r in db.query(Record)
               .filter(Record.id.in_({row["record_id"] for row in out}))} \
        if out else {}
    rows = []
    for row in out:
        record = records.get(row["record_id"])
        if record is None:
            continue
        row["title"] = record.title
        row["authors"] = record.authors or []
        row["year"] = record.year
        rows.append(row)
    rows.sort(key=lambda r: r["at"], reverse=True)
    return rows


@router.get("")
def list_notes(project_id: int, member: ProjectMemberDep, db: DbDep):
    get_project(project_id, db)
    return _rows(db, project_id, member.user_id)


@router.get("/export.csv")
def export_notes(project_id: int, member: ProjectMemberDep, db: DbDep):
    get_project(project_id, db)
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(["Stage", "Round", "Type", "Author", "Decision", "Note",
                     "Title", "First author", "Year", "Date"])
    for r in _rows(db, project_id, member.user_id):
        writer.writerow(safe_row([
            "title/abstract" if r["stage"] == "ta" else "full text",
            r["round"], r["kind"], r["author"], r["decision"], r["note"],
            r["title"], (r["authors"] or [""])[0], r["year"] or "", r["at"]]))
    return StreamingResponse(
        iter([buffer.getvalue().encode("utf-8-sig")]),
        media_type="text/csv",
        headers={"Content-Disposition":
                 'attachment; filename="screening_notes.csv"'})
