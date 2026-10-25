# SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
# SPDX-License-Identifier: AGPL-3.0-or-later
"""M3: run database searches, import reference files, browse the unified
record table, export the PRISMA-S style search report."""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field
from sqlalchemy import or_

from app.api.deps import (
    DbDep, ProjectMemberDep, SatelliteGuard, get_project,
    require_project_admin,
)
from app.models import Equation, Import, Project, Record, Source, User
from app.services.connectors.fetch import FETCHERS, KEYED_FETCHERS
from app.services.connectors.keys import resolve_db_key
from app.services.connectors.jobs import archive_raw, get_or_create_source, store_import
from app.services.equations import project_databases
from app.services.ris import ImportFileError, parse_file
from app.workers.runner import runner

router = APIRouter(prefix="/api/projects/{project_id}", tags=["imports"],
                   dependencies=[SatelliteGuard])

MAX_UPLOAD_BYTES = 100 * 1024 * 1024
MAX_CAP = 20000
# PRISMA-S: the fields a search ran on, as an uploader declares them (an
# equation searches title/abstract/keywords; a database may also offer the
# full text or an "all fields" index)
SEARCH_FIELDS = {"title": "title", "abstract": "abstract", "keywords": "keywords",
                 "fulltext": "full text", "all": "all fields"}
SEARCH_FIELD_IDS = list(SEARCH_FIELDS)


def _split_labels(value: str | None) -> list[str]:
    return [v.strip() for v in (value or "").split(",") if v.strip()]


def _fields_label(fields: list[str] | None) -> str:
    return ", ".join(SEARCH_FIELDS.get(f, f) for f in fields) if fields else "—"


class FetchIn(BaseModel):
    equation_id: int
    database: str
    cap: int = Field(default=5000, ge=1, le=MAX_CAP)


class ImportOut(BaseModel):
    id: int
    source_type: str
    source_name: str
    round: int
    equation_id: int | None
    equation_label: str | None
    filename: str
    n_records: int
    imported_by: str | None
    imported_at: datetime
    searched_at: datetime | None = None
    declared_hits: int | None = None
    # PRISMA-S limits applied to this run (None = not declared)
    date_restricted: bool | None = None
    discipline_restricted: bool | None = None
    disciplines: list[str] | None = None
    doc_type_restricted: bool | None = None
    doc_types: list[str] | None = None
    search_fields: list[str] | None = None


class RecordOut(BaseModel):
    id: int
    doi: str | None
    title: str
    authors: list
    year: int | None
    journal: str
    abstract: str
    source_name: str
    dedup_status: str


class RecordsPage(BaseModel):
    total: int
    items: list[RecordOut]


@router.post("/search/fetch")
def run_fetch(project_id: int, payload: FetchIn, member: ProjectMemberDep,
              db: DbDep, _admin=Depends(require_project_admin)):
    """Launch the paginated API search for one database (background job)."""
    if payload.database not in FETCHERS and payload.database not in KEYED_FETCHERS:
        raise HTTPException(status_code=400,
                            detail=f"'{payload.database}' has no API — use the "
                                   "assisted manual import instead")
    if (payload.database in KEYED_FETCHERS
            and not resolve_db_key(db, project_id, payload.database)):
        raise HTTPException(status_code=400,
                            detail=f"Configure the {payload.database} API key first "
                                   "(Database settings) to fetch automatically")
    equation = db.get(Equation, payload.equation_id)
    if equation is None or equation.project_id != project_id:
        raise HTTPException(status_code=404, detail="Equation not found")
    job = runner.submit("search_fetch",
                        {"equation_id": equation.id, "database": payload.database,
                         "cap": payload.cap, "user_id": member.user_id},
                        project_id=project_id, user_id=member.user_id)
    return {"job_id": job.id}


def _parse_searched_at(value: str | None) -> datetime | None:
    if not value or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip())
    except ValueError:
        raise HTTPException(status_code=400,
                            detail="searched_at must be a date (YYYY-MM-DD)")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


