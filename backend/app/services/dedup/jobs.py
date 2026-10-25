# SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Background job: (re-)run deduplication over a project."""
from app.core.db import SessionLocal
from app.services.dedup.core import run_dedup
from app.workers.runner import register_handler


@register_handler("dedup_run")
def dedup_run_handler(job_id: int, params: dict, progress) -> dict:
    def report(done: int, total: int):
        progress(done, total, f"Deduplicating ({done}/{total})...")

    with SessionLocal() as db:
        summary = run_dedup(db, params["project_id"], report)
    return summary
