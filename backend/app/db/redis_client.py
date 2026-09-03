"""Redis client management and connection pooling.

Mirrors the pattern established in session.py for MySQL.
Provides application-wide Redis connection pooling and dependency injection.
"""

from __future__ import annotations

import logging
from typing import AsyncGenerator

from redis.asyncio import Redis, ConnectionPool

from app.core.config import Settings

logger = logging.getLogger(__name__)

# Global connection pool created once at startup.
_redis_pool: ConnectionPool | None = None


def init_redis(settings: Settings) -> None:
    """Initialize the global Redis connection pool.
    
    Must be called exactly once during application startup.
    """
    global _redis_pool
    if _redis_pool is not None:
        logger.warning("redis_pool_already_initialized")
        return

    _redis_pool = ConnectionPool.from_url(
        settings.redis_url,
        max_connections=settings.REDIS_MAX_CONNECTIONS,
        decode_responses=True,
    )
    logger.info(
        "redis_pool_initialized",
        extra={"max_connections": settings.REDIS_MAX_CONNECTIONS}
    )


async def dispose_redis() -> None:
    """Close all Redis connections in the pool.
    
    Must be called exactly once during application shutdown.
    """
    global _redis_pool
    if _redis_pool is None:
        return

    await _redis_pool.disconnect()
    _redis_pool = None
    logger.info("redis_pool_disposed")


def get_redis_client() -> Redis:
    """Get a Redis client instance attached to the global pool.
    
    Raises:
        RuntimeError: If init_redis() hasn't been called yet.
    """
    if _redis_pool is None:
        raise RuntimeError("Redis pool not initialized. Call init_redis() first.")
    
    return Redis(connection_pool=_redis_pool)


async def get_redis() -> AsyncGenerator[Redis, None]:
    """FastAPI dependency for injecting the Redis client into routes."""
    client = get_redis_client()
    try:
        yield client
    finally:
        # Closing the client instance doesn't close the physical connection,
        # it just returns it to the pool.
        await client.aclose()


async def check_connection() -> bool:
    """Check if the Redis server is currently reachable.
    
    Used by readiness probes to verify the cache layer is up.
    Returns False instead of raising if the connection fails.
    """
    if _redis_pool is None:
        return False
        
    try:
        client = get_redis_client()
        return await client.ping()
    except Exception as e:
        logger.error("redis_connection_check_failed", extra={"error": str(e)})
        return False
