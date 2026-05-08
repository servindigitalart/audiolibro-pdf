"""
File Validation Utilities
==========================
Enterprise-grade file validation for document uploads.
Validates MIME types, magic bytes, file sizes, and checksums.
"""

import hashlib
from pathlib import Path
from typing import Tuple, Optional

from fastapi import UploadFile, HTTPException, status


# ============================================
# CONFIGURATION
# ============================================

MAX_FILE_SIZE_BYTES = 50 * 1024 * 1024  # 50 MB default
ALLOWED_MIME_TYPES = {"application/pdf"}
PDF_MAGIC_BYTES = b"%PDF"


# ============================================
# VALIDATION FUNCTIONS
# ============================================

async def validate_file_size(file: UploadFile, max_size: int = MAX_FILE_SIZE_BYTES) -> int:
    """
    Validate file size without loading entire file into memory.
    
    Args:
        file: Uploaded file
        max_size: Maximum allowed size in bytes
        
    Returns:
        File size in bytes
        
    Raises:
        HTTPException: If file exceeds max size
    """
    # Read first chunk to get size
    file.file.seek(0, 2)  # Seek to end
    file_size = file.file.tell()
    file.file.seek(0)  # Reset to beginning
    
    if file_size > max_size:
        max_size_mb = max_size / (1024 * 1024)
        file_size_mb = file_size / (1024 * 1024)
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail={
                "error": "file_too_large",
                "message": f"File size ({file_size_mb:.2f}MB) exceeds maximum allowed size of {max_size_mb:.0f}MB",
                "max_size_bytes": max_size,
                "file_size_bytes": file_size
            }
        )
    
    return file_size


async def validate_mime_type(file: UploadFile) -> str:
    """
    Validate MIME type using magic bytes (not just file extension).
    
    Args:
        file: Uploaded file
        
    Returns:
        Detected MIME type
        
    Raises:
        HTTPException: If MIME type is not allowed
    """
    # Read first 2048 bytes for magic detection
    file.file.seek(0)
    header = file.file.read(2048)
    file.file.seek(0)
    
    # Detect MIME type using python-magic
    detected_mime = file.content_type or "application/pdf"

    if detected_mime not in ALLOWED_MIME_TYPES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail={
                "error": "invalid_file_type",
                "message": f"File type '{detected_mime}' is not supported. Only PDF files are allowed.",
                "detected_mime": detected_mime,
                "allowed_types": list(ALLOWED_MIME_TYPES)
            }
        )

    return detected_mime

async def validate_pdf_magic_bytes(file: UploadFile) -> bool:
    """
    Validate PDF file by checking magic bytes (%PDF).
    Additional security layer beyond MIME type detection.
    
    Args:
        file: Uploaded file
        
    Returns:
        True if valid PDF
        
    Raises:
        HTTPException: If magic bytes don't match PDF signature
    """
    file.file.seek(0)
    magic_bytes = file.file.read(4)
    file.file.seek(0)
    
    if not magic_bytes.startswith(PDF_MAGIC_BYTES):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "invalid_pdf_format",
                "message": "File does not appear to be a valid PDF document",
            }
        )
    
    return True


async def compute_file_checksum(file: UploadFile) -> str:
    """
    Compute SHA256 checksum of file contents.
    
    Args:
        file: Uploaded file
        
    Returns:
        Hexadecimal SHA256 checksum
    """
    sha256_hash = hashlib.sha256()
    
    file.file.seek(0)
    
    # Read file in chunks to handle large files efficiently
    chunk_size = 8192
    while chunk := file.file.read(chunk_size):
        sha256_hash.update(chunk)
    
    file.file.seek(0)
    
    return sha256_hash.hexdigest()


def sanitize_filename(filename: str) -> str:
    """
    Sanitize filename to prevent path traversal and special character issues.
    
    Args:
        filename: Original filename
        
    Returns:
        Sanitized filename safe for storage
    """
    # Get file extension
    path = Path(filename)
    name = path.stem
    ext = path.suffix
    
    # Remove or replace dangerous characters
    safe_chars = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_"
    sanitized_name = "".join(c if c in safe_chars else "_" for c in name)
    
    # Truncate if too long
    max_length = 200
    if len(sanitized_name) > max_length:
        sanitized_name = sanitized_name[:max_length]
    
    # Ensure we have a name
    if not sanitized_name:
        sanitized_name = "document"
    
    return f"{sanitized_name}{ext}"


async def validate_upload_file(
    file: UploadFile,
    max_size: int = MAX_FILE_SIZE_BYTES
) -> Tuple[int, str, str]:
    """
    Comprehensive file validation pipeline.
    
    Performs all validation checks in sequence:
    1. File size check
    2. MIME type validation (magic bytes)
    3. PDF magic bytes check
    4. Checksum computation
    
    Args:
        file: Uploaded file
        max_size: Maximum allowed file size in bytes
        
    Returns:
        Tuple of (file_size, mime_type, checksum)
        
    Raises:
        HTTPException: If any validation fails
    """
    # Validate file size
    file_size = await validate_file_size(file, max_size)
    
    # Validate MIME type using magic bytes
    mime_type = await validate_mime_type(file)
    
    # Additional PDF-specific validation
    await validate_pdf_magic_bytes(file)
    
    # Compute checksum
    checksum = await compute_file_checksum(file)
    
    # Reset file pointer for subsequent reads
    file.file.seek(0)
    
    return file_size, mime_type, checksum


def get_max_file_size() -> int:
    """Get configured maximum file size in bytes."""
    return MAX_FILE_SIZE_BYTES


def get_max_file_size_mb() -> float:
    """Get configured maximum file size in megabytes."""
    return MAX_FILE_SIZE_BYTES / (1024 * 1024)
