# SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Where a review is registered, and how to say so.

PRISMA 2020 item 24a asks for the register name and the registration number,
*or* an explicit statement that the review was not registered. The distinction
between "not registered" and "we never said" is the whole point of this module:
`registry=""` means the question was never answered and the Methods draft must
flag the gap, while `registry="none"` is an answer the manuscript owes its
readers. Nothing here validates that a number really exists in a register —
LitUbik records what the team declares, and the URL is what makes it checkable.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Registry:
    key: str
    label: str
    # How to build a public URL from a bare identifier. "" when the register
    # has no stable per-record URL pattern (the team pastes the URL instead).
    url_template: str
    # Shown next to the identifier field so the format is obvious.
    id_hint: str


_REGISTRIES: tuple[Registry, ...] = (
    Registry(
        key="prospero", label="PROSPERO",
        url_template="https://www.crd.york.ac.uk/prospero/display_record.php"
                     "?RecordID={id}",
        id_hint="CRD42024512345",
    ),
    Registry(
        key="osf", label="OSF Registries",
        url_template="https://osf.io/{id}/",
        id_hint="the 5-character GUID, e.g. ab3cd",
    ),
    Registry(
        key="inplasy", label="INPLASY",
        url_template="https://inplasy.com/inplasy-{id}/",
        id_hint="2024-1-0001",
    ),
    Registry(
        key="research_registry", label="Research Registry",
        url_template="",
        id_hint="reviewregistry1234",
    ),
    Registry(
        key="other", label="Other register",
        url_template="",
        id_hint="the identifier as the register issues it",
    ),
    Registry(
        key="none", label="Not registered",
        url_template="",
        id_hint="",
    ),
)

REGISTRIES: dict[str, Registry] = {r.key: r for r in _REGISTRIES}

# "" is a valid stored value — it means the question has not been answered —
# so it is accepted by the API without being offered as a choice.
VALID_KEYS = set(REGISTRIES) | {""}


def registry(key: str | None) -> Registry | None:
    """None for an unanswered project, and for a key an older/newer instance
    wrote that this version does not know — same degrade-don't-raise rule as
    services/framing.py."""
    return REGISTRIES.get(key or "")


def public_url(key: str | None, identifier: str, stored_url: str) -> str:
    """The URL a reader would follow. A URL entered by hand always wins: a
    register that moved its records, or an identifier in an unexpected shape,
    must not be overridden by a template."""
    if stored_url:
        return stored_url
    reg = registry(key)
    if reg is None or not reg.url_template or not identifier.strip():
        return ""
    return reg.url_template.format(id=identifier.strip())


def audit_block(project) -> dict:
    """The `registration` block of the review dossier.

    `state` is what the Methods draft branches on: `registered` (name it and
    date it), `not_registered` (state it as a limitation), `undeclared` (the
    team never answered — the draft must leave a visible gap rather than
    assume either way).
    """
    key = (getattr(project, "registry", "") or "") if project else ""
    identifier = (getattr(project, "registration_id", "") or "") if project else ""
    stored_url = (getattr(project, "registration_url", "") or "") if project else ""
    reg = registry(key)
    if not key:
        state = "undeclared"
    elif key == "none":
        state = "not_registered"
    else:
        state = "registered"
    registered_at = getattr(project, "registered_at", None) if project else None
    return {
        "state": state,
        "registry": key,
        "registry_label": reg.label if reg else key,
        "identifier": identifier,
        "url": public_url(key, identifier, stored_url),
        "registered_at": registered_at.isoformat() if registered_at else None,
        "protocol_url": (getattr(project, "protocol_url", "") or "") if project else "",
    }
