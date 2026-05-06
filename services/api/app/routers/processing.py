"""
Processing API Router
=====================
BLOCK 5B: Processing Orchestration Layer

API endpoints for processing job management.
Pure orchestration - no TTS business logic.
"""

import logging
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth_dependencies import get_current_active_user
from app.db.models.user import User
from app.db.models.processing_job import JobStatus
from app.db.session import get_async_db
from app.schemas.processing import (
    ProcessDocumentRequest,
    ProcessingJobResponse,
    ProcessingJobListResponse,
    ProcessingJobDetail,
    CancelJobResponse,
    QueueDepthResponse,
)
from app.services.processing_service import ProcessingService
from app.services.account_service import AccountService
from app.financial.financial_metrics import (
    processing_jobs_total,
    processing_job_duration_seconds,
    processing_failures_total,
    processing_active_jobs,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/processing", tags=["processing"])


# ============================================
# PROCESS DOCUMENT
# ============================================

@router.post(
    "/documents/{document_id}/process",
    response_model=ProcessingJobResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Process Document",
    description="""
    Create a processing job for a document.
    
    **Requirements:**
    - Document must be uploaded successfully
    - Document not already being processed
    - User has not exceeded concurrent job limit
    
    **Job Types:**
    - `full_process`: Complete processing pipeline
    - `preview`: Quick preview (reduced quality)
    - `reprocess`: Reprocess existing job
    
    **Priority:**
    - 1-3: High priority (fast lane)
    - 4-7: Normal priority (default)
    - 8-10: Low priority (background)
    
    **Note:** This is orchestration only. The actual processing
    logic (TTS, chapter detection, etc.) will be in Block 6.
    """
)
async def process_document(
    document_id: UUID,
    request: ProcessDocumentRequest,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_active_user),
):
    """Create a processing job for a document."""
    
    try:
        logger.info(
            f"Processing request received",
            extra={
                "user_id": str(current_user.id),
                "document_id": str(document_id),
                "job_type": request.job_type,
                "priority": request.priority
            }
        )
        
        # Log activity
        account_service = AccountService(db)
        try:
            await account_service.log_activity(
                user_id=current_user.id,
                activity_type="processing_job_created",
                description=f"Started processing for document {document_id}",
                metadata={
                    "document_id": str(document_id),
                    "job_type": request.job_type,
                    "priority": request.priority
                }
            )
        except Exception as log_error:
            logger.warning(f"Failed to log activity: {str(log_error)}")
        
        # Create processing job
        processing_service = ProcessingService(db)
        result = await processing_service.create_processing_job(
            document_id=document_id,
            user=current_user,
            request=request,
        )
        
        # Record metrics
        processing_jobs_total.labels(status="created").inc()
        processing_active_jobs.inc()
        
        logger.info(
            f"Processing job created successfully",
            extra={
                "user_id": str(current_user.id),
                "document_id": str(document_id),
                "job_id": str(result.id),
                "celery_task_id": result.celery_task_id
            }
        )
        
        return result
        
    except Exception as e:
        processing_failures_total.labels(failure_reason="creation_error").inc()
        logger.error(
            f"Failed to create processing job: {str(e)}",
            extra={
                "user_id": str(current_user.id),
                "document_id": str(document_id)
            },
            exc_info=True
        )
        raise


# ============================================
# GET JOB STATUS
# ============================================

@router.get(
    "/jobs/{job_id}",
    response_model=ProcessingJobDetail,
    summary="Get Job Status",
    description="""
    Get detailed status of a processing job.
    
    **Returns:**
    - Current status and progress
    - Error message if failed
    - Timing information
    - Celery task ID for tracking
    """
)
async def get_job_status(
    job_id: UUID,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_active_user),
):
    """Get processing job status and details."""
    
    processing_service = ProcessingService(db)
    result = await processing_service.get_job(job_id=job_id, user=current_user)
    
    logger.info(
        f"Job status retrieved",
        extra={
            "user_id": str(current_user.id),
            "job_id": str(job_id),
            "status": result.status,
            "progress": result.progress_percentage
        }
    )
    
    return result


# ============================================
# LIST JOBS
# ============================================

@router.get(
    "/jobs",
    response_model=ProcessingJobListResponse,
    summary="List Processing Jobs",
    description="""
    List user's processing jobs with pagination and filtering.
    
    **Features:**
    - Pagination support
    - Filter by job status
    - Ordered by creation date (newest first)
    """
)
async def list_jobs(
    page: int = Query(1, ge=1, description="Page number (1-indexed)"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
    status: Optional[str] = Query(None, description="Filter by job status"),
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_active_user),
):
    """List user's processing jobs."""
    
    # Parse status filter if provided
    status_filter = None
    if status:
        try:
            status_filter = JobStatus(status)
        except ValueError:
            from fastapi import HTTPException
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid status: {status}"
            )
    
    processing_service = ProcessingService(db)
    result = await processing_service.list_jobs(
        user=current_user,
        page=page,
        page_size=page_size,
        status_filter=status_filter,
    )
    
    logger.info(
        f"Jobs listed",
        extra={
            "user_id": str(current_user.id),
            "page": page,
            "total": result.total
        }
    )
    
    return result


# ============================================
# CANCEL JOB
# ============================================

@router.delete(
    "/jobs/{job_id}",
    response_model=CancelJobResponse,
    summary="Cancel Processing Job",
    description="""
    Cancel a processing job.
    
    **Requirements:**
    - Job must be in QUEUED or PROCESSING status
    - User must own the job
    
    **Actions:**
    - Revokes Celery task
    - Updates job status to CANCELLED
    - Resets document processing status
    """
)
async def cancel_job(
    job_id: UUID,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_active_user),
):
    """Cancel a processing job."""
    
    try:
        processing_service = ProcessingService(db)
        result = await processing_service.cancel_job(job_id=job_id, user=current_user)
        
        # Record metrics
        processing_jobs_total.labels(status="cancelled").inc()
        processing_active_jobs.dec()
        
        # Log activity
        account_service = AccountService(db)
        try:
            await account_service.log_activity(
                user_id=current_user.id,
                activity_type="processing_job_cancelled",
                description=f"Cancelled processing job {job_id}",
                metadata={"job_id": str(job_id)}
            )
        except Exception as log_error:
            logger.warning(f"Failed to log activity: {str(log_error)}")
        
        logger.info(
            f"Job cancelled",
            extra={
                "user_id": str(current_user.id),
                "job_id": str(job_id)
            }
        )
        
        return result
        
    except Exception as e:
        logger.error(
            f"Failed to cancel job: {str(e)}",
            extra={
                "user_id": str(current_user.id),
                "job_id": str(job_id)
            },
            exc_info=True
        )
        raise


# ============================================
# QUEUE DEPTH
# ============================================

@router.get(
    "/queue/depth",
    response_model=QueueDepthResponse,
    summary="Get Queue Depth",
    description="""
    Get current processing queue statistics.
    
    **Returns:**
    - Number of queued jobs
    - Number of jobs currently processing
    - Total active jobs
    
    **Use Case:**
    - Monitor system load
    - Estimate wait time
    - Load balancing decisions
    """
)
async def get_queue_depth(
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_active_user),
):
    """Get processing queue depth."""
    
    processing_service = ProcessingService(db)
    result = await processing_service.get_queue_depth()
    
    # Update metrics
    from app.financial.financial_metrics import processing_queue_depth
    processing_queue_depth.set(result.total_active)
    
    return result
