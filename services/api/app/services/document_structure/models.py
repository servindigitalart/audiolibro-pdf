"""
Document Structure Models
=========================
BLOCK 6B: Text Segmentation & Chapter Detection Layer

Data models for chapter detection and text segmentation.
These are not database models, but internal data structures.
"""

from dataclasses import dataclass, field
from typing import List, Optional
from uuid import UUID


@dataclass
class DetectedChapter:
    """
    Chapter detected by one of the detection strategies.
    
    This is an intermediate representation before persistence.
    Multiple DetectedChapters are fused into final Chapter entities.
    """
    
    title: str
    start_page: int
    end_page: int
    confidence: float
    detection_method: str
    text_content: Optional[str] = None
    char_count: int = 0
    
    def __post_init__(self):
        """Validate chapter data."""
        if self.start_page < 1:
            raise ValueError("start_page must be >= 1")
        if self.end_page < self.start_page:
            raise ValueError("end_page must be >= start_page")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be between 0.0 and 1.0")
        
        # Calculate char_count if text_content provided
        if self.text_content and self.char_count == 0:
            self.char_count = len(self.text_content)
    
    @property
    def page_count(self) -> int:
        """Get number of pages in chapter."""
        return self.end_page - self.start_page + 1


@dataclass
class TextChunk:
    """
    Safe-sized text chunk for TTS processing.
    
    Chunks are created by intelligently splitting chapter text
    at sentence boundaries while respecting max character limits.
    """
    
    chapter_id: UUID
    chunk_index: int
    text: str
    char_count: int
    start_char: int
    end_char: int
    
    def __post_init__(self):
        """Validate chunk data."""
        if self.char_count != len(self.text):
            self.char_count = len(self.text)
        if self.char_count == 0:
            raise ValueError("Chunk cannot be empty")


@dataclass
class PageText:
    """
    Extracted text from a single PDF page with metadata.
    """
    
    page_number: int
    text: str
    char_count: int
    font_sizes: List[float] = field(default_factory=list)
    has_toc_bookmark: bool = False
    
    def __post_init__(self):
        """Calculate char count."""
        if self.char_count == 0:
            self.char_count = len(self.text)


@dataclass
class TOCEntry:
    """
    Table of Contents entry extracted from PDF.
    """
    
    title: str
    page_number: int
    level: int = 1  # Hierarchy level (1=chapter, 2=section, etc.)
    
    def __post_init__(self):
        """Validate TOC entry."""
        if self.page_number < 1:
            raise ValueError("page_number must be >= 1")
        if self.level < 1:
            raise ValueError("level must be >= 1")


@dataclass
class DocumentStructure:
    """
    Complete document structure after analysis.
    
    Contains all detected chapters and metadata about the
    detection process.
    """
    
    document_id: UUID
    total_pages: int
    total_chars: int
    chapters: List[DetectedChapter]
    average_confidence: float = 0.0
    detection_methods_used: List[str] = field(default_factory=list)
    
    def __post_init__(self):
        """Calculate average confidence."""
        if self.chapters:
            self.average_confidence = sum(
                ch.confidence for ch in self.chapters
            ) / len(self.chapters)
    
    @property
    def chapter_count(self) -> int:
        """Get number of detected chapters."""
        return len(self.chapters)
    
    @property
    def has_high_confidence(self) -> bool:
        """Check if detection has high overall confidence."""
        return self.average_confidence >= 0.8


@dataclass
class SegmentationResult:
    """
    Result of text segmentation into TTS-safe chunks.
    """
    
    chunks: List[TextChunk]
    total_chunks: int
    total_chars: int
    max_chunk_size: int
    
    def __post_init__(self):
        """Calculate totals."""
        if not self.total_chunks:
            self.total_chunks = len(self.chunks)
        if not self.total_chars:
            self.total_chars = sum(chunk.char_count for chunk in self.chunks)
