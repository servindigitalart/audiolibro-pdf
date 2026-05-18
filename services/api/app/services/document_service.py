"""
Document Service
================
Business logic layer for document lifecycle management.
Handles upload orchestration, metadata extraction, and document operations.
"""

import logging
from datetime import datetime, timedelta
from typing import Optional, List, Tuple
from uuid import UUID
import uuid

import fitz  # PyMuPDF
from langdetect import detect, LangDetectException
from fastapi import UploadFile, HTTPException, status
from sqlalchemy import select, func, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.document import Document, UploadStatus, ProcessingStatus
from app.db.models.user import User
from app.schemas.document import (
    DocumentUploadResponse,
    DocumentListResponse,
    DocumentListItem,
    DocumentDetail,
    DocumentDownloadURL,
    DocumentDeleteResponse,
    DocumentMetadata,
)
from app.services.storage_service import get_storage_service
from app.utils.file_validation import (
    validate_upload_file,
    sanitize_filename,
    get_max_file_size_mb,
)

logger = logging.getLogger(__name__)


# ============================================
# DOCUMENT SERVICE
# ============================================

class DocumentService:
    """
    Document lifecycle management service.
    
    Responsibilities:
    - Orchestrate document upload pipeline
    - Extract lightweight metadata (pages, chars, language)
    - Manage document CRUD operations
    - Generate secure download URLs
    - Handle cleanup and deletion
    """
    
    def __init__(self, db: AsyncSession):
        """
        Initialize document service.
        
        Args:
            db: Database session
        """
        self.db = db
        self.storage = get_storage_service()
    
    async def _extract_metadata(self, file: UploadFile) -> DocumentMetadata:
        """
        Extract lightweight metadata from PDF (synchronous, fast).
        
        Extracts:
        - Page count
        - Character estimate (first 10 pages sample)
        - Language detection (first page sample)
        
        Args:
            file: Uploaded PDF file
            
        Returns:
            DocumentMetadata with extracted information
        """
        try:
            # Reset file pointer
            file.file.seek(0)
            
            # Read file into memory (already validated for size)
            pdf_bytes = file.file.read()
            file.file.seek(0)
            
            # Open PDF with PyMuPDF
            doc = fitz.open(stream=pdf_bytes, filetype="pdf")
            
            # Extract page count
            page_count = doc.page_count
            
            # Estimate character count (sample first 10 pages)
            sample_pages = min(10, page_count)
            total_chars = 0
            sample_text = ""
            
            for page_num in range(sample_pages):
                page = doc[page_num]
                text = page.get_text()
                total_chars += len(text)
                
                # Collect first page text for language detection
                if page_num == 0:
                    sample_text = text[:1000]  # First 1000 chars
            
            # Extrapolate character count
            if sample_pages > 0:
                chars_per_page = total_chars / sample_pages
                character_estimate = int(chars_per_page * page_count)
            else:
                character_estimate = 0
            
            # Detect language from first page
            language_detected = None
            if sample_text.strip():
                try:
                    language_detected = detect(sample_text)
                except LangDetectException:
                    logger.warning("Language detection failed for document")
            
            doc.close()
            
            return DocumentMetadata(
                page_count=page_count,
                character_estimate=character_estimate,
                language_detected=language_detected,
                extraction_successful=True,
                extraction_error=None
            )
            
        except Exception as e:
            logger.error(
                f"Metadata extraction failed: {str(e)}",
                exc_info=True
            )
            return DocumentMetadata(
                page_count=None,
                character_estimate=None,
                language_detected=None,
                extraction_successful=False,
                extraction_error=str(e)
            )
    
    async def upload_document(
        self,
        file: UploadFile,
        user: User,
    ) -> DocumentUploadResponse:
        """
        Complete document upload pipeline.
        
        Steps:
        1. Validate file (size, type, magic bytes)
        2. Compute checksum
        3. Extract lightweight metadata
        4. Create database record
        5. Upload to storage
        6. Update database status
        
        Args:
            file: Uploaded PDF file
            user: Document owner
            
        Returns:
            DocumentUploadResponse with upload details
            
        Raises:
            HTTPException: If upload fails at any stage
        """
        document_id = uuid.uuid4()
        
        try:
            # Step 1: Validate file
            logger.info(
                f"Starting document upload",
                extra={
                    'user_id': str(user.id),
                    'document_id': str(document_id),
                    'uploaded_filename': file.filename
                }
            )
            
            max_size = int(get_max_file_size_mb() * 1024 * 1024)
            file_size, mime_type, checksum = await validate_upload_file(file, max_size)
            
            # Step 2: Sanitize filename
            sanitized = sanitize_filename(file.filename or "document.pdf")
            original_filename = file.filename or "document.pdf"
            
            # Step 3: Extract metadata
            metadata = await self._extract_metadata(file)
            
            # Step 4: Create database record (PENDING status)
            storage_path = f"documents/{user.id}/{document_id}.pdf"
            
            document = Document(
                id=document_id,
                user_id=user.id,
                filename=f"document_{document_id}.pdf",
                original_filename=original_filename,
                file_size_bytes=file_size,
                mime_type=mime_type,
                storage_path=storage_path,
                checksum_sha256=checksum,
                upload_status=UploadStatus.PENDING,
                processing_status=ProcessingStatus.NOT_STARTED,
                page_count=metadata.page_count,
                character_estimate=metadata.character_estimate,
                language_detected=metadata.language_detected,
            )
            
            self.db.add(document)
            await self.db.commit()
            await self.db.refresh(document)
            
            # Step 5: Upload to storage
            try:
                storage_metadata = {
                    'original-filename': original_filename,
                    'page-count': str(metadata.page_count) if metadata.page_count else '',
                    'language': metadata.language_detected or '',
                }
                
                await self.storage.upload_document(
                    file=file,
                    user_id=user.id,
                    document_id=document_id,
                    checksum=checksum,
                    metadata=storage_metadata
                )
                
                # Step 6: Update status to UPLOADED
                document.upload_status = UploadStatus.UPLOADED
                document.uploaded_at = datetime.utcnow()
                await self.db.commit()
                await self.db.refresh(document)
                
                logger.info(
                    f"Document uploaded successfully",
                    extra={
                        'user_id': str(user.id),
                        'document_id': str(document_id),
                        'file_size': file_size,
                        'page_count': metadata.page_count
                    }
                )
                
                return DocumentUploadResponse(
                    id=document.id,
                    user_id=document.user_id,
                    filename=document.filename,
                    original_filename=document.original_filename,
                    file_size_bytes=document.file_size_bytes,
                    file_size_mb=document.file_size_mb,
                    mime_type=document.mime_type,
                    upload_status=document.upload_status.value,
                    processing_status=document.processing_status.value,
                    page_count=document.page_count,
                    character_estimate=document.character_estimate,
                    language_detected=document.language_detected,
                    checksum_sha256=document.checksum_sha256,
                    created_at=document.created_at,
                )
                
            except Exception as storage_error:
                # Rollback database record on storage failure
                document.upload_status = UploadStatus.FAILED
                document.error_message = f"Storage upload failed: {str(storage_error)}"
                await self.db.commit()
                
                logger.error(
                    f"Storage upload failed",
                    extra={
                        'user_id': str(user.id),
                        'document_id': str(document_id),
                        'error': str(storage_error)
                    }
                )
                
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Failed to upload document to storage"
                )
                
        except HTTPException:
            # Re-raise HTTP exceptions (validation errors, etc.)
            raise
        except Exception as e:
            logger.error(
                f"Document upload failed: {str(e)}",
                extra={
                    'user_id': str(user.id),
                    'uploaded_filename': file.filename
                },
                exc_info=True
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Document upload failed: {str(e)}"
            )
    
    async def list_documents(
        self,
        user: User,
        page: int = 1,
        page_size: int = 20,
        processing_status: Optional[ProcessingStatus] = None
    ) -> DocumentListResponse:
        """
        List user's documents with pagination.
        
        Args:
            user: Document owner
            page: Page number (1-indexed)
            page_size: Items per page
            processing_status: Optional filter by processing status
            
        Returns:
            Paginated document list
        """
        offset = (page - 1) * page_size
        
        # Build query
        query = select(Document).where(Document.user_id == user.id)
        
        if processing_status:
            query = query.where(Document.processing_status == processing_status)
        
        query = query.order_by(desc(Document.created_at))
        
        # Get total count
        count_query = select(func.count()).select_from(Document).where(Document.user_id == user.id)
        if processing_status:
            count_query = count_query.where(Document.processing_status == processing_status)
        
        total_result = await self.db.execute(count_query)
        total = total_result.scalar_one()
        
        # Get paginated results
        query = query.offset(offset).limit(page_size)
        result = await self.db.execute(query)
        documents = result.scalars().all()
        
        # Build response
        items = [
            DocumentListItem(
                id=doc.id,
                filename=doc.filename,
                original_filename=doc.original_filename,
                file_size_bytes=doc.file_size_bytes,
                file_size_mb=doc.file_size_mb,
                mime_type=doc.mime_type,
                upload_status=doc.upload_status.value,
                processing_status=doc.processing_status.value,
                page_count=doc.page_count,
                language_detected=doc.language_detected,
                created_at=doc.created_at,
                updated_at=doc.updated_at,
            )
            for doc in documents
        ]
        
        has_more = (offset + len(items)) < total
        
        return DocumentListResponse(
            documents=items,
            total=total,
            page=page,
            page_size=page_size,
            has_more=has_more
        )
    
    async def get_document(
        self,
        document_id: UUID,
        user: User
    ) -> DocumentDetail:
        """
        Get detailed document information.
        
        Args:
            document_id: Document identifier
            user: Requesting user
            
        Returns:
            Complete document details
            
        Raises:
            HTTPException: If document not found or access denied
        """
        query = select(Document).where(
            Document.id == document_id,
            Document.user_id == user.id
        )
        result = await self.db.execute(query)
        document = result.scalar_one_or_none()
        
        if not document:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Document not found"
            )
        
        return DocumentDetail(
            id=document.id,
            user_id=document.user_id,
            filename=document.filename,
            original_filename=document.original_filename,
            file_size_bytes=document.file_size_bytes,
            file_size_mb=document.file_size_mb,
            mime_type=document.mime_type,
            storage_path=document.storage_path,
            checksum_sha256=document.checksum_sha256,
            upload_status=document.upload_status.value,
            processing_status=document.processing_status.value,
            page_count=document.page_count,
            character_estimate=document.character_estimate,
            language_detected=document.language_detected,
            error_message=document.error_message,
            created_at=document.created_at,
            updated_at=document.updated_at,
            uploaded_at=document.uploaded_at,
            processing_started_at=document.processing_started_at,
            processing_completed_at=document.processing_completed_at,
            is_ready_for_processing=document.is_ready_for_processing,
            is_processing_complete=document.is_processing_complete,
            has_failed=document.has_failed,
        )
    
    async def generate_download_url(
        self,
        document_id: UUID,
        user: User
    ) -> DocumentDownloadURL:
        """
        Generate secure pre-signed download URL.
        
        Args:
            document_id: Document identifier
            user: Requesting user
            
        Returns:
            Pre-signed download URL with expiry
            
        Raises:
            HTTPException: If document not found or not uploaded
        """
        # Verify ownership and upload status
        document = await self.get_document(document_id, user)
        
        if document.upload_status != UploadStatus.UPLOADED.value:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Document is not available for download"
            )
        
        # Generate pre-signed URL (1 hour expiry)
        expiry_seconds = 3600
        download_url = await self.storage.generate_download_url(
            storage_path=document.storage_path,
            filename=document.original_filename,
            expiry_seconds=expiry_seconds
        )
        
        return DocumentDownloadURL(
            document_id=document.id,
            download_url=download_url,
            expires_in_seconds=expiry_seconds,
            expires_at=datetime.utcnow() + timedelta(seconds=expiry_seconds),
            filename=document.original_filename
        )
    
    async def delete_document(
        self,
        document_id: UUID,
        user: User
    ) -> DocumentDeleteResponse:
        """
        Delete document from database and storage.
        
        Args:
            document_id: Document identifier
            user: Requesting user
            
        Returns:
            Deletion confirmation
            
        Raises:
            HTTPException: If document not found
        """
        # Verify ownership
        query = select(Document).where(
            Document.id == document_id,
            Document.user_id == user.id
        )
        result = await self.db.execute(query)
        document = result.scalar_one_or_none()
        
        if not document:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Document not found"
            )
        
        filename = document.filename
        storage_path = document.storage_path
        
        # Delete from storage first
        storage_deleted = False
        if document.upload_status == UploadStatus.UPLOADED:
            storage_deleted = await self.storage.delete_document(storage_path)
        
        # Delete from database
        await self.db.delete(document)
        await self.db.commit()
        
        logger.info(
            f"Document deleted",
            extra={
                'user_id': str(user.id),
                'document_id': str(document_id),
                'storage_deleted': storage_deleted
            }
        )
        
        return DocumentDeleteResponse(
            document_id=document_id,
            filename=filename,
            deleted_from_storage=storage_deleted,
            message="Document deleted successfully"
        )
