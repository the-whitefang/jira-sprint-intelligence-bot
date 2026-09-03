"""Text chunking logic for RAG."""

from __future__ import annotations

import logging
from collections.abc import Iterator

logger = logging.getLogger(__name__)


class SemanticChunker:
    """Chunks documents using a sliding window approach."""
    
    def __init__(self, chunk_size: int = 1000, overlap: int = 200) -> None:
        """Initialize the chunker.
        
        Args:
            chunk_size: Target size of each chunk in characters.
            overlap: Number of characters to overlap between chunks to preserve context.
        """
        self.chunk_size = chunk_size
        self.overlap = overlap
        
        if self.overlap >= self.chunk_size:
            raise ValueError("Overlap must be strictly less than chunk_size")

    def chunk_text(self, text: str) -> Iterator[str]:
        """Yield chunks of text using a sliding window.
        
        This is a simple character-based sliding window. In a more advanced
        implementation, we could use NLTK or spacy for sentence-boundary detection,
        or a specific tokenizer.
        """
        if not text:
            return

        text = text.strip()
        
        # If the text is smaller than our chunk size, yield it all
        if len(text) <= self.chunk_size:
            yield text
            return
            
        start = 0
        while start < len(text):
            end = start + self.chunk_size
            
            # If this isn't the very end, try to avoid cutting mid-word
            if end < len(text):
                # Look back for a space or newline to break on
                last_space = text.rfind(" ", start, end)
                last_newline = text.rfind("\n", start, end)
                
                break_point = max(last_space, last_newline)
                
                if break_point != -1 and break_point > start + (self.chunk_size // 2):
                    # We found a safe break point in the second half of the chunk
                    end = break_point + 1
            
            chunk = text[start:end].strip()
            if chunk:
                yield chunk
                
            # Advance start pointer, ensuring we make forward progress
            next_start = end - self.overlap
            if next_start <= start:
                next_start = start + 1 # Fallback to avoid infinite loop
            start = next_start
