"""
Storage Service
===============
S3-compatible object storage (Cloudflare R2, DigitalOcean Spaces, AWS S3) with
a local filesystem fallback for development.

Backend selection via STORAGE_BACKEND env var:
  local  — writes to STORAGE_LOCAL_PATH (default /tmp/sonoro-storage). Files are
            ephemeral on Railway restarts. Use for dev/initial testing only.
  s3     — boto3 against any S3-compatible endpoint. Required env vars:
              SPACES_ENDPOINT   — full URL, e.g. https://<id>.r2.cloudflarestorage.com
              SPACES_ACCESS_KEY — access key ID
              SPACES_SECRET_KEY — secret access key
              SPACES_BUCKET     — bucket name
              SPACES_REGION     — 'auto' for R2, 'nyc3' for DO Spaces, etc.
"""

import io
import logging
import os
import shutil
from datetime import datetime
from typing import Optional
from uuid import UUID

from fastapi import HTTPException, UploadFile, status

from app.core.config import settings

logger = logging.getLogger(__name__)


# ── helpers ───────────────────────────────────────────────────────────────────

def _storage_path_for_document(user_id: UUID, document_id: UUID) -> str:
    return f"documents/{user_id}/{document_id}.pdf"


def _storage_path_for_audio(user_id: UUID, document_id: UUID, filename: str) -> str:
    return f"audio/{user_id}/{document_id}/{filename}"


# ── local filesystem backend ──────────────────────────────────────────────────

class LocalStorageService:
    """
    Filesystem storage for development / initial testing.
    Files survive process restarts but are lost when the Railway
    container is redeployed. Swap to S3StorageService for production.
    """

    def __init__(self) -> None:
        self.base = settings.storage_local_path
        os.makedirs(self.base, exist_ok=True)
        logger.warning(
            "LOCAL filesystem storage is active (base=%s). "
            "Set STORAGE_BACKEND=s3 with S3 credentials for production.",
            self.base,
        )

    def _full(self, storage_path: str) -> str:
        return os.path.join(self.base, storage_path)

    async def upload_document(
        self,
        file: UploadFile,
        user_id: UUID,
        document_id: UUID,
        checksum: str,
        metadata: Optional[dict] = None,
    ) -> str:
        storage_path = _storage_path_for_document(user_id, document_id)
        full = self._full(storage_path)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        file.file.seek(0)
        with open(full, "wb") as fh:
            shutil.copyfileobj(file.file, fh)
        logger.info(
            "Document stored locally",
            extra={"user_id": str(user_id), "document_id": str(document_id), "path": full},
        )
        return storage_path

    async def generate_download_url(
        self,
        storage_path: str,
        filename: str,
        expiry_seconds: Optional[int] = None,
    ) -> str:
        return f"/api/v1/storage/local/{storage_path}"

    async def delete_document(self, storage_path: str) -> bool:
        try:
            os.remove(self._full(storage_path))
            return True
        except OSError:
            return False

    async def document_exists(self, storage_path: str) -> bool:
        return os.path.exists(self._full(storage_path))

    async def get_document_metadata(self, storage_path: str) -> Optional[dict]:
        return {}

    async def upload_audio(
        self,
        audio_data: bytes,
        user_id: UUID,
        document_id: UUID,
        filename: str = "full.mp3",
        metadata: Optional[dict] = None,
    ) -> str:
        storage_path = _storage_path_for_audio(user_id, document_id, filename)
        full = self._full(storage_path)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "wb") as fh:
            fh.write(audio_data)
        return storage_path


# ── S3-compatible backend ─────────────────────────────────────────────────────

