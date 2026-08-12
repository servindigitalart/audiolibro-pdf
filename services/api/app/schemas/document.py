"""
Document Schemas
================
Pydantic schemas for document upload, retrieval, and lifecycle management.
"""

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


# ============================================
# PREFLIGHT ANALYSIS SCHEMA
# ============================================

class AvailableVoiceSchema(BaseModel):
    voice_id: str
    display_name: str


class PreflightResult(BaseModel):
    """Lightweight pre-conversion analysis returned with the upload response."""

    language: str = Field(..., description="ISO 639-1 language code")
    language_name: str = Field(..., description="Human-readable language name")
    voice_id: str = Field(..., description="Selected TTS voice ID")
    voice_display_name: str = Field(..., description="Human-readable voice label")
    available_voices: list[AvailableVoiceSchema] = Field(
        default_factory=list,
        description="Voices selectable for this language"
    )
    estimated_characters: int = Field(..., description="Estimated character count")
    estimated_chapters: int = Field(..., description="Estimated chapter count")
    estimated_duration_seconds: int = Field(..., description="Estimated audiobook duration in seconds")
    estimated_processing_minutes: float = Field(..., description="Estimated processing time in minutes")
    fits_current_plan: bool = Field(..., description="True if character count fits within current plan quota")
    quota_exceeded: bool = Field(..., description="True if this document would exceed the quota")
    chars_limit: int = Field(..., description="Monthly character limit for current plan")
    chars_used: int = Field(..., description="Characters used this billing period")
    chars_remaining_before: int = Field(..., description="Characters remaining before this upload")
    chars_remaining_after: int = Field(..., description="Characters remaining after conversion (can be negative)")
    plan_tier: str = Field(..., description="Current plan tier (FREE | BASIC | PRO | ENTERPRISE)")
    plan_display_name: str = Field(..., description="Human-readable plan name")
    estimated_provider_cost_usd: float = Field(
        0.0,
        description="Estimated provider cost to produce this audiobook. An estimate for transparency, not a charge.",
    )


# ============================================
# REQUEST SCHEMAS
# ============================================

class DocumentUploadResponse(BaseModel):
    """Response after successful document upload."""

    id: UUID = Field(..., description="Document unique identifier")
    user_id: UUID = Field(..., description="Owner user ID")
    filename: str = Field(..., description="Sanitized filename")
    original_filename: str = Field(..., description="Original upload filename")
    file_size_bytes: int = Field(..., description="File size in bytes")
    file_size_mb: float = Field(..., description="File size in megabytes")
    mime_type: str = Field(..., description="MIME type")
    upload_status: str = Field(..., description="Upload status")
    processing_status: str = Field(..., description="Processing status")
    page_count: Optional[int] = Field(None, description="Number of pages (if extracted)")
    character_estimate: Optional[int] = Field(None, description="Estimated character count")
    language_detected: Optional[str] = Field(None, description="Detected language code")
    checksum_sha256: str = Field(..., description="SHA256 checksum")
    created_at: datetime = Field(..., description="Upload timestamp")

    # Duplicate detection fields — False / None on a fresh upload
    is_duplicate: bool = Field(False, description="True when this PDF was already uploaded by this user")
    duplicate_message: Optional[str] = Field(None, description="Human-readable explanation for the duplicate")
    can_reprocess: bool = Field(False, description="True when the duplicate failed and can be reprocessed")

    # Preflight analysis — populated when preflight_only=True on upload
    preflight: Optional[PreflightResult] = Field(None, description="Pre-conversion analysis (language, duration, quota)")
    
    class Config:
        from_attributes = True
        json_schema_extra = {
            "example": {
                "id": "123e4567-e89b-12d3-a456-426614174000",
                "user_id": "123e4567-e89b-12d3-a456-426614174001",
                "filename": "document_123e4567.pdf",
                "original_filename": "My Research Paper.pdf",
                "file_size_bytes": 2548736,
                "file_size_mb": 2.43,
                "mime_type": "application/pdf",
                "upload_status": "uploaded",
                "processing_status": "not_started",
                "page_count": 45,
                "character_estimate": 125000,
                "language_detected": "en",
                "checksum_sha256": "a1b2c3d4...",
                "created_at": "2026-02-11T14:30:00Z"
            }
        }


class DocumentListItem(BaseModel):
    """Document list item with essential metadata."""

    id: UUID
    filename: str
    original_filename: str
    display_title: Optional[str] = None
    author: Optional[str] = None
    file_size_bytes: int
    file_size_mb: float
    mime_type: str
    upload_status: str
    processing_status: str
    page_count: Optional[int] = None
    language_detected: Optional[str] = None
    cover_url: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True