@router.post("/imports/upload")
async def upload_import(project_id: int, file: UploadFile, db: DbDep,
                        member: ProjectMemberDep,
                        source_name: str = Form(min_length=1, max_length=100),
                        source_type: str = Form(default="manual",
                                                pattern="^(database|manual)$"),
                        equation_id: int | None = Form(default=None),
                        searched_at: str | None = Form(default=None),
                        declared_hits: int | None = Form(default=None, ge=0),
                        round_mode: str = Form(default="initial",
                                               pattern="^(initial|update)$"),
                        date_restricted: bool | None = Form(default=None),
                        discipline_restricted: bool | None = Form(default=None),
                        disciplines: str | None = Form(default=None, max_length=2000),
                        doc_type_restricted: bool | None = Form(default=None),
                        doc_types: str | None = Form(default=None, max_length=2000),
                        search_fields: str | None = Form(default=None, max_length=200),
                        _admin=Depends(require_project_admin)):
    """Import a reference file (.ris/.nbib/.bib/.csv) under a named source —
    assisted manual export of a closed database, or any side source.

    `searched_at` / `declared_hits`: what PRISMA-S asks for (the day the
    search ran, the count the database showed). `round_mode`: initial
    (default) = the export belongs to the initial search — a database's
    export often arrives after screening has started, and its records join
    the active round's queues (sync_assignments); update = a re-run of the
    search, a search update pass with its own round, like an API fetch
    during screening. `date_restricted` / `discipline_restricted`: whether the
    equation's date range and discipline limits were applied on the database
    (PRISMA-S limits; omitted = not declared); `disciplines`: the subject
    areas the search was limited to, comma-separated; `doc_type_restricted` /
    `doc_types`: the same for document types; `search_fields`: the fields the
    query ran on, comma-separated SEARCH_FIELD_IDS."""
    get_project(project_id, db)
    discipline_list = _split_labels(disciplines)
    if discipline_list and discipline_restricted is None:
        discipline_restricted = True
    doc_type_list = _split_labels(doc_types)
    if doc_type_list and doc_type_restricted is None:
        doc_type_restricted = True
    field_list = [f for f in SEARCH_FIELD_IDS if f in _split_labels(search_fields)]
    data = await file.read()
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File too large (max 100 MB)")
    if equation_id is not None:
        equation = db.get(Equation, equation_id)
        if equation is None or equation.project_id != project_id:
            raise HTTPException(status_code=404, detail="Equation not found")
    searched = _parse_searched_at(searched_at)
    try:
        records = parse_file(file.filename or "refs.ris", data)
    except ImportFileError as e:
        raise HTTPException(status_code=400, detail=str(e))
    # M6: sandbox accounts of a demo instance import at most a modest batch
    from app.core import demo
    if len(records) > demo.DEMO_MAX_IMPORT_RECORDS and demo.is_demo_user(
            db.get(User, member.user_id)):
        raise HTTPException(
            status_code=413,
            detail=f"Demo accounts import at most {demo.DEMO_MAX_IMPORT_RECORDS} "
                   "references per file")
    # ...and a visitor's project holds a bounded corpus, whatever the imports
    room = demo.sandbox_records_room(db, project_id)
    if room is not None and len(records) > room:
        raise HTTPException(
            status_code=413,
            detail=f"Demo projects hold at most {demo.DEMO_MAX_PROJECT_RECORDS} "
                   f"references — room is left for {room} more")

    from app.services.equations.recall import recall_from_imports
    from app.services.living.service import (
        count_new_unique, notify_members, open_next_screening_round,
        record_update_run,
    )
    from app.services.snowballing.service import next_round

    safe_name = (file.filename or "refs.ris").replace("\\", "/").rsplit("/", 1)[-1]
    archived = archive_raw(project_id, safe_name, data)
    update_pass = round_mode == "update"
    round_ = next_round(db, project_id) if update_pass else 1
    source = get_or_create_source(db, project_id, source_type, source_name.strip(),
                                  round_)
    imp = store_import(db, project_id=project_id, source_id=source.id,
                       equation_id=equation_id, filename=archived,
                       records=records, user_id=member.user_id,
                       searched_at=searched, declared_hits=declared_hits,
                       date_restricted=date_restricted,
                       discipline_restricted=discipline_restricted,
                       disciplines=discipline_list,
                       doc_type_restricted=doc_type_restricted,
                       doc_types=doc_type_list, search_fields=field_list)
    db.flush()
    if equation_id is not None and source_type == "database":
        recall_from_imports(db, equation_id, source.name)
    result = {"import_id": imp.id, "n_records": len(records),
              "source_name": source.name, "round": round_}
    if update_pass:
        # same bookkeeping as an API fetch during screening: dedup now so the
        # new records are screenable, open the next round, tell the team
        from app.services.dedup.core import run_dedup
        db.commit()
        run_dedup(db, project_id, None)
        n_new_unique = count_new_unique(db, [imp.id])
        ta_started = False
        if n_new_unique:
            ta_started = open_next_screening_round(db, project_id, round_)
        record_update_run(db, project_id, round_=round_, databases=[source.name],
                          since_at=None, n_fetched=len(records),
                          n_new_unique=n_new_unique, triggered_by="upload",
                          errors=None, user_id=member.user_id)
        project_name = db.get(Project, project_id).name
        notify_members(db, project_id, "search_update", {
            "project_name": project_name, "round": round_,
            "n_fetched": len(records), "n_new_unique": n_new_unique,
            "databases": [source.name], "ta_started": ta_started,
            "triggered_by": "upload"}, exclude_user=member.user_id)
        result.update({"n_new_unique": n_new_unique, "ta_round_started": ta_started})
    db.commit()
    # silent abstract backfill of what the file did not carry (open APIs)
    from app.services.connectors.abstracts import schedule_backfill
    schedule_backfill(project_id, [imp.id], member.user_id)
    return result


