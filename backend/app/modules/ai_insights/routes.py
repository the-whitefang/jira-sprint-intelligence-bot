"""REST API routes for AI Chat."""

import json
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from app.core.config import get_settings
from app.modules.auth.dependencies import get_current_user
from app.modules.auth.models import User
from app.modules.ai_insights.schemas import ChatRequest
from app.modules.ai_insights.service import ChatService
from app.modules.ai_insights.gemini_client import GeminiClient
from app.modules.ai_insights.rate_limiter import AIRateLimiter
from app.modules.ai_insights.cache import ChatSessionCache
from app.modules.sprints.cache import SprintCache
from app.modules.knowledge_base.service import KnowledgeBaseService
from app.modules.knowledge_base.embedder import GeminiEmbedder
from app.db.redis_client import get_redis

router = APIRouter(prefix="/chat", tags=["chat"])

async def get_chat_service(request: Request) -> ChatService:
    """Dependency injector for ChatService."""
    settings = get_settings()
    
    # We initialize clients here. In a strictly optimized app, these might be singletons on app.state
    gemini_client = GeminiClient(settings)
    redis_client = get_redis()
    rate_limiter = AIRateLimiter(redis_client, settings)
    chat_cache = ChatSessionCache(redis_client)
    sprint_cache = SprintCache(redis_client)
    
    jira_client = request.app.state.jira_client
    
    # Initialize KB service for semantic search
    embedder = GeminiEmbedder(settings)
    # Re-use chroma client if we have one on state, else this is a bit tricky
    # For now, let's assume we can get it from state or import
    from app.db.chroma_client import get_chroma_client
    chroma = await get_chroma_client()
    kb_service = KnowledgeBaseService(chroma, settings, embedder)
    
    return ChatService(
        gemini_client=gemini_client,
        rate_limiter=rate_limiter,
        chat_cache=chat_cache,
        sprint_cache=sprint_cache,
        jira_client=jira_client,
        kb_service=kb_service
    )

@router.post("/stream")
async def chat_stream(
    payload: ChatRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    chat_service: Annotated[ChatService, Depends(get_chat_service)]
) -> StreamingResponse:
    """Stream AI responses back using Server-Sent Events (SSE)."""
    
    # Create the generator
    generator = chat_service.process_message_stream(
        user_id=current_user.id,
        session_id=payload.session_id,
        message=payload.message
    )
    
    return StreamingResponse(
        generator,
        media_type="text/event-stream"
    )
