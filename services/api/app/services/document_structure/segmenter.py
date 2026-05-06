"""
Text Segmenter
==============
BLOCK 6B: Text Segmentation & Chapter Detection Layer

Safely segments chapter text into TTS-compatible chunks.
Respects sentence boundaries and character limits.
"""

import logging
import re
from typing import List
from uuid import UUID

from app.services.document_structure.models import TextChunk
from app.services.document_structure.exceptions import SegmentationError

logger = logging.getLogger(__name__)


class TextSegmenter:
    """
    Segment text into safe-sized chunks for TTS processing.
    
    Strategy:
    - Max chunk size: 4000 characters (Google TTS limit is 5000, use buffer)
    - Split at sentence boundaries when possible
    - Never split mid-word
    - Preserve paragraphs when feasible
    
    This ensures:
    - No TTS API errors from oversized input
    - Natural audio breaks at sentence boundaries
    - Efficient parallel processing
    """
    
    DEFAULT_MAX_CHUNK_SIZE = 4000
    MIN_CHUNK_SIZE = 100  # Minimum viable chunk
    
    # Sentence ending patterns (multi-language)
    SENTENCE_ENDINGS = re.compile(
        r'([.!?।。！？][\s\n]+)|'  # Period, exclamation, question + whitespace
        r'([.!?।。！？]$)',  # At end of text
        re.UNICODE
    )
    
    def __init__(self, max_chunk_size: int = DEFAULT_MAX_CHUNK_SIZE):
        """
        Initialize segmenter.
        
        Args:
            max_chunk_size: Maximum characters per chunk
        """
        if max_chunk_size < self.MIN_CHUNK_SIZE:
            raise ValueError(f"max_chunk_size must be >= {self.MIN_CHUNK_SIZE}")
        
        self.max_chunk_size = max_chunk_size
    
    def segment_text(
        self,
        text: str,
        chapter_id: UUID
    ) -> List[TextChunk]:
        """
        Segment text into TTS-safe chunks.
        
        Args:
            text: Text to segment
            chapter_id: Chapter UUID for chunk tracking
            
        Returns:
            List of text chunks
            
        Raises:
            SegmentationError: If segmentation fails
        """
        if not text or not text.strip():
            return []
        
        # Clean text
        text = self._clean_text(text)
        
        if len(text) <= self.max_chunk_size:
            # Single chunk
            return [
                TextChunk(
                    chapter_id=chapter_id,
                    chunk_index=0,
                    text=text,
                    char_count=len(text),
                    start_char=0,
                    end_char=len(text)
                )
            ]
        
        # Need to split
        try:
            chunks = self._split_at_sentences(text, chapter_id)
            
            logger.info(
                f"Segmented {len(text)} chars into {len(chunks)} chunks "
                f"for chapter {chapter_id}"
            )
            
            return chunks
            
        except Exception as e:
            logger.error(f"Segmentation failed: {str(e)}")
            raise SegmentationError(
                message=f"Failed to segment text: {str(e)}"
            )
    
    def _split_at_sentences(
        self,
        text: str,
        chapter_id: UUID
    ) -> List[TextChunk]:
        """
        Split text at sentence boundaries.
        
        Args:
            text: Text to split
            chapter_id: Chapter UUID
            
        Returns:
            List of chunks
        """
        # Find all sentence boundaries
        sentences = []
        last_end = 0
        
        for match in self.SENTENCE_ENDINGS.finditer(text):
            end_pos = match.end()
            sentence = text[last_end:end_pos].strip()
            if sentence:
                sentences.append((last_end, end_pos, sentence))
            last_end = end_pos
        
        # Add remaining text
        if last_end < len(text):
            remaining = text[last_end:].strip()
            if remaining:
                sentences.append((last_end, len(text), remaining))
        
        # If no sentences detected, split by paragraphs
        if not sentences:
            return self._split_by_paragraphs(text, chapter_id)
        
        # Group sentences into chunks
        chunks = []
        current_chunk = []
        current_size = 0
        chunk_start = 0
        
        for start, end, sentence in sentences:
            sentence_size = len(sentence)
            
            # Would adding this sentence exceed max size?
            if current_size + sentence_size > self.max_chunk_size and current_chunk:
                # Finalize current chunk
                chunk_text = ' '.join(current_chunk)
                chunks.append(
                    TextChunk(
                        chapter_id=chapter_id,
                        chunk_index=len(chunks),
                        text=chunk_text,
                        char_count=len(chunk_text),
                        start_char=chunk_start,
                        end_char=chunk_start + len(chunk_text)
                    )
                )
                
                # Start new chunk
                current_chunk = [sentence]
                current_size = sentence_size
                chunk_start = start
            else:
                # Add to current chunk
                current_chunk.append(sentence)
                current_size += sentence_size
        
        # Add final chunk
        if current_chunk:
            chunk_text = ' '.join(current_chunk)
            chunks.append(
                TextChunk(
                    chapter_id=chapter_id,
                    chunk_index=len(chunks),
                    text=chunk_text,
                    char_count=len(chunk_text),
                    start_char=chunk_start,
                    end_char=chunk_start + len(chunk_text)
                )
            )
        
        return chunks
    
    def _split_by_paragraphs(
        self,
        text: str,
        chapter_id: UUID
    ) -> List[TextChunk]:
        """
        Fallback: Split by paragraphs when sentence detection fails.
        
        Args:
            text: Text to split
            chapter_id: Chapter UUID
            
        Returns:
            List of chunks
        """
        paragraphs = [p.strip() for p in text.split('\n\n') if p.strip()]
        
        if not paragraphs:
            # Last resort: split at max size
            return self._split_at_size(text, chapter_id)
        
        chunks = []
        current_chunk = []
        current_size = 0
        chunk_start = 0
        
        for para in paragraphs:
            para_size = len(para)
            
            if current_size + para_size > self.max_chunk_size and current_chunk:
                # Finalize chunk
                chunk_text = '\n\n'.join(current_chunk)
                chunks.append(
                    TextChunk(
                        chapter_id=chapter_id,
                        chunk_index=len(chunks),
                        text=chunk_text,
                        char_count=len(chunk_text),
                        start_char=chunk_start,
                        end_char=chunk_start + len(chunk_text)
                    )
                )
                
                current_chunk = [para]
                current_size = para_size
                chunk_start += len(chunk_text)
            else:
                current_chunk.append(para)
                current_size += para_size
        
        # Final chunk
        if current_chunk:
            chunk_text = '\n\n'.join(current_chunk)
            chunks.append(
                TextChunk(
                    chapter_id=chapter_id,
                    chunk_index=len(chunks),
                    text=chunk_text,
                    char_count=len(chunk_text),
                    start_char=chunk_start,
                    end_char=chunk_start + len(chunk_text)
                )
            )
        
        return chunks
    
    def _split_at_size(
        self,
        text: str,
        chapter_id: UUID
    ) -> List[TextChunk]:
        """
        Last resort: Split at max size boundaries.
        
        Args:
            text: Text to split
            chapter_id: Chapter UUID
            
        Returns:
            List of chunks
        """
        chunks = []
        start = 0
        
        while start < len(text):
            end = min(start + self.max_chunk_size, len(text))
            
            # Try to end at whitespace
            if end < len(text):
                # Look back for whitespace
                for i in range(end, max(start, end - 100), -1):
                    if text[i].isspace():
                        end = i
                        break
            
            chunk_text = text[start:end].strip()
            if chunk_text:
                chunks.append(
                    TextChunk(
                        chapter_id=chapter_id,
                        chunk_index=len(chunks),
                        text=chunk_text,
                        char_count=len(chunk_text),
                        start_char=start,
                        end_char=end
                    )
                )
            
            start = end
        
        return chunks
    
    def _clean_text(self, text: str) -> str:
        """
        Clean text before segmentation.
        
        Args:
            text: Raw text
            
        Returns:
            Cleaned text
        """
        # Remove excessive whitespace
        text = re.sub(r'\n{3,}', '\n\n', text)  # Max 2 consecutive newlines
        text = re.sub(r' {2,}', ' ', text)  # Max 1 space
        
        # Remove page numbers/headers/footers patterns
        text = re.sub(r'\n\d+\n', '\n', text)  # Standalone page numbers
        
        return text.strip()
