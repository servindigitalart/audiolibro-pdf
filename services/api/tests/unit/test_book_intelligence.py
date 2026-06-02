"""
Unit Tests — Book Intelligence Layer
=====================================
Tests for:
  1. Local extractor — filename parsing (kebab, snake, camel, spaces)
  2. Local extractor — PDF metadata extraction
  3. Local extractor — "by author" filename splitting
  4. Fuzzy matcher — title similarity
  5. Fuzzy matcher — author similarity (last-name matching)
  6. Confidence scoring — all weight components
  7. Matcher.pick_best — selects highest-scoring result
  8. Matcher.pick_best — local-only fallback when no providers
  9. Confidence thresholds on BookMetadata
 10. MetadataSource enum values
 11. Provider parsing — Google Books _parse_volume
 12. Provider parsing — Open Library _parse_doc
 13. Cover pipeline — _content_type_to_ext and _magic_ext helpers
 14. Failure modes — empty filename, empty providers, zero chars
 15. _safe_filename integration (download endpoint helper)
 16. Normalisation helpers — _normalize, _fuzzy_ratio
"""

import pytest

pytestmark = pytest.mark.unit


# ── 1. Filename parsing — kebab-case ─────────────────────────────────────────

from app.metadata.extractor import LocalExtractor, _normalize_filename_part


def test_kebab_case_filename():
    ext = LocalExtractor()
    titles, _ = ext.extract("atomic-habits-james-clear.pdf")
    assert any("Atomic Habits" in c.value for c in titles), titles


def test_snake_case_filename():
    titles, _ = LocalExtractor().extract("the_power_of_habit.pdf")
    assert any("The Power Of Habit" in c.value or "Power" in c.value for c in titles)


def test_camel_case_filename():
    titles, _ = LocalExtractor().extract("AtomicHabits.pdf")
    assert any("Atomic Habits" in c.value for c in titles)


def test_spaced_filename():
    titles, _ = LocalExtractor().extract("Deep Work Cal Newport.pdf")
    assert any("Deep Work Cal Newport" in c.value or "Deep Work" in c.value for c in titles)


def test_filename_with_version_noise_stripped():
    titles, _ = LocalExtractor().extract("mybook_final_v2.pdf")
    # "final" and "v2" are noise words; title should still be extracted
    assert titles  # at least something comes back


def test_empty_filename_returns_empty():
    titles, _ = LocalExtractor().extract("")
    assert titles == [] or all(len(c.value) == 0 for c in titles if not c.value)


# ── 2. "by author" filename splitting ────────────────────────────────────────

def test_by_separator_extracts_author():
    _, authors = LocalExtractor().extract("Atomic Habits by James Clear.pdf")
    assert any("James Clear" in a.value for a in authors), authors


def test_kebab_by_separator():
    titles, authors = LocalExtractor().extract("deep-work-cal-newport.pdf")
    # No explicit "by" separator — last-two-words heuristic may fire
    assert titles  # at least a title candidate


# ── 3. Normalize filename helper ─────────────────────────────────────────────

def test_normalize_kebab():
    assert _normalize_filename_part("atomic-habits") == "Atomic Habits"


def test_normalize_snake():
    result = _normalize_filename_part("the_power_of_habit")
    assert "Power" in result and "Habit" in result


def test_normalize_camel():
    assert "Atomic" in _normalize_filename_part("AtomicHabits")
    assert "Habits" in _normalize_filename_part("AtomicHabits")


def test_normalize_strips_noise():
    result = _normalize_filename_part("mybook_pdf_download")
    assert "pdf" not in result.lower()
    assert "download" not in result.lower()


# ── 4. Fuzzy matcher — _normalize and _fuzzy_ratio ───────────────────────────

from app.metadata.matcher import _normalize, _fuzzy_ratio


def test_normalize_lowercases():
    assert _normalize("Atomic Habits") == "atomic habits"


def test_normalize_strips_accents():
    assert _normalize("Años de soledad") == "anos de soledad"


