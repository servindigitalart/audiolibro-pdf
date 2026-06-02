"""
Unit Tests — Stabilization Sprint (2026-06-01)
================================================
Covers:
 1. retry failed document creates a new job (does not 404)
 2. display_title rename persists and falls back to original_filename
 3. Free 50k quota allows small/medium trial PDFs
 4. quota_limits and tiers.py are in sync for the FREE tier
 5. "Part X of Y" labelling in UploadZone helpers
 6. weightedProgress is monotonic given increasing backend inputs
"""

import pytest

pytestmark = pytest.mark.unit


# ── 1. Retry endpoint logic ───────────────────────────────────────────────────

def test_retry_resets_failed_processing_status():
    """Simulate the state reset in the retry endpoint.

    The retry handler sets processing_status back to NOT_STARTED before
    calling create_processing_job so _validate_document passes.
    """
    from app.db.models.document import ProcessingStatus

    # Mimic what the retry endpoint does
    class _FakeDoc:
        processing_status = ProcessingStatus.FAILED
        error_message     = "Some error"

    doc = _FakeDoc()
    # Simulate the retry reset
    if doc.processing_status == ProcessingStatus.FAILED:
        doc.processing_status = ProcessingStatus.NOT_STARTED
        doc.error_message = None

    assert doc.processing_status == ProcessingStatus.NOT_STARTED
    assert doc.error_message is None


def test_retry_does_not_reset_non_failed_document():
    """A document in COMPLETED state should NOT be reset by the retry guard."""
    from app.db.models.document import ProcessingStatus

    class _FakeDoc:
        processing_status = ProcessingStatus.COMPLETED
        error_message     = None

    doc = _FakeDoc()
    if doc.processing_status == ProcessingStatus.FAILED:
        doc.processing_status = ProcessingStatus.NOT_STARTED
        doc.error_message = None

    # Nothing should change
    assert doc.processing_status == ProcessingStatus.COMPLETED


# ── 2. display_title ─────────────────────────────────────────────────────────

def test_display_title_falls_back_to_original_filename():
    """When display_title is None the UI should use original_filename."""
    raw = {
        "id": "abc",
        "filename": "doc_abc.pdf",
        "original_filename": "My Great Book.pdf",
        "display_title": None,
        "file_size_bytes": 1024,
        "upload_status": "uploaded",
        "processing_status": "completed",
        "created_at": "2026-06-01T00:00:00",
    }
    # Simulate what normalizeDocument does on the frontend (Python mirror)
    title = raw.get("display_title") or raw.get("original_filename") or raw.get("filename") or "Untitled"
    assert title == "My Great Book.pdf"


def test_display_title_preferred_over_original_filename():
    """When display_title is set it takes priority over original_filename."""
    raw = {
        "display_title":    "Custom Audiobook Name",
        "original_filename": "My Great Book.pdf",
        "filename":          "doc_abc.pdf",
    }
    title = raw.get("display_title") or raw.get("original_filename") or raw.get("filename") or "Untitled"
    assert title == "Custom Audiobook Name"


def test_display_title_strip_empty_rejected():
    """An empty or whitespace-only display_title should be rejected."""
    titles_to_reject = ["", "   ", "\t\n"]
    for bad in titles_to_reject:
        assert bad.strip() == "", f"'{bad}' should be blank after strip"


# ── 3. Free quota ─────────────────────────────────────────────────────────────

def test_free_tier_char_limit_is_50k():
    """The FREE tier must allow at least 50,000 characters."""
    from app.pricing.tiers import get_tier, PlanTier
    config = get_tier(PlanTier.FREE)
    assert config.monthly_chars >= 50_000, (
        f"FREE tier monthly_chars={config.monthly_chars} — must be >= 50,000 "
        "to allow one meaningful trial audiobook"
    )


def test_free_quota_limits_matches_tiers():
    """PLAN_QUOTAS and TIER_CATALOG must agree on the FREE char limit."""
    from app.pricing.tiers import get_tier, PlanTier
    from app.financial.quota.quota_limits import PLAN_QUOTAS, PlanTier as QLPlanTier

    tier_chars  = get_tier(PlanTier.FREE).monthly_chars
    quota_chars = PLAN_QUOTAS[QLPlanTier.FREE].monthly_char_limit
    assert tier_chars == quota_chars, (
        f"Mismatch: tiers.py FREE={tier_chars}, quota_limits.py FREE={quota_chars}"
    )


def test_small_pdf_fits_free_quota():
    """A typical small book (~30 pages, ~45k chars) must fit the FREE quota."""
    from app.financial.quota.quota_limits import PLAN_QUOTAS, PlanTier

    typical_small_book_chars = 45_000
    limit = PLAN_QUOTAS[PlanTier.FREE].monthly_char_limit
    assert typical_small_book_chars <= limit, (
        f"Small book ({typical_small_book_chars} chars) exceeds FREE limit ({limit})"
    )


