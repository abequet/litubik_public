# SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Equation variants: snapshot of concepts -> per-database translations (or a
raw equation typed per database), counts (API job or manual entry),
golden-set recall per database, freeze."""
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator, model_validator

from app.api.deps import (
    DbDep, ProjectMemberDep, SatelliteGuard, get_project,
    require_project_admin,
)
from app.models import Concept, Equation, EquationCount, GoldenRef
from app.services import framing
from app.services.connectors.keys import KEYED_PROVIDERS, available_db_keys
from app.services.equations import (
    DATABASES, build_structure, custom_syntaxes, project_databases, translate_all,
)
from app.services.equations import recall as recall_svc
from app.services.equations.apa import fetch_reference
from app.services.equations.translate import (
    DEFAULT_FIELDS,
    DISCIPLINE_IDS,
    DISCIPLINES,
    DOC_TYPE_IDS,
    DOC_TYPES,
    FIELD_CHOICES,
)
from app.workers.runner import runner

router = APIRouter(prefix="/api/projects/{project_id}/equations",
                   tags=["equations"], dependencies=[SatelliteGuard])

API_DATABASES = [d["id"] for d in DATABASES if d["count"] == "api"]


def api_databases(db, project_id: int) -> list[str]:
    """Databases whose counts/fetches can run automatically: the always-free
    ones plus any keyed provider (Scopus/IEEE) with a configured API key —
    restricted to the databases the review searches."""
    searched = {d["id"] for d in project_databases(db, project_id)}
    return [d for d in API_DATABASES + sorted(available_db_keys(db, project_id))
            if d in searched]


class EquationParams(BaseModel):
    year_from: int | None = Field(default=None, ge=1800, le=2100)
    year_to: int | None = Field(default=None, ge=1800, le=2100)
    languages: list[str] = []
    # where the equation searches; syntax is adapted per database
    fields: list[str] = ["title", "abstract"]
    # applied where the database supports them (empty = no restriction)
    doc_types: list[str] = []
    disciplines: list[str] = []

    @field_validator("fields")
    @classmethod
    def _known_fields(cls, v: list[str]) -> list[str]:
        cleaned = [f for f in v if f in FIELD_CHOICES]
        return cleaned or list(DEFAULT_FIELDS)

    @field_validator("doc_types")
    @classmethod
    def _known_doc_types(cls, v: list[str]) -> list[str]:
        return [t for t in v if t in DOC_TYPE_IDS]

    @field_validator("disciplines")
    @classmethod
    def _known_disciplines(cls, v: list[str]) -> list[str]:
        return [d for d in v if d in DISCIPLINE_IDS]


class EquationIn(BaseModel):
    """`groups` = the blocks AND-ed together, each block one or more concepts
    OR-ed together. `concept_ids` (one block per concept) stays accepted for
    clients that don't build blocks.

    `mode="raw"`: no concepts at all — `translations` holds the query typed
    for each database (the protocol's own equation, pasted as is)."""

    label: str = Field(min_length=1, max_length=255)
    mode: Literal["concepts", "raw"] = "concepts"
    concept_ids: list[int] = []
    groups: list[list[int]] = []
    translations: dict[str, str] = {}
    params: EquationParams = EquationParams()

    @model_validator(mode="after")
    def _normalise_groups(self):
        if self.mode == "raw":
            self.translations = {db_id: q for db_id, q in self.translations.items()
                                 if q and q.strip()}
            if not self.translations:
                raise ValueError("Type the query for at least one database")
            self.groups, self.concept_ids = [], []
            return self
        groups = self.groups or [[cid] for cid in self.concept_ids]
        seen: set[int] = set()
        cleaned: list[list[int]] = []
        for group in groups:
            ids = []
            for cid in group:
                if cid not in seen:  # a concept belongs to one block only
                    seen.add(cid)
                    ids.append(cid)
            if ids:
                cleaned.append(ids)
        if not cleaned:
            raise ValueError("Select at least one concept")
        self.groups = cleaned
        self.concept_ids = [cid for group in cleaned for cid in group]
        return self


class OverrideIn(BaseModel):
    database: str
    query: str  # empty string clears the override (back to auto)


class ManualCountIn(BaseModel):
    database: str
    count: int = Field(ge=0)


class CountsJobIn(BaseModel):
    databases: list[str] = []  # empty = all API databases


class CountOut(BaseModel):
    database_name: str
    count: int
    method: str
    noted_at: datetime

    model_config = {"from_attributes": True}


class RecallOut(BaseModel):
    database_name: str
    method: str  # api | import
    total: int
    found: int
    missing: list[dict]
    checked_at: datetime

    model_config = {"from_attributes": True}


class EquationOut(BaseModel):
    id: int
    label: str
    mode: str = "concepts"
    structure: dict
    translations: dict
    params: dict
    status: str
    frozen_at: datetime | None
    golden_results: dict | None
    created_at: datetime
    counts: list[CountOut]
    # latest golden-set check per (database, method)
    recall: list[RecallOut] = []

    model_config = {"from_attributes": True}


def _equation_out(equation: Equation) -> EquationOut:
    out = EquationOut.model_validate(equation)
    out.recall = [RecallOut.model_validate(r)
                  for r in recall_svc.latest_per_database(equation)]
    return out


class GoldenIn(BaseModel):
    """One reference, by DOI, by PMID, or by a single `identifier` the server
    sorts out (`doi` alone stays accepted for older clients)."""
    identifier: str = ""
    doi: str = ""
    pmid: str = ""
    title: str = ""
    year: int | None = None


class GoldenBulkIn(BaseModel):
    identifiers: str = Field(min_length=1, max_length=20000)  # one per line


class GoldenOut(BaseModel):
    id: int
    doi: str | None
    pmid: str | None
    title: str = ""
    year: int | None = None
    apa: str = ""

    model_config = {"from_attributes": True}


class DraftIn(BaseModel):
    from_db: str
    to_db: str


class DraftAllIn(BaseModel):
    from_db: str = "pubmed"
    mode: Literal["missing", "unreviewed"] = "missing"
    databases: list[str] = []  # empty = every target of `mode`


class ValidateIn(BaseModel):
    database: str


def _get_equation(project_id: int, equation_id: int, db) -> Equation:
    equation = db.get(Equation, equation_id)
    if equation is None or equation.project_id != project_id:
        raise HTTPException(status_code=404, detail="Equation not found")
    return equation


def _require_draft(equation: Equation):
    if equation.status == "frozen":
        raise HTTPException(status_code=400,
                            detail="This equation is frozen — create a new variant to change it")


def _snapshot(project_id: int, payload: EquationIn, db) -> tuple[dict, dict]:
    concepts = (db.query(Concept)
                .filter(Concept.project_id == project_id,
                        Concept.id.in_(payload.concept_ids))
                .order_by(Concept.position, Concept.id).all())
    if len(concepts) != len(payload.concept_ids):
        raise HTTPException(status_code=400, detail="Unknown concept in selection")
    by_id = {c.id: c for c in concepts}
    structure = build_structure([[by_id[cid] for cid in group]
                                for group in payload.groups])
    params = payload.params.model_dump()
    return structure, params


@router.get("/databases")
def databases(project_id: int, member: ProjectMemberDep, db: DbDep):
    # a keyed database (Scopus/IEEE) becomes an automatic 'api' source once its
    # key is configured; otherwise it stays a manual assisted import
    have_keys = available_db_keys(db, project_id)
    out = []
    for d in project_databases(db, project_id):
        if d["id"] in KEYED_PROVIDERS:
            d["count"] = "api" if d["id"] in have_keys else "manual"
            d["key_required"] = True
        out.append(d)
    return {
        "databases": out,
        "doc_types": [{"id": d["id"], "label": d["label"]} for d in DOC_TYPES],
        "disciplines": [{"id": d["id"], "label": d["label"]} for d in DISCIPLINES],
    }


@router.get("", response_model=list[EquationOut])
def list_equations(project_id: int, member: ProjectMemberDep, db: DbDep):
    get_project(project_id, db)
    rows = (db.query(Equation).filter_by(project_id=project_id)
            .order_by(Equation.created_at).all())
    return [_equation_out(e) for e in rows]


def _known_databases(db, project_id: int, translations: dict) -> dict:
    known = {d["id"] for d in project_databases(db, project_id)}
    unknown = sorted(k for k in translations if k not in known)
    if unknown:
        raise HTTPException(status_code=400,
                            detail=f"Unknown database: {', '.join(unknown)}")
    return translations


@router.post("", response_model=EquationOut,
             dependencies=[Depends(require_project_admin)])
def create_equation(project_id: int, payload: EquationIn, db: DbDep):
    get_project(project_id, db)
    if payload.mode == "raw":
        # the typed queries are overrides over an empty auto translation —
        # every consumer (counts, fetch, report, audit) already prefers them
        equation = Equation(
            project_id=project_id, label=payload.label, mode="raw",
            structure={}, params=payload.params.model_dump(),
            translations={"auto": {}, "overrides": _known_databases(
                db, project_id, payload.translations)})
    else:
        structure, params = _snapshot(project_id, payload, db)
        equation = Equation(
            project_id=project_id, label=payload.label, structure=structure,
            params=params,
            translations={
                "auto": translate_all(structure, params,
                                      extra=custom_syntaxes(db, project_id)),
                "overrides": {}},
        )
    db.add(equation)
    db.commit()
    db.refresh(equation)
    return _equation_out(equation)


@router.put("/{equation_id}", response_model=EquationOut,
            dependencies=[Depends(require_project_admin)])
def update_equation(project_id: int, equation_id: int, payload: EquationIn, db: DbDep):
    """Re-snapshot the selected concepts and regenerate translations
    (manual overrides are kept). A raw equation replaces its typed queries."""
    equation = _get_equation(project_id, equation_id, db)
    _require_draft(equation)
    if payload.mode == "raw" or equation.mode == "raw":
        if payload.mode != "raw":
            raise HTTPException(status_code=400,
                                detail="A raw equation stays raw — create a new "
                                       "variant to build one from concepts")
        equation.label = payload.label
        equation.params = payload.params.model_dump()
        equation.translations = {"auto": {}, "overrides": _known_databases(
            db, project_id, payload.translations)}
        db.commit()
        db.refresh(equation)
        return _equation_out(equation)
    structure, params = _snapshot(project_id, payload, db)
    equation.label = payload.label
    equation.structure = structure
    equation.params = params
    overrides = (equation.translations or {}).get("overrides", {})
    equation.translations = {
        "auto": translate_all(structure, params,
                              extra=custom_syntaxes(db, project_id)),
        "overrides": overrides}
    db.commit()
    db.refresh(equation)
    return _equation_out(equation)


@router.post("/{equation_id}/duplicate", response_model=EquationOut,
             dependencies=[Depends(require_project_admin)])
def duplicate_equation(project_id: int, equation_id: int, db: DbDep):
    """A new draft variant with the same structure, params and queries —
    how "Eq. 6 bis" is derived from "Eq. 6" without retyping it. Counts and
    recall checks belong to the original and are not copied."""
    source = _get_equation(project_id, equation_id, db)
    labels = {e.label for e in db.query(Equation).filter_by(project_id=project_id)}
    label, n = f"{source.label} (copy)", 2
    while label in labels:
        label, n = f"{source.label} (copy {n})", n + 1
    translations = source.translations or {}
    equation = Equation(
        project_id=project_id, label=label, mode=source.mode,
        structure=dict(source.structure or {}), params=dict(source.params or {}),
        translations={"auto": dict(translations.get("auto") or {}),
                      "overrides": dict(translations.get("overrides") or {})})
    db.add(equation)
    db.commit()
    db.refresh(equation)
    return _equation_out(equation)


@router.post("/{equation_id}/translations/draft",
             dependencies=[Depends(require_project_admin)])
def draft_translation(project_id: int, equation_id: int, payload: DraftIn,
                      member: ProjectMemberDep, db: DbDep):
    """One LLM call drafting the `to_db` syntax from the query of `from_db`.
    The draft is returned for the editor — nothing is saved until the user
    clicks save, and the hand-checked text is what the protocol reports."""
    from app.services.equations import drafting
    from app.services.llm.base import LLMError

    equation = _get_equation(project_id, equation_id, db)
    registry = {d["id"]: d for d in project_databases(db, project_id)}
    if payload.from_db not in registry or payload.to_db not in registry:
        raise HTTPException(status_code=400, detail="Unknown database")
    try:
        result = drafting.draft_query(db, project_id, equation, registry,
                                      payload.from_db, payload.to_db, member.user_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except LLMError as e:
        raise HTTPException(status_code=502, detail=f"LLM error: {e}")
    return {"query": result["query"], "notes": result["notes"], "cost": result["cost"]}


@router.post("/{equation_id}/translations/draft-all",
             dependencies=[Depends(require_project_admin)])
def draft_all_translations(project_id: int, equation_id: int, payload: DraftAllIn,
                           member: ProjectMemberDep, db: DbDep):
    """Background job: draft every target database of a raw variant from the
    query typed for `from_db` (the databases the review searches that have
    no query yet; `mode=unreviewed` also redoes the drafts nobody validated).
    Each draft is stored as the database's query, flagged "AI draft, not
    reviewed" until a human validates or edits it."""
    from app.services.equations import drafting
    equation = _get_equation(project_id, equation_id, db)
    _require_draft(equation)
    registry = {d["id"]: d for d in project_databases(db, project_id)}
    if payload.from_db not in registry:
        raise HTTPException(status_code=400, detail="Unknown database")
    if not recall_svc.effective_query(equation, payload.from_db).strip():
        raise HTTPException(status_code=400,
                            detail=f"No {registry[payload.from_db]['label']} "
                                   "query to translate from")
    wanted = payload.databases or drafting.targets(equation, registry,
                                                   payload.from_db, payload.mode)
    wanted = [d for d in wanted if d in registry and d != payload.from_db]
    if not wanted:
        return {"job_id": None, "targets": []}
    job = runner.submit("equation_draft_all",
                        {"equation_id": equation.id, "from_db": payload.from_db,
                         "mode": payload.mode, "databases": wanted,
                         "user_id": member.user_id},
                        project_id=project_id, user_id=member.user_id)
    return {"job_id": job.id, "targets": wanted}


@router.get("/draft-estimate")
def draft_estimate(project_id: int, member: ProjectMemberDep, db: DbDep,
                   from_db: str = "pubmed", chars: int = 0,
                   equation_id: int | None = None):
    """How many databases an auto-draft would cover and what it would cost —
    shown before a variant is created (`chars` = length of the typed query)
    or before "Draft missing" on an existing one (`equation_id`)."""
    from app.services.equations import drafting
    registry = {d["id"]: d for d in project_databases(db, project_id)}
    if equation_id is not None:
        equation = _get_equation(project_id, equation_id, db)
        wanted = drafting.targets(equation, registry, from_db, "missing")
        chars = len(recall_svc.effective_query(equation, from_db))
    else:
        wanted = [d for d in registry if d != from_db]
    out = drafting.estimate(db, project_id, len(wanted), max(chars, 0), member.user_id)
    out["targets"] = wanted
    return out


@router.post("/{equation_id}/translations/validate", response_model=EquationOut,
             dependencies=[Depends(require_project_admin)])
def validate_translation(project_id: int, equation_id: int, payload: ValidateIn,
                         member: ProjectMemberDep, db: DbDep):
    """A human read the AI draft of this database's query and keeps it."""
    from app.services.equations import drafting
    equation = _get_equation(project_id, equation_id, db)
    if not drafting.validate_draft(equation, payload.database, member.user_id):
        raise HTTPException(status_code=400,
                            detail="This query is not an AI draft")
    db.commit()
    db.refresh(equation)
    return _equation_out(equation)


@router.put("/{equation_id}/override", response_model=EquationOut,
            dependencies=[Depends(require_project_admin)])
def override_translation(project_id: int, equation_id: int, payload: OverrideIn,
                         db: DbDep):
    equation = _get_equation(project_id, equation_id, db)
    _require_draft(equation)
    if payload.database not in {d["id"] for d in project_databases(db, project_id)}:
        raise HTTPException(status_code=400, detail="Unknown database")
    translations = dict(equation.translations or {"auto": {}, "overrides": {}})
    overrides = dict(translations.get("overrides", {}))
    if payload.query.strip():
        overrides[payload.database] = payload.query
    else:
        overrides.pop(payload.database, None)
    translations["overrides"] = overrides
    equation.translations = translations
    # a query typed (or cleared) by hand is no longer an AI draft
    from app.services.equations import drafting
    drafting.drop_draft(equation, payload.database)
    db.commit()
    db.refresh(equation)
    return _equation_out(equation)


@router.delete("/{equation_id}", dependencies=[Depends(require_project_admin)])
def delete_equation(project_id: int, equation_id: int, db: DbDep):
    equation = _get_equation(project_id, equation_id, db)
    _require_draft(equation)
    db.delete(equation)
    db.commit()
    return {"ok": True}


@router.post("/{equation_id}/freeze", response_model=EquationOut,
             dependencies=[Depends(require_project_admin)])
def freeze(project_id: int, equation_id: int, db: DbDep):
    """Freeze the final equation (timestamped, for reproducibility and the
    PRISMA-S search report)."""
    equation = _get_equation(project_id, equation_id, db)
    _require_draft(equation)
    equation.status = "frozen"
    equation.frozen_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(equation)
    return _equation_out(equation)


@router.post("/{equation_id}/counts/manual", response_model=EquationOut,
             dependencies=[Depends(require_project_admin)])
def manual_count(project_id: int, equation_id: int, payload: ManualCountIn, db: DbDep):
    equation = _get_equation(project_id, equation_id, db)
    if payload.database not in {d["id"] for d in project_databases(db, project_id)}:
        raise HTTPException(status_code=400, detail="Unknown database")
    db.add(EquationCount(equation_id=equation.id, database_name=payload.database,
                         count=payload.count, method="manual"))
    db.commit()
    db.refresh(equation)
    return _equation_out(equation)


@router.post("/{equation_id}/counts",
             dependencies=[Depends(require_project_admin)])
def run_counts(project_id: int, equation_id: int, payload: CountsJobIn,
               member: ProjectMemberDep, db: DbDep):
    """Launch the background job fetching counts from the free APIs."""
    equation = _get_equation(project_id, equation_id, db)
    allowed = api_databases(db, project_id)
    databases = payload.databases or allowed
    unknown = [d for d in databases if d not in allowed]
    if unknown:
        raise HTTPException(status_code=400,
                            detail=f"No API counter for: {', '.join(unknown)} "
                                   "(configure the database's API key first)")
    job = runner.submit("equation_counts",
                        {"equation_id": equation.id, "databases": databases},
                        project_id=project_id, user_id=member.user_id)
    return {"job_id": job.id}


@router.post("/{equation_id}/golden-check",
             dependencies=[Depends(require_project_admin)])
def golden_check(project_id: int, equation_id: int, member: ProjectMemberDep,
                 db: DbDep, payload: CountsJobIn | None = None):
    """Golden-set recall, database by database (background job): the API
    check on the requested databases (default: every one that supports it),
    plus the import check on every source with records."""
    equation = _get_equation(project_id, equation_id, db)
    if not db.query(GoldenRef).filter_by(project_id=project_id).count():
        raise HTTPException(status_code=400,
                            detail="Golden set is empty — add reference DOIs or PMIDs first")
    checkable = recall_svc.api_checkable(db, project_id)
    databases = (payload.databases if payload else []) or checkable
    unknown = [d for d in databases if d not in checkable]
    if unknown:
        raise HTTPException(status_code=400,
                            detail=f"No recall check for: {', '.join(unknown)} "
                                   "(no identifier filter in that API, or no key)")
    job = runner.submit("golden_check",
                        {"equation_id": equation.id, "databases": databases},
                        project_id=project_id, user_id=member.user_id)
    return {"job_id": job.id}


@router.get("/{equation_id}/recall", response_model=list[RecallOut])
def recall_history(project_id: int, equation_id: int, member: ProjectMemberDep,
                   db: DbDep):
    """Every recall check ever run on this variant, newest first — the
    per-database table a protocol reports."""
    equation = _get_equation(project_id, equation_id, db)
    return sorted(equation.recalls, key=lambda r: (r.checked_at, r.id), reverse=True)


@router.get("/recall/databases")
def recall_databases(project_id: int, member: ProjectMemberDep, db: DbDep):
    """Which databases the API recall check can ask (the rest is checked on
    the imported records)."""
    get_project(project_id, db)
    return {"api": recall_svc.api_checkable(db, project_id)}


# -- golden set ------------------------------------------------------------------

golden_router = APIRouter(prefix="/api/projects/{project_id}/golden",
                          tags=["golden"], dependencies=[SatelliteGuard])


@golden_router.get("", response_model=list[GoldenOut])
def list_golden(project_id: int, member: ProjectMemberDep, db: DbDep):
    get_project(project_id, db)
    return (db.query(GoldenRef).filter_by(project_id=project_id)
            .order_by(GoldenRef.added_at).all())


def _add_golden_ref(db, project_id: int, identifier: str, title: str = "",
                    year: int | None = None) -> GoldenRef:
    doi, pmid = recall_svc.parse_identifier(identifier)
    if not doi and not pmid:
        raise HTTPException(status_code=400,
                            detail=f"Not a DOI nor a PMID: {identifier!r} "
                                   "(expected 10.xxxx/… or a PubMed number)")
    q = db.query(GoldenRef).filter_by(project_id=project_id)
    existing = (q.filter_by(doi=doi).first() if doi else None) \
        or (q.filter_by(pmid=pmid).first() if pmid else None)
    if existing:
        # the other identifier may be new information on a known reference
        if doi and not existing.doi:
            existing.doi = doi
        if pmid and not existing.pmid:
            existing.pmid = pmid
        return existing
    doi, pmid, pubmed_title = recall_svc.resolve_identifiers(doi, pmid)
    # enrich with Crossref metadata for a full APA reference, and the OpenAlex
    # abstract for the AI strategy advisor (both best effort)
    from app.services.equations.golden_meta import fetch_abstract
    meta = fetch_reference(doi) if doi else {}
    ref = GoldenRef(project_id=project_id, doi=doi, pmid=pmid,
                    title=title or meta.get("title", "") or pubmed_title,
                    year=year or meta.get("year"),
                    apa=meta.get("apa", ""),
                    abstract=fetch_abstract(doi) if doi else "")
    db.add(ref)
    db.flush()
    return ref


@golden_router.post("", response_model=GoldenOut,
                    dependencies=[Depends(require_project_admin)])
def add_golden(project_id: int, payload: GoldenIn, db: DbDep):
    get_project(project_id, db)
    identifier = payload.identifier or payload.doi or payload.pmid
    ref = _add_golden_ref(db, project_id, identifier, payload.title, payload.year)
    db.commit()
    db.refresh(ref)
    return ref


@golden_router.post("/bulk", dependencies=[Depends(require_project_admin)])
def add_golden_bulk(project_id: int, payload: GoldenBulkIn, db: DbDep):
    """One identifier per line (DOI or PMID, any mix). Lines that are
    neither are reported back, the rest is added."""
    get_project(project_id, db)
    added, rejected = [], []
    for line in payload.identifiers.splitlines():
        line = line.strip().strip(",;")
        if not line:
            continue
        try:
            ref = _add_golden_ref(db, project_id, line)
        except HTTPException:
            rejected.append(line)
            continue
        added.append(ref)
    db.commit()
    return {"added": len(added), "rejected": rejected,
            "refs": [GoldenOut.model_validate(r) for r in added]}


@golden_router.delete("/{ref_id}", dependencies=[Depends(require_project_admin)])
def delete_golden(project_id: int, ref_id: int, db: DbDep):
    ref = db.get(GoldenRef, ref_id)
    if ref is None or ref.project_id != project_id:
        raise HTTPException(status_code=404, detail="Reference not found")
    db.delete(ref)
    db.commit()
    return {"ok": True}


# ---- AI strategy advice (B4) --------------------------------------------------------

ADVISE_SCHEMA = {
    "type": "object",
    "properties": {
        "recommended_label": {
            "type": "string",
            "description": "The label of the variant to prefer (exactly as given)",
        },
        "rationale": {
            "type": "string",
            "description": "Why this variant offers the best recall/precision "
                           "trade-off for THIS review (3-6 sentences, concrete)",
        },
        "per_variant": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "label": {"type": "string"},
                    "verdict": {"type": "string",
                                "description": "One-sentence assessment "
                                               "(too broad / too narrow / missing "
                                               "concept X / good balance...)"},
                },
                "required": ["label", "verdict"],
            },
        },
        "improvements": {
            "type": "array",
            "items": {"type": "string"},
            "description": "2-5 concrete, actionable changes (add synonym X to "
                           "concept Y, relax the year filter, drop concept Z...)",
        },
    },
    "required": ["recommended_label", "rationale", "per_variant", "improvements"],
}


