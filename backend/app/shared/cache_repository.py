"""Generic Redis cache repository pattern.

Provides a unified interface for persisting Pydantic models to Redis with
built-in namespacing, graceful degradation (failing open if Redis is down),
and serialization handling.
"""

from __future__ import annotations

import logging
from typing import Generic, Type, TypeVar

from pydantic import BaseModel
from redis.asyncio import Redis

logger = logging.getLogger(__name__)

ModelType = TypeVar("ModelType", bound=BaseModel)


def build_cache_key(namespace: str, *parts: str | int) -> str:
    """Build a standard colon-separated Redis key.
    
    Args:
        namespace: The root prefix for this domain (e.g., 'sprint', 'auth').
        *parts: Additional identifying parts (e.g., ID, sub-resource name).
        
    Returns:
        A string key like 'sprint:current:123'.
    """
    key_parts = [namespace] + [str(p) for p in parts]
    return ":".join(key_parts)


class CacheRepository(Generic[ModelType]):
    """Base class for domain-specific cache repositories.
    
    Unlike database repositories which MUST raise on failure to preserve
    correctness, cache repositories default to graceful degradation — if
    Redis is down, they log an error and return None (for gets) or silently
    return (for sets/deletes), allowing the application to fall back to the
    primary data source.
    """
    
    def __init__(self, client: Redis, namespace: str, model_class: Type[ModelType]) -> None:
        """Initialize the repository.
        
        Args:
            client: The raw async Redis client.
            namespace: The root prefix for all keys managed by this repo.
            model_class: The Pydantic model this repository handles.
        """
        self._client = client
        self.namespace = namespace
        self.model_class = model_class

    async def get(self, key_suffix: str) -> ModelType | None:
        """Retrieve and deserialize a Pydantic model from cache.
        
        Args:
            key_suffix: The rest of the key after the namespace.
        """
        key = build_cache_key(self.namespace, key_suffix)
        try:
            raw_data = await self._client.get(key)
            if not raw_data:
                return None
            return self.model_class.model_validate_json(raw_data)
        except Exception as e:
            logger.warning(
                "cache_get_failed",
                extra={"key": key, "error": str(e)}
            )
            return None

    async def set(self, key_suffix: str, model: ModelType, ttl_seconds: int | None = None) -> None:
        """Serialize and store a Pydantic model in cache.
        
        Args:
            key_suffix: The rest of the key after the namespace.
            model: The Pydantic model to store.
            ttl_seconds: Optional expiration time in seconds.
        """
        key = build_cache_key(self.namespace, key_suffix)
        try:
            raw_data = model.model_dump_json()
            await self._client.set(key, raw_data, ex=ttl_seconds)
        except Exception as e:
            logger.warning(
                "cache_set_failed",
                extra={"key": key, "error": str(e)}
            )

    async def delete(self, key_suffix: str) -> None:
        """Remove a specific key from the cache."""
        key = build_cache_key(self.namespace, key_suffix)
        try:
            await self._client.delete(key)
        except Exception as e:
            logger.warning(
                "cache_delete_failed",
                extra={"key": key, "error": str(e)}
            )

    async def delete_by_prefix(self, prefix_suffix: str) -> None:
        """Delete all keys matching a specific prefix pattern.
        
        Uses SCAN to find keys iteratively without blocking the Redis server.
        """
        prefix = build_cache_key(self.namespace, prefix_suffix)
        pattern = f"{prefix}*"
        try:
            cursor = 0
            while True:
                cursor, keys = await self._client.scan(cursor, match=pattern, count=100)
                if keys:
                    await self._client.delete(*keys)
                if cursor == 0:
                    break
        except Exception as e:
            logger.warning(
                "cache_delete_prefix_failed",
                extra={"pattern": pattern, "error": str(e)}
            )

    async def get_ttl(self, key_suffix: str) -> int:
        """Get the remaining TTL for a key in seconds.
        
        Returns:
            The TTL in seconds, -1 if no TTL, -2 if key does not exist,
            or 0 if an error occurred checking Redis.
        """
        key = build_cache_key(self.namespace, key_suffix)
        try:
            return await self._client.ttl(key)
        except Exception as e:
            logger.warning(
                "cache_ttl_check_failed",
                extra={"key": key, "error": str(e)}
            )
            return 0