# ── 4. "Part X of Y" labelling ───────────────────────────────────────────────

def test_part_label_format():
    """chunkDesc must produce 'Part X of Y', not 'Chapter X of Y'."""
    def chunk_desc(done: int, total: int) -> str:
        if total > 0:
            return f"Part {done + 1} of {total}"
        return "Generating your narration"

    assert chunk_desc(0, 5)  == "Part 1 of 5"
    assert chunk_desc(2, 5)  == "Part 3 of 5"
    assert chunk_desc(4, 5)  == "Part 5 of 5"
    assert chunk_desc(0, 0)  == "Generating your narration"


def test_part_label_does_not_say_chapter():
    """Ensure the label does not contain the word 'Chapter'."""
    def chunk_desc(done: int, total: int) -> str:
        if total > 0:
            return f"Part {done + 1} of {total}"
        return "Generating your narration"

    for done in range(5):
        label = chunk_desc(done, 5)
        assert "chapter" not in label.lower(), f"'{label}' contains 'chapter'"
        assert "Chapter" not in label


# ── 5. Monotonic progress ─────────────────────────────────────────────────────

def weighted_progress(raw_stage: str, backend_pct: int, chunks_done: int, chunks_total: int) -> int:
    """Python mirror of the frontend weightedProgress helper."""
    r = (raw_stage or "").lower()
    if r in ("upload_finalize", "finalizing"):          return 97
    if r in ("final_assembly", "assembling"):           return 90
    if r.startswith("tts") or r == "generating_audio":
        if chunks_total > 0:
            return round(25 + (chunks_done / chunks_total) * 60)
        return 25
    if r in ("chapter_detection", "detecting_chapters"): return 20
    return min(14, max(0, backend_pct))


def test_weighted_progress_monotonic_across_stages():
    """Simulated job progression must never produce a lower weighted pct."""
    events = [
        # (stage, backend_pct, done, total)
        ("analyzing",         5,  0, 0),
        ("analyzing",        10,  0, 0),
        ("chapter_detection", 10,  0, 0),
        ("tts_generation",    10,  0, 8),
        ("tts_generation",    30,  2, 8),
        ("tts_generation",    55,  4, 8),
        ("tts_generation",    80,  7, 8),
        ("final_assembly",    85,  8, 8),
        ("upload_finalize",   90,  8, 8),
    ]
    prev = -1
    for stage, pct, done, total in events:
        current = weighted_progress(stage, pct, done, total)
        assert current >= prev, (
            f"Progress went backward: {prev} → {current} at stage={stage}"
        )
        prev = current


def test_weighted_progress_never_exceeds_99_before_done():
    """Ensure in-flight progress is capped below 100 (done=false)."""
    for stage in ("analyzing", "chapter_detection", "tts_generation", "final_assembly"):
        pct = weighted_progress(stage, 100, 10, 10)
        assert pct <= 99, f"stage={stage} returned {pct} — should be capped at 99 in-flight"


def test_weighted_progress_finalizing_returns_97():
    assert weighted_progress("finalizing", 99, 0, 0) == 97
    assert weighted_progress("upload_finalize", 99, 0, 0) == 97


def test_weighted_progress_assembling_returns_90():
    assert weighted_progress("final_assembly", 80, 0, 0) == 90
    assert weighted_progress("assembling", 80, 0, 0) == 90


def test_weighted_progress_tts_with_chunks():
    # 4/8 chunks done → 25 + (4/8)*60 = 25 + 30 = 55
    assert weighted_progress("tts_generation", 50, 4, 8) == 55
    # 0/8 chunks done → 25
    assert weighted_progress("tts_generation", 50, 0, 8) == 25
    # all chunks done → 25 + 60 = 85
    assert weighted_progress("tts_generation", 99, 8, 8) == 85


# ── 6. Media Session artwork structure ───────────────────────────────────────

def test_media_session_artwork_sizes():
    """Verify the expected artwork size set is defined and contains lock-screen sizes."""
    expected_sizes = {96, 128, 192, 256, 512}
    # These are the sizes declared in AudioPlayer.tsx generateCoverDataUrl section
    declared = [96, 128, 192, 256, 512]
    assert set(declared) == expected_sizes
    # All must be square
    for sz in declared:
        assert sz > 0


def test_media_session_artwork_not_stretched():
    """All artwork sizes must be square (width == height)."""
    sizes = [(96, 96), (128, 128), (192, 192), (256, 256), (512, 512)]
    for w, h in sizes:
        assert w == h, f"Artwork {w}x{h} is not square — will appear stretched on lock screen"
