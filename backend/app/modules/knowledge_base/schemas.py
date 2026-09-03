"""Schemas for the Knowledge Base module."""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict


class DocumentType(str, Enum):
    """The type of document being stored/retrieved."""
    SPRINT_GOAL = "sprint_goal"
    COMMENT = "comment"
    CONFLUENCE_PAGE = "confluence_page"
    RELEASE_NOTE = "release_note"
    RETROSPECTIVE = "retrospective"
    ARCHITECTURE_DOC = "architecture_doc"
    MEETING_NOTE = "meeting_note"


class DocumentMetadata(BaseModel):
    """Metadata attached to every chunk in ChromaDB.
    
    All fields are optional strings because ChromaDB metadata requires
    str/int/float/bool, not complex objects. We flatten attributes here.
    """
    model_config = ConfigDict(extra="ignore")
    
    doc_type: DocumentType
    document_id: str
    title: str | None = None
    author: str | None = None
    url: str | None = None
    created_at: str | None = None
    sprint_id: str | None = None
    project_key: str | None = None
    
    def to_chroma_dict(self) -> dict[str, str | int | float | bool]:
        """Convert to a dictionary safe for ChromaDB metadata."""
        return {
            k: (v.value if isinstance(v, Enum) else v) 
            for k, v in self.model_dump().items()
            if v is not None and (isinstance(v, (str, int, float, bool)) or isinstance(v, Enum))
        }


class DocumentChunk(BaseModel):
    """A single piece of text with metadata to be embedded."""
    id: str
    text: str
    metadata: DocumentMetadata


class SearchResult(BaseModel):
    """A retrieved chunk from ChromaDB."""
    id: str
    text: str
    metadata: dict[str, Any]
    distance: float | None = None
