"""
Document Upload & Management Router
====================================
BLOCK 5A: Document Upload & Storage Layer

API endpoints for secure PDF document management:
- Upload documents with validation
- List user documents with pagination
- Get document details
- Generate secure download URLs
- Delete documents

Security:
- All endpoints require authentication
- User ownership enforced
- Private storage with pre-signed URLs only
- Rate limiting applied

Integration:
- Cost governance: Quota checks before upload
- Observability: Prometheus metrics + structured logging
- Activity logging: All operations tracked
"""

import logging
import time
from typing import Optional
from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    File,
    UploadFile,
    HTTPException,
    status,
    Query,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth_dependencies import get_current_active_user
from app.db.models.user import User
from app.db.models.document import ProcessingStatus
from app.db.session import get_async_db
from app.schemas.document import (
    DocumentUploadResponse,
    DocumentListResponse,
    DocumentDetail,
    DocumentDownloadURL,
    DocumentDeleteResponse,
)
from app.db.models.processing_job import ProcessingJob as ProcessingJobModel, JobStatus
from app.services.document_service import DocumentService
from app.services.account_service import AccountService
from app.services.processing_service import ProcessingService
from app.schemas.processing import ProcessDocumentRequest
from app.financial.financial_metrics import (
    documents_uploaded_total,
    documents_failed_total,
    documents_bytes_uploaded,
    upload_latency_seconds,
    documents_deleted_total,
    download_url_generated_total,
)
from app.utils.file_validation import get_max_file_size_mb

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/documents", tags=["documents"])


# ============================================
# UPLOAD ENDPOINT
# ============================================

@router.post(
    "/upload",
    response_model=DocumentUploadResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload PDF Document",
    description="""
    Upload a PDF document for processing.
    
    **Requirements:**
    - File must be a valid PDF
    - Maximum size: 50MB (configurable)
    - Must have available quota
    
    **Process:**
    1. Validates file integrity and format
    2. Extracts metadata (pages, characters, language)
    3. Uploads to secure private storage
    4. Returns document details
    
    **Notes:**
    - Document is not processed immediately
    - Use processing endpoints to queue for TTS conversion
    - All uploads are tracked for cost governance
    """
)
async def upload_document(
    file: UploadFile = File(..., description="PDF file to upload"),
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_active_user),
):
    """Upload a PDF document with validation and metadata extraction."""
    
    start_time = time.time()
    
    try:
        # Log upload attempt
        logger.info(
            f"Document upload initiated",
            extra={
                'user_id': str(current_user.id),
                'uploaded_filename': file.filename,
                'plan_tier': current_user.plan_tier
            }
        )
        
        # Check quota before processing
        account_service = AccountService(db)
        try:
            await account_service.log_activity(
                user_id=current_user.id,
                activity_type="document_upload",
                description=f"Uploading document: {file.filename}",
                metadata={"filename": file.filename}
            )
        except Exception as log_error:
            logger.warning(f"Failed to log activity: {str(log_error)}")
        
        # Upload document
        document_service = DocumentService(db)
        result = await document_service.upload_document(
            file=file,
            user=current_user
        )
        
        # Record metrics
        documents_uploaded_total.labels(
            user_plan_tier=current_user.plan_tier
        ).inc()
        
        documents_bytes_uploaded.labels(
            user_plan_tier=current_user.plan_tier
        ).inc(result.file_size_bytes)
        
        upload_duration = time.time() - start_time
        upload_latency_seconds.labels(operation="full_upload").observe(upload_duration)
        
        logger.info(
            f"Document uploaded successfully",
            extra={
                'user_id': str(current_user.id),
                'document_id': str(result.id),
                'file_size_mb': result.file_size_mb,
                'page_count': result.page_count,
                'duration_seconds': upload_duration
            }
        )

        # Auto-enqueue processing immediately after upload.
        # A failed enqueue is logged but does not fail the upload response —
        # the user can still see their document and retry from the dashboard.
        try:
            processing_service = ProcessingService(db)
            await processing_service.create_processing_job(
                document_id=result.id,
                user=current_user,
                request=ProcessDocumentRequest(),
            )
            logger.info(
                f"Processing job enqueued",
                extra={'document_id': str(result.id), 'user_id': str(current_user.id)}
            )
        except Exception as enqueue_err:
            # str(HTTPException) returns "" — always log .detail and the type explicitly.
            err_detail = getattr(enqueue_err, "detail", None) or repr(enqueue_err)
            logger.error(
                "[SONORO] auto_enqueue_failed document_id=%s user_id=%s "
                "error_type=%s error=%s",
                result.id, current_user.id,
                type(enqueue_err).__name__, err_detail,
                exc_info=True,
            )

        return result
        
    except HTTPException:
        # Re-raise validation errors
        documents_failed_total.labels(failure_reason="validation_error").inc()
        raise
        
    except Exception as e:
        documents_failed_total.labels(failure_reason="internal_error").inc()
        logger.error(
            f"Document upload failed: {str(e)}",
            extra={
                'user_id': str(current_user.id),
                'uploaded_filename': file.filename
            },
            exc_info=True
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Document upload failed. Please try again."
        )


