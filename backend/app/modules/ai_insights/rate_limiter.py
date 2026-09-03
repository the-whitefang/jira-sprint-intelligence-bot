"""Rate limiting for AI API usage."""

from __future__ import annotations

import datetime
import logging

from redis.asyncio import Redis

from app.core.config import Settings
from app.core.exceptions import RateLimitExceededException

logger = logging.getLogger(__name__)

class AIRateLimiter:
    """Limits daily AI queries per user using Redis."""

    def __init__(self, client: Redis, settings: Settings) -> None:
        self._client = client
        self._daily_limit = settings.AI_DAILY_QUERY_QUOTA_PER_USER
        self.namespace = "ratelimit:ai"

    def _get_key(self, user_id: int) -> str:
        today = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")
        return f"{self.namespace}:{user_id}:{today}"

    async def check_and_increment(self, user_id: int) -> None:
        """Check if user has exceeded quota; if not, increment their usage.
        
        Raises:
            RateLimitExceededException if quota is exceeded.
        """
        key = self._get_key(user_id)
        
        try:
            # We use an atomic pipeline to increment and optionally set expiry
            async with self._client.pipeline(transaction=True) as pipe:
                pipe.incr(key)
                # Ensure the key expires after 24h (86400 seconds) so it doesn't leak memory
                pipe.expire(key, 86400, nx=True)
                results = await pipe.execute()
                
            current_usage = results[0]
            
            if current_usage > self._daily_limit:
                logger.warning(
                    "ai_rate_limit_exceeded",
                    extra={"user_id": user_id, "usage": current_usage, "limit": self._daily_limit}
                )
                raise RateLimitExceededException(
                    "Daily AI query quota exceeded. Please try again tomorrow.",
                    details={"quota": self._daily_limit, "used": current_usage}
                )
                
        except RateLimitExceededException:
            raise
        except Exception as e:
            # If Redis goes down, we fail open (allow the query) rather than breaking the app
            logger.warning("rate_limiter_redis_error", extra={"error": str(e)})
