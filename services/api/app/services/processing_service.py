"""
Processing Service
==================
BLOCK 5B: Processing Orchestration Layer

Business logic for processing job management.
Pure orchestration - no TTS implementation.
"""

import logging
from datetime import datetime
from typing import Optional, Tuple
from uuid import UUID

from sqlalchemy import select, func, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import HTTPException, status

from app.db.models.processing_job import ProcessingJob, JobType, JobStatus
from app.db.models.document import Document, ProcessingStatus, UploadStatus
from app.db.models.user import User
from app.schemas.processing import (
    ProcessDocumentRequest,
    ProcessingJobResponse,
    ProcessingJobListResponse,
    ProcessingJobListItem,
    ProcessingJobDetail,
    CancelJobResponse,
    QueueDepthResponse,
    ProcessingStatsResponse,
)
from app.celery_app import celery_app, revoke_task
from app.tasks.processing import process_document_job

logger = logging.getLogger(__name__)


# ============================================
# CONFIGURATION
# ============================================

class ProcessingConfig:
    """Processing service configuration."""
    
    MAX_CONCURRENT_JOBS_PER_USER = 3
    MAX_GLOBAL_ACTIVE_JOBS = 100
    DEFAULT_PRIORITY = 5


# ============================================
# PROCESSING SERVICE
# ============================================

