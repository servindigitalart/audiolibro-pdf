"""
Chapter Model
=============
BLOCK 6B: Text Segmentation & Chapter Detection Layer

Represents detected chapters/sections within a document.
Chapters are automatically detected using multiple strategies:
- TOC extraction from PDF
- Heuristic pattern matching (multi-language)
- Font size analysis
- Structural density changes
"""

from datetime import datetime
from typing import Optional
import uuid

from sqlalchemy import (
    Column,
    String,
    Integer,
    BigInteger,
    Float,
    ForeignKey,
    DateTime,
    Index,
    Text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.db.session import Base


class Chapter(Base):
    """
    Chapter/Section entity detected within a document.
    
    Chapters are automatically detected using a multi-strategy fusion system:
    - TOC extraction: Reads document outline/bookmarks
    - Heuristic detection: Pattern matching for chapter markers
    - Structural analysis: Font size and text density changes
    
    Each chapter has a confidence score indicating detection reliability.
    
    Structure:
    - Document → Chapters (ordered) → Text chunks
    
    Usage:
        chapter = Chapter(
            document_id=doc_id,
            title="Chapter 1: Introduction",
            start_page=1,
            end_page=5,
            order_index=0,
            confidence_score=0.95,
            char_count=12450
        )
    """

    __tablename__ = "chapters"

    # Identity
    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        index=True,
        comment="Unique chapter identifier"
    )
    document_id = Column(
        UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="Parent document"
    )

    # Chapter metadata
    title = Column(
        String(512),
        nullable=False,
        comment="Chapter title (detected or generated)"
    )
    start_page = Column(
        Integer,
        nullable=False,
        comment="Starting page number (1-indexed)"
    )
    end_page = Column(
        Integer,
        nullable=False,
        comment="Ending page number (inclusive)"
    )
    order_index = Column(
        Integer,
        nullable=False,
        comment="Sequential order within document (0-indexed)"
    )

    # Detection metadata
    confidence_score = Column(
        Float,
        nullable=False,
        default=0.0,
        comment="Detection confidence (0.0-1.0)"
    )
    detection_method = Column(
        String(50),
        nullable=True,
        comment="Primary detection method (toc, heuristic, structural, manual)"
    )

    # Content metadata
    char_count = Column(
        BigInteger,
        nullable=False,
        default=0,
        comment="Character count in chapter"
    )
    text_preview = Column(
        Text,
        nullable=True,
        comment="First 500 characters for preview"
    )

    # Timestamps
    created_at = Column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
        comment="Chapter detection timestamp"
    )

    # Relationships
    document = relationship(
        "Document",
        back_populates="chapters",
        lazy="joined"
    )

    # Indexes
    __table_args__ = (
        # Query chapters by document in order
        Index(
            "ix_chapters_document_order",
            "document_id",
            "order_index"
        ),
        # Query chapters by document and page range
        Index(
            "ix_chapters_document_pages",
            "document_id",
            "start_page",
            "end_page"
        ),
        # Query chapters by confidence
        Index(
            "ix_chapters_confidence",
            "confidence_score"
        ),
        # Query chapters by detection method
        Index(
            "ix_chapters_detection_method",
            "detection_method"
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<Chapter(id={self.id}, document_id={self.document_id}, "
            f"title='{self.title}', pages={self.start_page}-{self.end_page}, "
            f"order={self.order_index}, confidence={self.confidence_score:.2f})>"
        )

    @property
    def page_count(self) -> int:
        """Calculate number of pages in chapter."""
        return self.end_page - self.start_page + 1

    @property
    def is_high_confidence(self) -> bool:
        """Check if chapter was detected with high confidence."""
        return self.confidence_score >= 0.8

    @property
    def is_medium_confidence(self) -> bool:
        """Check if chapter was detected with medium confidence."""
        return 0.5 <= self.confidence_score < 0.8

    @property
    def is_low_confidence(self) -> bool:
        """Check if chapter was detected with low confidence."""
        return self.confidence_score < 0.5
