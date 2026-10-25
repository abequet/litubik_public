# SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
# SPDX-License-Identifier: AGPL-3.0-or-later
"""M6: full-text retrieval — settings, batch download, manual upload, PDF serving."""
import os
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import func
from starlette.background import BackgroundTask

from app.api.deps import (
    CurrentUser, DbDep, NoSandbox, ProjectMemberDep, SatelliteGuard, get_project,
    require_project_admin,
)
from app.core.demo import (
    DEMO_MAX_PDF_BYTES, is_demo_user, sandbox_owner, sandbox_storage_error,
)
from app.core.crypto import encrypt_secret
from app.core.ssrf import SSRFError, validate_url_shape
from app.models import FullText, FulltextConfig, Record
from app.services.fulltext.service import (
    ascii_words, export_filename, included_record_ids, pdf_dir,
)
from app.workers.runner import runner

router = APIRouter(prefix="/api/projects/{project_id}/fulltext",
                   tags=["fulltext"], dependencies=[SatelliteGuard])

MAX_PDF_BYTES = 100 * 1024 * 1024


def _reject_internal_url(url: str, label: str) -> None:
    """C1/H4: an operator/reviewer-supplied outbound URL must not point at an
    internal/private host (cloud metadata, localhost, LAN services)."""
    if not (url or "").strip():
        return
    try:
        # shape-only at the boundary (no DNS): a legitimate host that is not
        # resolvable right now still saves; the connect-time guard in doibatch
        # does the full private-IP resolution when it actually navigates.
        validate_url_shape(url)
    except SSRFError as e:
        raise HTTPException(status_code=400, detail=f"{label} : {e}")


class Institution(BaseModel):
    name: str = ""
    ezproxy_url: str = ""
    username: str = ""
    password: str = ""  # write-only; stored encrypted, never returned
    scope: str = ""
    auth_type: str = ""


class ConfigIn(BaseModel):
    unpaywall_email: str = Field(default="", max_length=255)
    institutions: list[Institution] = []


class InstitutionsIn(BaseModel):
    institutions: list[Institution] = []


class InstitutionOut(BaseModel):
    name: str
    ezproxy_url: str
    username: str
    scope: str
    auth_type: str
    has_password: bool


class ConfigOut(BaseModel):
    unpaywall_email: str
    institutions: list[InstitutionOut]
    default_email: str = ""  # login email, used when unpaywall_email is empty
    inherited_institutions: list[InstitutionOut] = []  # global, read-only here


class RetrieveIn(BaseModel):
    record_ids: list[int] = []  # empty = all T/A-included records
    force: bool = False
    # M4b: the caller's own institutional credentials, held in their browser.
    # Never persisted: handed to the job through an in-memory token (the job
    # params land in the DB, these must not).
    institutions: list[Institution] = []


class FullTextRow(BaseModel):
    record_id: int
    doi: str | None
    title: str
    authors: list = []
    year: int | None
    status: str  # pending | retrieved | not_found | manual
    via: str
    filename: str
    oa_url: str
    error: str
    size_kb: int | None
    has_file: bool
    # full-text screening outcome across rounds: include | exclude | pending
    ft_decision: str = "pending"
    # bumped on every (re)upload — the front uses it as a cache-buster so a
    # replaced PDF shows immediately (bug B2)
    updated_at: str = ""


def _inst_out(institutions: list[dict]) -> list[InstitutionOut]:
    return [InstitutionOut(
        name=i.get("name", ""), ezproxy_url=i.get("ezproxy_url", ""),
        username=i.get("username", ""), scope=i.get("scope", ""),
        auth_type=i.get("auth_type", ""),
        has_password=bool(i.get("password_encrypted"))) for i in institutions]


