# SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Concepts (the building blocks of the search equation) + keyword help:
LLM synonym suggestions and MeSH lookup via the NLM API."""
import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.api.deps import (
    DbDep, ProjectMemberDep, SatelliteGuard, get_project,
    require_project_admin,
)
from app.models import Concept, Protocol
from app.services import framing
from app.services.llm import pricing
from app.services.llm.base import LLMError
from app.services.llm.credentials import open_provider_chain
from app.services.llm.prompts import resolve_prompt
from app.services.protocol.service import validated_protocol

router = APIRouter(prefix="/api/projects/{project_id}/concepts",
                   tags=["concepts"], dependencies=[SatelliteGuard])


class ConceptIn(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str = ""
    keywords: list[str] = []


class ConceptOut(ConceptIn):
    id: int
    position: int

    model_config = {"from_attributes": True}


def _get_concept(project_id: int, concept_id: int, db) -> Concept:
    concept = db.get(Concept, concept_id)
    if concept is None or concept.project_id != project_id:
        raise HTTPException(status_code=404, detail="Concept not found")
    return concept


def _context_protocol(db, project_id: int) -> Protocol | None:
    """The protocol to reason from: the validated one, or failing that the
    latest draft that has content — an imported-but-not-yet-validated protocol
    is still better context than none."""
    protocol = validated_protocol(db, project_id)
    if protocol is not None:
        return protocol
    return (db.query(Protocol)
            .filter(Protocol.project_id == project_id, Protocol.protocol_md != "")
            .order_by(Protocol.version.desc()).first())


def _clean_keywords(keywords: list[str]) -> list[str]:
    seen, out = set(), []
    for kw in keywords:
        kw = " ".join(str(kw).split())
        if kw and kw.lower() not in seen:
            seen.add(kw.lower())
            out.append(kw)
    return out


@router.get("", response_model=list[ConceptOut])
def list_concepts(project_id: int, member: ProjectMemberDep, db: DbDep):
    get_project(project_id, db)
    return (db.query(Concept).filter_by(project_id=project_id)
            .order_by(Concept.position, Concept.id).all())


@router.post("", response_model=ConceptOut,
             dependencies=[Depends(require_project_admin)])
def create_concept(project_id: int, payload: ConceptIn, db: DbDep):
    get_project(project_id, db)
    position = db.query(Concept).filter_by(project_id=project_id).count()
    concept = Concept(project_id=project_id, name=payload.name,
                      description=payload.description,
                      keywords=_clean_keywords(payload.keywords), position=position)
    db.add(concept)
    db.commit()
    db.refresh(concept)
    return concept


@router.put("/{concept_id}", response_model=ConceptOut,
            dependencies=[Depends(require_project_admin)])
def update_concept(project_id: int, concept_id: int, payload: ConceptIn, db: DbDep):
    concept = _get_concept(project_id, concept_id, db)
    concept.name = payload.name
    concept.description = payload.description
    concept.keywords = _clean_keywords(payload.keywords)
    db.commit()
    db.refresh(concept)
    return concept


@router.delete("/{concept_id}", dependencies=[Depends(require_project_admin)])
def delete_concept(project_id: int, concept_id: int, db: DbDep):
    concept = _get_concept(project_id, concept_id, db)
    db.delete(concept)
    db.commit()
    return {"ok": True}


# -- keyword assistance ---------------------------------------------------------

SUGGEST_SCHEMA = {
    "type": "object",
    "properties": {"keywords": {"type": "array", "items": {"type": "string"},
                                "description": "8-15 search keywords/synonyms"}},
    "required": ["keywords"],
}


@router.post("/{concept_id}/suggest",
             dependencies=[Depends(require_project_admin)])
def suggest_keywords(project_id: int, concept_id: int,
                     member: ProjectMemberDep, db: DbDep):
    """One LLM call proposing synonyms for this concept; results are merged
    into the concept's keyword list (nothing is removed). Returns the updated
    concept plus the call's cost."""
    concept = _get_concept(project_id, concept_id, db)
    try:
        provider = open_provider_chain(db, project_id,
                                       feature="concepts_suggest",
                                       user_id=member.user_id)
    except LLMError as e:
        raise HTTPException(status_code=400, detail=str(e))

    protocol = _context_protocol(db, project_id)
    project = get_project(project_id, db)
    system = (resolve_prompt(db, project_id, "concepts_suggest")
              + framing.review_context(project))
    if protocol:
        system += "\n\nReview protocol for context:\n" + protocol.protocol_md[:4000]

    prompt = f"Concept: {concept.name}"
    if concept.description:
        prompt += f"\nDescription: {concept.description}"
    if concept.keywords:
        prompt += "\nAlready listed (do not repeat): " + ", ".join(concept.keywords)
    if project.research_question:
        prompt += f"\nResearch question of the review: {project.research_question}"
    others = [c.name for c in db.query(Concept).filter_by(project_id=project_id)
              .order_by(Concept.position, Concept.id).all() if c.id != concept.id]
    if others:
        prompt += ("\nOther concepts of the equation, which will be AND-ed with "
                   "this one — stay on this concept's axis and do not propose "
                   "terms belonging to them: " + ", ".join(others))

    try:
        result = provider.generate_json([{"role": "user", "content": prompt}],
                                        json_schema=SUGGEST_SCHEMA, system=system,
                                        max_tokens=1024)
    except LLMError as e:
        raise HTTPException(status_code=502, detail=f"LLM error: {e}")
    suggested = [str(k) for k in (result.data or {}).get("keywords", [])]
    concept.keywords = _clean_keywords(list(concept.keywords) + suggested)
    db.commit()
    db.refresh(concept)
    return {**ConceptOut.model_validate(concept).model_dump(),
            "cost": pricing.call_cost(provider, result)}


