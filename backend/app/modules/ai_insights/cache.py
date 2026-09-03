"""AI Insights chat session caching.

Acts as a read-through cache over the MySQL chat_messages table to provide
fast session history retrieval for the LLM context window.
"""

from __future__ import annotations

from redis.asyncio import Redis

from app.modules.ai_insights.schemas import ChatSessionHistory
from app.shared.cache_repository import CacheRepository


class ChatSessionCache(CacheRepository[ChatSessionHistory]):
    """Cache manager for AI chat sessions."""
    
    def __init__(self, client: Redis) -> None:
        super().__init__(client, "chat", ChatSessionHistory)

    async def get_session(self, session_id: int) -> ChatSessionHistory | None:
        return await self.get(f"session:{session_id}")

    async def set_session(self, session_id: int, history: ChatSessionHistory) -> None:
        # Cache chat history for 10 minutes. If a user returns later, we rebuild from DB.
        await self.set(f"session:{session_id}", history, ttl_seconds=600)

    async def invalidate_session(self, session_id: int) -> None:
        """Invalidate the cached session history.
        
        Should be called immediately after persisting any new message to DB.
        """
        await self.delete(f"session:{session_id}")