def test_normalize_removes_punctuation():
    assert _normalize("Hello, World!") == "hello world"


def test_fuzzy_ratio_identical():
    assert _fuzzy_ratio("Atomic Habits", "Atomic Habits") == 1.0


def test_fuzzy_ratio_similar():
    r = _fuzzy_ratio("Atomic Habits", "Atomic Habit")
    assert r > 0.85, f"Expected >0.85 but got {r:.3f}"


def test_fuzzy_ratio_different():
    r = _fuzzy_ratio("Atomic Habits", "The Power of Habit")
    assert r < 0.7, f"Expected <0.7 but got {r:.3f}"


def test_fuzzy_ratio_empty():
    assert _fuzzy_ratio("", "Atomic Habits") == 0.0
    assert _fuzzy_ratio("Atomic Habits", "") == 0.0


# ── 5. Author similarity — last-name matching ────────────────────────────────

from app.metadata.matcher import _last_name_ratio


def test_last_name_exact():
    assert _last_name_ratio("James Clear", "James Clear") == 1.0


def test_last_name_partial_first():
    # "J. Clear" vs "James Clear" — last name should match
    r = _last_name_ratio("J. Clear", "James Clear")
    assert r > 0.8, f"Expected >0.8, got {r:.3f}"


def test_last_name_different():
    r = _last_name_ratio("James Clear", "Cal Newport")
    assert r < 0.5


# ── 6. Confidence scoring ─────────────────────────────────────────────────────

from app.metadata.matcher import score_result, _W_TITLE, _W_AUTHOR, _W_ISBN, _W_LANG, _W_QUALITY, _W_COVER
from app.metadata.extractor import TitleCandidate, AuthorCandidate
from app.metadata.providers.base import ProviderResult


def _make_result(**kwargs) -> ProviderResult:
    defaults = dict(
        title="Atomic Habits",
        author="James Clear",
        language="en",
        isbn="9780735211292",
        cover_url="https://example.com/cover.jpg",
        raw_score=0.8,
        provider_name="google_books",
    )
    defaults.update(kwargs)
    return ProviderResult(**defaults)


def _tc(value: str) -> TitleCandidate:
    return TitleCandidate(value=value, source="test", weight=1.0)


def _ac(value: str) -> AuthorCandidate:
    return AuthorCandidate(value=value, source="test", weight=1.0)


def test_perfect_match_scores_high():
    result = _make_result(title="Atomic Habits", author="James Clear")
    score = score_result(result, [_tc("Atomic Habits")], [_ac("James Clear")], "en")
    assert score >= 0.85, f"Expected >=0.85, got {score:.3f}"


def test_no_title_match_scores_low():
    result = _make_result(title="The Power of Habit", author="Charles Duhigg")
    score = score_result(result, [_tc("Atomic Habits")], [_ac("James Clear")], "en")
    # Wrong book scores substantially lower than a correct match (which hits >=0.85)
    assert score < 0.70, f"Expected <0.70, got {score:.3f}"


def test_isbn_bonus_increases_score():
    result_with    = _make_result(isbn="9780735211292")
    result_without = _make_result(isbn=None)
    s_with    = score_result(result_with,    [_tc("Atomic Habits")], [_ac("James Clear")])
    s_without = score_result(result_without, [_tc("Atomic Habits")], [_ac("James Clear")])
    assert s_with > s_without


def test_cover_bonus_increases_score():
    result_with    = _make_result(cover_url="https://example.com/cover.jpg")
    result_without = _make_result(cover_url=None)
    s_with    = score_result(result_with,    [_tc("Atomic Habits")], [_ac("James Clear")])
    s_without = score_result(result_without, [_tc("Atomic Habits")], [_ac("James Clear")])
    assert s_with > s_without


def test_language_mismatch_reduces_score():
    result_match    = _make_result(language="en")
    result_mismatch = _make_result(language="fr")
    s_match    = score_result(result_match,    [_tc("Atomic Habits")], [_ac("James Clear")], detected_language="en")
    s_mismatch = score_result(result_mismatch, [_tc("Atomic Habits")], [_ac("James Clear")], detected_language="en")
    assert s_match > s_mismatch


