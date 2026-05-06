"""
Document Structure Exceptions
==============================
BLOCK 6B: Text Segmentation & Chapter Detection Layer

Custom exceptions for document structure analysis.
"""


class DocumentStructureError(Exception):
    """Base exception for document structure operations."""
    
    def __init__(self, message: str, document_id: str = None):
        self.message = message
        self.document_id = document_id
        super().__init__(self.message)


class PDFExtractionError(DocumentStructureError):
    """Raised when PDF text extraction fails."""
    pass


class ChapterDetectionError(DocumentStructureError):
    """Raised when chapter detection fails."""
    pass


class SegmentationError(DocumentStructureError):
    """Raised when text segmentation fails."""
    pass


class InvalidChapterError(DocumentStructureError):
    """Raised when chapter data is invalid."""
    pass


class NoChaptersDetectedError(ChapterDetectionError):
    """Raised when no chapters could be detected in document."""
    pass