# ============================================
# LIST ENDPOINT
# ============================================

@router.get(
    "/",
    response_model=DocumentListResponse,
    summary="List Documents",
    description="""
    Get paginated list of user's documents.
    
    **Features:**
    - Pagination support
    - Filter by processing status
    - Ordered by creation date (newest first)
    """
)
async def list_documents(
    page: int = Query(1, ge=1, description="Page number (1-indexed)"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
    processing_status: Optional[str] = Query(
        None,
        description="Filter by processing status"
    ),
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_active_user),
):
    """List user's documents with pagination and filtering."""
    
    # Parse processing status if provided
    status_filter = None
    if processing_status:
        try:
            status_filter = ProcessingStatus(processing_status)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid processing status: {processing_status}"
            )
    
    document_service = DocumentService(db)
    result = await document_service.list_documents(
        user=current_user,
        page=page,
        page_size=page_size,
        processing_status=status_filter
    )
    
    logger.info(
        f"Documents listed",
        extra={
            'user_id': str(current_user.id),
            'page': page,
            'total': result.total
        }
    )
    
    return result


# ============================================
# GET DETAIL ENDPOINT
# ============================================

@router.get(
    "/{document_id}",
    response_model=DocumentDetail,
    summary="Get Document Details",
    description="""
    Get complete details for a specific document.
    
    **Returns:**
    - All metadata and timestamps
    - Processing status
    - Error messages (if any)
    - Computed properties (ready for processing, etc.)
    """
)
async def get_document(
    document_id: UUID,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_active_user),
):
    """Get detailed document information."""
    
    document_service = DocumentService(db)
    result = await document_service.get_document(
        document_id=document_id,
        user=current_user
    )
    
    return result


# ============================================
# DOWNLOAD URL ENDPOINT
# ============================================

@router.get(
    "/{document_id}/download-url",
    response_model=DocumentDownloadURL,
    summary="Generate Download URL",
    description="""
    Generate a secure pre-signed URL for document download.
    
    **Security:**
    - URL expires after 1 hour
    - Only accessible by document owner
    - Private bucket access
    
    **Use Case:**
    - Direct download from client
    - Preview in browser
    - Share with authorized users
    """
)
async def generate_download_url(
    document_id: UUID,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_active_user),
):
    """Generate secure pre-signed download URL."""
    
    document_service = DocumentService(db)
    result = await document_service.generate_download_url(
        document_id=document_id,
        user=current_user
    )
    
    download_url_generated_total.inc()
    
    logger.info(
        f"Download URL generated",
        extra={
            'user_id': str(current_user.id),
            'document_id': str(document_id)
        }
    )
    
    return result


