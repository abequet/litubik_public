# SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Thin wrapper around the vendored DOI batch downloader (doibatch.py).

We only call its pure `process_doi(doi, email, institutions, ...)` entry point.
Two guards for running it inside a server rather than a solo desktop app:
- Playwright is used only if the package is already importable — the module
  never installs anything at runtime;
- every navigation to a user-supplied host goes through the SSRF guard.
"""
from app.core.ssrf import validate_public_url
from app.services.fulltext import doibatch

# Enable the Playwright tiers only if the operator installed the package (and
# `playwright install chromium`) on purpose.
try:  # pragma: no cover - depends on the environment
    import playwright  # noqa: F401
except ImportError:
    doibatch._playwright_available = False

# C1/H4: gate every navigation to a user-supplied host (an EZProxy entry point)
# against private/internal addresses when running server-side. Left None in the
# standalone desktop tool.
doibatch._url_guard = validate_public_url

process_doi = doibatch.process_doi
normalize_doi = doibatch.normalize_doi