def get_config_response(project_id: int, user: CurrentUser, db: DbDep) -> ConfigOut:
    config = db.query(FulltextConfig).filter_by(project_id=project_id).first()
    global_cfg = db.query(FulltextConfig).filter_by(project_id=None).first()
    if is_demo_user(user):
        # a demo visitor retrieves from open sources only, and must not even
        # see which institutional accounts the instance holds
        return ConfigOut(unpaywall_email="", institutions=[])
    return ConfigOut(
        unpaywall_email=config.unpaywall_email if config else "",
        institutions=_inst_out((config.institutions if config else None) or []),
        default_email=user.email,
        inherited_institutions=_inst_out(
            (global_cfg.institutions if global_cfg else None) or []))


@router.get("/config", response_model=ConfigOut,
            dependencies=[Depends(require_project_admin)])
def get_config(project_id: int, user: CurrentUser, db: DbDep):
    get_project(project_id, db)
    return get_config_response(project_id, user, db)


@router.put("/config", response_model=ConfigOut,
            dependencies=[Depends(require_project_admin), NoSandbox])
def put_config(project_id: int, payload: ConfigIn, user: CurrentUser, db: DbDep):
    get_project(project_id, db)
    for inst in payload.institutions:
        _reject_internal_url(inst.ezproxy_url,
                             f"URL EZProxy de « {inst.name or '?'} »")
    config = db.query(FulltextConfig).filter_by(project_id=project_id).first()
    if config is None:
        config = FulltextConfig(project_id=project_id)
        db.add(config)
    existing = {i.get("name"): i for i in (config.institutions or [])}
    config.unpaywall_email = payload.unpaywall_email.strip()
    institutions = []
    for inst in payload.institutions:
        entry = {"name": inst.name, "ezproxy_url": inst.ezproxy_url,
                 "username": inst.username, "scope": inst.scope,
                 "auth_type": inst.auth_type}
        if inst.password:
            entry["password_encrypted"] = encrypt_secret(inst.password)
        elif inst.name in existing and existing[inst.name].get("password_encrypted"):
            entry["password_encrypted"] = existing[inst.name]["password_encrypted"]
        institutions.append(entry)
    config.institutions = institutions
    db.commit()
    return get_config_response(project_id, user, db)


# -- app-wide institutions ---------------------------------------------------
# The global FulltextConfig row (project_id NULL) holds the institutions every
# project inherits. Projects could only *see* them, read-only, from their own
# full-text settings — there was no screen to add or fix one. This router is
# that screen's API (application admin, like the global AI/database keys).
global_router = APIRouter(prefix="/api/fulltext", tags=["fulltext"])


def _require_app_admin(user: CurrentUser) -> None:
    if not user.is_admin:
        raise HTTPException(
            status_code=403,
            detail="Only an application admin manages the app-wide institutions")


@global_router.get("/institutions", response_model=list[InstitutionOut])
def list_global_institutions(user: CurrentUser, db: DbDep):
    _require_app_admin(user)
    config = db.query(FulltextConfig).filter_by(project_id=None).first()
    return _inst_out((config.institutions if config else None) or [])


@global_router.put("/institutions", response_model=list[InstitutionOut])
def put_global_institutions(payload: InstitutionsIn, user: CurrentUser, db: DbDep):
    """Replace the app-wide list. An entry sent without a password keeps the
    stored one (passwords are write-only and never travel back)."""
    _require_app_admin(user)
    for inst in payload.institutions:
        _reject_internal_url(inst.ezproxy_url,
                             f"URL EZProxy de « {inst.name or '?'} »")
    config = db.query(FulltextConfig).filter_by(project_id=None).first()
    if config is None:
        config = FulltextConfig(project_id=None)
        db.add(config)
    existing = {i.get("name"): i for i in (config.institutions or [])}
    institutions = []
    for inst in payload.institutions:
        if not inst.name.strip():
            continue  # a nameless entry is an empty form row
        entry = {"name": inst.name, "ezproxy_url": inst.ezproxy_url,
                 "username": inst.username, "scope": inst.scope,
                 "auth_type": inst.auth_type}
        if inst.password:
            entry["password_encrypted"] = encrypt_secret(inst.password)
        elif inst.name in existing and existing[inst.name].get("password_encrypted"):
            entry["password_encrypted"] = existing[inst.name]["password_encrypted"]
        institutions.append(entry)
    config.institutions = institutions
    db.commit()
    return _inst_out(institutions)


