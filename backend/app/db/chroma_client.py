"""ChromaDB connection lifecycle management."""

from __future__ import annotations

import logging
from typing import Any

import chromadb
from chromadb.config import Settings as ChromaSettings

from app.core.config import Settings

logger = logging.getLogger(__name__)

# Global client singleton
_chroma_client: Any | None = None


async def init_chroma(settings: Settings) -> None:
    """Initialize the ChromaDB async client."""
    global _chroma_client
    if _chroma_client is not None:
        return

    logger.info("Initializing ChromaDB connection...", extra={"host": settings.CHROMA_HOST})
    try:
        # Use AsyncHttpClient to be async native
        _chroma_client = await chromadb.AsyncHttpClient(
            host=settings.CHROMA_HOST,
            port=settings.CHROMA_PORT,
            settings=ChromaSettings(anonymized_telemetry=False)
        )
    except Exception as e:
        logger.error("Failed to connect to ChromaDB", extra={"error": str(e)})
        raise


async def dispose_chroma() -> None:
    """Close the ChromaDB connection."""
    global _chroma_client
    if _chroma_client:
        logger.info("Closing ChromaDB connection...")
        _chroma_client = None


def get_chroma_client() -> Any:
    """Return the global ChromaDB client.
    
    Raises:
        RuntimeError: If called before init_chroma().
    """
    if _chroma_client is None:
        raise RuntimeError("ChromaDB is not initialized. Call init_chroma() first.")
    return _chroma_client


async def check_connection() -> bool:
    """Check if ChromaDB is responsive (used for health probes)."""
    try:
        client = get_chroma_client()
        await client.heartbeat()
        return True
    except Exception:
        return False
