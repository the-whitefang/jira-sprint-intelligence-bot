"""Authentication session caching.

Manages JWT revocation checks and active user session tracking.
This class does NOT extend CacheRepository because it relies on raw Redis
primitives (HSET, HDEL, direct SET with specific TTLs) rather than
JSON-serializing Pydantic models.
"""

from __future__ import annotations

import logging

from redis.asyncio import Redis

logger = logging.getLogger(__name__)


class SessionCache:
    """Manages active sessions and token revocation state."""

    def __init__(self, client: Redis) -> None:
        self._client = client
        self.namespace = "auth"

    def _build_key(self, suffix: str) -> str:
        return f"{self.namespace}:{suffix}"

    async def revoke_token(self, jti: str, remaining_ttl_seconds: int) -> None:
        """Mark a JWT as revoked until its natural expiration.
        
        Args:
            jti: The JWT ID to revoke.
            remaining_ttl_seconds: The exact remaining lifetime of the token.
                Once the token naturally expires, it no longer needs to be
                tracked in the revocation list.
        """
        if remaining_ttl_seconds <= 0:
            return
            
        key = self._build_key(f"revoked:{jti}")
        try:
            await self._client.set(key, "1", ex=remaining_ttl_seconds)
        except Exception as e:
            logger.warning(
                "token_revocation_failed",
                extra={"jti": jti, "error": str(e)}
            )

    async def is_token_revoked(self, jti: str) -> bool:
        """Check if a token has been explicitly revoked."""
        key = self._build_key(f"revoked:{jti}")
        try:
            # gracefully fail open (false) if Redis is down
            return await self._client.exists(key) > 0
        except Exception as e:
            logger.warning(
                "token_revocation_check_failed",
                extra={"jti": jti, "error": str(e)}
            )
            return False

    async def track_active_session(self, user_id: int, jti: str, expiry_timestamp: int) -> None:
        """Add a session to the user's active devices map.
        
        Uses a Redis Hash where key = session JTI, value = expiry timestamp.
        """
        key = self._build_key(f"active_sessions:{user_id}")
        try:
            await self._client.hset(key, jti, str(expiry_timestamp))
        except Exception as e:
            logger.warning(
                "session_tracking_failed",
                extra={"user_id": user_id, "jti": jti, "error": str(e)}
            )

    async def remove_active_session(self, user_id: int, jti: str) -> None:
        """Remove a specific session from the user's active devices."""
        key = self._build_key(f"active_sessions:{user_id}")
        try:
            await self._client.hdel(key, jti)
        except Exception as e:
            logger.warning(
                "session_removal_failed",
                extra={"user_id": user_id, "jti": jti, "error": str(e)}
            )

    async def get_active_sessions(self, user_id: int) -> dict[str, int]:
        """Get all tracked sessions and their expiry timestamps for a user."""
        key = self._build_key(f"active_sessions:{user_id}")
        try:
            raw = await self._client.hgetall(key)
            return {k: int(v) for k, v in raw.items()}
        except Exception as e:
            logger.warning(
                "active_sessions_fetch_failed",
                extra={"user_id": user_id, "error": str(e)}
            )
            return {}
