# SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
# SPDX-License-Identifier: AGPL-3.0-or-later
import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy.exc import OperationalError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api import (
    annotations, appraisal, auth, backup, concepts, custom_databases,
    db_settings, dedup,
    demo,
    equations, export,
    extraction, framings, fulltext, help, imports, institution_proxies,
    integrations, jobs, legal,
    living, llm_settings, notes, notifications, paper_download, prisma, projects,
    prompts, protocols, registries, reporting, results, screening, snowballing,
    sync, synthesis, tags,
    tickets, topics, translation, users, worktime,
)
from app.core.bodylimit import BodySizeLimit
from app.core.config import get_settings
from app.core.db import SessionLocal
from app.core.instance import get_instance_id
from app.services.connectors import jobs as connector_jobs  # noqa: F401 — registers handlers
from app.services.connectors import abstracts as abstract_jobs  # noqa: F401 — registers handlers
from app.services.dedup import jobs as dedup_jobs  # noqa: F401 — registers handlers
from app.services.equations import jobs as equation_jobs  # noqa: F401 — registers handlers
from app.services.fulltext import jobs as fulltext_jobs  # noqa: F401 — registers handlers
from app.services.fulltext import standalone as paper_download_jobs  # noqa: F401 — registers handlers
from app.services.integrations import zotero_jobs  # noqa: F401 — registers handlers
from app.services.living import jobs as living_jobs  # noqa: F401 — registers handlers
from app.services.protocol import jobs as protocol_jobs  # noqa: F401 — registers handlers
from app.services.screening import ai_batch as screening_ai_batch  # noqa: F401 — registers handlers
from app.services.screening import triage as screening_triage  # noqa: F401 — registers handlers
from app.services.snowballing import jobs as snowballing_jobs  # noqa: F401 — registers handlers
from app.services.topics import service as topics_jobs  # noqa: F401 — registers handlers
from app.workers.runner import fail_stale_jobs, runner


FOLDER_SYNC_INTERVAL_S = 300  # shared-folder scan period (sync phase 4)
SEARCH_UPDATE_INTERVAL_S = 3600  # living review: due plans are checked hourly


async def _search_update_loop():
    from app.services.living.service import run_due_plans
    loop = asyncio.get_running_loop()
    while True:
        await asyncio.sleep(SEARCH_UPDATE_INTERVAL_S)
        try:
            await loop.run_in_executor(None, run_due_plans)
        except Exception:
            logging.getLogger(__name__).exception("search update loop")


async def _folder_sync_loop():
    from app.services.sync.folder import scan_all_projects
    loop = asyncio.get_running_loop()
    while True:
        await asyncio.sleep(FOLDER_SYNC_INTERVAL_S)
        try:
            await loop.run_in_executor(None, scan_all_projects)
        except Exception:
            logging.getLogger(__name__).exception("folder sync loop")


async def _demo_reset_loop():
    from app.services.demo_reset import CHECK_INTERVAL_S, tick
    loop = asyncio.get_running_loop()
    while True:
        try:
            await loop.run_in_executor(None, tick)
        except Exception:
            logging.getLogger(__name__).exception("demo reset loop")
        await asyncio.sleep(CHECK_INTERVAL_S)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # the instance uuid must exist before any sync export references it
    try:
        with SessionLocal() as db:
            get_instance_id(db)
    except OperationalError:  # migrations not applied yet — created lazily later
        logging.getLogger(__name__).warning(
            "instance_meta unavailable (run `alembic upgrade head`)")
    # Provision the allowlist from LITUBIK_TRUSTED_EMAILS. Used by the M6 demo
    # tiers AND by restricted registration (H1), so it must run on any instance
    # that sets it — not only demo ones. A failure here must never take the
    # whole app down at boot.
    if get_settings().trusted_emails.strip():
        try:
            from app.core.demo import seed_trusted_emails
            with SessionLocal() as db:
                seed_trusted_emails(db)
        except Exception:
            logging.getLogger(__name__).exception(
                "seeding trusted emails failed — continuing without it")
    # jobs left running by a previous process can never finish
    try:
        with SessionLocal() as db:
            pass
        fail_stale_jobs()
    except OperationalError:
        pass
    runner.start(asyncio.get_running_loop())
    folder_task = asyncio.create_task(_folder_sync_loop())
    update_task = asyncio.create_task(_search_update_loop())
    reset_task = (asyncio.create_task(_demo_reset_loop())
                  if get_settings().demo_mode else None)
    if get_settings().demo_mode and get_settings().allow_registration:
        logging.getLogger(__name__).warning(
            "LITUBIK_ALLOW_REGISTRATION is ignored on a demo instance: visitors "
            "use the guest session, e-mail accounts are for the allowlist")
    yield
    folder_task.cancel()
    update_task.cancel()
    if reset_task is not None:
        reset_task.cancel()


# M1: the interactive API explorer maps the whole attack surface for anyone who
# loads the page. Useful while developing, needless on a served instance —
# LITUBIK_API_DOCS=true brings /docs, /redoc and /openapi.json back.
_docs = get_settings().api_docs
app = FastAPI(
    title=get_settings().app_name,
    lifespan=lifespan,
    docs_url="/docs" if _docs else None,
    redoc_url="/redoc" if _docs else None,
    openapi_url="/openapi.json" if _docs else None,
)


