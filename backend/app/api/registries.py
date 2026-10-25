# SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Catalogue of systematic-review registers (read-only).

Served rather than duplicated in the frontend, for the same reason as
/api/framings: the labels and the URL patterns are also what the audit trail
and the Methods draft use, and two copies of a catalogue drift.
"""
from fastapi import APIRouter
from pydantic import BaseModel

from app.api.deps import CurrentUser
from app.services import registration

router = APIRouter(prefix="/api/registries", tags=["registries"])


class RegistryOut(BaseModel):
    key: str
    label: str
    id_hint: str
    # whether an identifier alone is enough to build a public URL
    has_url_template: bool


@router.get("", response_model=list[RegistryOut])
def list_registries(user: CurrentUser):
    return [RegistryOut(key=r.key, label=r.label, id_hint=r.id_hint,
                        has_url_template=bool(r.url_template))
            for r in registration.REGISTRIES.values()]
