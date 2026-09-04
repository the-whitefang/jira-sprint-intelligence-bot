"""FastAPI application factory and entry point.

This module wires together everything built so far — settings, logging,
exception handling — into a runnable FastAPI application, using the
application factory pattern (:func:`create_app`) rather than a
module-level ``app = FastAPI()``. The factory pattern is used because it:

* Lets tests construct isolated app instances with overridden settings,
  instead of sharing one process-wide app object across the whole test
  suite.
* Keeps import-time side effects out of module load — nothing runs until
  ``create_app()`` is actually called.

Feature routers (auth, sprints, analytics, chat, dashboard, admin,
reports) are intentionally **not** wired in yet — each will be added via
``app.include_router(...)`` as its module is built, per the agreed build
order. This file currently only establishes the foundation every future
router will sit on top of.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import Settings, get_settings
from app.core.logging_config import configure_logging
from app.db.redis_client import check_connection as check_redis_connection
from app.db.redis_client import dispose_redis, init_redis
from app.db.chroma_client import check_connection as check_chroma_connection
from app.db.chroma_client import dispose_chroma, init_chroma
from app.db.session import check_connection, dispose_engine, init_engine
from app.integrations.jira.client import JiraClient
from app.middleware.error_handler import RequestIdMiddleware, register_exception_handlers

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Manage startup and shutdown of process-wide resources.

    FastAPI's recommended ``lifespan`` context manager replaces the older
    ``@app.on_event("startup"/"shutdown")`` decorators — everything before
    ``yield`` runs on startup, everything after runs on shutdown, and the
    app only starts accepting traffic once startup completes.

    At this stage of the build, startup configures logging and creates
    both the database engine and the Jira integration client. Once
    ``db/redis_client.py`` exists, this is where its connection pool
    will be created and disposed of the same way.
    """
    settings = get_settings()
    configure_logging(settings)
    logger.info(
        "application_startup",
        extra={
            "app_name": settings.APP_NAME,
            "app_version": settings.APP_VERSION,
            "environment": settings.ENVIRONMENT.value,
        },
    )

    init_engine(settings)
    init_redis(settings)
    await init_chroma(settings)

    jira_client = JiraClient(settings)
    # A failed Jira connection at startup is logged, not raised: Jira being
    # briefly unreachable shouldn't take the whole API down, since most
    # endpoints (auth, health checks, anything not touching Jira data)
    # don't depend on it. Endpoints that do need Jira will surface a clean
    # 502 via JiraIntegrationError when they're actually called.
    jira_connected = await jira_client.test_connection()
    if jira_connected:
        logger.info("jira_connection_verified")
    else:
        logger.warning("jira_connection_failed_at_startup")
    app.state.jira_client = jira_client
    app.state.jira_connected = jira_connected

    yield

    await jira_client.aclose()
    await dispose_engine()
    await dispose_redis()
    await dispose_chroma()
    logger.info("application_shutdown")


def create_app() -> FastAPI:
    """Construct and configure the FastAPI application instance.

    Returns:
        A fully configured :class:`FastAPI` instance with logging,
        request-ID correlation, CORS, and global exception handling
        wired in, ready for feature routers to be attached.
    """
    settings = get_settings()

    app = FastAPI(
        title=settings.APP_NAME,
        version=settings.APP_VERSION,
        # Hide interactive API docs in production — an internal enterprise
        # tool's endpoint surface shouldn't be publicly browsable.
        docs_url="/docs" if not settings.is_production else None,
        redoc_url="/redoc" if not settings.is_production else None,
        openapi_url="/openapi.json" if not settings.is_production else None,
        lifespan=lifespan,
    )

    # Order matters: middleware is executed in the reverse order it's
    # added (outermost-added = outermost-executed), so RequestIdMiddleware
    # is added last to ensure it runs first and every downstream log line
    # — including ones from CORS rejections — has a request ID attached.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(RequestIdMiddleware)

    register_exception_handlers(app)
    _register_health_routes(app, settings)

    from app.modules.auth.routes import router as auth_router
    from app.modules.reports.routes import router as reports_router
    from app.modules.ai_insights.routes import router as chat_router
    
    app.include_router(auth_router, prefix=settings.API_V1_PREFIX)
    app.include_router(reports_router, prefix=settings.API_V1_PREFIX)
    app.include_router(chat_router, prefix=settings.API_V1_PREFIX)

    return app


def _register_health_routes(app: FastAPI, settings: Settings) -> None:
    """Register liveness/readiness endpoints.

    Kept separate from feature routers and outside ``/api/v1`` since
    these are infrastructure endpoints (used by Docker/Kubernetes health
    checks and load balancers), not part of the versioned business API.

    ``/health`` is a liveness check: "is the process up." ``/health/ready``
    will be extended to check Redis/ChromaDB connectivity once those
    clients exist — it currently reports Jira and database status.
    """

    @app.get("/health", tags=["infrastructure"])
    async def health() -> dict[str, str]:
        """Liveness probe: confirms the process is running and serving requests."""
        return {"status": "ok"}

    @app.get("/health/ready", tags=["infrastructure"])
    async def readiness(request: Request) -> dict[str, str | bool]:
        """Readiness probe: confirms the app is ready to serve real traffic.

        Reports Jira connectivity from the status captured at startup
        (see ``lifespan`` for why that's cached rather than tested live).
        Database connectivity, in contrast, is tested live on every call
        via :func:`app.db.session.check_connection` — a pooled,
        same-network query is cheap enough that a readiness probe
        catching a real DB outage promptly is worth the extra round trip,
        unlike an external rate-limited vendor call.
        """
        return {
            "status": "ok",
            "environment": settings.ENVIRONMENT.value,
            "jira_connected": request.app.state.jira_connected,
            "db_connected": await check_connection(),
            "redis_connected": await check_redis_connection(),
            "chroma_connected": await check_chroma_connection(),
        }


app = create_app()