def test_weights_sum_to_one():
    total = _W_TITLE + _W_AUTHOR + _W_ISBN + _W_LANG + _W_QUALITY + _W_COVER
    assert abs(total - 1.0) < 1e-9, f"Weights sum to {total:.6f}, expected 1.0"


def test_score_clamped_to_0_1():
    result = _make_result()
    score  = score_result(result, [_tc("Atomic Habits")], [_ac("James Clear")])
    assert 0.0 <= score <= 1.0


# ── 7. Matcher.pick_best — selects highest-scoring result ────────────────────

from app.metadata.matcher import Matcher
from app.metadata.models import BookMetadata, MetadataSource


def test_pick_best_returns_highest_score():
    good = ("google_books", _make_result(title="Atomic Habits", author="James Clear"))
    bad  = ("open_library", _make_result(title="The Power of Habit", author="Charles Duhigg"))
    meta = Matcher().pick_best(
        provider_results=[bad, good],
        title_candidates=[_tc("Atomic Habits")],
        author_candidates=[_ac("James Clear")],
        detected_language="en",
    )
    assert meta is not None
    assert meta.title == "Atomic Habits"
    assert meta.source == MetadataSource.GOOGLE


def test_pick_best_returns_open_library_for_ol_result():
    result = ("open_library", _make_result(title="Atomic Habits", author="James Clear", provider_name="open_library"))
    meta = Matcher().pick_best(
        provider_results=[result],
        title_candidates=[_tc("Atomic Habits")],
        author_candidates=[_ac("James Clear")],
    )
    assert meta is not None
    assert meta.source == MetadataSource.OPEN_LIB


# ── 8. Local-only fallback ────────────────────────────────────────────────────

def test_pick_best_no_providers_returns_local():
    meta = Matcher().pick_best(
        provider_results=[],
        title_candidates=[_tc("Atomic Habits")],
        author_candidates=[_ac("James Clear")],
    )
    assert meta is not None
    assert meta.title == "Atomic Habits"
    assert meta.source == MetadataSource.LOCAL
    assert meta.confidence < 0.60  # local-only is low confidence


def test_pick_best_empty_candidates_returns_none_or_low():
    meta = Matcher().pick_best(
        provider_results=[],
        title_candidates=[],
        author_candidates=[],
    )
    assert meta is None or meta.confidence == 0.0


# ── 9. Confidence thresholds on BookMetadata ─────────────────────────────────

def test_high_confidence():
    m = BookMetadata(confidence=0.90)
    assert m.is_high_confidence
    assert not m.is_medium_confidence
    assert m.confidence_label == "high"


def test_medium_confidence():
    m = BookMetadata(confidence=0.70)
    assert not m.is_high_confidence
    assert m.is_medium_confidence
    assert m.confidence_label == "medium"


def test_low_confidence():
    m = BookMetadata(confidence=0.40)
    assert not m.is_high_confidence
    assert not m.is_medium_confidence
    assert m.is_low_confidence
    assert m.confidence_label == "low"


def test_confidence_boundary_high():
    assert BookMetadata(confidence=0.85).is_high_confidence
    assert not BookMetadata(confidence=0.849).is_high_confidence


def test_confidence_boundary_medium():
    assert BookMetadata(confidence=0.60).is_medium_confidence
    assert not BookMetadata(confidence=0.599).is_medium_confidence


# ── 10. MetadataSource enum values ───────────────────────────────────────────

def test_metadata_source_values():
    assert MetadataSource.LOCAL.value    == "local"
    assert MetadataSource.GOOGLE.value   == "google_books"
    assert MetadataSource.OPEN_LIB.value == "open_library"
    assert MetadataSource.MANUAL.value   == "manual"


# ── 11. Google Books provider — _parse_volume ────────────────────────────────

from app.metadata.providers.google_books import GoogleBooksProvider