@router.get("/imports", response_model=list[ImportOut])
def list_imports(project_id: int, member: ProjectMemberDep, db: DbDep):
    get_project(project_id, db)
    rows = (
        db.query(Import, Source, Equation, User)
        .join(Source, Source.id == Import.source_id)
        .outerjoin(Equation, Equation.id == Import.equation_id)
        .outerjoin(User, User.id == Import.imported_by)
        .filter(Import.project_id == project_id)
        .order_by(Import.imported_at.desc())
        .all()
    )
    return [ImportOut(id=i.id, source_type=s.type, source_name=s.name, round=s.round,
                      equation_id=i.equation_id,
                      equation_label=e.label if e else None, filename=i.filename,
                      n_records=i.n_records,
                      imported_by=u.display_name if u else None,
                      imported_at=i.imported_at, searched_at=i.searched_at,
                      declared_hits=i.declared_hits,
                      date_restricted=i.date_restricted,
                      discipline_restricted=i.discipline_restricted,
                      disciplines=i.disciplines,
                      doc_type_restricted=i.doc_type_restricted,
                      doc_types=i.doc_types, search_fields=i.search_fields)
            for i, s, e, u in rows]


@router.delete("/imports/{import_id}", dependencies=[Depends(require_project_admin)])
def delete_import(project_id: int, import_id: int, db: DbDep):
    """Remove a bad import and all its records (the archived raw file stays)."""
    imp = db.get(Import, import_id)
    if imp is None or imp.project_id != project_id:
        raise HTTPException(status_code=404, detail="Import not found")
    db.query(Record).filter_by(import_id=import_id).delete()
    db.delete(imp)
    db.commit()
    return {"ok": True}


RECORD_SORTS = {
    "recent": (Record.id.desc(),),
    "source": (Source.name.asc(), Record.id.desc()),
    "year": (Record.year.desc().nullslast(), Record.id.desc()),
    "title": (Record.title.asc(),),
}


@router.get("/records/sources")
def record_sources(project_id: int, member: ProjectMemberDep, db: DbDep):
    """Distinct source names having records (for the filter dropdown)."""
    get_project(project_id, db)
    rows = (
        db.query(Source.name)
        .join(Import, Import.source_id == Source.id)
        .join(Record, Record.import_id == Import.id)
        .filter(Record.project_id == project_id)
        .distinct().order_by(Source.name).all()
    )
    return {"sources": [name for (name,) in rows]}


@router.get("/records", response_model=RecordsPage)
def list_records(project_id: int, member: ProjectMemberDep, db: DbDep,
                 q: str = "", source: str = "", sort: str = "recent",
                 equation_id: int | None = None, dedup: str = "",
                 page: int = 1, page_size: int = 50):
    get_project(project_id, db)
    page_size = min(max(page_size, 1), 200)
    query = (
        db.query(Record, Source.name)
        .join(Import, Import.id == Record.import_id)
        .join(Source, Source.id == Import.source_id)
        .filter(Record.project_id == project_id)
    )
    if q.strip():
        like = f"%{q.strip()}%"
        query = query.filter(or_(Record.title.ilike(like), Record.doi.ilike(like)))
    if source.strip():
        query = query.filter(Source.name == source.strip())
    if equation_id is not None:
        # free imports (hand search, expert lists, IEEE manual export…) carry no
        # equation but belong to the whole project — keep them visible under any
        # equation scope, and only hide records tied to a *different* equation.
        query = query.filter(or_(Import.equation_id == equation_id,
                                 Import.equation_id.is_(None)))
    if dedup.strip() in ("pending", "unique", "duplicate", "uncertain"):
        query = query.filter(Record.dedup_status == dedup.strip())
    total = query.count()
    rows = (query.order_by(*RECORD_SORTS.get(sort, RECORD_SORTS["recent"]))
            .offset((max(page, 1) - 1) * page_size).limit(page_size).all())
    return RecordsPage(total=total, items=[
        RecordOut(id=r.id, doi=r.doi, title=r.title, authors=r.authors,
                  year=r.year, journal=r.journal,
                  abstract=(r.abstract[:400] + "…") if len(r.abstract) > 400
                           else r.abstract,
                  source_name=source_name, dedup_status=r.dedup_status)
        for r, source_name in rows])


class AbstractIn(BaseModel):
    abstract: str = Field(max_length=20000)


