"""Gemini-powered text embedding."""

from __future__ import annotations

import logging

import google.generativeai as genai
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from app.core.config import Settings
from app.core.exceptions import ExternalServiceException

logger = logging.getLogger(__name__)


class GeminiEmbedder:
    """Wrapper for Google Generative AI embeddings."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        genai.configure(api_key=settings.GEMINI_API_KEY)
        # Using the standard embedding model
        self._embedding_model = "models/text-embedding-004"
        
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type(Exception),
        reraise=True
    )
    async def embed_text(self, text: str, task_type: str = "retrieval_document") -> list[float]:
        """Generate a vector embedding for a single string.
        
        Args:
            text: The text to embed.
            task_type: "retrieval_document" for indexing, "retrieval_query" for searching.
            
        Raises:
            ExternalServiceException: If the API call fails after retries.
        """
        try:
            # We must use synchronous since `embed_content_async` was added only very recently in some SDK versions, 
            # and might not be available or stable. We'll wrap the sync call if needed or use the async one if it exists.
            # Usually `genai.embed_content_async` exists in modern versions. Let's rely on it.
            result = await genai.embed_content_async(
                model=self._embedding_model,
                content=text,
                task_type=task_type
            )
            return result['embedding']
        except AttributeError:
            # Fallback for slightly older SDKs without async embed
            import asyncio
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(
                None,
                lambda: genai.embed_content(
                    model=self._embedding_model,
                    content=text,
                    task_type=task_type
                )
            )
            return result['embedding']
        except Exception as e:
            logger.error("gemini_embedding_failed", extra={"error": str(e)})
            raise ExternalServiceException(f"Failed to generate embedding: {str(e)}")

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type(Exception),
        reraise=True
    )
    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Generate vector embeddings for a list of strings."""
        if not texts:
            return []
            
        try:
            try:
                result = await genai.embed_content_async(
                    model=self._embedding_model,
                    content=texts,
                    task_type="retrieval_document"
                )
            except AttributeError:
                import asyncio
                loop = asyncio.get_running_loop()
                result = await loop.run_in_executor(
                    None,
                    lambda: genai.embed_content(
                        model=self._embedding_model,
                        content=texts,
                        task_type="retrieval_document"
                    )
                )
            return result['embedding']
        except Exception as e:
            logger.error("gemini_batch_embedding_failed", extra={"error": str(e)})
            raise ExternalServiceException(f"Failed to generate batch embeddings: {str(e)}")
