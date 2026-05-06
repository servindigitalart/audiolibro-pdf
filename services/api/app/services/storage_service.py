"""
Storage Service
===============
Enterprise-grade document storage using DigitalOcean Spaces (S3-compatible).
Handles secure upload, download, and deletion of PDF documents.
"""

import logging
from datetime import datetime, timedelta
from typing import Optional, BinaryIO
from uuid import UUID

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError
from fastapi import HTTPException, status, UploadFile

from app.core.config import settings

logger = logging.getLogger(__name__)


# ============================================
# CONFIGURATION
# ============================================

class StorageConfig:
    """Storage configuration for DigitalOcean Spaces."""
    
    # DigitalOcean Spaces credentials (S3-compatible)
    SPACES_REGION = getattr(settings, 'spaces_region', 'nyc3')
    SPACES_BUCKET = getattr(settings, 'spaces_bucket', 'sonoro-documents')
    SPACES_ENDPOINT = getattr(settings, 'spaces_endpoint', f'https://{SPACES_REGION}.digitaloceanspaces.com')
    SPACES_ACCESS_KEY = getattr(settings, 'spaces_access_key', '')
    SPACES_SECRET_KEY = getattr(settings, 'spaces_secret_key', '')
    
    # Storage settings
    STORAGE_PREFIX = "documents"
    MAX_RETRIES = 3
    CONNECT_TIMEOUT = 10
    READ_TIMEOUT = 60
    PRESIGNED_URL_EXPIRY = 3600  # 1 hour
    
    # Content settings
    DEFAULT_CONTENT_TYPE = "application/pdf"
    CONTENT_DISPOSITION = "attachment"


# ============================================
# STORAGE SERVICE
# ============================================

