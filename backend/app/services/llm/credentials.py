# SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Pick and open an LLM credential for pipeline jobs."""
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.crypto import decrypt_secret
from app.core.demo import sandbox_owner
from app.core.ssrf import SSRFError, validate_public_url
from app.models import LLMCredential
from app.services.llm.base import LLMError, LLMProvider, LLMResult
from app.services.llm.registry import PROVIDERS, get_provider
from app.services.llm.routing import (DEFAULT_ROUTE, model_for, order_for_route,
                                      route_for)
from app.services.llm.tasks import tier_for_feature


def _ranked_candidates(db: Session, project_id: int | None,
                       provider: str | None = None) -> list[LLMCredential]:
    """Stored credentials visible from this project, best first: project scope
    beats global, the scope's chosen default beats the rest, then registry
    order (`PROVIDERS`)."""
    scope = LLMCredential.project_id.is_(None)
    if project_id is not None:
        scope = or_(LLMCredential.project_id == project_id, scope)
    candidates = db.query(LLMCredential).filter(scope).all()
    if provider:
        candidates = [c for c in candidates if c.provider == provider]
    # demo instances: a visitor sandbox runs on the app-wide key only, through
    # the capped demo budget (demo_budget.py) — never on keys of its own
    if sandbox_owner(db, project_id) is not None:
        from app.services.llm.demo_budget import demo_ai_enabled
        candidates = ([c for c in candidates if c.project_id is None]
                      if demo_ai_enabled() else [])

    def rank(c: LLMCredential) -> tuple:
        return (c.project_id is None,  # project-scoped first
                not c.is_default,      # then the scope's chosen default
                PROVIDERS.index(c.provider) if c.provider in PROVIDERS else 99)

    return sorted(candidates, key=rank)


def resolve_credential(
    db: Session,
    project_id: int | None,
    provider: str | None = None,
    credential_id: int | None = None,
) -> LLMCredential:
    """Choose a stored credential: explicit id > project-scoped > global;
    within a scope, the credential marked default (AI Settings) wins.

    Without a provider filter, providers are tried in registry order.
    """
    if credential_id is not None:
        credential = db.get(LLMCredential, credential_id)
        # only a key this project can see: its own, or an app-wide one —
        # never another project's key picked by its id
        if credential is None or credential.project_id not in (None, project_id):
            raise LLMError("Credential not found")
        if sandbox_owner(db, project_id) is not None:
            raise LLMError("A demo project cannot pick a specific AI key")
        return credential

    candidates = _ranked_candidates(db, project_id, provider)
    if not candidates:
        raise LLMError("No API key configured — add one in AI Settings first")
    return candidates[0]


def resolve_model(db: Session, project_id: int | None,
                  feature: str | None = None) -> tuple[str, str] | None:
    """The (provider, model) an AI call for `feature` *would* use right now,
    without opening a provider or making a request. Used to price cost
    estimates. None if no key is configured."""
    route, tier = _route_and_tier(db, project_id, feature)
    candidates = order_for_route(_ranked_candidates(db, project_id), route)
    if not candidates:
        return None
    top = candidates[0]
    return top.provider, model_for(top, route, tier)


def _route_and_tier(db: Session, project_id: int | None,
                    feature: str | None) -> tuple:
    """The route and tier a call runs on. A demo sandbox ignores the routes
    and always gets the bulk-tier model of the app-wide key: the visitors'
    budget is small, and nobody has to pick a cheap model for them."""
    if sandbox_owner(db, project_id) is not None:
        return DEFAULT_ROUTE, "bulk"
    return route_for(db, project_id, feature), tier_for_feature(feature)


def endpoint_allowed(base_url: str | None, project_id: int | None) -> bool:
    """A project key's self-hosted endpoint, on a hosted demo instance, must be
    a public address: localhost or the platform's private network would let
    any project admin make the server query its internal services (SSRF).
    The app-wide keys are the superadmin's and may point anywhere; desktop and
    self-hosted instances, where a local model is the point, are unaffected."""
    if not base_url or project_id is None or not get_settings().demo_mode:
        return True
    try:
        validate_public_url(base_url)
        return True
    except SSRFError:
        return False


