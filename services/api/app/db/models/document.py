"""
Document Model
==============
Enterprise-grade document lifecycle tracking for Sonoro.
Tracks uploaded PDFs from ingestion to processing completion.
"""

import enum
from datetime import datetime
from typing import Optional
import uuid

from sqlalchemy import (
    Column,
    String,
    Integer,
    BigInteger,
    ForeignKey,
    DateTime,
    Enum,
    Index,
    Text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.db.session import Base


class UploadStatus(str, enum.Enum):
    """Upload lifecycle status."""
    PENDING = "pending"
    UPLOADED = "uploaded"
    FAILED = "failed"


class ProcessingStatus(str, enum.Enum):
    """Processing pipeline status."""
    NOT_STARTED = "not_started"
    QUEUED = "queued"
    PROCESSING = "processing"
    ASSEMBLING = "assembling"      # BLOCK 6C: Concatenating chapters
    FINALIZING = "finalizing"      # BLOCK 6C: Normalizing and adding metadata
    COMPLETED = "completed"
    FAILED = "failed"


class Document(Base):
    """
    Document lifecycle tracking.
    
    Represents a PDF document uploaded by a user, stored in DigitalOcean Spaces,
    and awaiting or undergoing processing (TTS conversion, etc).
    
    Security:
    - All documents are stored in private S3 buckets
    - Access requires pre-signed URLs
    - User ownership enforced at API layer
    
    Lifecycle:
    1. User uploads PDF → upload_status=PENDING
    2. File stored in S3 → upload_status=UPLOADED
    3. Queued for processing → processing_status=QUEUED
    4. Processing begins → processing_status=PROCESSING
    5. Completion → processing_status=COMPLETED
    
    Storage path format: documents/{user_id}/{document_id}.pdf
    """

    __tablename__ = "documents"

    # Identity
    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        index=True,
        comment="Unique document identifier"
    )
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="Document owner"
    )

    # File metadata
    filename = Column(
        String(255),
        nullable=False,
        comment="Sanitized filename used in storage"
    )
    original_filename = Column(
        String(512),
        nullable=False,
        comment="Original filename from upload"
    )
    file_size_bytes = Column(
        BigInteger,
        nullable=False,
        comment="File size in bytes"
    )
    mime_type = Column(
        String(100),
        nullable=False,
        default="application/pdf",
        comment="MIME type (validated)"
    )

    # Storage
    storage_path = Column(
        String(1024),
        nullable=False,
        unique=True,
        comment="Full S3 object key"
    )
    checksum_sha256 = Column(
        String(64),
        nullable=False,
        index=True,
        comment="SHA256 hash for integrity verification"
    )
    
    # Audio output (BLOCK 6C)
    final_audio_path = Column(
        String(1024),
        nullable=True,
        comment="Path to final assembled audiobook MP3"
    )
    audio_duration_seconds = Column(
        Integer,
        nullable=True,
        comment="Total audiobook duration in seconds"
    )
    audio_file_size_bytes = Column(
        BigInteger,
        nullable=True,
        comment="Final audiobook file size in bytes"
    )

    # Status tracking
    upload_status = Column(
        Enum(UploadStatus),
        nullable=False,
        default=UploadStatus.PENDING,
        index=True,
        comment="Upload completion status"
    )
    processing_status = Column(
        Enum(ProcessingStatus),
        nullable=False,
        default=ProcessingStatus.NOT_STARTED,
        index=True,
        comment="Processing pipeline status"
    )

    # Document analysis (lightweight metadata extraction)
    page_count = Column(
        Integer,
        nullable=True,
        comment="Number of pages in PDF"
    )
    character_estimate = Column(
        BigInteger,
        nullable=True,
        comment="Rough character count estimate"
    )
    language_detected = Column(
        String(10),
        nullable=True,
        comment="ISO 639-1 language code (e.g., 'en', 'es')"
    )

    # Error tracking
    error_message = Column(
        Text,
        nullable=True,
        comment="Error details if upload or processing failed"
    )

    # Timestamps
    created_at = Column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
        comment="Upload initiated timestamp"
    )
    updated_at = Column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        comment="Last modification timestamp"
    )
    uploaded_at = Column(
        DateTime,
        nullable=True,
        comment="Storage completion timestamp"
    )
    processing_started_at = Column(
        DateTime,
        nullable=True,
        comment="Processing initiation timestamp"
    )
    processing_completed_at = Column(
        DateTime,
        nullable=True,
        comment="Processing completion timestamp"
    )

    # Relationships
    user = relationship("User", back_populates="documents")
    processing_jobs = relationship(
        "ProcessingJob", back_populates="document", lazy="selectin", cascade="all, delete-orphan"
    )
    chapters = relationship(
        "Chapter", back_populates="document", lazy="selectin", cascade="all, delete-orphan",
        order_by="Chapter.order_index"
    )

    # Composite indexes for common queries
    __table_args__ = (
        Index("idx_documents_user_created", "user_id", "created_at"),
        Index("idx_documents_processing_created", "processing_status", "created_at"),
        Index("idx_documents_upload_status", "upload_status", "created_at"),
    )

    def __repr__(self) -> str:
        return (
            f"<Document(id={self.id}, "
            f"user_id={self.user_id}, "
            f"filename={self.filename}, "
            f"upload_status={self.upload_status}, "
            f"processing_status={self.processing_status})>"
        )

    @property
    def is_ready_for_processing(self) -> bool:
        """Check if document is successfully uploaded and ready to be queued."""
        return (
            self.upload_status == UploadStatus.UPLOADED
            and self.processing_status == ProcessingStatus.NOT_STARTED
        )

    @property
    def is_processing_complete(self) -> bool:
        """Check if document processing has completed successfully."""
        return self.processing_status == ProcessingStatus.COMPLETED

    @property
    def has_failed(self) -> bool:
        """Check if document has failed at any stage."""
        return (
            self.upload_status == UploadStatus.FAILED
            or self.processing_status == ProcessingStatus.FAILED
        )

    @property
    def file_size_mb(self) -> float:
        """Get file size in megabytes."""
        return self.file_size_bytes / (1024 * 1024)