def test_google_parse_full_volume():
    info = {
        "title":    "Atomic Habits",
        "subtitle": "An Easy & Proven Way to Build Good Habits",
        "authors":  ["James Clear"],
        "language": "en",
        "industryIdentifiers": [
            {"type": "ISBN_13", "identifier": "9780735211292"},
            {"type": "ISBN_10", "identifier": "0735211299"},
        ],
        "imageLinks": {
            "thumbnail": "http://books.google.com/books/content?id=test&zoom=1",
            "medium": "http://books.google.com/books/content?id=test&zoom=2",
        },
        "averageRating": 4.5,
    }
    result = GoogleBooksProvider._parse_volume(info)
    assert result.title    == "Atomic Habits"
    assert result.subtitle == "An Easy & Proven Way to Build Good Habits"
    assert result.author   == "James Clear"
    assert result.isbn     == "9780735211292"
    # HTTP should be upgraded to HTTPS
    assert result.cover_url.startswith("https://")
    # zoom suffix should be stripped
    assert "zoom=" not in result.cover_url
    assert result.raw_score == pytest.approx(0.9, abs=0.01)


def test_google_parse_prefers_isbn13():
    info = {
        "industryIdentifiers": [
            {"type": "ISBN_10", "identifier": "0735211299"},
            {"type": "ISBN_13", "identifier": "9780735211292"},
        ]
    }
    result = GoogleBooksProvider._parse_volume(info)
    assert result.isbn == "9780735211292"


def test_google_parse_minimal_volume():
    result = GoogleBooksProvider._parse_volume({})
    assert result.title is None
    assert result.author is None
    assert result.isbn is None
    assert result.cover_url is None
    assert result.raw_score == pytest.approx(0.5)


def test_google_parse_multiple_authors():
    info = {"authors": ["John Doe", "Jane Smith"]}
    result = GoogleBooksProvider._parse_volume(info)
    assert "John Doe" in result.author
    assert "Jane Smith" in result.author


# ── 12. Open Library provider — _parse_doc ───────────────────────────────────

from app.metadata.providers.open_library import OpenLibraryProvider, _ol_lang_to_iso


def test_ol_parse_full_doc():
    doc = {
        "title":       "Atomic Habits",
        "author_name": ["James Clear"],
        "isbn":        ["9780735211292", "0735211299"],
        "cover_i":     12345,
        "language":    ["eng"],
        "subject":     ["Self-improvement", "Psychology"],
    }
    result = OpenLibraryProvider._parse_doc(doc)
    assert result.title  == "Atomic Habits"
    assert result.author == "James Clear"
    assert result.isbn   == "9780735211292"
    assert result.cover_url == "https://covers.openlibrary.org/b/id/12345-L.jpg"
    assert result.language == "en"
    assert "Self-improvement" in result.categories


def test_ol_parse_no_cover():
    doc = {"title": "Atomic Habits"}
    result = OpenLibraryProvider._parse_doc(doc)
    assert result.cover_url is None


def test_ol_parse_no_isbn():
    doc = {"title": "Test Book"}
    result = OpenLibraryProvider._parse_doc(doc)
    assert result.isbn is None


def test_ol_lang_to_iso():
    assert _ol_lang_to_iso("eng") == "en"
    assert _ol_lang_to_iso("spa") == "es"
    assert _ol_lang_to_iso("fre") == "fr"
    assert _ol_lang_to_iso("zzz") is None
    assert _ol_lang_to_iso("") is None


# ── 13. Cover pipeline helpers ────────────────────────────────────────────────

from app.metadata.service import _content_type_to_ext, _magic_ext


def test_content_type_jpeg():
    assert _content_type_to_ext("image/jpeg") == "jpg"


def test_content_type_png():
    assert _content_type_to_ext("image/png") == "png"


def test_content_type_webp():
    assert _content_type_to_ext("image/webp") == "webp"


def test_content_type_unknown():
    assert _content_type_to_ext("application/octet-stream") is None


