# SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Protocol module (M1): upload -> LLM extraction -> edit -> human validation.

The validated protocol.md is the "context pack" injected into every AI prompt
downstream; editing is locked once validated (upload/regenerate = new version).
"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import func

from app.api.deps import (
    DbDep, ProjectMemberDep, SatelliteGuard, get_project,
    require_project_admin,
)
from app.core.config import get_settings
from app.models import Protocol
from app.services.protocol import ProtocolFileError, extract_text, osf
from app.workers.runner import runner

router = APIRouter(prefix="/api/projects/{project_id}/protocols",
                   tags=["protocols"], dependencies=[SatelliteGuard])

MAX_UPLOAD_BYTES = 30 * 1024 * 1024


class CriterionModel(BaseModel):
    code: str = Field(min_length=1, max_length=10)
    type: str = Field(pattern="^(include|exclude)$")
    label: str = Field(min_length=1, max_length=255)
    description: str = ""


class ProtocolSummary(BaseModel):
    id: int
    version: int
    source_filename: str
    generated_with: str
    validated_at: datetime | None
    created_at: datetime
    has_content: bool


class ProtocolOut(ProtocolSummary):
    protocol_md: str
    criteria: list[CriterionModel]
    source_text_chars: int


class ProtocolUpdate(BaseModel):
    protocol_md: str
    criteria: list[CriterionModel]


class GenerateIn(BaseModel):
    credential_id: int | None = None


class OsfCandidate(BaseModel):
    kind: str = Field(pattern="^(file|form)$")
    name: str = ""
    download_url: str = ""
    guid: str = ""
    size: int | None = None


class OsfImportIn(BaseModel):
    url: str = Field(min_length=10, max_length=2000)
    pick: OsfCandidate | None = None  # candidate chosen after a multi-file response


def _get_protocol(project_id: int, protocol_id: int, db) -> Protocol:
    protocol = db.get(Protocol, protocol_id)
    if protocol is None or protocol.project_id != project_id:
        raise HTTPException(status_code=404, detail="Protocol version not found")
    return protocol


def _out(p: Protocol) -> ProtocolOut:
    return ProtocolOut(
        id=p.id, version=p.version, source_filename=p.source_filename,
        generated_with=p.generated_with, validated_at=p.validated_at,
        created_at=p.created_at, has_content=bool(p.protocol_md),
        protocol_md=p.protocol_md, criteria=p.criteria,
        source_text_chars=len(p.source_text),
    )


@router.get("", response_model=list[ProtocolSummary])
def list_versions(project_id: int, member: ProjectMemberDep, db: DbDep):
    get_project(project_id, db)
    versions = (
        db.query(Protocol)
        .filter_by(project_id=project_id)
        .order_by(Protocol.version.desc())
        .all()
    )
    return [ProtocolSummary(
        id=p.id, version=p.version, source_filename=p.source_filename,
        generated_with=p.generated_with, validated_at=p.validated_at,
        created_at=p.created_at, has_content=bool(p.protocol_md),
    ) for p in versions]


@router.get("/{protocol_id}", response_model=ProtocolOut)
def get_version(project_id: int, protocol_id: int, member: ProjectMemberDep, db: DbDep):
    return _out(_get_protocol(project_id, protocol_id, db))


def _persist_version(project_id: int, filename: str, text: str,
                     raw: bytes, db) -> Protocol:
    """Archive the raw source and create the next protocol version from its
    extracted text."""
    next_version = (
        db.query(func.max(Protocol.version))
        .filter_by(project_id=project_id).scalar() or 0
    ) + 1

    # archive the raw upload for audit/reproducibility
    protocol_dir = get_settings().storage_dir / str(project_id) / "protocol"
    protocol_dir.mkdir(parents=True, exist_ok=True)
    safe_name = filename.replace("\\", "/").rsplit("/", 1)[-1]
    (protocol_dir / f"v{next_version}_{safe_name}").write_bytes(raw)

    protocol = Protocol(project_id=project_id, version=next_version,
                        source_filename=safe_name, source_text=text)
    db.add(protocol)
    db.commit()
    db.refresh(protocol)
    return protocol


def _create_version(project_id: int, filename: str, data: bytes, db) -> Protocol:
    """Extract text, archive the raw file and create the next protocol version."""
    try:
        text = extract_text(filename, data)
    except ProtocolFileError as e:
        raise HTTPException(status_code=400, detail=str(e))
    safe_name = filename.replace("\\", "/").rsplit("/", 1)[-1]
    return _persist_version(project_id, safe_name, text, data, db)


@router.post("/upload", response_model=ProtocolOut,
             dependencies=[Depends(require_project_admin)])
async def upload_protocol(project_id: int, file: UploadFile, db: DbDep):
    """New protocol version from an uploaded PDF/DOCX/MD/TXT file."""
    get_project(project_id, db)
    data = await file.read()
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File too large (max 30 MB)")
    return _out(_create_version(project_id, file.filename or "protocol", data, db))


class PasteIn(BaseModel):
    text: str = Field(min_length=1)
    name: str = Field(default="Pasted protocol", max_length=200)


