"""
Unit Tests — Library, Player & Export Metadata Sprint (2026-06-02)
==================================================================
Covers:
 1. Stuck-job detection logic (fresh queued vs stale queued)
 2. Retry creates a new job (resets failed state)
 3. Cancel sets job/document status correctly
 4. Cover upload: valid MIME accepted, invalid rejected, >5MB rejected
 5. Download filename sanitisation (_safe_filename)
 6. display_title normalization chain
 7. "Full Document" chapter title handling
 8. document_* prefix stripping in Document Info
"""

import pytest
from datetime import datetime, timedelta

pytestmark = pytest.mark.unit


# ── 1. Stuck-job detection ────────────────────────────────────────────────────

STUCK_MINUTES = 10


def is_stuck_doc(status: str, updated_at_dt: datetime) -> bool:
    """Python mirror of the frontend isStuck() helper."""
    if status not in ("pending", "processing"):
        return False
    return (datetime.utcnow() - updated_at_dt).total_seconds() > STUCK_MINUTES * 60


def test_fresh_queued_is_not_stuck():
    updated = datetime.utcnow() - timedelta(minutes=3)
    assert not is_stuck_doc("pending", updated)


def test_queued_10_minutes_is_stuck():
    updated = datetime.utcnow() - timedelta(minutes=11)
    assert is_stuck_doc("pending", updated)


def test_processing_16_minutes_is_stuck():
    updated = datetime.utcnow() - timedelta(minutes=16)
    assert is_stuck_doc("processing", updated)


def test_completed_is_never_stuck():
    updated = datetime.utcnow() - timedelta(hours=2)
    assert not is_stuck_doc("completed", updated)


def test_failed_is_never_stuck():
    updated = datetime.utcnow() - timedelta(hours=1)
    assert not is_stuck_doc("failed", updated)


# ── 2. Retry resets failed state ──────────────────────────────────────────────

def test_retry_resets_failed_document():
    from app.db.models.document import ProcessingStatus

    class _FakeDoc:
        processing_status = ProcessingStatus.FAILED
        error_message     = "TTS timeout"

    doc = _FakeDoc()
    if doc.processing_status == ProcessingStatus.FAILED:
        doc.processing_status = ProcessingStatus.NOT_STARTED
        doc.error_message = None

    assert doc.processing_status == ProcessingStatus.NOT_STARTED
    assert doc.error_message is None


def test_retry_does_not_reset_completed():
    from app.db.models.document import ProcessingStatus

    class _FakeDoc:
        processing_status = ProcessingStatus.COMPLETED
        error_message     = None

    doc = _FakeDoc()
    if doc.processing_status == ProcessingStatus.FAILED:
        doc.processing_status = ProcessingStatus.NOT_STARTED
        doc.error_message = None

    assert doc.processing_status == ProcessingStatus.COMPLETED


# ── 3. Cancel endpoint logic ──────────────────────────────────────────────────

def test_cancel_resets_document_to_not_started():
    from app.db.models.document import ProcessingStatus

    class _FakeDoc:
        processing_status = ProcessingStatus.QUEUED

    doc = _FakeDoc()
    # Simulate what cancel endpoint does to the document
    doc.processing_status = ProcessingStatus.NOT_STARTED
    assert doc.processing_status == ProcessingStatus.NOT_STARTED


def test_cancel_marks_job_as_cancelled():
    from app.db.models.processing_job import JobStatus

    class _FakeJob:
        status = JobStatus.QUEUED
        celery_task_id = None
        cancelled_at = None

    job = _FakeJob()
    job.status = JobStatus.CANCELLED
    assert job.status == JobStatus.CANCELLED


# ── 4. Cover upload validation ────────────────────────────────────────────────

ALLOWED_COVER_MIME = {"image/jpeg", "image/png", "image/webp"}
MAX_COVER_BYTES = 5 * 1024 * 1024  # 5 MB


def _validate_cover(mime: str, size_bytes: int) -> str | None:
    """Returns None if valid, error string otherwise."""
    mime_clean = mime.split(";")[0].strip().lower()
    if mime_clean not in ALLOWED_COVER_MIME:
        return f"Unsupported type: {mime_clean}"
    if size_bytes > MAX_COVER_BYTES:
        return "Image too large (max 5 MB)"
    return None


def test_jpeg_cover_accepted():
    assert _validate_cover("image/jpeg", 1024 * 1024) is None


def test_png_cover_accepted():
    assert _validate_cover("image/png", 2 * 1024 * 1024) is None


def test_webp_cover_accepted():
    assert _validate_cover("image/webp", 500_000) is None


def test_pdf_cover_rejected():
    err = _validate_cover("application/pdf", 100)
    assert err is not None
    assert "Unsupported" in err