class S3StorageService:
    """
    S3-compatible storage: Cloudflare R2, DigitalOcean Spaces, AWS S3.

    R2 notes:
      - SPACES_REGION must be "auto"
      - SPACES_ENDPOINT must be the full account-scoped URL
      - Object-level ACLs are not supported; bucket visibility is set at bucket level
    """

    PRESIGNED_URL_EXPIRY = 3600  # 1 hour

    def __init__(self) -> None:
        import boto3
        from botocore.client import Config

        access_key = settings.spaces_access_key
        secret_key = settings.spaces_secret_key
        endpoint = settings.spaces_endpoint.strip()
        region = settings.spaces_region or "auto"
        bucket = settings.spaces_bucket

        # Validate before attempting to create client
        missing = [k for k, v in [
            ("SPACES_ACCESS_KEY", access_key),
            ("SPACES_SECRET_KEY", secret_key),
            ("SPACES_ENDPOINT", endpoint),
            ("SPACES_BUCKET", bucket),
        ] if not v]

        if missing:
            logger.error(
                "S3 storage is misconfigured — missing env vars: %s. "
                "Set STORAGE_BACKEND=local for development or add the missing vars to Railway.",
                ", ".join(missing),
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=(
                    f"Storage service is not configured. "
                    f"Missing: {', '.join(missing)}. Contact support."
                ),
            )

        try:
            self.client = boto3.client(
                "s3",
                region_name=region,
                endpoint_url=endpoint,
                aws_access_key_id=access_key,
                aws_secret_access_key=secret_key,
                config=Config(
                    signature_version="s3v4",
                    # path-style addressing is required for R2 and most non-AWS providers
                    s3={"addressing_style": "path"},
                    retries={"max_attempts": 3, "mode": "adaptive"},
                    connect_timeout=10,
                    read_timeout=60,
                ),
            )
            self.bucket = bucket
            logger.info(
                "S3 storage client ready (endpoint=%s, bucket=%s)", endpoint, bucket
            )
        except Exception as exc:
            logger.error("Failed to initialise S3 storage client: %s", exc)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Storage service unavailable",
            ) from exc

    async def upload_document(
        self,
        file: UploadFile,
        user_id: UUID,
        document_id: UUID,
        checksum: str,
        metadata: Optional[dict] = None,
    ) -> str:
        from botocore.exceptions import ClientError

        storage_path = _storage_path_for_document(user_id, document_id)
        upload_metadata: dict[str, str] = {
            "user-id": str(user_id),
            "document-id": str(document_id),
            "checksum-sha256": checksum,
            "upload-timestamp": datetime.utcnow().isoformat(),
        }
        if metadata:
            upload_metadata.update(metadata)

        file.file.seek(0)
        try:
            self.client.upload_fileobj(
                file.file,
                self.bucket,
                storage_path,
                ExtraArgs={
                    "ContentType": "application/pdf",
                    "Metadata": upload_metadata,
                },
            )
            logger.info(
                "Document uploaded to S3",
                extra={
                    "user_id": str(user_id),
                    "document_id": str(document_id),
                    "storage_path": storage_path,
                },
            )
            return storage_path
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "Unknown")
            logger.error(
                "S3 upload failed (code=%s): %s",
                code,
                exc,
                extra={"user_id": str(user_id), "document_id": str(document_id)},
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to upload document to storage",
            ) from exc

    async def generate_download_url(
        self,
        storage_path: str,
        filename: str,
        expiry_seconds: Optional[int] = None,
    ) -> str:
        from botocore.exceptions import ClientError

        expiry = expiry_seconds or self.PRESIGNED_URL_EXPIRY
        try:
            return self.client.generate_presigned_url(
                "get_object",
                Params={
                    "Bucket": self.bucket,
                    "Key": storage_path,
                    "ResponseContentDisposition": f'attachment; filename="{filename}"',
                    "ResponseContentType": "application/pdf",
                },
                ExpiresIn=expiry,
            )
        except ClientError as exc:
            logger.error("Failed to generate presigned URL: %s", exc)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to generate download URL",
            ) from exc

    async def delete_document(self, storage_path: str) -> bool:
        from botocore.exceptions import ClientError

        try:
            self.client.delete_object(Bucket=self.bucket, Key=storage_path)
            return True
        except ClientError as exc:
            logger.error("Failed to delete from S3: %s", exc, extra={"storage_path": storage_path})
            return False

    async def document_exists(self, storage_path: str) -> bool:
        from botocore.exceptions import ClientError

        try:
            self.client.head_object(Bucket=self.bucket, Key=storage_path)
            return True
        except ClientError:
            return False

    async def get_document_metadata(self, storage_path: str) -> Optional[dict]:
        from botocore.exceptions import ClientError

        try:
            resp = self.client.head_object(Bucket=self.bucket, Key=storage_path)
            return resp.get("Metadata", {})
        except ClientError:
            return None

    async def upload_audio(
        self,
        audio_data: bytes,
        user_id: UUID,
        document_id: UUID,
        filename: str = "full.mp3",
        metadata: Optional[dict] = None,
    ) -> str:
        from botocore.exceptions import ClientError

        storage_path = _storage_path_for_audio(user_id, document_id, filename)
        upload_metadata: dict[str, str] = {
            "user-id": str(user_id),
            "document-id": str(document_id),
            "upload-timestamp": datetime.utcnow().isoformat(),
        }
        if metadata:
            upload_metadata.update(metadata)

        try:
            self.client.put_object(
                Bucket=self.bucket,
                Key=storage_path,
                Body=audio_data,
                ContentType="audio/mpeg",
                Metadata=upload_metadata,
            )
            return storage_path
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "Unknown")
            logger.error(
                "S3 audio upload failed (code=%s): %s",
                code,
                exc,
                extra={"user_id": str(user_id), "document_id": str(document_id)},
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to upload audio to storage",
            ) from exc


# ── factory ───────────────────────────────────────────────────────────────────

# Type alias so callers don't need to know which backend is active
StorageService = LocalStorageService | S3StorageService  # type: ignore[assignment]

_storage_service: Optional[object] = None


def get_storage_service() -> "LocalStorageService | S3StorageService":
    """Return the singleton storage service, creating it on first call."""
    global _storage_service
    if _storage_service is None:
        backend = settings.storage_backend.strip().lower()
        if backend == "s3":
            _storage_service = S3StorageService()
        else:
            if settings.is_production and backend == "local":
                logger.warning(
                    "STORAGE_BACKEND=local in production (APP_ENV=%s). "
                    "Uploaded files will be lost on container restarts. "
                    "Set STORAGE_BACKEND=s3 with valid credentials.",
                    settings.app_env,
                )
            _storage_service = LocalStorageService()
    return _storage_service  # type: ignore[return-value]


def reset_storage_service() -> None:
    """Clear the singleton — used in tests to swap backends between cases."""
    global _storage_service
    _storage_service = None