@router.get("", response_model=list[FullTextRow])
def list_fulltexts(project_id: int, member: ProjectMemberDep, db: DbDep):
    get_project(project_id, db)
    eligible = included_record_ids(db, project_id)
    records = {r.id: r for r in db.query(Record)
              .filter(Record.id.in_(eligible)).all()} if eligible else {}
    fts = {ft.record_id: ft for ft in db.query(FullText)
           .filter(FullText.record_id.in_(eligible))} if eligible else {}
    # full-text screening outcome per record, across every round (library colours)
    from app.models import ScreeningConfig
    from app.services.screening.core import screening_outcomes
    ft_out: dict[int, str] = {}
    for config in db.query(ScreeningConfig).filter_by(
            project_id=project_id, stage="ft", status="active"):
        ft_out.update(screening_outcomes(db, config))
    rows = []
    for rid in eligible:
        record = records.get(rid)
        if record is None:
            continue
        ft = fts.get(rid)
        rows.append(FullTextRow(
            record_id=rid, doi=record.doi, title=record.title,
            authors=record.authors or [], year=record.year,
            status=ft.status if ft else "pending",
            via=ft.via if ft else "", filename=ft.filename if ft else "",
            oa_url=ft.oa_url if ft else "", error=ft.error if ft else "",
            size_kb=ft.size_kb if ft else None,
            has_file=bool(ft and ft.file_path and Path(ft.file_path).exists()),
            ft_decision=ft_out.get(rid, "pending"),
            updated_at=ft.updated_at.isoformat() if ft and ft.updated_at else ""))
    # not-yet-retrieved first, then not_found, then done
    order = {"pending": 0, "not_found": 1, "manual": 2, "retrieved": 3}
    rows.sort(key=lambda r: order.get(r.status, 0))
    return rows


@router.get("/summary")
def summary(project_id: int, member: ProjectMemberDep, db: DbDep):
    get_project(project_id, db)
    eligible = included_record_ids(db, project_id)
    by_status = dict(db.query(FullText.status, func.count(FullText.id))
                     .filter(FullText.record_id.in_(eligible))
                     .group_by(FullText.status).all()) if eligible else {}
    retrieved = by_status.get("retrieved", 0) + by_status.get("manual", 0)
    not_found = by_status.get("not_found", 0)
    return {"eligible": len(eligible), "retrieved": retrieved,
            "not_found": not_found,
            "pending": len(eligible) - retrieved - not_found}


@router.post("/retrieve")
def retrieve(project_id: int, payload: RetrieveIn, user: CurrentUser,
             member: ProjectMemberDep, db: DbDep):
    """Any project member can launch retrieval (M4b): a reviewer whose
    institution covers missing PDFs runs it with their own browser-held
    credentials, and the PDFs land in the shared project library."""
    get_project(project_id, db)
    for inst in payload.institutions:
        _reject_internal_url(inst.ezproxy_url,
                             f"URL EZProxy de « {inst.name or '?'} »")
    # demo instances: a visitor (or a visitor's project) gets the open sources
    # only — no institution, no extension, never their address to Unpaywall
    sandbox = is_demo_user(user) or sandbox_owner(db, project_id) is not None
    params = {"project_id": project_id, "record_ids": payload.record_ids,
              "force": payload.force,
              "fallback_email": "" if sandbox else user.email,
              "use_extensions": not sandbox, "sandbox": sandbox}
    ephemeral = ([] if sandbox else
                 [inst.model_dump() for inst in payload.institutions
                  if inst.ezproxy_url and inst.password])
    if ephemeral:
        from app.services.fulltext.ephemeral import stash_institutions
        params["institutions_token"] = stash_institutions(ephemeral)
    job = runner.submit("fulltext_retrieve", params,
                        project_id=project_id, user_id=member.user_id)
    return {"job_id": job.id}