# M2: baseline response headers. The frontend is served from this same origin
# and loads no third-party script, so a strict CSP costs nothing here. pdf.js
# needs blob: workers and data: images; `frame-ancestors 'none'` also covers
# clickjacking for browsers that ignore X-Frame-Options.
_CSP = ("default-src 'self'; "
        "script-src 'self' 'wasm-unsafe-eval' blob:; "
        "worker-src 'self' blob:; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data: blob:; "
        "font-src 'self' data:; "
        "connect-src 'self'; "
        "object-src 'none'; "
        "base-uri 'self'; "
        "form-action 'self'; "
        "frame-ancestors 'none'")


@app.middleware("http")
async def security_headers(request, call_next):
    response = await call_next(request)
    response.headers.setdefault("Content-Security-Policy", _CSP)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "same-origin")
    response.headers.setdefault(
        "Permissions-Policy", "geolocation=(), microphone=(), camera=()")
    # HSTS only once we know the exchange was already protected — sending it
    # over plain HTTP is meaningless, and on a LAN it would be harmful.
    if (request.url.scheme == "https"
            or request.headers.get("x-forwarded-proto", "").split(",")[0].strip()
            == "https"):
        response.headers.setdefault("Strict-Transport-Security",
                                    "max-age=31536000; includeSubDomains")
    return response


# request bodies are size-checked before they are read (anonymous: 64 KB,
# demo visitor: 25 MB) — see app/core/bodylimit.py
app.add_middleware(BodySizeLimit)

# Vite dev server origins (LAN access included — cookies need explicit origins)
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1|192\.168\.\d+\.\d+|10\.\d+\.\d+\.\d+)(:\d+)?",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(backup.router)
app.include_router(projects.router)
app.include_router(llm_settings.router)
app.include_router(db_settings.router)
app.include_router(custom_databases.router)
app.include_router(jobs.router)
app.include_router(protocols.router)
app.include_router(concepts.router)
app.include_router(equations.router)
app.include_router(equations.golden_router)
app.include_router(imports.router)
app.include_router(dedup.router)
app.include_router(prisma.router)
app.include_router(screening.router)
app.include_router(fulltext.router)
app.include_router(fulltext.global_router)
app.include_router(paper_download.router)
app.include_router(users.router)
app.include_router(translation.router)
app.include_router(annotations.router)
app.include_router(snowballing.router)
app.include_router(tickets.router)
app.include_router(worktime.router)
app.include_router(living.router)
app.include_router(notifications.router)
app.include_router(extraction.router)
app.include_router(results.router)
app.include_router(reporting.router)
app.include_router(tags.router)
app.include_router(notes.router)
app.include_router(sync.router)
app.include_router(prompts.router)
app.include_router(help.router)
app.include_router(framings.router)
app.include_router(registries.router)
app.include_router(appraisal.router)
app.include_router(synthesis.router)
app.include_router(institution_proxies.router)
app.include_router(integrations.router)
app.include_router(integrations.project_router)
app.include_router(topics.router)
app.include_router(export.router)
app.include_router(demo.router)
app.include_router(demo.reset_router)
app.include_router(demo.budget_router)
app.include_router(legal.router)


@app.get("/api/health")
def health():
    return {"status": "ok", "app": get_settings().app_name}


@app.get("/api/instance")
def instance_info(request: Request):
    """Public instance profile (M6): the front shows the demo banner and the
    superadmin's Demo access page only when `demo` is true.

    `guest_entry` is per host name: on a demo instance, the guest names
    (`demo.*` by default) open the one-click guest session, the others keep
    an ordinary sign-in. `legal` lists the legal pages the instance publishes.

    Also carries the AGPLv3 §13 offer — version, licence and a link to the
    Corresponding Source of the build being served — which the interface
    renders, so remote users get it without the operator having to act."""
    from app.core.db import SessionLocal
    from app.core.demo import guest_entry_for_host
    from app.core.version import LICENSE_NAME, SOURCE_URL, __version__
    from app.services.legal import available_slugs
    settings = get_settings()
    try:
        with SessionLocal() as db:
            legal_pages = available_slugs(db)
    except OperationalError:  # migrations not applied yet
        legal_pages = []
    return {"demo": settings.demo_mode, "reset_hour": settings.demo_reset_hour,
            "guest_entry": guest_entry_for_host(request.headers.get("host")),
            "legal": legal_pages,
            "version": __version__, "license": LICENSE_NAME,
            "source_url": SOURCE_URL}


# In local production the backend serves the built frontend on the same port.
class SPAStaticFiles(StaticFiles):
    """Serve index.html for unknown paths so client-side routes
    (/projects/1/search, deep links, page reloads) reach the React router
    instead of a JSON 404.

    index.html is served with no-cache: a cached shell referencing old hashed
    bundles is exactly the 'blank page until manual reload' bug. The hashed
    /assets/* files themselves stay cacheable."""

    async def get_response(self, path: str, scope):
        is_api = scope.get("path", "").startswith("/api")
        try:
            response = await super().get_response(path, scope)
        except StarletteHTTPException as e:
            if e.status_code != 404 or is_api:
                raise
            response = await super().get_response("index.html", scope)
        else:
            if response.status_code == 404 and not is_api:
                response = await super().get_response("index.html", scope)
        if "text/html" in (response.headers.get("content-type") or ""):
            response.headers["Cache-Control"] = "no-cache, must-revalidate"
        return response


from app.core.paths import frontend_dist  # noqa: E402 — after app creation

_frontend_dist = frontend_dist()
if _frontend_dist.exists():
    app.mount("/", SPAStaticFiles(directory=_frontend_dist, html=True),
              name="frontend")
