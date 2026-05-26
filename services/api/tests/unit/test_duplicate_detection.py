"""
Unit tests for duplicate PDF detection.

Covers:
- First upload creates a new document (no duplicate)
- Duplicate completed PDF reuses existing document (is_duplicate=True)
- Duplicate in-flight (processing) PDF routes to existing job
- Duplicate failed PDF returns can_reprocess=True
- force_reprocess=True bypasses duplicate check and creates fresh document
- Duplicate upload does NOT create a new processing job (no quota charge path)
"""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock
from uuid import uuid4

import pytest

from app.db.models.document import Document, UploadStatus, ProcessingStatus
from app.schemas.document import DocumentUploadResponse
from app.services.document_service import DocumentService


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_user():
    user = MagicMock()
    user.id = uuid4()
    user.plan_tier = "FREE"
    return user


def _make_document(
    user_id=None,
    checksum: str = "abc123",
    processing_status: ProcessingStatus = ProcessingStatus.COMPLETED,
    upload_status: UploadStatus = UploadStatus.UPLOADED,
) -> Document:
    doc = MagicMock(spec=Document)
    doc.id = uuid4()
    doc.user_id = user_id or uuid4()
    doc.filename = "document.pdf"
    doc.original_filename = "my_book.pdf"
    doc.file_size_bytes = 1_024_000
    doc.file_size_mb = 1.0
    doc.mime_type = "application/pdf"
    doc.storage_path = f"documents/{doc.user_id}/{doc.id}.pdf"
    doc.checksum_sha256 = checksum
    doc.upload_status = upload_status
    doc.processing_status = processing_status
    doc.page_count = 10
    doc.character_estimate = 5000
    doc.language_detected = "en"
    doc.created_at = datetime.utcnow()
    return doc


def _mock_db(find_result=None):
    """Minimal AsyncSession mock."""
    db = AsyncMock()
    exec_result = MagicMock()
    exec_result.scalar_one_or_none.return_value = find_result
    db.execute = AsyncMock(return_value=exec_result)
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    return db


def _make_upload_file(filename: str = "my_book.pdf") -> MagicMock:
    uf = MagicMock()
    uf.filename = filename
    uf.file = MagicMock()
    uf.file.seek = MagicMock()
    uf.file.read = MagicMock(return_value=b"%PDF-fake")
    return uf


FAKE_CHECKSUM = "deadbeef" * 8  # 64 hex chars


# ---------------------------------------------------------------------------
# Tests: _find_duplicate
# ---------------------------------------------------------------------------

class TestFindDuplicate:
    """Direct tests for the _find_duplicate helper."""

    @pytest.mark.asyncio
    async def test_returns_none_when_no_match(self):
        db = _mock_db(find_result=None)
        svc = DocumentService(db)
        result = await svc._find_duplicate(uuid4(), FAKE_CHECKSUM)
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_existing_document_on_match(self):
        user_id = uuid4()
        existing = _make_document(user_id=user_id, checksum=FAKE_CHECKSUM)
        db = _mock_db(find_result=existing)
        svc = DocumentService(db)
        result = await svc._find_duplicate(user_id, FAKE_CHECKSUM)
        assert result is existing


# ---------------------------------------------------------------------------
# Tests: upload_document — duplicate paths
# ---------------------------------------------------------------------------