@router.post("/paste", response_model=ProtocolOut,
             dependencies=[Depends(require_project_admin)])
def paste_protocol(project_id: int, payload: PasteIn, db: DbDep):
    """New protocol version from text typed or pasted directly in the app —
    the alternative to uploading a file. The pasted text becomes the source
    text, ready for AI extraction / manual editing like an upload."""
    get_project(project_id, db)
    text = payload.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="Nothing to import")
    name = payload.name.strip() or "Pasted protocol"
    if not name.lower().endswith((".txt", ".md")):
        name += ".txt"
    return _out(_persist_version(project_id, name, text,
                                 text.encode("utf-8"), db))


@router.post("/import-osf", dependencies=[Depends(require_project_admin)])
def import_osf(project_id: int, payload: OsfImportIn, db: DbDep):
    """New protocol version fetched from an OSF link (project, registration or
    file). Returns {candidates: [...]} when the link holds several possible
    protocol documents — call again with the chosen one as `pick`."""
    project = get_project(project_id, db)
    try:
        result = osf.fetch_protocol(
            payload.url, payload.pick.model_dump() if payload.pick else None)
    except osf.OsfError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if isinstance(result, list):
        return {"candidates": result}
    filename, data = result
    version = _create_version(project_id, filename, data, db)
    # A protocol pulled from OSF is the strongest signal we will ever get that
    # the review is registered there (PRISMA 24a). Proposed, never imposed: an
    # answer already given is left alone. The number is filled only when the
    # link is a registration (its GUID); an OSF *project* is not one, so the
    # team then types it on the settings page.
    if not project.registry:
        project.registry = "osf"
        project.registration_url = payload.url.strip()[:500]
    if project.registry == "osf" and not project.registration_id:
        reg = osf.registration_of(payload.url)
        if reg is not None:
            project.registration_id = reg["guid"]
            if project.registered_at is None and reg["date_registered"]:
                try:
                    project.registered_at = datetime.fromisoformat(
                        reg["date_registered"].replace("Z", "+00:00"))
                except ValueError:
                    pass
    db.commit()
    return {"protocol": _out(version)}


@router.post("/{protocol_id}/generate",
             dependencies=[Depends(require_project_admin)])
def generate(project_id: int, protocol_id: int, payload: GenerateIn,
             member: ProjectMemberDep, db: DbDep):
    """Launch the LLM structured-extraction job for this version."""
    protocol = _get_protocol(project_id, protocol_id, db)
    if protocol.validated_at is not None:
        raise HTTPException(status_code=400,
                            detail="Version is validated — upload a new version instead")
    job = runner.submit("protocol_extract",
                        {"protocol_id": protocol.id,
                         "credential_id": payload.credential_id},
                        project_id=project_id, user_id=member.user_id)
    return {"job_id": job.id}


@router.put("/{protocol_id}", response_model=ProtocolOut)
def update_protocol(project_id: int, protocol_id: int, payload: ProtocolUpdate,
                    member: ProjectMemberDep, db: DbDep):
    protocol = _get_protocol(project_id, protocol_id, db)
    if protocol.validated_at is not None:
        raise HTTPException(status_code=400,
                            detail="Version is validated — upload a new version to change it")
    codes = [c.code.strip().upper() for c in payload.criteria]
    if len(set(codes)) != len(codes):
        raise HTTPException(status_code=400, detail="Criteria codes must be unique")
    protocol.protocol_md = payload.protocol_md
    protocol.criteria = [
        {**c.model_dump(), "code": code} for c, code in zip(payload.criteria, codes)
    ]
    db.commit()
    db.refresh(protocol)
    return _out(protocol)


@router.post("/{protocol_id}/validate", response_model=ProtocolOut,
             dependencies=[Depends(require_project_admin)])
def validate(project_id: int, protocol_id: int, db: DbDep):
    """Mandatory human validation: freezes the version and makes it the
    context pack used by all AI modules."""
    protocol = _get_protocol(project_id, protocol_id, db)
    if not protocol.protocol_md.strip():
        raise HTTPException(status_code=400, detail="Nothing to validate yet")
    if not protocol.criteria:
        raise HTTPException(status_code=400,
                            detail="Define at least one inclusion/exclusion criterion")
    protocol.validated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(protocol)
    return _out(protocol)


@router.post("/{protocol_id}/unvalidate", response_model=ProtocolOut,
             dependencies=[Depends(require_project_admin)])
def unvalidate(project_id: int, protocol_id: int, db: DbDep):
    protocol = _get_protocol(project_id, protocol_id, db)
    protocol.validated_at = None
    db.commit()
    db.refresh(protocol)
    return _out(protocol)


@router.delete("/{protocol_id}", dependencies=[Depends(require_project_admin)])
def delete_version(project_id: int, protocol_id: int, db: DbDep):
    protocol = _get_protocol(project_id, protocol_id, db)
    if protocol.validated_at is not None:
        raise HTTPException(status_code=400, detail="Cannot delete a validated version")
    db.delete(protocol)
    db.commit()
    return {"ok": True}