class ProcessingService:
    """
    Processing job orchestration service.
    
    Responsibilities:
    - Validate document eligibility for processing
    - Enforce concurrency limits
    - Create processing jobs
    - Enqueue Celery tasks
    - Track job status
    - Manage job lifecycle (cancel, retry, etc.)
    
    NO TTS logic - pure orchestration.
    """
    
    def __init__(self, db: AsyncSession):
        """Initialize processing service."""
        self.db = db
    
    async def create_processing_job(
        self,
        document_id: UUID,
        user: User,
        request: ProcessDocumentRequest,
    ) -> ProcessingJobResponse:
        """
        Create a new processing job and enqueue it.
        
        Validation:
        - Document exists and belongs to user
        - Document is uploaded successfully
        - Document is not already being processed
        - User has not exceeded concurrent job limit
        - Global job limit not exceeded
        
        Args:
            document_id: Document to process
            user: Job owner
            request: Processing configuration
            
        Returns:
            Created processing job
            
        Raises:
            HTTPException: If validation fails
        """
        
        # Validate document
        document = await self._validate_document(document_id, user.id)
        
        # Check for existing active jobs for this document
        await self._check_document_not_processing(document_id)
        
        # Enforce concurrency limits
        await self._enforce_user_job_limit(user.id)
        await self._enforce_global_job_limit()
        
        # Parse job type
        job_type = JobType(request.job_type)
        
        # Create processing job
        job = ProcessingJob(
            document_id=document_id,
            user_id=user.id,
            job_type=job_type,
            priority=request.priority,
            status=JobStatus.QUEUED,
            progress_percentage=0,
        )
        
        self.db.add(job)
        
        # Update document status
        document.processing_status = ProcessingStatus.QUEUED
        
        await self.db.commit()
        await self.db.refresh(job)
        
        logger.info(
            f"Processing job created",
            extra={
                "job_id": str(job.id),
                "document_id": str(document_id),
                "user_id": str(user.id),
                "job_type": job_type.value,
                "priority": request.priority
            }
        )
        
        # Enqueue Celery task
        try:
            celery_task = process_document_job.apply_async(
                args=[str(job.id)],
                priority=request.priority,
                task_id=str(job.id),  # Use job ID as task ID for easy tracking
            )
            
            # Update job with Celery task ID
            job.celery_task_id = celery_task.id
            await self.db.commit()
            
            logger.info(
                f"Job enqueued to Celery",
                extra={
                    "job_id": str(job.id),
                    "celery_task_id": celery_task.id,
                    "priority": request.priority
                }
            )
            
        except Exception as e:
            logger.error(
                f"Failed to enqueue job: {str(e)}",
                extra={
                    "job_id": str(job.id),
                    "document_id": str(document_id)
                }
            )
            
            # Mark job as failed
            job.status = JobStatus.FAILED
            job.error_message = f"Failed to enqueue job: {str(e)}"
            document.processing_status = ProcessingStatus.FAILED
            
            await self.db.commit()
            
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to enqueue processing job"
            )
        
        # Build response
        return self._build_job_response(job)
    
    async def get_job(
        self,
        job_id: UUID,
        user: User,
    ) -> ProcessingJobDetail:
        """
        Get processing job details.
        
        Args:
            job_id: Job identifier
            user: Request user (for ownership check)
            
        Returns:
            Job details
            
        Raises:
            HTTPException: If job not found or access denied
        """
        
        result = await self.db.execute(
            select(ProcessingJob)
            .where(
                ProcessingJob.id == job_id,
                ProcessingJob.user_id == user.id
            )
        )
        job = result.scalar_one_or_none()
        
        if not job:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Processing job not found"
            )
        
        # Get document info
        doc_result = await self.db.execute(
            select(Document.filename).where(Document.id == job.document_id)
        )
        document_filename = doc_result.scalar_one_or_none()
        
        return ProcessingJobDetail(
            id=job.id,
            document_id=job.document_id,
            user_id=job.user_id,
            job_type=job.job_type.value,
            status=job.status.value,
            priority=job.priority,
            progress_percentage=job.progress_percentage,
            error_message=job.error_message,
            retry_count=job.retry_count,
            celery_task_id=job.celery_task_id,
            created_at=job.created_at,
            started_at=job.started_at,
            completed_at=job.completed_at,
            cancelled_at=job.cancelled_at,
            is_active=job.is_active,
            is_terminal=job.is_terminal,
            is_cancellable=job.is_cancellable,
            duration_seconds=job.duration_seconds,
            document_filename=document_filename,
        )
    
    async def list_jobs(
        self,
        user: User,
        page: int = 1,
        page_size: int = 20,
        status_filter: Optional[JobStatus] = None,
    ) -> ProcessingJobListResponse:
        """
        List user's processing jobs with pagination.
        
        Args:
            user: Job owner
            page: Page number (1-indexed)
            page_size: Items per page
            status_filter: Filter by job status
            
        Returns:
            Paginated list of jobs
        """
        
        # Build query
        query = select(ProcessingJob).where(ProcessingJob.user_id == user.id)
        
        if status_filter:
            query = query.where(ProcessingJob.status == status_filter)
        
        # Count total
        count_query = select(func.count()).select_from(ProcessingJob).where(ProcessingJob.user_id == user.id)
        if status_filter:
            count_query = count_query.where(ProcessingJob.status == status_filter)
        
        total_result = await self.db.execute(count_query)
        total = total_result.scalar()
        
        # Apply pagination and ordering
        query = query.order_by(ProcessingJob.created_at.desc())
        query = query.offset((page - 1) * page_size).limit(page_size)
        
        result = await self.db.execute(query)
        jobs = result.scalars().all()
        
        # Build response
        items = [
            ProcessingJobListItem(
                id=job.id,
                document_id=job.document_id,
                job_type=job.job_type.value,
                status=job.status.value,
                priority=job.priority,
                progress_percentage=job.progress_percentage,
                retry_count=job.retry_count,
                created_at=job.created_at,
                started_at=job.started_at,
                completed_at=job.completed_at,
                is_active=job.is_active,
            )
            for job in jobs
        ]
        
        return ProcessingJobListResponse(
            jobs=items,
            total=total,
            page=page,
            page_size=page_size,
            has_more=(page * page_size) < total,
        )
    
    async def cancel_job(
        self,
        job_id: UUID,
        user: User,
    ) -> CancelJobResponse:
        """
        Cancel a processing job.
        
        Args:
            job_id: Job to cancel
            user: Request user (for ownership check)
            
        Returns:
            Cancellation confirmation
            
        Raises:
            HTTPException: If job not found, access denied, or not cancellable
        """
        
        result = await self.db.execute(
            select(ProcessingJob)
            .where(
                ProcessingJob.id == job_id,
                ProcessingJob.user_id == user.id
            )
        )
        job = result.scalar_one_or_none()
        
        if not job:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Processing job not found"
            )
        
        if not job.is_cancellable:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Job cannot be cancelled (status: {job.status.value})"
            )
        
        # Revoke Celery task if it exists
        if job.celery_task_id:
            revoke_task(job.celery_task_id, terminate=True)
        
        # Update job status
        job.status = JobStatus.CANCELLED
        job.cancelled_at = datetime.utcnow()
        
        # Update document status if needed
        doc_result = await self.db.execute(
            select(Document).where(Document.id == job.document_id)
        )
        document = doc_result.scalar_one_or_none()
        
        if document and document.processing_status in (ProcessingStatus.QUEUED, ProcessingStatus.PROCESSING):
            document.processing_status = ProcessingStatus.NOT_STARTED
        
        await self.db.commit()
        
        logger.info(
            f"Job cancelled",
            extra={
                "job_id": str(job_id),
                "user_id": str(user.id),
                "celery_task_id": job.celery_task_id
            }
        )
        
        return CancelJobResponse(
            job_id=job.id,
            status=job.status.value,
            message="Job cancelled successfully",
            cancelled_at=job.cancelled_at,
        )
    
    async def get_queue_depth(self) -> QueueDepthResponse:
        """Get current queue depth statistics."""
        
        queued_result = await self.db.execute(
            select(func.count())
            .select_from(ProcessingJob)
            .where(ProcessingJob.status == JobStatus.QUEUED)
        )
        queued_count = queued_result.scalar()
        
        processing_result = await self.db.execute(
            select(func.count())
            .select_from(ProcessingJob)
            .where(ProcessingJob.status == JobStatus.PROCESSING)
        )
        processing_count = processing_result.scalar()
        
        return QueueDepthResponse(
            queued_jobs=queued_count,
            processing_jobs=processing_count,
            total_active=queued_count + processing_count,
        )
    
    # ============================================
    # VALIDATION HELPERS
    # ============================================
    
    async def _validate_document(self, document_id: UUID, user_id: UUID) -> Document:
        """Validate document exists, belongs to user, and is ready for processing."""
        
        result = await self.db.execute(
            select(Document).where(
                Document.id == document_id,
                Document.user_id == user_id
            )
        )
        document = result.scalar_one_or_none()
        
        if not document:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Document not found"
            )
        
        if document.upload_status != UploadStatus.UPLOADED:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Document upload not complete (status: {document.upload_status.value})"
            )
        
        return document
    
    async def _check_document_not_processing(self, document_id: UUID):
        """Check that document is not already being processed."""
        
        result = await self.db.execute(
            select(func.count())
            .select_from(ProcessingJob)
            .where(
                ProcessingJob.document_id == document_id,
                ProcessingJob.status.in_([JobStatus.QUEUED, JobStatus.PROCESSING])
            )
        )
        active_count = result.scalar()
        
        if active_count > 0:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Document is already being processed"
            )
    
    async def _enforce_user_job_limit(self, user_id: UUID):
        """Enforce maximum concurrent jobs per user."""
        
        result = await self.db.execute(
            select(func.count())
            .select_from(ProcessingJob)
            .where(
                ProcessingJob.user_id == user_id,
                ProcessingJob.status.in_([JobStatus.QUEUED, JobStatus.PROCESSING])
            )
        )
        active_count = result.scalar()
        
        if active_count >= ProcessingConfig.MAX_CONCURRENT_JOBS_PER_USER:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Maximum concurrent jobs limit reached ({ProcessingConfig.MAX_CONCURRENT_JOBS_PER_USER})"
            )
    
    async def _enforce_global_job_limit(self):
        """Enforce global maximum active jobs."""
        
        result = await self.db.execute(
            select(func.count())
            .select_from(ProcessingJob)
            .where(ProcessingJob.status.in_([JobStatus.QUEUED, JobStatus.PROCESSING]))
        )
        global_active = result.scalar()
        
        if global_active >= ProcessingConfig.MAX_GLOBAL_ACTIVE_JOBS:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Processing system at capacity. Please try again later."
            )
    
    def _build_job_response(self, job: ProcessingJob) -> ProcessingJobResponse:
        """Build processing job response."""
        
        return ProcessingJobResponse(
            id=job.id,
            document_id=job.document_id,
            user_id=job.user_id,
            job_type=job.job_type.value,
            status=job.status.value,
            priority=job.priority,
            progress_percentage=job.progress_percentage,
            error_message=job.error_message,
            retry_count=job.retry_count,
            celery_task_id=job.celery_task_id,
            created_at=job.created_at,
            started_at=job.started_at,
            completed_at=job.completed_at,
            is_active=job.is_active,
            is_terminal=job.is_terminal,
            is_cancellable=job.is_cancellable,
        )
