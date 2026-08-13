"""
Document Structure Module
==========================
BLOCK 6B: Text Segmentation & Chapter Detection Layer

Complete document structure analysis and chapter detection system.
"""

from app.services.document_structure.engine import DocumentStructureEngine
from app.services.document_structure.models import (
    DetectedChapter,
    TextChunk,
    PageText,
    TOCEntry,
    DocumentStructure,
    SegmentationResult,
)
from app.services.document_structure.exceptions import (
    DocumentStructureError,
    PDFExtractionError,
    ChapterDetectionError,
    SegmentationError,
    InvalidChapterError,
    NoChaptersDetectedError,
)

__all__ = [
    "DocumentStructureEngine",
    "DetectedChapter",
    "TextChunk",
    "PageText",
    "TOCEntry",
    "DocumentStructure",
    "SegmentationResult",
    "DocumentStructureError",
    "PDFExtractionError",
    "ChapterDetectionError",
    "SegmentationError",
    "InvalidChapterError",
    "NoChaptersDetectedError",
]