def open_provider(credential: LLMCredential) -> LLMProvider:
    if not endpoint_allowed(credential.base_url, credential.project_id):
        raise LLMError("This key's endpoint is not a public address — not "
                       "allowed for a project key on this instance")
    api_key = decrypt_secret(credential.api_key_encrypted)
    if api_key is None:
        raise LLMError("Could not decrypt the API key (app secret changed?)")
    return get_provider(credential.provider, api_key, credential.default_model,
                        base_url=credential.base_url)


def _no_fallback(db: Session, project_id: int | None) -> bool:
    """Project setting: use only the top-ranked key, never another provider.
    A team running a local model for confidentiality must not be silently
    moved to a cloud key the day the local server is down."""
    if project_id is None:
        return False
    from app.models import Project
    project = db.get(Project, project_id)
    return bool(project is not None and project.llm_no_fallback)


class FallbackProvider(LLMProvider):
    """Chains the stored credentials: when a call errors (no credit, invalid
    key, provider outage), the next key takes over — in the ranking order of
    `_ranked_candidates`. JSON-parsing problems do NOT switch providers (the
    model answered; retrying elsewhere would not be cheaper)."""

    def __init__(self, providers: list[tuple[str, LLMProvider]]):
        self._providers = providers
        self.api_key = ""
        self.model = providers[0][1].model
        self.name = providers[0][1].name

    def generate(self, messages, system=None, max_tokens=4096) -> LLMResult:
        errors: list[str] = []
        billed = []  # failed attempts that still cost tokens, for the journal
        for label, provider in self._providers:
            try:
                result = provider.generate(messages, system=system,
                                           max_tokens=max_tokens)
            except LLMError as e:
                errors.append(f"{label}: {e}")
                billed.extend(e.billed)
                continue
            # report who actually answered (screening AI logs the model)
            self.model = getattr(provider, "answered_model", None) or provider.model
            self.name = provider.name
            result.failed_attempts = billed + result.failed_attempts
            return result
        raise LLMError("Every configured AI key failed — "
                       + " | ".join(errors), billed=billed)


def open_provider_chain(
    db: Session,
    project_id: int | None,
    provider: str | None = None,
    credential_id: int | None = None,
    feature: str | None = None,
    user_id: int | None = None,
) -> LLMProvider:
    """What AI features should use: the ranked credentials chained with
    automatic failover. An explicit credential_id disables the fallback
    (used to test one specific key), and so does the project's
    `llm_no_fallback` setting (only the best-ranked key is opened).

    `feature` names the pipeline helper making the call (a prompt key from
    services/llm/prompts.py): passing it records the call in the project's
    AI-use journal, which is what the AI disclosure statement is written from.
    Leave it out only for calls that are not review work (connectivity tests).
    """
    if credential_id is not None:
        opened = open_provider(
            resolve_credential(db, project_id, credential_id=credential_id))
        return _logged(opened, feature, project_id, user_id)
    # the task's route (AI Settings): its provider first in the chain, its
    # model and effort on that provider; the tier model on the others
    route, tier = _route_and_tier(db, project_id, feature)
    owner = sandbox_owner(db, project_id)
    candidates = order_for_route(_ranked_candidates(db, project_id, provider), route)
    providers: list[tuple[str, LLMProvider]] = []
    for credential in candidates:
        if not endpoint_allowed(credential.base_url, credential.project_id):
            continue  # internal endpoint of a project key, on a hosted demo
        api_key = decrypt_secret(credential.api_key_encrypted)
        if api_key is None:
            continue  # undecryptable key (app secret changed) — skip it
        providers.append((credential.provider,
                          get_provider(credential.provider, api_key,
                                       model_for(credential, route, tier),
                                       base_url=credential.base_url,
                                       effort=route.effort)))
        if owner is not None or _no_fallback(db, project_id):
            break  # the first decryptable key is the only one allowed
    if not providers:
        if owner is not None:
            raise LLMError("AI features are not available on this demo instance")
        raise LLMError("No API key configured — add one in AI Settings first")
    chain = (providers[0][1] if len(providers) == 1
             else FallbackProvider(providers))
    if owner is not None:
        # one key, one model: the budget guard can price each call exactly
        from app.services.llm.demo_budget import DemoBudgetGuard
        chain = DemoBudgetGuard(chain, owner.id)
    return _logged(chain, feature, project_id, user_id)


def _logged(chain: LLMProvider, feature: str | None, project_id: int | None,
            user_id: int | None) -> LLMProvider:
    if not feature:
        return chain
    from app.services.llm.usage import UsageLogger
    return UsageLogger(chain, feature, project_id, user_id)