@router.post("/records/{record_id}/upload", response_model=FullTextRow)
async def upload_pdf(project_id: int, record_id: int, file: UploadFile,
                     member: ProjectMemberDep, db: DbDep):
    """Upload or replace one record's PDF. Open to every project member: a
    reviewer who finds the file missing or wrong mid-screening fixes it on the
    spot rather than waiting for an admin. Deleting stays admin-only."""
    record = db.get(Record, record_id)
    if record is None or record.project_id != project_id:
        raise HTTPException(status_code=404, detail="Record not found")
    data = await file.read()
    if len(data) > MAX_PDF_BYTES:
        raise HTTPException(status_code=413, detail="File too large (max 100 MB)")
    if sandbox_owner(db, project_id) is not None:
        if len(data) > DEMO_MAX_PDF_BYTES:
            raise HTTPException(status_code=413,
                                detail="File too large for the demo (max 20 MB)")
        full = sandbox_storage_error(project_id, len(data))
        if full:
            raise HTTPException(status_code=413, detail=full)
    if not data[:5].startswith(b"%PDF"):
        raise HTTPException(status_code=400, detail="Not a PDF file")
    target = pdf_dir(project_id) / f"{record_id}.pdf"
    target.write_bytes(data)
    ft = db.query(FullText).filter_by(record_id=record_id).first()
    if ft is None:
        ft = FullText(record_id=record_id)
        db.add(ft)
    ft.status = "manual"
    ft.via = "upload"
    ft.filename = (file.filename or f"{record_id}.pdf").replace("\\", "/").rsplit("/", 1)[-1]
    ft.file_path = str(target)
    ft.size_kb = round(len(data) / 1024)
    ft.error = ""
    db.commit()
    return FullTextRow(
        record_id=record_id, doi=record.doi, title=record.title, year=record.year,
        status="manual", via="upload", filename=ft.filename, oa_url=ft.oa_url,
        error="", size_kb=ft.size_kb, has_file=True,
        updated_at=ft.updated_at.isoformat() if ft.updated_at else "")


@router.post("/pdf-import", dependencies=[Depends(require_project_admin)])
async def pdf_bulk_import(project_id: int, files: list[UploadFile], db: DbDep,
                          member: ProjectMemberDep,
                          overwrite: bool = Form(default=False)):
    """Bulk PDF import: each file is matched to a record (DOI in the text,
    DOI in the filename, then title fuzzy) and stored like a manual upload.
    Ambiguous/unmatched files are reported with candidates — the client keeps
    the files and resolves them through the per-record upload endpoint."""
    get_project(project_id, db)
    from app.services.fulltext import bulk_import
    index = bulk_import.build_index(db, project_id)
    sandbox = sandbox_owner(db, project_id) is not None
    results = []
    for file in files:
        filename = (file.filename or "file.pdf") \
            .replace("\\", "/").rsplit("/", 1)[-1]
        data = await file.read()
        if len(data) > MAX_PDF_BYTES:
            results.append({"filename": filename, "status": "error",
                            "reason": "File too large (max 100 MB)"})
            continue
        if sandbox:
            reason = ("File too large for the demo (max 20 MB)"
                      if len(data) > DEMO_MAX_PDF_BYTES
                      else sandbox_storage_error(project_id, len(data)))
            if reason:
                results.append({"filename": filename, "status": "error",
                                "reason": reason})
                continue
        if not data[:5].startswith(b"%PDF"):
            results.append({"filename": filename, "status": "error",
                            "reason": "Not a PDF file"})
            continue
        match = bulk_import.match_pdf(filename, data, index)
        record = match["record"]
        if record is not None:
            if record.id in index["with_pdf"] and not overwrite:
                results.append({
                    "filename": filename, "status": "already_has_pdf",
                    "record_id": record.id, "title": record.title,
                    "method": match["method"]})
                continue
            bulk_import.store_pdf(db, project_id, record, filename, data)
            index["with_pdf"].add(record.id)
            results.append({
                "filename": filename, "status": "linked",
                "record_id": record.id, "title": record.title,
                "method": match["method"]})
        else:
            results.append({
                "filename": filename,
                "status": "ambiguous" if match["candidates"] else "unmatched",
                "candidates": [{
                    "record_id": r.id, "title": r.title, "year": r.year,
                    "score": round(score),
                } for r, score in match["candidates"]]})
    db.commit()
    linked = sum(1 for r in results if r["status"] == "linked")
    return {"results": results, "linked": linked,
            "total": len(results)}