class DocumentListResponse(BaseModel):
    """Paginated document list response."""
    
    documents: list[DocumentListItem] = Field(..., description="List of documents")
    total: int = Field(..., description="Total number of documents")
    page: int = Field(..., description="Current page number")
    page_size: int = Field(..., description="Items per page")
    has_more: bool = Field(..., description="Whether more pages exist")
    
    class Config:
        json_schema_extra = {
            "example": {
                "documents": [
                    {
                        "id": "123e4567-e89b-12d3-a456-426614174000",
                        "filename": "document_123e4567.pdf",
                        "original_filename": "Book Chapter 1.pdf",
                        "file_size_bytes": 1024000,
                        "file_size_mb": 0.98,
                        "mime_type": "application/pdf",
                        "upload_status": "uploaded",
                        "processing_status": "completed",
                        "page_count": 15,
                        "language_detected": "en",
                        "created_at": "2026-02-11T14:00:00Z",
                        "updated_at": "2026-02-11T14:05:00Z"
                    }
                ],
                "total": 42,
                "page": 1,
                "page_size": 20,
                "has_more": True
            }
        }


class DocumentDetail(BaseModel):
    """Complete document details including all metadata and timestamps."""

    id: UUID
    user_id: UUID
    filename: str
    original_filename: str
    display_title: Optional[str] = None
    file_size_bytes: int
    file_size_mb: float
    mime_type: str
    storage_path: str
    checksum_sha256: str
    
    # Status
    upload_status: str
    processing_status: str
    
    # Metadata
    page_count: Optional[int] = None
    character_estimate: Optional[int] = None
    language_detected: Optional[str] = None
    
    # Error tracking
    error_message: Optional[str] = None
    
    # Timestamps
    created_at: datetime
    updated_at: datetime
    uploaded_at: Optional[datetime] = None
    processing_started_at: Optional[datetime] = None
    processing_completed_at: Optional[datetime] = None
    
    # Book Intelligence metadata
    author: Optional[str] = Field(None, description="Detected or user-provided author name")
    subtitle: Optional[str] = Field(None, description="Book subtitle")
    isbn: Optional[str] = Field(None, description="ISBN-13 or ISBN-10")
    metadata_source: Optional[str] = Field(None, description="Source: local, google_books, open_library, manual")
    metadata_confidence: Optional[float] = Field(None, description="Metadata confidence score 0.0–1.0")

    # Cover art
    cover_url: Optional[str] = Field(None, description="Presigned URL for custom cover image")

    # Audio output
    audio_url: Optional[str] = Field(None, description="Presigned URL for audiobook playback")
    audio_duration_seconds: Optional[int] = Field(None, description="Total duration in seconds")
    audio_file_size_bytes: Optional[int] = Field(None, description="Final audiobook file size")

    # Computed properties
    is_ready_for_processing: bool = Field(..., description="Ready to be queued")
    is_processing_complete: bool = Field(..., description="Processing finished")
    has_failed: bool = Field(..., description="Failed at any stage")
    
    class Config:
        from_attributes = True


class DocumentDownloadURL(BaseModel):
    """Pre-signed URL for secure document download."""
    
    document_id: UUID = Field(..., description="Document identifier")
    download_url: str = Field(..., description="Pre-signed S3 URL")
    expires_in_seconds: int = Field(..., description="URL expiration time")
    expires_at: datetime = Field(..., description="URL expiration timestamp")
    filename: str = Field(..., description="Suggested download filename")
    
    class Config:
        json_schema_extra = {
            "example": {
                "document_id": "123e4567-e89b-12d3-a456-426614174000",
                "download_url": "https://spaces.digitalocean.com/...",
                "expires_in_seconds": 3600,
                "expires_at": "2026-02-11T15:30:00Z",
                "filename": "My Document.pdf"
            }
        }


class DocumentDeleteResponse(BaseModel):
    """Response after document deletion."""
    
    document_id: UUID = Field(..., description="Deleted document ID")
    filename: str = Field(..., description="Deleted filename")
    deleted_from_storage: bool = Field(..., description="Whether file was removed from S3")
    message: str = Field(..., description="Confirmation message")
    
    class Config:
        json_schema_extra = {
            "example": {
                "document_id": "123e4567-e89b-12d3-a456-426614174000",
                "filename": "document_123e4567.pdf",
                "deleted_from_storage": True,
                "message": "Document deleted successfully"
            }
        }


# ============================================
# METADATA EXTRACTION SCHEMAS (Internal)
# ============================================

class DocumentMetadata(BaseModel):
    """Lightweight metadata extracted during upload (internal use)."""
    
    page_count: Optional[int] = None
    character_estimate: Optional[int] = None
    language_detected: Optional[str] = None
    extraction_successful: bool = True
    extraction_error: Optional[str] = None
    
    class Config:
        json_schema_extra = {
            "example": {
                "page_count": 45,
                "character_estimate": 125000,
                "language_detected": "en",
                "extraction_successful": True,
                "extraction_error": None
            }
        }


# ============================================
# ERROR SCHEMAS
# ============================================

class DocumentUploadError(BaseModel):
    """Error response for upload failures."""
    
    error: str = Field(..., description="Error type")
    detail: str = Field(..., description="Error details")
    filename: Optional[str] = Field(None, description="Affected filename")
    
    class Config:
        json_schema_extra = {
            "example": {
                "error": "file_too_large",
                "detail": "File size exceeds maximum allowed size of 50MB",
                "filename": "large_document.pdf"
            }
        }