# ============================================
# DELETE ENDPOINT
# ============================================

@router.delete(
    "/{document_id}",
    response_model=DocumentDeleteResponse,
    summary="Delete Document",
    description="""
    Permanently delete a document.
    
    **Actions:**
    - Removes from database
    - Deletes from storage
    - Cannot be undone
    
    **Note:**
    - Associated processing results will also be deleted
    """
)
async def delete_document(
    document_id: UUID,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_active_user),
):
    """Delete document from database and storage."""
    
    document_service = DocumentService(db)
    result = await document_service.delete_document(
        document_id=document_id,
        user=current_user
    )
    
    documents_deleted_total.labels(
        user_plan_tier=current_user.plan_tier
    ).inc()
    
    # Log activity
    account_service = AccountService(db)
    try:
        await account_service.log_activity(
            user_id=current_user.id,
            activity_type="document_delete",
            description=f"Deleted document: {result.filename}",
            metadata={"document_id": str(document_id)}
        )
    except Exception as log_error:
        logger.warning(f"Failed to log activity: {str(log_error)}")
    
    logger.info(
        f"Document deleted",
        extra={
            'user_id': str(current_user.id),
            'document_id': str(document_id),
            'storage_deleted': result.deleted_from_storage
        }
    )
    
    return result


# ============================================
# PROCESSING JOB STATUS ENDPOINT
# ============================================

def _derive_stage(progress: int) -> str | None:
    """Map progress percentage to a frontend-friendly stage label."""
    if progress <= 20:
        return "analyzing"
    if progress <= 60:
        return "detecting_chapters"
    if progress <= 90:
        return "generating_audio"
    return "finalizing"


@router.get(
    "/{document_id}/job",
    summary="Get Processing Job for Document",
    description="Return the most recent processing job for a document, used by the upload UI to poll progress.",
)
async def get_document_job(
    document_id: UUID,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_active_user),
):
    """Return the latest processing job for a document, or 404 if none exists."""

    # Verify document ownership
    from app.db.models.document import Document as DocumentModel
    doc_result = await db.execute(
        select(DocumentModel).where(
            DocumentModel.id == document_id,
            DocumentModel.user_id == current_user.id,
        )
    )
    doc = doc_result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    # Find the most recent non-cancelled job for this document
    job_result = await db.execute(
        select(ProcessingJobModel)
        .where(
            ProcessingJobModel.document_id == document_id,
            ProcessingJobModel.status != JobStatus.CANCELLED,
        )
        .order_by(ProcessingJobModel.created_at.desc())
        .limit(1)
    )
    job = job_result.scalar_one_or_none()

    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No processing job found")

    progress = job.progress_percentage or 0
    status_str = job.status.value if hasattr(job.status, 'value') else str(job.status)

    return {
        "id":           str(job.id),
        "document_id":  str(job.document_id),
        "status":       status_str,
        "stage":        _derive_stage(progress) if status_str == "processing" else None,
        "progress":     progress,
        "started_at":   job.started_at.isoformat() if job.started_at else None,
        "completed_at": job.completed_at.isoformat() if job.completed_at else None,
        "error_message": job.error_message,
        "metadata": {
            "job_type":    job.job_type,
            "retry_count": job.retry_count,
        },
    }


# ============================================
# INFO ENDPOINT
# ============================================

@router.get(
    "/info/limits",
    summary="Get Upload Limits",
    description="Get current upload size limits and constraints"
)
async def get_upload_limits(
    current_user: User = Depends(get_current_active_user),
):
    """Get upload configuration and limits."""
    
    return {
        "max_file_size_mb": get_max_file_size_mb(),
        "max_file_size_bytes": int(get_max_file_size_mb() * 1024 * 1024),
        "allowed_mime_types": ["application/pdf"],
        "supported_formats": ["PDF"],
        "user_plan_tier": current_user.plan_tier,
    }
