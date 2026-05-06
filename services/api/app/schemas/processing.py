"""
Processing Job Schemas
=======================
BLOCK 5B: Processing Orchestration Layer

Pydantic schemas for processing job API endpoints.
Pure orchestration - no TTS business logic.
"""

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


# ============================================
# REQUEST SCHEMAS
# ============================================

class ProcessDocumentRequest(BaseModel):
    """Request to process a document."""
    
    job_type: str = Field(
        default="full_process",
        description="Type of processing job"
    )
    priority: int = Field(
        default=5,
        ge=1,
        le=10,
        description="Job priority (1=highest, 10=lowest)"
    )
    
    @field_validator("job_type")
    @classmethod
    def validate_job_type(cls, v: str) -> str:
        """Validate job type is supported."""
        valid_types = ["full_process", "preview", "reprocess"]
        if v not in valid_types:
            raise ValueError(f"Invalid job_type. Must be one of: {valid_types}")
        return v
    
    class Config:
        json_schema_extra = {
            "example": {
                "job_type": "full_process",
                "priority": 5
            }
        }


# ============================================
# RESPONSE SCHEMAS
# ============================================

class ProcessingJobResponse(BaseModel):
    """Response after creating a processing job."""
    
    id: UUID = Field(..., description="Job unique identifier")
    document_id: UUID = Field(..., description="Document being processed")
    user_id: UUID = Field(..., description="Job owner")
    job_type: str = Field(..., description="Job type")
    status: str = Field(..., description="Current status")
    priority: int = Field(..., description="Job priority")
    progress_percentage: int = Field(..., description="Progress (0-100)")
    error_message: Optional[str] = Field(None, description="Error details if failed")
    retry_count: int = Field(..., description="Number of retries")
    celery_task_id: Optional[str] = Field(None, description="Celery task ID")
    created_at: datetime = Field(..., description="Creation timestamp")
    started_at: Optional[datetime] = Field(None, description="Start timestamp")
    completed_at: Optional[datetime] = Field(None, description="Completion timestamp")
    
    # Computed properties
    is_active: bool = Field(..., description="Is job currently active")
    is_terminal: bool = Field(..., description="Is job in terminal state")
    is_cancellable: bool = Field(..., description="Can job be cancelled")
    
    class Config:
        from_attributes = True
        json_schema_extra = {
            "example": {
                "id": "123e4567-e89b-12d3-a456-426614174000",
                "document_id": "123e4567-e89b-12d3-a456-426614174001",
                "user_id": "123e4567-e89b-12d3-a456-426614174002",
                "job_type": "full_process",
                "status": "queued",
                "priority": 5,
                "progress_percentage": 0,
                "error_message": None,
                "retry_count": 0,
                "celery_task_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
                "created_at": "2026-02-11T16:30:00Z",
                "started_at": None,
                "completed_at": None,
                "is_active": True,
                "is_terminal": False,
                "is_cancellable": True
            }
        }


class ProcessingJobListItem(BaseModel):
    """Processing job list item with essential info."""
    
    id: UUID
    document_id: UUID
    job_type: str
    status: str
    priority: int
    progress_percentage: int
    retry_count: int
    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    is_active: bool
    
    class Config:
        from_attributes = True


class ProcessingJobListResponse(BaseModel):
    """Paginated list of processing jobs."""
    
    jobs: list[ProcessingJobListItem] = Field(..., description="List of jobs")
    total: int = Field(..., description="Total number of jobs")
    page: int = Field(..., description="Current page number")
    page_size: int = Field(..., description="Items per page")
    has_more: bool = Field(..., description="Whether more pages exist")
    
    class Config:
        json_schema_extra = {
            "example": {
                "jobs": [
                    {
                        "id": "123e4567-e89b-12d3-a456-426614174000",
                        "document_id": "123e4567-e89b-12d3-a456-426614174001",
                        "job_type": "full_process",
                        "status": "processing",
                        "priority": 5,
                        "progress_percentage": 45,
                        "retry_count": 0,
                        "created_at": "2026-02-11T16:00:00Z",
                        "started_at": "2026-02-11T16:01:00Z",
                        "completed_at": None,
                        "is_active": True
                    }
                ],
                "total": 15,
                "page": 1,
                "page_size": 20,
                "has_more": False
            }
        }


class ProcessingJobDetail(BaseModel):
    """Complete processing job details."""
    
    id: UUID
    document_id: UUID
    user_id: UUID
    job_type: str
    status: str
    priority: int
    progress_percentage: int
    error_message: Optional[str] = None
    retry_count: int
    celery_task_id: Optional[str] = None
    
    # Timestamps
    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    cancelled_at: Optional[datetime] = None
    
    # Computed properties
    is_active: bool
    is_terminal: bool
    is_cancellable: bool
    duration_seconds: Optional[float] = None
    
    # Related document info (optional expansion)
    document_filename: Optional[str] = None
    
    class Config:
        from_attributes = True


class CancelJobResponse(BaseModel):
    """Response after cancelling a job."""
    
    job_id: UUID = Field(..., description="Cancelled job ID")
    status: str = Field(..., description="New status (should be 'cancelled')")
    message: str = Field(..., description="Confirmation message")
    cancelled_at: datetime = Field(..., description="Cancellation timestamp")
    
    class Config:
        json_schema_extra = {
            "example": {
                "job_id": "123e4567-e89b-12d3-a456-426614174000",
                "status": "cancelled",
                "message": "Job cancelled successfully",
                "cancelled_at": "2026-02-11T16:35:00Z"
            }
        }


# ============================================
# STATUS SCHEMAS
# ============================================

class QueueDepthResponse(BaseModel):
    """Queue depth statistics."""
    
    queued_jobs: int = Field(..., description="Number of jobs in queue")
    processing_jobs: int = Field(..., description="Number of jobs currently processing")
    total_active: int = Field(..., description="Total active jobs (queued + processing)")
    
    class Config:
        json_schema_extra = {
            "example": {
                "queued_jobs": 12,
                "processing_jobs": 3,
                "total_active": 15
            }
        }


class ProcessingStatsResponse(BaseModel):
    """Processing statistics for user or global."""
    
    total_jobs: int = Field(..., description="Total jobs created")
    completed_jobs: int = Field(..., description="Successfully completed jobs")
    failed_jobs: int = Field(..., description="Failed jobs")
    cancelled_jobs: int = Field(..., description="Cancelled jobs")
    active_jobs: int = Field(..., description="Currently active jobs")
    
    # Averages
    average_duration_seconds: Optional[float] = Field(None, description="Average job duration")
    success_rate: float = Field(..., description="Success rate (0.0-1.0)")
    
    class Config:
        json_schema_extra = {
            "example": {
                "total_jobs": 42,
                "completed_jobs": 35,
                "failed_jobs": 3,
                "cancelled_jobs": 1,
                "active_jobs": 3,
                "average_duration_seconds": 145.5,
                "success_rate": 0.921
            }
        }
