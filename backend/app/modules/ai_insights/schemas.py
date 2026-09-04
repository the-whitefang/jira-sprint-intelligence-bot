"""Schemas for AI Insights module."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel


class CachedChatMessage(BaseModel):
    """A single chat message in a session history."""

    role: Literal["user", "assistant", "system"]
    content: str
    timestamp: datetime


class ChatSessionHistory(BaseModel):
    """The cached recent history of a chat session."""

    session_id: int
    messages: list[CachedChatMessage]


class IntentType(str, Enum):
    """Classification of what the user wants to accomplish."""
    
    JQL_SEARCH = "JQL_SEARCH"
    SPRINT_METRICS = "SPRINT_METRICS"
    KNOWLEDGE_SEARCH = "KNOWLEDGE_SEARCH"
    ANALYTICS_LOOKUP = "ANALYTICS_LOOKUP"
    GENERAL_QNA = "GENERAL_QNA"


class IntentDetectionResponse(BaseModel):
    """The structured output format Gemini should return when detecting intent."""
    
    intent: IntentType
    confidence: float
    reasoning: str


class EntityExtractionResponse(BaseModel):
    """The structured output for entities extracted to build a JQL query."""
    
    projects: list[str] | None = None
    statuses: list[str] | None = None
    priorities: list[str] | None = None
    assignees: list[str] | None = None
    unassigned: bool | None = None
    sprint_id: int | None = None
    date_range_start: str | None = None
    date_range_end: str | None = None
    extra_keywords: str | None = None


class ChatRequest(BaseModel):
    """API request payload for a new chat message."""
    
    session_id: int
    message: str


class ChatResponse(BaseModel):
    """API response payload containing Gemini's response."""
    
    session_id: int
    reply: str
    intent_detected: IntentType | None = None
