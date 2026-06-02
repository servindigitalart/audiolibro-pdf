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
    Body,
    Depends,
    File,
    Form,
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
from app.services.storage_service import get_storage_service
from app.services.preflight_service import PreflightService
from app.schemas.processing import ProcessDocumentRequest
from app.schemas.document import PreflightResult
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
    force_reprocess: bool = Form(False, description="Re-upload even if this PDF was already converted"),
    preflight_only: bool = Form(False, description="Return preflight analysis instead of auto-enqueuing processing"),
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
        
        # Upload document (duplicate check happens inside the service)
        document_service = DocumentService(db)
        result = await document_service.upload_document(
            file=file,
            user=current_user,
            force_reprocess=force_reprocess,
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

        # Preflight analysis: computed when preflight_only=True so the frontend
        # can show the analysis card before the user clicks "Start conversion".
        # Duplicates skip preflight — they already have a completed/failed job.
        preflight_data = None
        if preflight_only and not result.is_duplicate:
            try:
                from app.db.models.document import Document as _DocModel
                doc_result = await db.execute(
                    select(_DocModel).where(_DocModel.id == result.id)
                )
                doc_obj = doc_result.scalar_one_or_none()
                if doc_obj:
                    analysis = await PreflightService.analyze(
                        document=doc_obj,
                        user=current_user,
                        db=db,
                    )
                    preflight_data = PreflightResult(
                        language=analysis.language,
                        language_name=analysis.language_name,
                        voice_id=analysis.voice_id,
                        voice_display_name=analysis.voice_display_name,
                        available_voices=[
                            {"voice_id": v.voice_id, "display_name": v.display_name}
                            for v in analysis.available_voices
                        ],
                        estimated_characters=analysis.estimated_characters,
                        estimated_chapters=analysis.estimated_chapters,
                        estimated_duration_seconds=analysis.estimated_duration_seconds,
                        estimated_processing_minutes=analysis.estimated_processing_minutes,
                        fits_current_plan=analysis.fits_current_plan,
                        quota_exceeded=analysis.quota_exceeded,
                        chars_limit=analysis.chars_limit,
                        chars_used=analysis.chars_used,
                        chars_remaining_before=analysis.chars_remaining_before,
                        chars_remaining_after=analysis.chars_remaining_after,
                        plan_tier=analysis.plan_tier,
                        plan_display_name=analysis.plan_display_name,
                    )
                    result.preflight = preflight_data
            except Exception as pf_err:
                logger.warning(
                    "[SONORO] preflight_analysis_failed document_id=%s error=%s",
                    result.id, repr(pf_err),
                )

        # Auto-enqueue processing immediately after upload.
        # Skipped when preflight_only=True (user must click "Start conversion").
        # Skipped for duplicates — the existing job (or completed audiobook)
        # is already in the right state; no need to queue another run and
        # waste quota.  force_reprocess creates a fresh document row so
        # result.is_duplicate is always False in that branch.
        if not result.is_duplicate and not preflight_only:
            try:
                processing_service = ProcessingService(db)
                await processing_service.create_processing_job(
                    document_id=result.id,
                    user=current_user,
                    request=ProcessDocumentRequest(),
                )
                logger.info(
                    "[SONORO] processing_job_enqueued document_id=%s user_id=%s",
                    result.id, current_user.id,
                )
            except Exception as enqueue_err:
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
    
    logger.info(
        "[SONORO] library_query user_id=%s page=%d page_size=%d status_filter=%s",
        current_user.id, page, page_size, status_filter,
    )

    document_service = DocumentService(db)
    result = await document_service.list_documents(
        user=current_user,
        page=page,
        page_size=page_size,
        processing_status=status_filter
    )

    logger.info(
        "[SONORO] library_results user_id=%s count=%d total=%d",
        current_user.id, len(result.documents), result.total,
    )
    for doc in result.documents:
        logger.info(
            "[SONORO] document_serialized id=%s processing_status=%s upload_status=%s final_audio_path=%s",
            doc.id, doc.processing_status, doc.upload_status,
            bool(getattr(doc, 'final_audio_path', None)),
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
# TITLE RENAME ENDPOINT
# ============================================

from pydantic import BaseModel as _PydanticBase

class DocumentTitleRequest(_PydanticBase):
    display_title: str


@router.patch(
    "/{document_id}/title",
    summary="Rename Audiobook Title",
    description="Update the user-facing display title of a document (does not change the original filename).",
)
async def rename_document_title(
    document_id: UUID,
    body: DocumentTitleRequest,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_active_user),
):
    from app.db.models.document import Document as _DocModel

    doc_result = await db.execute(
        select(_DocModel).where(
            _DocModel.id == document_id,
            _DocModel.user_id == current_user.id,
        )
    )
    doc = doc_result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    title = body.display_title.strip()
    if not title:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Title cannot be empty")

    doc.display_title = title
    await db.commit()
    logger.info("[SONORO] document_renamed document_id=%s user_id=%s", document_id, current_user.id)
    return {"id": str(document_id), "display_title": doc.display_title}


# ============================================
# START PROCESSING ENDPOINT
# ============================================

@router.post(
    "/{document_id}/process",
    status_code=status.HTTP_201_CREATED,
    summary="Start Document Processing",
    description="Create a processing job for a document (called after user reviews preflight analysis).",
)
async def start_document_processing(
    document_id: UUID,
    body: Optional[ProcessDocumentRequest] = Body(default=None),
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_active_user),
):
    """Enqueue processing for a document that was uploaded with preflight_only=True.

    Body is optional — existing clients that send no body continue to work.
    """
    from app.db.models.document import Document as _DocModel

    doc_result = await db.execute(
        select(_DocModel).where(
            _DocModel.id == document_id,
            _DocModel.user_id == current_user.id,
        )
    )
    doc = doc_result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    request = body or ProcessDocumentRequest()
    logger.info(
        "[SONORO] processing_start_requested document_id=%s user_id=%s "
        "narration_style=%s voice_id_override=%s",
        document_id, current_user.id,
        request.narration_style or "default",
        request.voice_id or "auto",
    )

    processing_service = ProcessingService(db)
    job = await processing_service.create_processing_job(
        document_id=document_id,
        user=current_user,
        request=request,
    )
    logger.info(
        "[SONORO] processing_job_enqueued_via_start document_id=%s user_id=%s job_id=%s",
        document_id, current_user.id, job.id,
    )
    return {"job_id": str(job.id), "status": "queued"}


