"""Knowledge Base Orchestration Service."""

from __future__ import annotations

import logging
import uuid
from typing import Any

from chromadb.api import AsyncClientAPI

from app.core.config import Settings
from app.core.exceptions import ExternalServiceException
from app.modules.knowledge_base.chunker import SemanticChunker
from app.modules.knowledge_base.embedder import GeminiEmbedder
from app.modules.knowledge_base.schemas import DocumentMetadata, SearchResult

logger = logging.getLogger(__name__)


class KnowledgeBaseService:
    """Orchestrates indexing and retrieval for RAG."""

    def __init__(
        self,
        chroma_client: AsyncClientAPI,
        settings: Settings,
        embedder: GeminiEmbedder,
        chunker: SemanticChunker | None = None
    ) -> None:
        self._chroma = chroma_client
        self._collection_name = settings.CHROMA_KNOWLEDGE_COLLECTION
        self._embedder = embedder
        self._chunker = chunker or SemanticChunker()
        self._collection = None

    async def _get_collection(self) -> Any:
        """Get or create the unified ChromaDB collection."""
        if self._collection is None:
            try:
                # We use get_or_create_collection so we don't have to manage migrations
                self._collection = await self._chroma.get_or_create_collection(
                    name=self._collection_name,
                    metadata={"hnsw:space": "cosine"} # Cosine similarity for Gemini embeddings
                )
            except Exception as e:
                logger.error("failed_to_get_chroma_collection", extra={"error": str(e)})
                raise ExternalServiceException(f"ChromaDB error: {str(e)}")
        return self._collection

    async def index_document(self, text: str, metadata: DocumentMetadata) -> list[str]:
        """Chunk, embed, and index a document into ChromaDB.
        
        Returns:
            A list of chunk IDs that were successfully indexed.
        """
        if not text:
            return []

        chunks = list(self._chunker.chunk_text(text))
        if not chunks:
            return []

        # Generate embeddings
        embeddings = await self._embedder.embed_batch(chunks)

        # Prepare payload for ChromaDB
        chunk_ids = [f"{metadata.document_id}_{i}_{uuid.uuid4().hex[:8]}" for i in range(len(chunks))]
        chroma_metadata = metadata.to_chroma_dict()
        metadatas = [chroma_metadata for _ in chunks]

        collection = await self._get_collection()
        try:
            await collection.add(
                ids=chunk_ids,
                embeddings=embeddings,
                documents=chunks,
                metadatas=metadatas
            )
            logger.info("indexed_document", extra={
                "document_id": metadata.document_id,
                "doc_type": metadata.doc_type.value,
                "chunks_count": len(chunks)
            })
            return chunk_ids
        except Exception as e:
            logger.error("failed_to_index_document", extra={"error": str(e)})
            raise ExternalServiceException(f"Failed to index document in ChromaDB: {str(e)}")

    async def semantic_search(
        self, 
        query: str, 
        limit: int = 5, 
        filter_criteria: dict[str, Any] | None = None
    ) -> list[SearchResult]:
        """Perform a semantic search across the knowledge base.
        
        Args:
            query: The search string.
            limit: Maximum number of results to return.
            filter_criteria: Optional ChromaDB metadata filter (e.g. {"doc_type": "sprint_goal"})
        
        Returns:
            A list of SearchResult objects, ordered by relevance.
        """
        if not query:
            return []

        # Embed the query
        query_embedding = await self._embedder.embed_text(query, task_type="retrieval_query")

        collection = await self._get_collection()
        try:
            results = await collection.query(
                query_embeddings=[query_embedding],
                n_results=limit,
                where=filter_criteria
            )
            
            # Parse Chroma's shape into our strongly typed SearchResult list
            parsed_results = []
            if results and results["ids"] and len(results["ids"]) > 0:
                ids = results["ids"][0]
                documents = results["documents"][0] if results["documents"] else []
                metadatas = results["metadatas"][0] if results["metadatas"] else []
                distances = results["distances"][0] if results.get("distances") else []
                
                for i in range(len(ids)):
                    parsed_results.append(SearchResult(
                        id=ids[i],
                        text=documents[i] if i < len(documents) else "",
                        metadata=metadatas[i] if i < len(metadatas) else {},
                        distance=distances[i] if i < len(distances) else None
                    ))
            
            return parsed_results
        except Exception as e:
            logger.error("semantic_search_failed", extra={"error": str(e)})
            raise ExternalServiceException(f"Failed to perform semantic search: {str(e)}")
