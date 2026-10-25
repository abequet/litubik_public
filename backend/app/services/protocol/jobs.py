# SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Background job: LLM structured extraction of an uploaded protocol."""
from app.core.db import SessionLocal
from app.models import Job, Project, Protocol
from app.services import framing
from app.services.llm.base import LLMError
from app.services.llm.credentials import open_provider_chain
from app.services.llm.prompts import resolve_prompt
from app.services.protocol.service import (
    build_extraction_messages,
    extraction_schema,
    normalize_criteria,
    render_protocol_md,
)
from app.workers.runner import register_handler


@register_handler("protocol_extract")
def protocol_extract_handler(job_id: int, params: dict, progress) -> dict:
    with SessionLocal() as db:
        protocol = db.get(Protocol, params["protocol_id"])
        if protocol is None:
            raise LLMError("Protocol not found")
        if protocol.validated_at is not None:
            raise LLMError("This version is validated — upload a new version to regenerate")
        if not protocol.source_text.strip():
            raise LLMError("No source text to extract from")
        source_text = protocol.source_text
        # read here rather than from the job params: a job resubmitted after
        # the project was re-framed must follow the project, not the params
        project = db.get(Project, protocol.project_id)
        framework_key = framing.framework(
            getattr(project, "question_framework", None)).key
        system = (resolve_prompt(db, protocol.project_id, "protocol_extract")
                  + framing.review_context(project))
        job = db.get(Job, job_id)
        provider = open_provider_chain(db, protocol.project_id,
                                       credential_id=params.get("credential_id"),
                                       feature="protocol_extract",
                                       user_id=job.created_by if job else None)
        generated_with = f"{provider.name}:{provider.model}"

    progress(0, 2, f"Extracting protocol structure with {generated_with}...")
    result = provider.generate_json(
        build_extraction_messages(source_text),
        json_schema=extraction_schema(framework_key),
        system=system,
        # a 25-page protocol extracted in its own language runs past 8k
        # tokens of JSON — and a thinking model spends part of the cap on
        # reasoning first. Output tokens are billed only when generated.
        max_tokens=16384,
    )
    structured = result.data
    if not isinstance(structured, dict):
        raise LLMError("Model returned a JSON array instead of an object")
    # the fallback chain may have answered with another key than the first
    generated_with = f"{provider.name}:{provider.model}"

    progress(1, 2, "Rendering protocol.md...")
    criteria = normalize_criteria(structured)
    protocol_md = render_protocol_md(structured, criteria, framework_key)

    with SessionLocal() as db:
        protocol = db.get(Protocol, params["protocol_id"])
        if protocol is None:
            raise LLMError("Protocol was deleted while extracting")
        protocol.protocol_md = protocol_md
        protocol.criteria = criteria
        protocol.generated_with = generated_with
        job = db.get(Job, job_id)
        if job is not None:
            job.tokens_input = result.tokens_input
            job.tokens_output = result.tokens_output
        db.commit()

    from app.services.llm import pricing
    return {
        "n_criteria": len(criteria),
        "tokens_input": result.tokens_input,
        "tokens_output": result.tokens_output,
        "cost": pricing.call_cost(provider, result),
    }