class TestUploadDocumentDuplicate:

    def _make_service(self, existing_doc=None):
        """Create a DocumentService with mocked DB and storage."""
        db = _mock_db()
        svc = DocumentService(db)
        svc.storage = AsyncMock()
        svc._find_duplicate = AsyncMock(return_value=existing_doc)
        return svc

    @pytest.mark.asyncio
    async def test_first_upload_creates_new_document(self):
        """No existing doc → normal upload flow, is_duplicate=False."""
        svc = self._make_service(existing_doc=None)

        new_doc = _make_document(processing_status=ProcessingStatus.NOT_STARTED)
        new_doc.upload_status = UploadStatus.UPLOADED
        # db.refresh populates the doc object in place
        svc.db.refresh = AsyncMock(side_effect=lambda obj: None)

        with (
            patch("app.services.document_service.validate_upload_file",
                  new=AsyncMock(return_value=(1_024_000, "application/pdf", FAKE_CHECKSUM))),
            patch("app.services.document_service.sanitize_filename", return_value="my_book.pdf"),
            patch.object(svc, "_extract_metadata", new=AsyncMock(return_value=MagicMock(
                page_count=10,
                character_estimate=5000,
                language_detected="en",
            ))),
            patch.object(svc.storage, "upload_document", new=AsyncMock()),
        ):
            # Simulate db.refresh assigning needed attrs to the document object
            created_doc = MagicMock()
            created_doc.id = uuid4()
            created_doc.user_id = uuid4()
            created_doc.filename = "my_book.pdf"
            created_doc.original_filename = "my_book.pdf"
            created_doc.file_size_bytes = 1_024_000
            created_doc.file_size_mb = 1.0
            created_doc.mime_type = "application/pdf"
            created_doc.upload_status = UploadStatus.UPLOADED
            created_doc.processing_status = ProcessingStatus.NOT_STARTED
            created_doc.page_count = 10
            created_doc.character_estimate = 5000
            created_doc.language_detected = "en"
            created_doc.checksum_sha256 = FAKE_CHECKSUM
            created_doc.created_at = datetime.utcnow()

            # Patch Document constructor to return our mock
            with patch("app.services.document_service.Document", return_value=created_doc):
                result = await svc.upload_document(
                    file=_make_upload_file(),
                    user=_make_user(),
                    force_reprocess=False,
                )

        assert result.is_duplicate is False
        assert result.duplicate_message is None
        assert result.can_reprocess is False

    @pytest.mark.asyncio
    async def test_duplicate_completed_reuses_existing(self):
        """Duplicate of a completed doc → returns existing, is_duplicate=True."""
        user = _make_user()
        existing = _make_document(
            user_id=user.id,
            checksum=FAKE_CHECKSUM,
            processing_status=ProcessingStatus.COMPLETED,
        )
        svc = self._make_service(existing_doc=existing)

        with patch("app.services.document_service.validate_upload_file",
                   new=AsyncMock(return_value=(1_024_000, "application/pdf", FAKE_CHECKSUM))):
            result = await svc.upload_document(
                file=_make_upload_file(),
                user=user,
                force_reprocess=False,
            )

        assert result.is_duplicate is True
        assert result.id == existing.id
        assert result.can_reprocess is False
        assert "already converted" in (result.duplicate_message or "").lower()

    @pytest.mark.asyncio
    async def test_duplicate_processing_routes_to_existing_job(self):
        """Duplicate of an in-flight doc → is_duplicate=True, processing_status active."""
        user = _make_user()
        existing = _make_document(
            user_id=user.id,
            checksum=FAKE_CHECKSUM,
            processing_status=ProcessingStatus.PROCESSING,
        )
        svc = self._make_service(existing_doc=existing)

        with patch("app.services.document_service.validate_upload_file",
                   new=AsyncMock(return_value=(1_024_000, "application/pdf", FAKE_CHECKSUM))):
            result = await svc.upload_document(
                file=_make_upload_file(),
                user=user,
                force_reprocess=False,
            )

        assert result.is_duplicate is True
        assert result.processing_status == ProcessingStatus.PROCESSING.value
        assert result.can_reprocess is False

    @pytest.mark.asyncio
    async def test_duplicate_failed_allows_reprocess(self):
        """Duplicate of a failed doc → can_reprocess=True."""
        user = _make_user()
        existing = _make_document(
            user_id=user.id,
            checksum=FAKE_CHECKSUM,
            processing_status=ProcessingStatus.FAILED,
        )
        svc = self._make_service(existing_doc=existing)

        with patch("app.services.document_service.validate_upload_file",
                   new=AsyncMock(return_value=(1_024_000, "application/pdf", FAKE_CHECKSUM))):
            result = await svc.upload_document(
                file=_make_upload_file(),
                user=user,
                force_reprocess=False,
            )

        assert result.is_duplicate is True
        assert result.can_reprocess is True

    @pytest.mark.asyncio
    async def test_force_reprocess_bypasses_duplicate_check(self):
        """force_reprocess=True ignores existing doc and creates a fresh one."""
        user = _make_user()
        existing = _make_document(
            user_id=user.id,
            checksum=FAKE_CHECKSUM,
            processing_status=ProcessingStatus.COMPLETED,
        )
        svc = self._make_service(existing_doc=existing)

        created_doc = MagicMock()
        created_doc.id = uuid4()
        created_doc.user_id = user.id
        created_doc.filename = "my_book.pdf"
        created_doc.original_filename = "my_book.pdf"
        created_doc.file_size_bytes = 1_024_000
        created_doc.file_size_mb = 1.0
        created_doc.mime_type = "application/pdf"
        created_doc.upload_status = UploadStatus.UPLOADED
        created_doc.processing_status = ProcessingStatus.NOT_STARTED
        created_doc.page_count = 10
        created_doc.character_estimate = 5000
        created_doc.language_detected = "en"
        created_doc.checksum_sha256 = FAKE_CHECKSUM
        created_doc.created_at = datetime.utcnow()

        with (
            patch("app.services.document_service.validate_upload_file",
                  new=AsyncMock(return_value=(1_024_000, "application/pdf", FAKE_CHECKSUM))),
            patch("app.services.document_service.sanitize_filename", return_value="my_book.pdf"),
            patch.object(svc, "_extract_metadata", new=AsyncMock(return_value=MagicMock(
                page_count=10, character_estimate=5000, language_detected="en",
            ))),
            patch.object(svc.storage, "upload_document", new=AsyncMock()),
            patch("app.services.document_service.Document", return_value=created_doc),
        ):
            result = await svc.upload_document(
                file=_make_upload_file(),
                user=user,
                force_reprocess=True,
            )

        # Should return fresh document, not the existing one
        assert result.id != existing.id
        assert result.is_duplicate is False

    @pytest.mark.asyncio
    async def test_duplicate_does_not_create_new_document_in_db(self):
        """Duplicate response must not touch db.add — no new row created."""
        user = _make_user()
        existing = _make_document(
            user_id=user.id,
            checksum=FAKE_CHECKSUM,
            processing_status=ProcessingStatus.COMPLETED,
        )
        svc = self._make_service(existing_doc=existing)

        with patch("app.services.document_service.validate_upload_file",
                   new=AsyncMock(return_value=(1_024_000, "application/pdf", FAKE_CHECKSUM))):
            await svc.upload_document(
                file=_make_upload_file(),
                user=user,
                force_reprocess=False,
            )

        # db.add must NOT have been called — no new document row written
        svc.db.add.assert_not_called()
        # db.commit likewise skipped — no DB write
        svc.db.commit.assert_not_called()