@router.get("/records/{record_id}/file")
def serve_pdf(project_id: int, record_id: int, member: ProjectMemberDep, db: DbDep):
    record = db.get(Record, record_id)
    if record is None or record.project_id != project_id:
        raise HTTPException(status_code=404, detail="Record not found")
    ft = db.query(FullText).filter_by(record_id=record_id).first()
    if ft is None or not ft.file_path or not Path(ft.file_path).exists():
        raise HTTPException(status_code=404, detail="No PDF stored for this record")
    # no-cache: the URL is identical before/after a "Replace PDF", so the
    # browser must revalidate instead of serving its cached copy (bug B2)
    return FileResponse(ft.file_path, media_type="application/pdf",
                        filename=ft.filename or f"{record_id}.pdf",
                        content_disposition_type="inline",
                        headers={"Cache-Control": "no-cache"})


@router.get("/download-zip")
def download_zip(project_id: int, member: ProjectMemberDep, db: DbDep,
                 ids: str = ""):
    """Bundle the stored PDFs into a zip, one file per record named
    `Author_Year_five_first_title_words.pdf`. `ids` is a comma-separated
    selection; empty means every downloaded PDF of the library.

    A GET (a download is a read): it streams from disk rather than through the
    browser's memory, and it stays available on a satellite instance."""
    project = get_project(project_id, db)
    eligible = included_record_ids(db, project_id)
    if ids.strip():
        try:
            wanted = {int(part) for part in ids.split(",") if part.strip()}
        except ValueError:
            raise HTTPException(status_code=400,
                                detail="ids must be integers") from None
        eligible = [rid for rid in eligible if rid in wanted]
    records = {r.id: r for r in db.query(Record)
               .filter(Record.id.in_(eligible)).all()} if eligible else {}
    fts = {ft.record_id: ft for ft in db.query(FullText)
           .filter(FullText.record_id.in_(eligible))} if eligible else {}

    taken: set[str] = set()
    entries = []
    for rid in eligible:
        record, ft = records.get(rid), fts.get(rid)
        if record is None or ft is None or not ft.file_path:
            continue
        path = Path(ft.file_path)
        if path.exists():
            entries.append((path, export_filename(record, taken)))
    if not entries:
        raise HTTPException(status_code=404,
                            detail="No PDF stored for this selection")

    handle, tmp_path = tempfile.mkstemp(prefix="litubik_pdfs_", suffix=".zip")
    os.close(handle)
    try:
        # PDFs are already compressed: level 1 buys the little that is left
        # without making a 300-file library crawl
        with zipfile.ZipFile(tmp_path, "w", zipfile.ZIP_DEFLATED,
                             compresslevel=1) as archive:
            for path, name in entries:
                archive.write(path, arcname=name)
    except Exception:
        os.unlink(tmp_path)
        raise
    stem = "_".join(ascii_words(project.name)[:6]) or "project"
    return FileResponse(
        tmp_path, media_type="application/zip", filename=f"{stem}_pdfs.zip",
        background=BackgroundTask(os.unlink, tmp_path))


@router.delete("/records/{record_id}", dependencies=[Depends(require_project_admin)])
def delete_pdf(project_id: int, record_id: int, db: DbDep):
    record = db.get(Record, record_id)
    if record is None or record.project_id != project_id:
        raise HTTPException(status_code=404, detail="Record not found")
    ft = db.query(FullText).filter_by(record_id=record_id).first()
    if ft is not None:
        if ft.file_path and Path(ft.file_path).exists():
            Path(ft.file_path).unlink()
        db.delete(ft)
        db.commit()
    return {"ok": True}