PROPOSE_SCHEMA = {
    "type": "object",
    "properties": {
        "research_question": {
            "type": "string",
            "description": "The review's main research question, taken from the "
                           "protocol (reformulated as one clear question if the "
                           "protocol lists several)",
        },
        "concepts": {
            "type": "array",
            "description": "2-5 searchable concepts derived from the "
                           "research question",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Short concept name"},
                    "description": {"type": "string"},
                    "keywords": {"type": "array", "items": {"type": "string"},
                                 "description": "5-10 search keywords/synonyms"},
                },
                "required": ["name", "keywords"],
            },
        },
    },
    "required": ["research_question", "concepts"],
}


@router.post("/propose", dependencies=[Depends(require_project_admin)])
def propose_from_protocol(project_id: int, member: ProjectMemberDep, db: DbDep):
    """One LLM call: extract the research question from the protocol and
    pre-identify searchable concepts. Existing concepts are never replaced —
    a proposal whose name is already in use only adds its new keywords to that
    concept. Everything stays editable."""
    project = get_project(project_id, db)
    protocol = _context_protocol(db, project_id)
    if protocol is None:
        raise HTTPException(status_code=400,
                            detail="No protocol with content yet — import it in the "
                                   "Protocol page first")
    try:
        provider = open_provider_chain(db, project_id,
                                       feature="concepts_propose",
                                       user_id=member.user_id)
    except LLMError as e:
        raise HTTPException(status_code=400, detail=str(e))

    system = (resolve_prompt(db, project_id, "concepts_propose")
              + framing.review_context(project))
    concepts = (db.query(Concept).filter_by(project_id=project_id)
                .order_by(Concept.position, Concept.id).all())
    prompt = "Review protocol:\n\n" + protocol.protocol_md[:12000]
    if concepts:
        prompt += ("\n\nConcepts the reviewers have already listed — keep them, "
                   "complete their keywords rather than restating them, and only "
                   "add a new concept for an axis that is genuinely missing:\n"
                   + "\n".join(f"- {c.name}: {', '.join(c.keywords) or 'no keyword yet'}"
                               for c in concepts))
    try:
        result = provider.generate_json(
            [{"role": "user", "content": prompt}],
            json_schema=PROPOSE_SCHEMA, system=system, max_tokens=2048)
    except LLMError as e:
        raise HTTPException(status_code=502, detail=f"LLM error: {e}")

    data = result.data if isinstance(result.data, dict) else {}
    project = get_project(project_id, db)
    question = str(data.get("research_question", "")).strip()
    if question:
        project.research_question = question

    existing = {c.name.lower(): c for c in concepts}
    position = len(concepts)
    created, enriched = [], []
    for item in data.get("concepts") or []:
        name = str(item.get("name", "")).strip()
        keywords = _clean_keywords([str(k) for k in item.get("keywords") or []])
        if not name or not keywords:
            continue
        concept = existing.get(name.lower())
        if concept is not None:  # enrich, never overwrite what reviewers wrote
            merged = _clean_keywords(list(concept.keywords) + keywords)
            if merged != list(concept.keywords):
                concept.keywords = merged
                enriched.append(concept)
            continue
        concept = Concept(project_id=project_id, name=name,
                          description=str(item.get("description", "")).strip(),
                          keywords=keywords, position=position)
        db.add(concept)
        existing[name.lower()] = concept
        position += 1
        created.append(concept)
    db.commit()
    return {
        "research_question": project.research_question,
        "created": [ConceptOut.model_validate(c).model_dump() for c in created],
        "enriched": [ConceptOut.model_validate(c).model_dump() for c in enriched],
        "cost": pricing.call_cost(provider, result),
    }


@router.get("/mesh/lookup")
def mesh_lookup(project_id: int, q: str, member: ProjectMemberDep, db: DbDep):
    """MeSH term suggestions from the NLM lookup API (no key required)."""
    if len(q.strip()) < 3:
        return {"terms": []}
    try:
        with httpx.Client(timeout=15) as client:
            r = client.get("https://id.nlm.nih.gov/mesh/lookup/term",
                           params={"label": q.strip(), "match": "contains",
                                   "limit": 15})
            r.raise_for_status()
            data = r.json()
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"MeSH lookup failed: {e}")
    return {"terms": [item.get("label", "") for item in data if item.get("label")]}
