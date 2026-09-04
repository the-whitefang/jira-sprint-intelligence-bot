"""Chat Service Orchestration."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from app.core.exceptions import AppException
from app.integrations.jira.client import JiraClient
from app.integrations.jira.jql.builder import JQLFilter
from app.modules.ai_insights.cache import ChatSessionCache
from app.modules.ai_insights.gemini_client import GeminiClient
from app.modules.ai_insights.prompt_templates import (
    ENTITY_EXTRACTION_PROMPT,
    INTENT_DETECTION_PROMPT,
    RESPONSE_GENERATION_PROMPT,
)
from app.modules.ai_insights.rate_limiter import AIRateLimiter
from app.modules.ai_insights.schemas import (
    CachedChatMessage,
    ChatResponse,
    ChatSessionHistory,
    EntityExtractionResponse,
    IntentDetectionResponse,
    IntentType,
)
from app.modules.sprints.cache import SprintCache
from app.modules.knowledge_base.service import KnowledgeBaseService

logger = logging.getLogger(__name__)


class ChatService:
    """Orchestrates the AI chat flow."""

    def __init__(
        self,
        gemini_client: GeminiClient,
        rate_limiter: AIRateLimiter,
        chat_cache: ChatSessionCache,
        sprint_cache: SprintCache,
        jira_client: JiraClient,
        kb_service: KnowledgeBaseService,
    ) -> None:
        self._gemini = gemini_client
        self._rate_limiter = rate_limiter
        self._chat_cache = chat_cache
        self._sprint_cache = sprint_cache
        self._jira = jira_client
        self._kb_service = kb_service

    async def process_message_stream(self, user_id: int, session_id: int, message: str):
        """Process a message and yield Server-Sent Events (SSE) for streaming responses."""
        
        # 1. Enforce Rate Limiting
        await self._rate_limiter.check_and_increment(user_id)
        
        # 2. Retrieve Conversation Memory
        session = await self._chat_cache.get_session(session_id)
        if not session:
            session = ChatSessionHistory(session_id=session_id, messages=[])
            
        history_text = self._format_history(session.messages)
        
        # yield an initial event so the UI knows we are thinking
        yield f"data: {json.dumps({'event': 'thinking', 'data': 'Analyzing intent...'})}\n\n"
        
        # 3. Detect Intent
        intent_prompt = INTENT_DETECTION_PROMPT.format(history=history_text, message=message)
        intent_response = await self._gemini.generate_structured_response(
            prompt=intent_prompt, 
            schema=IntentDetectionResponse
        )
        
        intent = intent_response.intent
        context_data = {}
        
        yield f"data: {json.dumps({'event': 'intent', 'data': intent.value})}\n\n"
        
        # 4. Backend Data Fetching based on Intent
        if intent == IntentType.JQL_SEARCH:
            context_data = await self._handle_jql_search(message)
            yield f"data: {json.dumps({'event': 'context', 'data': 'Fetched Jira tickets.'})}\n\n"
        elif intent == IntentType.SPRINT_METRICS:
            context_data = await self._handle_sprint_metrics(message)
            yield f"data: {json.dumps({'event': 'context', 'data': 'Fetched Sprint metrics.'})}\n\n"
        elif intent == IntentType.KNOWLEDGE_SEARCH:
            context_data = await self._handle_semantic_search(message)
            yield f"data: {json.dumps({'event': 'context', 'data': 'Fetched Knowledge Base articles.'})}\n\n"
        elif intent == IntentType.ANALYTICS_LOOKUP:
            context_data = {"note": "Analytics data lookup placeholder. Currently routing to general knowledge."}
            yield f"data: {json.dumps({'event': 'context', 'data': 'Fetched Employee Analytics.'})}\n\n"
        else:
            context_data = {"note": "General Q&A. No external context needed."}
            
        # 5. Generate Streamed Response
        response_prompt = RESPONSE_GENERATION_PROMPT.format(
            context=json.dumps(context_data, default=str),
            history=history_text,
            message=message
        )
        
        reply_buffer = ""
        
        # We start the chunk stream
        async for chunk in self._gemini.generate_text_stream(prompt=response_prompt):
            reply_buffer += chunk
            yield f"data: {json.dumps({'event': 'chunk', 'data': chunk})}\n\n"
            
        # 6. Update Memory
        session.messages.append(CachedChatMessage(role="user", content=message, timestamp=datetime.now(timezone.utc)))
        session.messages.append(CachedChatMessage(role="assistant", content=reply_buffer, timestamp=datetime.now(timezone.utc)))
        if len(session.messages) > 10:
            session.messages = session.messages[-10:]
            
        await self._chat_cache.set_session(session_id, session)
        
        # Signal completion
        yield f"data: {json.dumps({'event': 'done', 'data': ''})}\n\n"

    async def process_message(self, user_id: int, session_id: int, message: str) -> ChatResponse:
        """Process a user chat message and generate an AI response."""
        
        # 1. Enforce Rate Limiting
        await self._rate_limiter.check_and_increment(user_id)
        
        # 2. Retrieve Conversation Memory
        session = await self._chat_cache.get_session(session_id)
        if not session:
            session = ChatSessionHistory(session_id=session_id, messages=[])
            
        history_text = self._format_history(session.messages)
        
        # 3. Detect Intent
        intent_prompt = INTENT_DETECTION_PROMPT.format(history=history_text, message=message)
        intent_response = await self._gemini.generate_structured_response(
            prompt=intent_prompt, 
            schema=IntentDetectionResponse
        )
        
        intent = intent_response.intent
        context_data = {}
        
        # 4. Backend Data Fetching based on Intent
        if intent == IntentType.JQL_SEARCH:
            context_data = await self._handle_jql_search(message)
        elif intent == IntentType.SPRINT_METRICS:
            context_data = await self._handle_sprint_metrics(message)
        else:
            context_data = {"note": "General Q&A. No external context needed."}
            
        # 5. Generate Response
        response_prompt = RESPONSE_GENERATION_PROMPT.format(
            context=json.dumps(context_data, default=str),
            history=history_text,
            message=message
        )
        reply = await self._gemini.generate_text(prompt=response_prompt)
        
        # 6. Update Memory
        session.messages.append(CachedChatMessage(role="user", content=message, timestamp=datetime.now(timezone.utc)))
        session.messages.append(CachedChatMessage(role="assistant", content=reply, timestamp=datetime.now(timezone.utc)))
        # Keep only last 10 messages for context window bounds
        if len(session.messages) > 10:
            session.messages = session.messages[-10:]
            
        await self._chat_cache.set_session(session_id, session)
        
        return ChatResponse(
            session_id=session_id,
            reply=reply,
            intent_detected=intent
        )

    def _format_history(self, messages: list[CachedChatMessage]) -> str:
        if not messages:
            return "No previous conversation."
        return "\n".join(f"{msg.role}: {msg.content}" for msg in messages)

    async def _handle_jql_search(self, message: str) -> dict:
        """Extract entities and perform Jira JQL Search natively."""
        entity_prompt = ENTITY_EXTRACTION_PROMPT.format(message=message)
        entities = await self._gemini.generate_structured_response(
            prompt=entity_prompt,
            schema=EntityExtractionResponse
        )
        
        try:
            # Build JQL filter safely on the backend
            filter_kwargs = {}
            if entities.projects:
                filter_kwargs["projects"] = entities.projects
            if entities.statuses:
                filter_kwargs["statuses"] = entities.statuses
            if entities.priorities:
                filter_kwargs["priorities"] = entities.priorities
            if entities.assignees:
                filter_kwargs["assignees"] = entities.assignees
            if entities.unassigned:
                filter_kwargs["unassigned"] = True
            if entities.sprint_id:
                filter_kwargs["sprint_id"] = entities.sprint_id
            if entities.extra_keywords:
                filter_kwargs["extra_jql"] = f'text ~ "{entities.extra_keywords}"'
                
            jql_filter = JQLFilter(**filter_kwargs)
            page = await self._jira.jql.search(jql_filter, page_size=10) # limit to top 10 for context
            
            return {
                "total_matches": page.total if page else 0,
                "issues": [issue.model_dump() for issue in page.issues] if page else []
            }
        except Exception as e:
            logger.warning("jql_search_failed", extra={"error": str(e)})
            return {"error": "Failed to fetch issues from Jira due to an error or invalid query."}

    async def _handle_sprint_metrics(self, message: str) -> dict:
        """Fetch sprint metrics context."""
        # For a fully robust system, we might need Gemini to extract a specific sprint_id.
        # But we'll assume it's referring to the current sprint for simplicity in this orchestrated example.
        # In a real scenario, you'd fetch the active sprint from a known project context.
        # Since we don't have board context here directly from the user without more schema, 
        # we will instruct the LLM that we are assuming general context or returning a placeholder if board is unknown.
        
        # We simulate returning some metrics data.
        return {
            "note": "Sprint metrics context would be fetched here using self._sprint_cache.get_velocity() etc.",
            "status": "In a full implementation, pass the board_id to fetch specific sprint data."
        }

    async def _handle_semantic_search(self, message: str) -> dict:
        """Fetch context from ChromaDB based on the query."""
        results = await self._kb_service.semantic_search(query=message, limit=3)
        if not results:
            return {"note": "No relevant documentation found in the knowledge base."}
            
        docs = []
        for res in results:
            docs.append({
                "source": res.metadata.get("title", "Unknown"),
                "content": res.text,
                "relevance_score": res.distance
            })
            
        return {"knowledge_base_articles": docs}
