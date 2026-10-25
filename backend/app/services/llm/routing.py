# SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Which (provider, model, effort) an AI task runs on.

Resolution, for a call-site `feature` (prompt key):
  1. the project's stored route for the feature's task, else the app-wide one;
  2. no route: the best-ranked credential, on the tier model of its provider
     (registry.TIER_MODELS), else the credential's own default_model.
A route names a provider; when no visible credential has that provider, the
route only contributes its effort and the tier default applies.
"""
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.models import LLMCredential, LLMTaskRoute
from app.services.llm.registry import DEFAULT_EFFORT, tier_model
from app.services.llm.tasks import TASKS, task_for_feature


@dataclass(frozen=True)
class Route:
    provider: str | None   # None = whichever credential ranks first
    model: str | None      # None = the tier model of the credential's provider
    effort: str
    source: str            # "project" | "global" | "default"


DEFAULT_ROUTE = Route(None, None, DEFAULT_EFFORT, "default")


def stored_route(db: Session, project_id: int | None, task: str) -> LLMTaskRoute | None:
    """The project's row for this task, else the app-wide row."""
    if project_id is not None:
        row = db.query(LLMTaskRoute).filter_by(project_id=project_id, task=task).first()
        if row is not None:
            return row
    return db.query(LLMTaskRoute).filter_by(project_id=None, task=task).first()


def route_for(db: Session, project_id: int | None, feature: str | None) -> Route:
    task = task_for_feature(feature)
    if task is None:
        return DEFAULT_ROUTE
    row = stored_route(db, project_id, task.key)
    if row is None:
        return DEFAULT_ROUTE
    return Route(row.provider, row.model, row.effort or DEFAULT_EFFORT,
                 "project" if row.project_id is not None else "global")


def model_for(credential: LLMCredential, route: Route, tier: str) -> str:
    """The model this credential answers with for a task of `tier`."""
    if route.provider == credential.provider and route.model:
        return route.model
    return tier_model(credential.provider, tier) or credential.default_model


def order_for_route(candidates: list[LLMCredential], route: Route) -> list[LLMCredential]:
    """Ranked credentials with the route's provider first; the others stay
    behind as the failover chain."""
    if route.provider is None:
        return candidates
    return ([c for c in candidates if c.provider == route.provider]
            + [c for c in candidates if c.provider != route.provider])


def effective_routes(db: Session, project_id: int | None,
                     candidates: list[LLMCredential]) -> list[dict]:
    """One row per task for the settings UI: the stored route of this scope
    (if any), and what a call would actually run on right now."""
    out = []
    for task in TASKS:
        own = (db.query(LLMTaskRoute)
               .filter_by(project_id=project_id, task=task.key).first())
        route = route_for(db, project_id, task.features[0])
        ordered = order_for_route(candidates, route)
        top = ordered[0] if ordered else None
        out.append({
            "task": task.key,
            "label": task.label,
            "description": task.description,
            "tier": task.tier,
            "features": list(task.features),
            "route": None if own is None else {
                "provider": own.provider, "model": own.model, "effort": own.effort},
            "effective": {
                "source": route.source,
                "provider": top.provider if top else route.provider,
                "model": model_for(top, route, task.tier) if top else route.model,
                "effort": route.effort,
                # the route names a provider nobody has a key for
                "provider_missing": bool(
                    route.provider and (top is None or top.provider != route.provider)),
            },
        })
    return out
