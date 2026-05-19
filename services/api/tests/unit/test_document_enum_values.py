"""
Unit Tests: document enum values and SQLAlchemy column configuration
====================================================================
Regression guard for the asyncpg/SQLAlchemy 2.0 bug where native PostgreSQL
enum columns serialise using the Python enum member's .name (uppercase) instead
of its .value (lowercase), causing:

    asyncpg.exceptions.InvalidTextRepresentationError:
      invalid input value for enum uploadstatus: "PENDING"

These tests run without a real database and verify:
1. Every UploadStatus / ProcessingStatus value is a lowercase string.
2. The Document SQLAlchemy columns use native_enum=False so values are stored
   as plain VARCHAR strings, bypassing asyncpg's native enum codec entirely.
3. A Document instance carries the correct string values for its default statuses.
"""

import pytest
from uuid import uuid4

from sqlalchemy import Enum as SAEnum

from app.db.models.document import Document, UploadStatus, ProcessingStatus

pytestmark = pytest.mark.unit


# ── UploadStatus ──────────────────────────────────────────────────────────────

class TestUploadStatusValues:
    def test_pending_value_is_lowercase(self):
        assert UploadStatus.PENDING.value == "pending"

    def test_uploaded_value_is_lowercase(self):
        assert UploadStatus.UPLOADED.value == "uploaded"

    def test_failed_value_is_lowercase(self):
        assert UploadStatus.FAILED.value == "failed"

    def test_all_values_are_lowercase(self):
        for member in UploadStatus:
            assert member.value == member.value.lower(), (
                f"UploadStatus.{member.name}.value must be lowercase; got {member.value!r}"
            )

    def test_member_equals_its_value_string(self):
        """str enum members must compare equal to their .value."""
        assert UploadStatus.PENDING == "pending"
        assert UploadStatus.UPLOADED == "uploaded"
        assert UploadStatus.FAILED == "failed"


# ── ProcessingStatus ──────────────────────────────────────────────────────────

class TestProcessingStatusValues:
    def test_not_started_value_is_lowercase(self):
        assert ProcessingStatus.NOT_STARTED.value == "not_started"

    def test_queued_value_is_lowercase(self):
        assert ProcessingStatus.QUEUED.value == "queued"

    def test_processing_value_is_lowercase(self):
        assert ProcessingStatus.PROCESSING.value == "processing"

    def test_assembling_value_is_lowercase(self):
        assert ProcessingStatus.ASSEMBLING.value == "assembling"

    def test_finalizing_value_is_lowercase(self):
        assert ProcessingStatus.FINALIZING.value == "finalizing"

    def test_completed_value_is_lowercase(self):
        assert ProcessingStatus.COMPLETED.value == "completed"

    def test_failed_value_is_lowercase(self):
        assert ProcessingStatus.FAILED.value == "failed"

    def test_all_values_are_lowercase(self):
        for member in ProcessingStatus:
            assert member.value == member.value.lower(), (
                f"ProcessingStatus.{member.name}.value must be lowercase; got {member.value!r}"
            )


# ── SQLAlchemy column configuration ──────────────────────────────────────────

class TestDocumentColumnConfiguration:
    """
    Guard that the Enum columns are defined with native_enum=False.
    If either reverts to native_enum=True the asyncpg codec bug will resurface.
    """

    def _get_column(self, column_name: str):
        return Document.__table__.c[column_name]

    def test_upload_status_uses_non_native_enum(self):
        col = self._get_column("upload_status")
        assert isinstance(col.type, SAEnum)
        assert col.type.native_enum is False, (
            "upload_status must use native_enum=False to avoid the asyncpg enum "
            "serialisation bug (sends .name instead of .value)"
        )

    def test_processing_status_uses_non_native_enum(self):
        col = self._get_column("processing_status")
        assert isinstance(col.type, SAEnum)
        assert col.type.native_enum is False, (
            "processing_status must use native_enum=False to avoid the asyncpg "
            "enum serialisation bug (sends .name instead of .value)"
        )

    def test_upload_status_enum_values_match_db(self):
        """Values registered in the SQLAlchemy Enum must match the DB VARCHAR data."""
        col = self._get_column("upload_status")
        registered = set(col.type.enums)
        expected = {"pending", "uploaded", "failed"}
        assert registered == expected, (
            f"upload_status Enum values mismatch. Got {registered}, want {expected}"
        )

    def test_processing_status_enum_values_match_db(self):
        col = self._get_column("processing_status")
        registered = set(col.type.enums)
        expected = {
            "not_started", "queued", "processing",
            "assembling", "finalizing", "completed", "failed",
        }
        assert registered == expected, (
            f"processing_status Enum values mismatch. Got {registered}, want {expected}"
        )


# ── Document instance defaults ────────────────────────────────────────────────

class TestDocumentInstanceDefaults:
    """
    Verify that a Document created with the initial statuses carries the correct
    lowercase string values — the same strings that will be inserted into the DB.
    """

    def _make_document(self) -> Document:
        return Document(
            id=uuid4(),
            user_id=uuid4(),
            filename="document_test.pdf",
            original_filename="test.pdf",
            file_size_bytes=1024,
            mime_type="application/pdf",
            storage_path=f"documents/{uuid4()}/{uuid4()}.pdf",
            checksum_sha256="a" * 64,
            upload_status=UploadStatus.PENDING,
            processing_status=ProcessingStatus.NOT_STARTED,
        )

    def test_initial_upload_status_is_pending_enum(self):
        doc = self._make_document()
        assert doc.upload_status == UploadStatus.PENDING

    def test_initial_upload_status_string_value_is_lowercase(self):
        doc = self._make_document()
        # This is what asyncpg will send to Postgres
        assert str(doc.upload_status.value) == "pending"

    def test_initial_processing_status_is_not_started_enum(self):
        doc = self._make_document()
        assert doc.processing_status == ProcessingStatus.NOT_STARTED

    def test_initial_processing_status_string_value_is_lowercase(self):
        doc = self._make_document()
        assert str(doc.processing_status.value) == "not_started"

    def test_upload_status_name_is_uppercase_but_value_is_lowercase(self):
        """Explicitly document the name/value distinction that caused the bug."""
        assert UploadStatus.PENDING.name == "PENDING"   # name = uppercase
        assert UploadStatus.PENDING.value == "pending"  # value = lowercase (stored in DB)