class StorageService:
    """
    Enterprise storage service for document management.
    
    Features:
    - DigitalOcean Spaces (S3-compatible) backend
    - Private bucket with pre-signed URLs
    - Automatic retry logic
    - Structured storage paths
    - Metadata tagging
    - Graceful error handling
    """
    
    def __init__(self):
        """Initialize S3-compatible storage client."""
        self.config = StorageConfig()
        self.client = self._create_client()
        self.bucket = self.config.SPACES_BUCKET
        
    def _create_client(self):
        """Create boto3 S3 client configured for DigitalOcean Spaces."""
        try:
            return boto3.client(
                's3',
                region_name=self.config.SPACES_REGION,
                endpoint_url=self.config.SPACES_ENDPOINT,
                aws_access_key_id=self.config.SPACES_ACCESS_KEY,
                aws_secret_access_key=self.config.SPACES_SECRET_KEY,
                config=Config(
                    signature_version='s3v4',
                    retries={
                        'max_attempts': self.config.MAX_RETRIES,
                        'mode': 'adaptive'
                    },
                    connect_timeout=self.config.CONNECT_TIMEOUT,
                    read_timeout=self.config.READ_TIMEOUT,
                )
            )
        except Exception as e:
            logger.error(f"Failed to create storage client: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Storage service unavailable"
            )
    
    def _get_storage_path(self, user_id: UUID, document_id: UUID) -> str:
        """
        Generate structured storage path.
        Format: documents/{user_id}/{document_id}.pdf
        
        Args:
            user_id: Document owner ID
            document_id: Document unique ID
            
        Returns:
            Full S3 object key
        """
        return f"{self.config.STORAGE_PREFIX}/{user_id}/{document_id}.pdf"
    
    async def upload_document(
        self,
        file: UploadFile,
        user_id: UUID,
        document_id: UUID,
        checksum: str,
        metadata: Optional[dict] = None
    ) -> str:
        """
        Upload document to storage with metadata.
        
        Args:
            file: File to upload
            user_id: Document owner
            document_id: Document identifier
            checksum: SHA256 checksum for integrity
            metadata: Optional metadata tags
            
        Returns:
            Storage path (S3 key)
            
        Raises:
            HTTPException: If upload fails
        """
        storage_path = self._get_storage_path(user_id, document_id)
        
        try:
            # Prepare metadata
            upload_metadata = {
                'user-id': str(user_id),
                'document-id': str(document_id),
                'checksum-sha256': checksum,
                'upload-timestamp': datetime.utcnow().isoformat(),
            }
            
            if metadata:
                upload_metadata.update(metadata)
            
            # Reset file pointer
            file.file.seek(0)
            
            # Upload with metadata
            self.client.upload_fileobj(
                file.file,
                self.bucket,
                storage_path,
                ExtraArgs={
                    'ContentType': self.config.DEFAULT_CONTENT_TYPE,
                    'Metadata': upload_metadata,
                    'ACL': 'private',  # Ensure private access
                }
            )
            
            logger.info(
                f"Document uploaded successfully",
                extra={
                    'user_id': str(user_id),
                    'document_id': str(document_id),
                    'storage_path': storage_path,
                    'checksum': checksum
                }
            )
            
            return storage_path
            
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', 'Unknown')
            logger.error(
                f"Storage upload failed: {error_code}",
                extra={
                    'user_id': str(user_id),
                    'document_id': str(document_id),
                    'error': str(e)
                }
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to upload document to storage"
            )
        except Exception as e:
            logger.error(
                f"Unexpected upload error: {str(e)}",
                extra={
                    'user_id': str(user_id),
                    'document_id': str(document_id)
                }
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Document upload failed"
            )
    
    async def generate_download_url(
        self,
        storage_path: str,
        filename: str,
        expiry_seconds: int = None
    ) -> str:
        """
        Generate pre-signed URL for secure document download.
        
        Args:
            storage_path: S3 object key
            filename: Suggested download filename
            expiry_seconds: URL expiration time (default: 1 hour)
            
        Returns:
            Pre-signed download URL
            
        Raises:
            HTTPException: If URL generation fails
        """
        if expiry_seconds is None:
            expiry_seconds = self.config.PRESIGNED_URL_EXPIRY
        
        try:
            url = self.client.generate_presigned_url(
                'get_object',
                Params={
                    'Bucket': self.bucket,
                    'Key': storage_path,
                    'ResponseContentDisposition': f'attachment; filename="{filename}"',
                    'ResponseContentType': self.config.DEFAULT_CONTENT_TYPE,
                },
                ExpiresIn=expiry_seconds
            )
            
            logger.info(
                f"Generated download URL",
                extra={
                    'storage_path': storage_path,
                    'expiry_seconds': expiry_seconds
                }
            )
            
            return url
            
        except ClientError as e:
            logger.error(
                f"Failed to generate download URL: {str(e)}",
                extra={'storage_path': storage_path}
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to generate download URL"
            )
    
    async def delete_document(self, storage_path: str) -> bool:
        """
        Delete document from storage.
        
        Args:
            storage_path: S3 object key
            
        Returns:
            True if deletion successful, False otherwise
        """
        try:
            self.client.delete_object(
                Bucket=self.bucket,
                Key=storage_path
            )
            
            logger.info(
                f"Document deleted from storage",
                extra={'storage_path': storage_path}
            )
            
            return True
            
        except ClientError as e:
            logger.error(
                f"Failed to delete document: {str(e)}",
                extra={'storage_path': storage_path}
            )
            return False
        except Exception as e:
            logger.error(
                f"Unexpected deletion error: {str(e)}",
                extra={'storage_path': storage_path}
            )
            return False
    
    async def document_exists(self, storage_path: str) -> bool:
        """
        Check if document exists in storage.
        
        Args:
            storage_path: S3 object key
            
        Returns:
            True if document exists
        """
        try:
            self.client.head_object(
                Bucket=self.bucket,
                Key=storage_path
            )
            return True
        except ClientError:
            return False
    
    async def get_document_metadata(self, storage_path: str) -> Optional[dict]:
        """
        Retrieve document metadata from storage.
        
        Args:
            storage_path: S3 object key
            
        Returns:
            Metadata dictionary or None if not found
        """
        try:
            response = self.client.head_object(
                Bucket=self.bucket,
                Key=storage_path
            )
            return response.get('Metadata', {})
        except ClientError as e:
            logger.warning(
                f"Failed to retrieve metadata: {str(e)}",
                extra={'storage_path': storage_path}
            )
            return None
    
    async def upload_audio(
        self,
        audio_data: bytes,
        user_id: UUID,
        document_id: UUID,
        filename: str = "full.mp3",
        metadata: Optional[dict] = None
    ) -> str:
        """
        Upload generated audio file to storage.
        
        BLOCK 6A: Audio storage for TTS-generated files.
        Path format: audio/{user_id}/{document_id}/full.mp3
        
        Args:
            audio_data: MP3 audio bytes
            user_id: User who owns the document
            document_id: Document identifier
            filename: Audio filename (default: full.mp3)
            metadata: Optional metadata tags
            
        Returns:
            Storage path (S3 key)
            
        Raises:
            HTTPException: If upload fails
        """
        storage_path = f"audio/{user_id}/{document_id}/{filename}"
        
        try:
            # Prepare metadata
            upload_metadata = {
                'user-id': str(user_id),
                'document-id': str(document_id),
                'upload-timestamp': datetime.utcnow().isoformat(),
                'content-type': 'audio/mpeg',
            }
            
            if metadata:
                upload_metadata.update(metadata)
            
            # Upload audio file
            self.client.put_object(
                Bucket=self.bucket,
                Key=storage_path,
                Body=audio_data,
                ContentType='audio/mpeg',
                Metadata=upload_metadata,
                ACL='private',
            )
            
            logger.info(
                f"Audio uploaded successfully",
                extra={
                    'user_id': str(user_id),
                    'document_id': str(document_id),
                    'storage_path': storage_path,
                    'audio_size_bytes': len(audio_data)
                }
            )
            
            return storage_path
            
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', 'Unknown')
            logger.error(
                f"Audio upload failed: {error_code}",
                extra={
                    'user_id': str(user_id),
                    'document_id': str(document_id),
                    'error': str(e)
                }
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to upload audio to storage"
            )
        except Exception as e:
            logger.error(
                f"Unexpected audio upload error: {str(e)}",
                extra={
                    'user_id': str(user_id),
                    'document_id': str(document_id)
                }
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Audio upload failed"
            )


# ============================================
# SINGLETON INSTANCE
# ============================================

_storage_service: Optional[StorageService] = None


def get_storage_service() -> StorageService:
    """Get singleton storage service instance."""
    global _storage_service
    if _storage_service is None:
        _storage_service = StorageService()
    return _storage_service