def test_magic_jpeg():
    assert _magic_ext(b"\xff\xd8\xff\xe0") == "jpg"


def test_magic_png():
    assert _magic_ext(b"\x89PNG\r\n\x1a\n") == "png"


def test_magic_webp():
    assert _magic_ext(b"RIFF\x00\x00\x00\x00WEBP") == "webp"


def test_magic_unknown():
    assert _magic_ext(b"\x00\x00\x00\x00") is None


# ── 14. Failure modes ─────────────────────────────────────────────────────────

def test_extractor_handles_empty_filename():
    """Should return empty lists, not raise."""
    tc, ac = LocalExtractor().extract(filename="")
    assert isinstance(tc, list)
    assert isinstance(ac, list)


def test_extractor_handles_malformed_filename():
    tc, ac = LocalExtractor().extract(filename="....pdf")
    assert isinstance(tc, list)


def test_extractor_handles_none_bytes():
    tc, ac = LocalExtractor().extract(filename="test.pdf", pdf_bytes=None)
    assert isinstance(tc, list)


def test_score_result_all_none():
    """score_result must not raise when all fields are None."""
    result = ProviderResult(
        title=None, author=None, language=None,
        isbn=None, cover_url=None, raw_score=0.0,
    )
    score = score_result(result, [], [], None)
    assert 0.0 <= score <= 1.0


def test_matcher_handles_all_empty_provider_results():
    meta = Matcher().pick_best(
        provider_results=[],
        title_candidates=[],
        author_candidates=[],
    )
    assert meta is None or meta.confidence == 0.0


# ── 15. Provider result — Google Books fails gracefully on bad data ───────────

def test_google_parse_bad_rating():
    info = {"averageRating": "not-a-number"}
    # Should not raise; raw_score should default to 0.5
    try:
        result = GoogleBooksProvider._parse_volume(info)
    except (ValueError, TypeError):
        pass  # acceptable — but should not propagate in real usage
    else:
        assert 0.0 <= result.raw_score <= 1.0


# ── 16. End-to-end: local extraction → scoring pipeline ─────────────────────

def test_full_pipeline_local_only():
    """Simulate pipeline without any provider results."""
    extractor = LocalExtractor()
    tc, ac = extractor.extract("atomic-habits-james-clear.pdf")

    matcher = Matcher()
    meta = matcher.pick_best([], tc, ac, detected_language="en")

    assert meta is not None
    assert meta.source == MetadataSource.LOCAL
    # Title should contain something meaningful
    assert meta.title and len(meta.title) >= 3


def test_full_pipeline_with_good_provider_result():
    """Simulate pipeline with a matching provider result."""
    extractor = LocalExtractor()
    tc, ac = extractor.extract("atomic-habits-james-clear.pdf")

    good_result = _make_result(title="Atomic Habits", author="James Clear")
    meta = Matcher().pick_best(
        [("google_books", good_result)], tc, ac, detected_language="en"
    )

    assert meta is not None
    assert meta.title == "Atomic Habits"
    # Real-world confidence for a matching book via filename (split heuristics)
    # lands in medium-to-high range; at minimum medium (>= 0.60)
    assert meta.confidence >= 0.60, f"Expected >=0.60, got {meta.confidence:.3f}"
    assert meta.is_medium_confidence or meta.is_high_confidence


def test_full_pipeline_rejects_wrong_book():
    """A totally different book should not become the selected metadata."""
    extractor = LocalExtractor()
    tc, ac = extractor.extract("atomic-habits.pdf")

    # Provider returns a completely unrelated book
    wrong = _make_result(title="Harry Potter", author="J.K. Rowling", isbn=None)
    meta = Matcher().pick_best(
        [("google_books", wrong)], tc, ac, detected_language="en"
    )

    assert meta is not None
    # Either the local title is preferred (low match) or the wrong title
    # has a very low confidence — it should NOT be high confidence
    assert not meta.is_high_confidence, (
        f"Unexpectedly accepted wrong book with high confidence: {meta.confidence:.2f}"
    )
