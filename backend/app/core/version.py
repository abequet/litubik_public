# SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Release identity and the Corresponding Source offer required by AGPLv3 §13.

LitUbik is a network service: anyone interacting with it remotely must be
offered the source of the *running* version. `/api/instance` publishes these
three fields and the interface links to them, so the offer travels with every
deployment instead of depending on the operator remembering to make it.

`SOURCE_URL` must point at the sources of the build being served. A deployment
that patches LitUbik has to change it to its own repository — that is the whole
point of the clause, not a formality.
"""
import os

__version__ = "1.0.0"

HOMEPAGE = "https://github.com/abequet/litubik_public"

# the project's public contact, the default of an instance's legal pages
CONTACT_EMAIL = "contact@litubik.org"


def _source_url() -> str:
    """Where the sources of the running build are.

    An operator's own setting wins. A build Railway made from the repository
    follows its default branch rather than a release, so it links that branch.
    Otherwise (the packaged exe, a release image) the tagged tree of this very
    version — not the moving default branch."""
    configured = os.environ.get("LITUBIK_SOURCE_URL", "").strip()
    if configured:
        return configured
    if os.environ.get("RAILWAY_GIT_COMMIT_SHA"):
        return HOMEPAGE
    return f"{HOMEPAGE}/tree/v{__version__}"


SOURCE_URL = _source_url()

LICENSE_NAME = "AGPL-3.0-or-later"