@router.get("/records/{record_id}/card")
def record_card(project_id: int, record_id: int, member: ProjectMemberDep,
                db: DbDep):
    """The "paper card": metadata, provenance, screening outcomes per round,
    PDF state, and its snowballing story (how it was found; what its own
    crawls found when it served as a seed)."""
    from app.services.snowballing.service import record_card as build_card
    get_project(project_id, db)
    try:
        return build_card(db, project_id, record_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.put("/records/{record_id}/abstract")
def set_abstract(project_id: int, record_id: int, payload: AbstractIn,
                 member: ProjectMemberDep, db: DbDep):
    """Paste a missing abstract or edit the displayed one (T21). Edits are
    traced: the imported text is kept once in abstract_original, with who
    last edited and when — the abstract is the screening's source data."""
    record = db.get(Record, record_id)
    if record is None or record.project_id != project_id:
        raise HTTPException(status_code=404, detail="Record not found")
    new = payload.abstract.strip()
    if new != (record.abstract or ""):
        if record.abstract_original is None:
            record.abstract_original = record.abstract or ""
        record.abstract = new
        record.abstract_edited_by = member.user_id
        record.abstract_edited_at = datetime.now(timezone.utc)
        db.commit()
    return {"ok": True}


@router.get("/search-report", response_class=PlainTextResponse)
def search_report(project_id: int, member: ProjectMemberDep, db: DbDep):
    """PRISMA-S style search report: per source, the query used, date and count."""
    project = get_project(project_id, db)
    lines = [f"# Search report — {project.name}", ""]
    if project.research_question:
        lines += [f"**Research question:** {project.research_question}", ""]

    frozen = (db.query(Equation)
              .filter_by(project_id=project_id, status="frozen")
              .order_by(Equation.frozen_at.desc()).all())
    for eq in frozen:
        lines += [f"## Frozen equation — {eq.label} "
                  f"(frozen {eq.frozen_at:%Y-%m-%d})", ""]
        translations = eq.translations or {}
        drafts = translations.get("drafts") or {}
        for database in project_databases(db, project_id):
            query = ((translations.get("overrides") or {}).get(database["id"])
                     or (translations.get("auto") or {}).get(database["id"], ""))
            if query:
                draft = drafts.get(database["id"])
                note = ""
                if draft:
                    note = (" — AI draft, reviewed" if draft.get("validated")
                            else " — AI draft, NOT reviewed")
                lines += [f"**{database['label']}**{note}", "```", query, "```", ""]

    lines += ["## Imports (records identified per source)", ""]
    lines += ["| Source | Type | Equation | Searched | Imported | Hits shown | "
              "Records | Date limit | Discipline limit | Disciplines | "
              "Doc-type limit | Doc types | Search fields | File |",
              "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    limit = {True: "yes", False: "no", None: "—"}
    rows = (db.query(Import, Source, Equation)
            .join(Source, Source.id == Import.source_id)
            .outerjoin(Equation, Equation.id == Import.equation_id)
            .filter(Import.project_id == project_id)
            .order_by(Import.imported_at).all())
    total = 0
    for i, s, e in rows:
        total += i.n_records
        searched = f"{i.searched_at:%Y-%m-%d}" if i.searched_at else "—"
        hits = str(i.declared_hits) if i.declared_hits is not None else "—"
        lines.append(f"| {s.name} | {s.type} | {e.label if e else '—'} | "
                     f"{searched} | {i.imported_at:%Y-%m-%d} | {hits} | "
                     f"{i.n_records} | {limit[i.date_restricted]} | "
                     f"{limit[i.discipline_restricted]} | "
                     f"{'; '.join(i.disciplines) if i.disciplines else '—'} | "
                     f"{limit[i.doc_type_restricted]} | "
                     f"{'; '.join(i.doc_types) if i.doc_types else '—'} | "
                     f"{_fields_label(i.search_fields)} | "
                     f"{i.filename} |")
    lines += ["", f"**Total records identified: {total}**", ""]

    # golden-set recall per database — the protocol's acceptance test of the
    # equation, reported for every variant that was checked
    checked = [eq for eq in (db.query(Equation).filter_by(project_id=project_id)
                             .order_by(Equation.id)) if eq.recalls]
    if checked:
        from app.services.equations.recall import latest_per_database
        lines += ["## Golden-set recall per database", "",
                  "| Equation | Database | Method | Found | Checked | Missing |",
                  "|---|---|---|---|---|---|"]
        for eq in checked:
            for r in latest_per_database(eq):
                missing = "; ".join(m.get("citation") or m.get("doi") or m.get("pmid") or ""
                                    for m in (r.missing or [])) or "—"
                lines.append(f"| {eq.label} | {r.database_name} | {r.method} | "
                             f"{r.found}/{r.total} | {r.checked_at:%Y-%m-%d} | "
                             f"{missing} |")
        lines.append("")
    return "\n".join(lines)