# ============================================
# RETRY ENDPOINT
# ============================================

@router.post(
    "/{document_id}/retry",
    status_code=status.HTTP_201_CREATED,
    summary="Retry Failed Document",
    description="Create a new processing job for a previously failed document.",
)
async def retry_document_processing(
    document_id: UUID,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_active_user),
):
    """Retry processing for a failed document.

    Resets failed state so create_processing_job can enqueue a fresh job.
    Safe to call on any document owned by the user that has a failed job —
    idempotent when the document is already in a terminal-but-clean state.
    """
    from app.db.models.document import Document as _DocModel

    doc_result = await db.execute(
        select(_DocModel).where(
            _DocModel.id == document_id,
            _DocModel.user_id == current_user.id,
        )
    )
    doc = doc_result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    # Reset failed processing state so _validate_document / _check_document_not_processing pass.
    if doc.processing_status == ProcessingStatus.FAILED:
        doc.processing_status = ProcessingStatus.NOT_STARTED
        doc.error_message = None
        await db.commit()

    logger.info(
        "[SONORO] retry_requested document_id=%s user_id=%s",
        document_id, current_user.id,
    )

    processing_service = ProcessingService(db)
    job = await processing_service.create_processing_job(
        document_id=document_id,
        user=current_user,
        request=ProcessDocumentRequest(),
    )
    logger.info(
        "[SONORO] retry_job_enqueued document_id=%s job_id=%s",
        document_id, job.id,
    )
    return {"job_id": str(job.id), "status": "queued"}


# ============================================
# PROCESSING JOB STATUS ENDPOINT
# ============================================

_STAGE_MAP = {
    "analyzing":        "analyzing",
    "chapter_detection": "detecting_chapters",
    "tts_generation":   "generating_audio",
    "final_assembly":   "finalizing",
    "upload_finalize":  "finalizing",
}


def _derive_stage(progress: int, current_stage: str | None = None) -> str | None:
    """Map stored current_stage (preferred) or progress % to a frontend step label."""
    if current_stage:
        return _STAGE_MAP.get(current_stage, "analyzing")
    # Fallback for jobs created before migration 020
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
    current_stage = job.current_stage if hasattr(job, "current_stage") else None

    # Estimated seconds remaining: derived from chunk throughput rate, not stored.
    # Uses started_at as the reference so it covers the full job elapsed time,
    # which slightly over-estimates during the analyzing/chapter-detection phases
    # but converges to accurate once TTS starts (the dominant cost).
    estimated_seconds_remaining = None
    completed = getattr(job, "completed_chunks", None) or 0
    total = getattr(job, "total_chunks", None) or 0
    if status_str == "processing" and completed > 0 and total > completed and job.started_at:
        from datetime import datetime as _dt
        elapsed = (_dt.utcnow() - job.started_at).total_seconds()
        rate = completed / max(elapsed, 1)  # chunks/sec
        if rate > 0:
            estimated_seconds_remaining = max(0, int((total - completed) / rate))

    return {
        "id":           str(job.id),
        "document_id":  str(job.document_id),
        "status":       status_str,
        "stage":        _derive_stage(progress, current_stage) if status_str == "processing" else None,
        "current_stage": current_stage,
        "progress":     progress,
        "completed_chunks": completed,
        "total_chunks":     total,
        "estimated_seconds_remaining": estimated_seconds_remaining,
        "started_at":   job.started_at.isoformat() if job.started_at else None,
        "completed_at": job.completed_at.isoformat() if job.completed_at else None,
        "error_message": job.error_message,
        "metadata": {
            "job_type":    job.job_type,
            "retry_count": job.retry_count,
        },
    }