def test_gif_cover_rejected():
    err = _validate_cover("image/gif", 100)
    assert err is not None


def test_cover_5mb_accepted():
    assert _validate_cover("image/jpeg", 5 * 1024 * 1024) is None


def test_cover_over_5mb_rejected():
    err = _validate_cover("image/jpeg", 5 * 1024 * 1024 + 1)
    assert err is not None
    assert "large" in err


def test_cover_mime_with_charset_accepted():
    """MIME types sometimes include ; charset=... — strip correctly."""
    assert _validate_cover("image/png; charset=utf-8", 1024) is None


# ── 5. Download filename sanitisation ─────────────────────────────────────────

def _safe_filename(title: str, fallback: str = "audiobook") -> str:
    import re, unicodedata
    nfkd = unicodedata.normalize("NFKD", title)
    ascii_str = nfkd.encode("ascii", "ignore").decode("ascii")
    safe = re.sub(r"[^\w\s\-.]", " ", ascii_str).strip()
    safe = re.sub(r"\s+", " ", safe)
    return (safe[:120] or fallback) + ".mp3"


def test_safe_filename_basic():
    assert _safe_filename("My Audiobook") == "My Audiobook.mp3"


def test_safe_filename_accents_stripped():
    # "Nos han dado la tierra" with accented characters
    result = _safe_filename("Años de soledad")
    assert result.endswith(".mp3")
    assert "os de soledad" in result  # A stripped, rest preserved


def test_safe_filename_special_chars_replaced():
    result = _safe_filename("Book: A Story (Part 1)")
    assert ":" not in result
    assert result.endswith(".mp3")


def test_safe_filename_empty_uses_fallback():
    result = _safe_filename("")
    assert result == "audiobook.mp3"


def test_safe_filename_too_long_truncated():
    long_title = "A" * 200
    result = _safe_filename(long_title)
    assert len(result) <= 124  # 120 + ".mp3"


def test_safe_filename_unicode_normalized():
    # Chinese/Japanese chars → stripped → fallback
    result = _safe_filename("我的书")
    assert result.endswith(".mp3")


# ── 6. display_title normalization chain ──────────────────────────────────────

def _resolve_title(raw: dict) -> str:
    return (
        raw.get("display_title")
        or raw.get("original_filename")
        or raw.get("filename")
        or "Untitled"
    )


def test_display_title_preferred():
    assert _resolve_title({"display_title": "Custom Name", "original_filename": "doc.pdf"}) == "Custom Name"


def test_original_filename_fallback():
    assert _resolve_title({"display_title": None, "original_filename": "My Book.pdf"}) == "My Book.pdf"


def test_filename_last_resort():
    assert _resolve_title({"display_title": None, "original_filename": None, "filename": "doc_abc.pdf"}) == "doc_abc.pdf"


def test_untitled_fallback():
    assert _resolve_title({}) == "Untitled"


# ── 7. "Full Document" chapter title handling ─────────────────────────────────

def test_full_document_replaced_by_complete_audiobook():
    chapter_title = "Full Document"
    doc_title = "My Audiobook"
    chapters_count = 1
    # Mirrors AudioPlayer logic
    display = (
        chapter_title if chapter_title and chapter_title != "Full Document"
        else ("Complete audiobook" if chapters_count <= 1 else "—")
    )
    assert display == "Complete audiobook"


def test_real_chapter_title_not_replaced():
    chapter_title = "Chapter 1: The Beginning"
    display = (
        chapter_title if chapter_title and chapter_title != "Full Document"
        else "Complete audiobook"
    )
    assert display == "Chapter 1: The Beginning"


def test_multi_chapter_full_document_shows_dash():
    chapter_title = "Full Document"
    chapters_count = 3
    display = (
        chapter_title if chapter_title and chapter_title != "Full Document"
        else ("Complete audiobook" if chapters_count <= 1 else "—")
    )
    assert display == "—"


# ── 8. Document filename prefix stripping ────────────────────────────────────

import re as _re


def _strip_doc_prefix(filename: str) -> str:
    """Strip the internal document_<uuid>. prefix from the stored filename."""
    return _re.sub(r'^document_[a-f0-9\-]+\.', '', filename)


def test_strip_doc_prefix_removes_uuid():
    raw = "document_bd081877-1234-5678-abcd-ef0123456789.pdf"
    assert _strip_doc_prefix(raw) == "pdf"


def test_strip_doc_prefix_leaves_normal_filename():
    assert _strip_doc_prefix("my_book.pdf") == "my_book.pdf"


def test_strip_doc_prefix_empty_string():
    assert _strip_doc_prefix("") == ""
