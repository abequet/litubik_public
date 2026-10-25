# SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
# SPDX-License-Identifier: AGPL-3.0-or-later
"""In-process async job runner.

Long-running work (searches, batch AI, downloads) is persisted in the `jobs`
table and executed in a background thread so API requests return immediately.
Progress updates are pushed to subscribers over SSE via an asyncio queue per
job. No Celery/Redis — sufficient for a single-host deployment (~5 users).
"""
import asyncio
import logging
import traceback
from collections.abc import Callable
from datetime import datetime, timezone

from app.core.db import SessionLocal
from app.models import Job

logger = logging.getLogger(__name__)

# job type -> handler(job_id, params, progress_cb) run in a worker thread
_HANDLERS: dict[str, Callable] = {}


def register_handler(job_type: str):
    def decorator(fn):
        _HANDLERS[job_type] = fn
        return fn
    return decorator


class JobRunner:
    def __init__(self):
        self._subscribers: dict[int, list[asyncio.Queue]] = {}
        self._cancelled: set[int] = set()
        self._loop: asyncio.AbstractEventLoop | None = None

    def start(self, loop: asyncio.AbstractEventLoop):
        self._loop = loop

    # -- submission ---------------------------------------------------------
    def submit(self, job_type: str, params: dict, project_id: int | None,
               user_id: int | None) -> Job:
        if job_type not in _HANDLERS:
            raise ValueError(f"No handler registered for job type '{job_type}'")
        with SessionLocal() as db:
            # demo instances: a visitor's jobs are rationed (HTTP 429/503)
            from app.core.demo import check_sandbox_job_quota
            check_sandbox_job_quota(db, user_id, job_type)
            job = Job(type=job_type, params=params, project_id=project_id,
                      created_by=user_id)
            db.add(job)
            db.commit()
            db.refresh(job)
        assert self._loop is not None, "JobRunner not started"
        self._loop.run_in_executor(None, self._run, job.id, job_type, params)
        return job

    def cancel(self, job_id: int):
        self._cancelled.add(job_id)

    def is_cancelled(self, job_id: int) -> bool:
        return job_id in self._cancelled

    def transient_progress(self, job_id: int, job_type: str):
        """Progress callback that only publishes to SSE subscribers, without
        touching the jobs table. For handlers that hold a long write
        transaction on the (SQLite) DB: persisting progress from another
        connection would wait on their own uncommitted lock and deadlock.
        The final state is still persisted by _run when the handler returns."""
        def progress(done: int, total: int, message: str = ""):
            if self.is_cancelled(job_id):
                raise JobCancelled()
            self._publish(job_id, {
                "id": job_id, "type": job_type, "status": "running",
                "progress": done, "total": total, "message": message,
                "error": ""})
        return progress

    # -- execution (worker thread) ------------------------------------------
    def _run(self, job_id: int, job_type: str, params: dict):
        self._update(job_id, status="running", started_at=datetime.now(timezone.utc))
        try:
            def progress(done: int, total: int, message: str = ""):
                if self.is_cancelled(job_id):
                    raise JobCancelled()
                self._update(job_id, progress=done, total=total, message=message)

            result = _HANDLERS[job_type](job_id, params, progress) or {}
            self._update(job_id, status="done", result=result,
                         finished_at=datetime.now(timezone.utc))
        except JobCancelled:
            self._update(job_id, status="cancelled",
                         finished_at=datetime.now(timezone.utc))
        except Exception as e:
            logger.exception("Job %s (%s) failed", job_id, job_type)
            self._update(job_id, status="failed",
                         error=f"{e}\n{traceback.format_exc(limit=5)}",
                         finished_at=datetime.now(timezone.utc))
        finally:
            self._cancelled.discard(job_id)

    def _update(self, job_id: int, **fields):
        with SessionLocal() as db:
            job = db.get(Job, job_id)
            if job is None:
                return
            for key, value in fields.items():
                setattr(job, key, value)
            db.commit()
            payload = {
                "id": job.id, "type": job.type, "status": job.status,
                "progress": job.progress, "total": job.total,
                "message": job.message, "error": job.error,
            }
        self._publish(job_id, payload)

    # -- SSE fan-out ---------------------------------------------------------
    def _publish(self, job_id: int, payload: dict):
        if self._loop is None:
            return
        for queue in self._subscribers.get(job_id, []):
            self._loop.call_soon_threadsafe(queue.put_nowait, payload)

    def subscribe(self, job_id: int) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue()
        self._subscribers.setdefault(job_id, []).append(queue)
        return queue

    def unsubscribe(self, job_id: int, queue: asyncio.Queue):
        subscribers = self._subscribers.get(job_id, [])
        if queue in subscribers:
            subscribers.remove(queue)
        if not subscribers:
            self._subscribers.pop(job_id, None)


class JobCancelled(Exception):
    pass


def fail_stale_jobs() -> int:
    """At boot: a job still queued/running belongs to a previous process
    (the worker thread died with it) — mark it failed so the UI stops
    waiting and the living-review scheduler can resubmit."""
    now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        stale = (db.query(Job)
                 .filter(Job.status.in_(["queued", "running"])).all())
        for job in stale:
            job.status = "failed"
            job.error = "Interrupted by an application restart"
            job.finished_at = now
        db.commit()
        return len(stale)


runner = JobRunner()


@register_handler("llm_test")
def _llm_test_handler(job_id: int, params: dict, progress) -> dict:
    """Smoke-test job: one LLM call. Exercises the whole job+SSE pipeline.

    The API key never enters the persisted params — only the credential id.
    """
    from app.core.crypto import decrypt_secret
    from app.models import LLMCredential
    from app.services.llm import LLMError, get_provider

    with SessionLocal() as db:
        credential = db.get(LLMCredential, params["credential_id"])
        if credential is None:
            raise LLMError("Credential not found")
        api_key = decrypt_secret(credential.api_key_encrypted)
        if api_key is None:
            raise LLMError("Could not decrypt the API key (app secret changed?)")
        provider_name, model = credential.provider, credential.default_model
        base_url = credential.base_url

    progress(0, 1, "Calling the model...")
    provider = get_provider(provider_name, api_key, model, base_url=base_url)
    result = provider.test_connection()
    progress(1, 1, "Done")
    return {
        "reply": result.text,
        "tokens_input": result.tokens_input,
        "tokens_output": result.tokens_output,
    }