@router.post("/advise", dependencies=[Depends(require_project_admin)])
def advise(project_id: int, member: ProjectMemberDep, db: DbDep):
    """One LLM call on the search strategy — from the FIRST variant on. With
    one variant it critiques it and proposes concrete improvements; with
    several it compares them. The golden references travel in the prompt
    (title/year + cached OpenAlex abstract) as a terminology mine, along with
    the DOIs each variant MISSED at its last golden check. Advice only —
    nothing is changed."""
    from app.services.equations.golden_meta import fetch_abstract
    from app.services.llm.base import LLMError
    from app.services.llm.credentials import open_provider_chain
    from app.services.protocol.service import validated_protocol

    get_project(project_id, db)
    equations = (db.query(Equation).filter_by(project_id=project_id)
                 .order_by(Equation.id).all())
    if not equations:
        raise HTTPException(status_code=400,
                            detail="Create a first equation variant to get "
                                   "AI advice on it")
    try:
        provider = open_provider_chain(db, project_id,
                                       feature="equations_advise",
                                       user_id=member.user_id)
    except LLMError as e:
        raise HTTPException(status_code=400, detail=str(e))

    golden_refs = (db.query(GoldenRef).filter_by(project_id=project_id)
                   .order_by(GoldenRef.added_at).all())
    # lazy backfill for refs added before abstracts were cached (bounded)
    fetched = 0
    for ref in golden_refs:
        if ref.doi and not ref.abstract and fetched < 15:
            ref.abstract = fetch_abstract(ref.doi)
            fetched += 1
    if fetched:
        db.commit()
    titles_by_doi = {r.doi: (r.title or r.doi) for r in golden_refs}
    golden_details = [
        {"doi": r.doi, "title": r.title, "year": r.year,
         "abstract_excerpt": (r.abstract or "")[:700]}
        for r in golden_refs]

    variants = []
    for eq in equations:
        latest: dict[str, dict] = {}
        for c in sorted(eq.counts, key=lambda c: c.noted_at or c.id):
            latest[c.database_name] = {"count": c.count, "method": c.method}
        golden = None
        if eq.golden_results:
            golden = {"found": eq.golden_results.get("found"),
                      "total": eq.golden_results.get("total"),
                      "database": eq.golden_results.get("database"),
                      "missed_references": [
                          {"doi": doi, "title": titles_by_doi.get(doi, doi)}
                          for doi in eq.golden_results.get("missing", [])]}
        concepts = [
            {"name": c.get("name"), "keywords": c.get("keywords", [])}
            for c in (eq.structure or {}).get("concepts", [])]
        variants.append({
            "label": eq.label, "status": eq.status, "params": eq.params or {},
            "concepts": concepts, "counts": latest, "golden_check": golden,
        })

    from app.services.llm.prompts import resolve_prompt
    system = (resolve_prompt(db, project_id, "equations_advise")
              + framing.review_context(get_project(project_id, db)))
    if len(equations) == 1:
        system += (
            "\n\nOnly ONE variant exists so far: do not compare — critique "
            "it and propose concrete improvements (synonyms, truncations, "
            "blocks to relax or split), so the user can build a better "
            "second variant.")
    else:
        system += ("\n\nSeveral variants were tested: compare them on the "
                   "recall/precision trade-off and recommend one.")
    protocol = validated_protocol(db, project_id)
    if protocol:
        system += "\n\nReview protocol (context):\n" + protocol.protocol_md[:4000]

    import json as _json
    prompt = (
        f"Golden set ({len(golden_refs)} must-find references):\n"
        + _json.dumps(golden_details, ensure_ascii=False, indent=1)
        + "\n\nVariants:\n"
        + _json.dumps(variants, ensure_ascii=False, indent=1))
    try:
        result = provider.generate_json([{"role": "user", "content": prompt}],
                                        json_schema=ADVISE_SCHEMA, system=system,
                                        max_tokens=2048)
    except LLMError as e:
        raise HTTPException(status_code=502, detail=f"LLM error: {e}")
    data = result.data or {}
    known = {eq.label for eq in equations}
    if data.get("recommended_label") not in known:
        data["recommended_label"] = ""  # model invented a label: keep the text only
    from app.services.llm import pricing
    data["cost"] = pricing.call_cost(provider, result)
    return data
