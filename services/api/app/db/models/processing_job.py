"""
Processing Job Model
====================
BLOCK 5B: Processing Orchestration Layer

Tracks document processing jobs through the Celery pipeline.
Pure orchestration - no TTS business logic.
"""

import enum
from datetime import datetime
from typing import Optional
import uuid

from sqlalchemy import (
    Column,
    String,
    Integer,
    Float,
    ForeignKey,
    DateTime,
    Enum,
    Index,
    Text,
    CheckConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.db.session import Base


class JobType(str, enum.Enum):
    """Processing job type."""
    FULL_PROCESS = "full_process"
    PREVIEW = "preview"
    REPROCESS = "reprocess"


class JobStatus(str, enum.Enum):
    """Processing job status."""
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ProcessingJob(Base):
    """
    Processing job orchestration tracking.
    
    Represents a Celery task that processes a document through the pipeline.
    This is pure infrastructure - no TTS logic lives here.
    
    Lifecycle:
    1. User requests processing → status=QUEUED
    2. Celery worker picks up → status=PROCESSING
    3. Processing completes → status=COMPLETED
    4. Or fails → status=FAILED
    5. User can cancel → status=CANCELLED
    
    The actual processing logic will be in Block 6 (TTS Engine).
    Block 5B only builds the orchestration infrastructure.
    """

    __tablename__ = "processing_jobs"

    # Identity
    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        index=True,
        comment="Unique job identifier"
    )
    
    # References
    document_id = Column(
        UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="Document being processed"
    )
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="Job owner"
    )
    
    # Job configuration
    #
    # native_enum=False + values_callable: same fix as Document.upload_status (migration 012).
    # SQLAlchemy 2.0 + asyncpg sends enum member .name ("FULL_PROCESS") through the native
    # codec instead of .value ("full_process"), causing InvalidTextRepresentationError.
    # Storing as VARCHAR(50) bypasses the native codec entirely. Migration 014 converts
    # the columns from PostgreSQL ENUM to VARCHAR(50).
    job_type = Column(
        Enum(JobType, native_enum=False, values_callable=lambda obj: [e.value for e in obj]),
        nullable=False,
        default=JobType.FULL_PROCESS,
        index=True,
        comment="Type of processing job"
    )
    priority = Column(
        Integer,
        nullable=False,
        default=5,
        server_default="5",
        comment="Job priority (1=highest, 10=lowest)"
    )

    # Status tracking
    status = Column(
        Enum(JobStatus, native_enum=False, values_callable=lambda obj: [e.value for e in obj]),
        nullable=False,
        default=JobStatus.QUEUED,
        index=True,
        comment="Current job status"
    )
    progress_percentage = Column(
        Integer,
        nullable=False,
        default=0,
        comment="Processing progress (0-100)"
    )

    # Chunk-level progress (migration 020)
    total_chunks = Column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
        comment="Total TTS chunks across all chapters; set before TTS loop starts"
    )
    completed_chunks = Column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
        comment="TTS chunks synthesised so far; incremented after each chunk"
    )
    current_stage = Column(
        String(50),
        nullable=True,
        comment="Pipeline stage: analyzing | chapter_detection | tts_generation | final_assembly | upload_finalize"
    )
    
    # Cost telemetry (Phase 3.6 — migration 021)
    characters_processed = Column(
        Integer,
        nullable=True,
        comment="TTS characters actually synthesised (exact, set on completion)"
    )
    # Written BEFORE TTS starts (migration 031 semantics), from the document's
    # character estimate × the rate of the voice actually selected.  Previously
    # this was written only on success, which is why failed jobs had no cost.
    estimated_cost_usd = Column(
        Float,
        nullable=True,
        comment="Pre-generation estimated provider cost in USD (set before TTS begins)"
    )
    # Written after synthesis from characters ACTUALLY sent to the provider.
    # Calculated from published per-character rates — Google exposes no
    # per-request invoice, so this is arithmetic, not a billed amount.
    calculated_cost_usd = Column(
        Float,
        nullable=True,
        comment="Calculated provider cost from characters actually synthesized (not an invoice)"
    )
    plan_tier_at_generation = Column(
        String(20),
        nullable=True,
        comment="User's plan tier when this job ran (FREE/BASIC/PRO/ENTERPRISE)"
    )

    # Narration preferences (migration 024)
    narration_style = Column(
        String(50),
        nullable=True,
        comment="User-selected style: calm | storytelling | documentary | podcast | educational"
    )
    voice_id_override = Column(
        String(255),
        nullable=True,
        comment="User-selected voice; overrides auto-detected voice when set"
    )

    # Error handling
    error_message = Column(
        Text,
        nullable=True,
        comment="Error details if job failed"
    )
    retry_count = Column(
        Integer,
        nullable=False,
        default=0,
        comment="Number of retry attempts"
    )
    
    # Celery task tracking
    celery_task_id = Column(
        String(255),
        nullable=True,
        index=True,
        comment="Celery task ID for tracking"
    )
    
    # Timestamps
    created_at = Column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
        index=True,
        comment="Job creation timestamp"
    )
    started_at = Column(
        DateTime,
        nullable=True,
        comment="Processing start timestamp"
    )
    completed_at = Column(
        DateTime,
        nullable=True,
        comment="Processing completion timestamp"
    )
    cancelled_at = Column(
        DateTime,
        nullable=True,
        comment="Cancellation timestamp"
    )
    
    # Relationships
    document = relationship("Document", back_populates="processing_jobs")
    user = relationship("User", back_populates="processing_jobs")
    
    # Constraints
    __table_args__ = (
        CheckConstraint(
            "progress_percentage >= 0 AND progress_percentage <= 100",
            name="ck_progress_percentage_range"
        ),
        CheckConstraint(
            "priority >= 1 AND priority <= 10",
            name="ck_priority_range"
        ),
        # Composite indexes for common queries
        Index("idx_processing_jobs_user_created", "user_id", "created_at"),
        Index("idx_processing_jobs_user_status", "user_id", "status"),
        Index("idx_processing_jobs_status_created", "status", "created_at"),
        Index("idx_processing_jobs_document_status", "document_id", "status"),
    )

    def __repr__(self) -> str:
        return (
            f"<ProcessingJob(id={self.id}, "
            f"document_id={self.document_id}, "
            f"status={self.status}, "
            f"progress={self.progress_percentage}%)>"
        )

    @property
    def is_active(self) -> bool:
        """Check if job is currently active (queued or processing)."""
        return self.status in (JobStatus.QUEUED, JobStatus.PROCESSING)

    @property
    def is_terminal(self) -> bool:
        """Check if job is in a terminal state (completed, failed, or cancelled)."""
        return self.status in (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED)

    @property
    def is_cancellable(self) -> bool:
        """Check if job can be cancelled."""
        return self.status in (JobStatus.QUEUED, JobStatus.PROCESSING)

    @property
    def duration_seconds(self) -> Optional[float]:
        """Calculate job duration in seconds if completed."""
        if self.started_at and self.completed_at:
            return (self.completed_at - self.started_at).total_seconds()
        return None
