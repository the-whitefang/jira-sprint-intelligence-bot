"""Async SQLAlchemy engine, session factory, and connection pooling.

This is the only module that constructs the database engine. Every other
module obtains a session through :func:`get_db` (a FastAPI dependency)
or :func:`session_scope` (for code running outside a request — a future
background worker, a CLI script) — never by importing the engine
directly.

**Transaction model**: both :func:`get_db` and :func:`session_scope`
commit on clean completion, roll back on any exception, and always
close. Because FastAPI caches dependency results per request, every
repository called with the same injected session participates in the
same transaction — composing several repository calls into one atomic
unit of work is just "call them with the same session," not something
each repository has to coordinate itself. See
``app/shared/base_repository.py`` for the other half of this: repository
methods flush but never commit, so they never have opinions about where
a transaction boundary is.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import Settings, get_settings

logger = logging.getLogger(__name__)

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def create_engine_from_settings(settings: Settings) -> AsyncEngine:
    """Build the async engine with production-appropriate connection pooling.

    Two settings matter most here, both easy to get wrong by leaving at
    SQLAlchemy's defaults:

    * ``pool_recycle`` — MySQL closes idle connections after a period
      (``wait_timeout``, commonly 8 hours, sometimes far less on managed
      database services). Without recycling, the pool eventually hands
      out a connection MySQL has already dropped, which surfaces as an
      opaque "MySQL server has gone away" error on an otherwise-healthy
      app. Recycling connections before that limit avoids it entirely.
    * ``pool_pre_ping`` — issues a lightweight liveness check before
      handing out a pooled connection, so one that died for any other
      reason (network blip, DB restart, load balancer timeout) gets
      quietly replaced instead of surfacing as a failed request.
    """
    return create_async_engine(
        settings.database_url,
        pool_size=settings.DB_POOL_SIZE,
        max_overflow=settings.DB_MAX_OVERFLOW,
        pool_timeout=settings.DB_POOL_TIMEOUT,
        pool_recycle=1800,
        pool_pre_ping=True,
        echo=settings.DB_ECHO,
    )


def init_engine(settings: Settings | None = None) -> AsyncEngine:
    """Create the process-wide engine and session factory.

    Call exactly once, from ``app/main.py``'s ``lifespan`` startup hook.
    Idempotent-unsafe by design (calling twice leaks the first engine's
    pool) — this is deliberately a singleton, not a per-call constructor.
    """
    global _engine, _session_factory
    settings = settings or get_settings()
    _engine = create_engine_from_settings(settings)
    _session_factory = async_sessionmaker(bind=_engine, expire_on_commit=False, autoflush=False)
    logger.info(
        "db_engine_initialized",
        extra={"pool_size": settings.DB_POOL_SIZE, "max_overflow": settings.DB_MAX_OVERFLOW},
    )
    return _engine


async def dispose_engine() -> None:
    """Dispose the engine's connection pool. Call exactly once, on shutdown."""
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
        logger.info("db_engine_disposed")
    _engine = None
    _session_factory = None


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Return the process-wide session factory.

    Raises:
        RuntimeError: :func:`init_engine` hasn't been called yet — a
            programming error (a route or worker running before startup
            completed), not a runtime condition callers should catch.
    """
    if _session_factory is None:
        raise RuntimeError(
            "Database engine not initialized — call init_engine() during application startup first."
        )
    return _session_factory


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    """Yield a session scoped to one unit of work: commit, rollback, or close.

    Commits if the ``with`` block completes cleanly, rolls back if it
    raises, and always closes the session afterward. Use this directly
    for any database work happening outside a FastAPI request — a
    background worker, a startup script, a one-off CLI task.
    """
    session_factory = get_session_factory()
    async with session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def get_db() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency yielding a request-scoped session.

    .. code-block:: python

        from fastapi import Depends
        from app.db.session import get_db

        @router.get("/example")
        async def example(db: AsyncSession = Depends(get_db)) -> ...:
            repo = UserRepository(db)
            ...

    Thin wrapper over :func:`session_scope` — kept as a separate function
    because FastAPI's ``Depends`` expects an async generator, not an
    ``@asynccontextmanager``-decorated function, even though the
    underlying commit/rollback/close contract is identical.
    """
    async with session_scope() as session:
        yield session


async def check_connection() -> bool:
    """Lightweight connectivity check, used by the ``/health/ready`` endpoint.

    Unlike the Jira connectivity check (deliberately cached from startup
    to avoid hammering a rate-limited external vendor on every probe),
    this issues a live ``SELECT 1`` on every call. That's appropriate
    here: the query runs against a pooled, typically same-network
    database rather than an external HTTP API, so the cost is low and a
    readiness probe catching a real DB outage promptly is exactly the
    point of checking live.

    Returns:
        ``True`` if a connection could be acquired and queried, ``False``
        otherwise. Never raises — a failed check is a normal, expected
        outcome for a readiness probe to report, not an application error.
    """
    try:
        session_factory = get_session_factory()
        async with session_factory() as session:
            await session.execute(text("SELECT 1"))
        return True
    except SQLAlchemyError:
        logger.warning("db_connection_check_failed", exc_info=True)
        return False