# ============================================
# CHAPTERS ENDPOINT
# ============================================

@router.get(
    "/{document_id}/chapters",
    summary="Get Document Chapters",
    description="Return all chapters for a document with presigned audio URLs.",
)
async def get_document_chapters(
    document_id: UUID,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_active_user),
):
    """Return chapters with audio URLs; status is derived from audio availability."""
    from app.db.models.document import Document as DocumentModel
    from app.db.models.chapter import Chapter as ChapterModel

    doc_result = await db.execute(
        select(DocumentModel).where(
            DocumentModel.id == document_id,
            DocumentModel.user_id == current_user.id,
        )
    )
    doc = doc_result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    chapters_result = await db.execute(
        select(ChapterModel)
        .where(ChapterModel.document_id == document_id)
        .order_by(ChapterModel.order_index)
    )
    chapters = chapters_result.scalars().all()

    storage_service = get_storage_service()
    doc_status = doc.processing_status.value if hasattr(doc.processing_status, "value") else str(doc.processing_status)

    result = []
    for chapter in chapters:
        audio_url = None
        if chapter.audio_url:
            try:
                audio_url = await storage_service.generate_audio_url(
                    storage_path=chapter.audio_url,
                    expiry_seconds=3600,
                )
            except Exception as e:
                logger.warning(
                    "[SONORO] chapter_audio_url_failed chapter_id=%s error=%s",
                    chapter.id, e,
                )

        if audio_url:
            ch_status = "completed"
        elif doc_status in ("processing", "assembling", "finalizing"):
            ch_status = "processing"
        elif doc_status == "failed":
            ch_status = "failed"
        else:
            ch_status = "pending"

        result.append({
            "id": str(chapter.id),
            "document_id": str(chapter.document_id),
            "chapter_number": chapter.order_index + 1,
            "title": chapter.title,
            "start_page": chapter.start_page,
            "end_page": chapter.end_page,
            "confidence_score": chapter.confidence_score,
            "audio_url": audio_url,
            "duration_seconds": None,
            "status": ch_status,
        })

    return result


# ============================================
# CHAPTER MANAGEMENT ENDPOINTS
# ============================================

from pydantic import BaseModel as PydanticBaseModel

class ChapterRenameRequest(PydanticBaseModel):
    title: str


@router.patch(
    "/{document_id}/chapters/{chapter_id}",
    summary="Rename Chapter",
    description="Update the title of a chapter.",
)
async def rename_chapter(
    document_id: UUID,
    chapter_id: UUID,
    body: ChapterRenameRequest,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_active_user),
):
    from app.db.models.document import Document as DocumentModel
    from app.db.models.chapter import Chapter as ChapterModel

    # Verify document ownership
    doc_result = await db.execute(
        select(DocumentModel).where(
            DocumentModel.id == document_id,
            DocumentModel.user_id == current_user.id,
        )
    )
    if not doc_result.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    ch_result = await db.execute(
        select(ChapterModel).where(
            ChapterModel.id == chapter_id,
            ChapterModel.document_id == document_id,
        )
    )
    chapter = ch_result.scalar_one_or_none()
    if not chapter:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chapter not found")

    title = body.title.strip()
    if not title:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Title cannot be empty")

    chapter.title = title
    await db.commit()
    logger.info("[SONORO] chapter_renamed document_id=%s chapter_id=%s", document_id, chapter_id)
    return {"id": str(chapter.id), "title": chapter.title}


@router.delete(
    "/{document_id}/chapters/{chapter_id}",
    summary="Remove Chapter",
    description="Remove a chapter from a completed audiobook.",
)
async def delete_chapter(
    document_id: UUID,
    chapter_id: UUID,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_active_user),
):
    from app.db.models.document import Document as DocumentModel
    from app.db.models.chapter import Chapter as ChapterModel

    doc_result = await db.execute(
        select(DocumentModel).where(
            DocumentModel.id == document_id,
            DocumentModel.user_id == current_user.id,
        )
    )
    if not doc_result.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    ch_result = await db.execute(
        select(ChapterModel).where(
            ChapterModel.id == chapter_id,
            ChapterModel.document_id == document_id,
        )
    )
    chapter = ch_result.scalar_one_or_none()
    if not chapter:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chapter not found")

    await db.delete(chapter)
    await db.commit()
    logger.info("[SONORO] chapter_deleted document_id=%s chapter_id=%s", document_id, chapter_id)
    return {"deleted": True, "id": str(chapter_id)}


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
