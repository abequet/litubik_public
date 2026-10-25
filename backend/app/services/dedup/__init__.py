# SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
# SPDX-License-Identifier: AGPL-3.0-or-later
from app.services.dedup.core import (
    AUTO_THRESHOLD,
    UNCERTAIN_THRESHOLD,
    dedup_summary,
    first_author_key,
    merge_into,
    normalize_title,
    run_dedup,
)

__all__ = [
    "AUTO_THRESHOLD", "UNCERTAIN_THRESHOLD",
    "normalize_title", "first_author_key",
    "run_dedup", "merge_into", "dedup_summary",
]
