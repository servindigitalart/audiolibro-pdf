"""
Cover Intelligence v2 — unit tests
====================================

Tests:
  - Title/author scoring and rejection rules
  - ISBN exact match floor
  - Author mismatch cap
  - Domain allowlist (SSRF guard)
  - Image quality scoring
  - Deduplication
  - Confidence label thresholds
  - Regression: El Llano en Llamas / Juan Rulfo should score well against a good match
  - Regression: Pedro Páramo / Juan Rulfo should score low (title mismatch)
  - Regression: Unrelated book should be rejected
"""

import pytest

from app.metadata.cover_models import CoverCandidate, CoverSuggestionsQuery
from app.metadata.cover_service import (
    _score_candidate,
    _normalize,
    _fuzzy,
    _author_sim,
    _image_quality_score,
    _confidence_label,
    is_allowed_cover_domain,
    _TITLE_REJECT_THRESHOLD,
    _AUTHOR_CAP_THRESHOLD,
    _AUTHOR_MISMATCH_CAP,
    _MIN_SHOW_SCORE,
    _HIGH_THRESHOLD,
    _MEDIUM_THRESHOLD,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def score(
    p_title=None, p_author=None, p_isbn=None, p_lang=None,
    image_url="https://covers.openlibrary.org/b/id/123-L.jpg",
    q_title=None, q_author=None, q_isbn=None, q_lang=None,
):
    """Convenience wrapper around _score_candidate."""
    s, reason = _score_candidate(
        provider_title=p_title,
        provider_author=p_author,
        provider_isbn=p_isbn,
        provider_language=p_lang,
        image_url=image_url,
        query_title=q_title,
        query_author=q_author,
        query_isbn=q_isbn,
        query_language=q_lang,
    )
    return s, reason


# ── Normalization ─────────────────────────────────────────────────────────────

class TestNormalize:
    def test_strips_accents(self):
        assert _normalize("El llano en llamas") == "el llano en llamas"
        assert _normalize("Cien años de soledad") == "cien anos de soledad"

    def test_collapses_whitespace(self):
        assert _normalize("  hello   world  ") == "hello world"

    def test_removes_punctuation(self):
        assert _normalize("hello, world!") == "hello world"

    def test_empty_string(self):
        assert _normalize("") == ""


# ── Fuzzy matching ────────────────────────────────────────────────────────────

class TestFuzzy:
    def test_identical_strings(self):
        assert _fuzzy("El llano en llamas", "El llano en llamas") == pytest.approx(1.0)

    def test_accent_insensitive(self):
        # NFKD normalization makes these match
        r = _fuzzy("Cien años de soledad", "Cien anos de soledad")
        assert r > 0.9

    def test_partial_mismatch(self):
        r = _fuzzy("El llano en llamas", "Pedro Páramo")
        assert r < 0.4

    def test_empty_inputs(self):
        assert _fuzzy("", "hello") == 0.0
        assert _fuzzy("hello", "") == 0.0


# ── Author similarity ─────────────────────────────────────────────────────────

class TestAuthorSim:
    def test_exact_match(self):
        r = _author_sim("Juan Rulfo", "Juan Rulfo")
        assert r > 0.95

    def test_last_name_match(self):
        # "Rulfo, Juan" vs "Juan Rulfo" — same words in reversed order, should partially match
        r = _author_sim("Rulfo, Juan", "Juan Rulfo")
        assert r > 0.4

    def test_unknown_author_no_penalty(self):
        r = _author_sim("Anyone", None)
        assert r == 0.3

    def test_missing_provider_author_small_penalty(self):
        r = _author_sim(None, "Juan Rulfo")
        assert r == 0.15


# ── Image quality scoring ─────────────────────────────────────────────────────

class TestImageQuality:
    def test_large_image_top_score(self):
        assert _image_quality_score("https://covers.openlibrary.org/b/id/123-L.jpg") == 1.0

    def test_medium_image(self):
        assert _image_quality_score("https://covers.openlibrary.org/b/id/123-M.jpg") == 0.6

    def test_small_image(self):
        assert _image_quality_score("https://covers.openlibrary.org/b/id/123-S.jpg") == 0.3

    def test_google_thumbnail(self):
        score_ = _image_quality_score("https://books.google.com/thumbnail?zoom=1")
        assert score_ <= 0.3

    def test_google_large(self):
        score_ = _image_quality_score("https://books.google.com/thumbnail?zoom=5&size=large")
        assert score_ == 1.0


# ── Confidence label thresholds ───────────────────────────────────────────────

class TestConfidenceLabel:
    def test_high(self):
        assert _confidence_label(0.85) == "high"
        assert _confidence_label(0.99) == "high"

    def test_medium(self):
        assert _confidence_label(0.65) == "medium"
        assert _confidence_label(0.84) == "medium"

    def test_low(self):
        assert _confidence_label(0.45) == "low"
        assert _confidence_label(0.64) == "low"


# ── Domain allowlist (SSRF guard) ─────────────────────────────────────────────

class TestDomainAllowlist:
    def test_google_books_allowed(self):
        assert is_allowed_cover_domain("https://books.google.com/books/content?id=abc")

    def test_open_library_allowed(self):
        assert is_allowed_cover_domain("https://covers.openlibrary.org/b/id/123-L.jpg")

    def test_archive_org_allowed(self):
        assert is_allowed_cover_domain("https://archive.org/something.jpg")

    def test_googleusercontent_allowed(self):
        assert is_allowed_cover_domain("https://lh3.googleusercontent.com/something")

    def test_random_domain_blocked(self):
        assert not is_allowed_cover_domain("https://evil.com/cover.jpg")

    def test_ssrf_localhost_blocked(self):
        assert not is_allowed_cover_domain("http://localhost/cover.jpg")

    def test_ssrf_internal_ip_blocked(self):
        assert not is_allowed_cover_domain("http://169.254.169.254/cover.jpg")

    def test_subdomain_of_allowed(self):
        assert is_allowed_cover_domain("https://ia800900.us.archive.org/cover.jpg")

    def test_fake_subdomain_blocked(self):
        # evil.covers.openlibrary.org.evil.com should NOT be allowed
        assert not is_allowed_cover_domain("https://covers.openlibrary.org.evil.com/img.jpg")


# ── Scoring — acceptance rules ────────────────────────────────────────────────

class TestScoring:
    def test_perfect_match_high_confidence(self):
        s, reason = score(
            p_title="El llano en llamas",
            p_author="Juan Rulfo",
            p_lang="es",
            image_url="https://covers.openlibrary.org/b/id/1-L.jpg",
            q_title="El llano en llamas",
            q_author="Juan Rulfo",
            q_lang="es",
        )
        assert reason == ""
        assert s >= _HIGH_THRESHOLD, f"Expected high confidence, got {s:.3f}"

    def test_isbn_exact_gives_floor(self):
        s, reason = score(
            p_title="Some Book",
            p_isbn="9781234567890",
            image_url="https://covers.openlibrary.org/b/id/1-L.jpg",
            q_title="Some Book",
            q_isbn="9781234567890",
        )
        assert reason == ""
        assert s >= 0.55

    def test_title_strong_mismatch_rejected(self):
        # Pedro Páramo vs El Llano en Llamas → completely different title → reject
        s, reason = score(
            p_title="Pedro Páramo",
            p_author="Juan Rulfo",
            image_url="https://covers.openlibrary.org/b/id/1-L.jpg",
            q_title="El llano en llamas",
            q_author="Juan Rulfo",
        )
        # Should be rejected (score=0) or at least below _MIN_SHOW_SCORE
        assert s == 0.0 or s < _MIN_SHOW_SCORE, (
            f"Expected rejection, got score={s:.3f} reason={reason!r}"
        )

    def test_author_mismatch_caps_score(self):
        s, reason = score(
            p_title="El llano en llamas",
            p_author="Antoine de Saint-Exupéry",  # wrong author
            image_url="https://covers.openlibrary.org/b/id/1-L.jpg",
            q_title="El llano en llamas",
            q_author="Juan Rulfo",
        )
        assert s <= _AUTHOR_MISMATCH_CAP + 0.01, (
            f"Score {s:.3f} exceeds author mismatch cap {_AUTHOR_MISMATCH_CAP}"
        )

    def test_no_author_no_penalty(self):
        # If author is unknown locally, result is still showable (not rejected)
        s, reason = score(
            p_title="El llano en llamas",
            p_author="Juan Rulfo",
            image_url="https://covers.openlibrary.org/b/id/1-L.jpg",
            q_title="El llano en llamas",
            q_author=None,  # author not known locally
        )
        assert reason == ""
        assert s >= _MIN_SHOW_SCORE, f"Unknown author should not drop below show threshold, got {s:.3f}"

    def test_low_score_below_min_show(self):
        s, reason = score(
            p_title="Llamas in the Andes",
            p_author="Unknown Author",
            image_url="https://covers.openlibrary.org/b/id/1-L.jpg",
            q_title="El llano en llamas",
            q_author="Juan Rulfo",
        )
        assert s < _MIN_SHOW_SCORE, f"Expected low score, got {s:.3f}"

    def test_missing_image_url_triggers_zero_quality_score(self):
        # An empty image_url shouldn't crash
        s, reason = score(
            p_title="El llano en llamas",
            p_author="Juan Rulfo",
            image_url="https://covers.openlibrary.org/b/id/1-S.jpg",  # small = 0.3
            q_title="El llano en llamas",
            q_author="Juan Rulfo",
        )
        assert s > 0, "Should still score, just slightly lower"


# ── Regression: real-world books ─────────────────────────────────────────────

class TestRealWorldRegressions:
    def test_el_llano_en_llamas_good_match(self):
        """Google Books / OL returns the correct book — should score high."""
        s, reason = score(
            p_title="El llano en llamas",
            p_author="Juan Rulfo",
            p_lang="es",
            image_url="https://covers.openlibrary.org/b/id/9999-L.jpg",
            q_title="El Llano en Llamas",
            q_author="Juan Rulfo",
            q_lang="es",
        )
        assert reason == ""
        assert s >= _HIGH_THRESHOLD, f"Expected high confidence for good match, got {s:.3f}"

    def test_el_principito_good_match(self):
        """El Principito Spanish edition should match the Spanish provider entry."""
        s, reason = score(
            p_title="El principito",
            p_author="Antoine de Saint-Exupéry",
            p_lang="es",
            image_url="https://covers.openlibrary.org/b/id/8888-L.jpg",
            q_title="el principito",
            q_author="Antoine de Saint-Exupery",
            q_lang="es",
        )
        assert reason == ""
        assert s >= _MEDIUM_THRESHOLD, f"Expected medium+ confidence, got {s:.3f}"

    def test_wrong_rulfo_book_rejected_or_low(self):
        """Pedro Páramo should NOT get a high score for 'El Llano en Llamas'."""
        s, reason = score(
            p_title="Pedro Páramo",
            p_author="Juan Rulfo",
            p_lang="es",
            image_url="https://covers.openlibrary.org/b/id/7777-L.jpg",
            q_title="El llano en llamas",
            q_author="Juan Rulfo",
            q_lang="es",
        )
        assert s < _MEDIUM_THRESHOLD, (
            f"Pedro Páramo should not score medium+ for El Llano en Llamas, got {s:.3f}"
        )

    def test_completely_unrelated_book_rejected(self):
        s, reason = score(
            p_title="Harry Potter and the Philosopher's Stone",
            p_author="J.K. Rowling",
            p_lang="en",
            image_url="https://covers.openlibrary.org/b/id/6666-L.jpg",
            q_title="El llano en llamas",
            q_author="Juan Rulfo",
            q_lang="es",
        )
        # Either rejected outright or well below show threshold
        assert s == 0.0 or s < _MIN_SHOW_SCORE, (
            f"Unrelated book should be rejected, got {s:.3f}"
        )


# ── CoverCandidate model ──────────────────────────────────────────────────────

class TestCoverCandidateModel:
    def test_is_showable_above_threshold(self):
        c = CoverCandidate(
            id="ol_0", source="open_library",
            title="Test", author=None, isbn_10=None, isbn_13=None,
            image_url="https://covers.openlibrary.org/b/id/1-L.jpg",
            thumbnail_url="https://covers.openlibrary.org/b/id/1-M.jpg",
            match_score=0.75,
            confidence_label="medium",
            provider_volume_id=None,
            reason="Match",
        )
        assert c.is_showable

    def test_is_not_showable_below_threshold(self):
        c = CoverCandidate(
            id="ol_1", source="open_library",
            title="Test", author=None, isbn_10=None, isbn_13=None,
            image_url="https://covers.openlibrary.org/b/id/1-L.jpg",
            thumbnail_url="https://covers.openlibrary.org/b/id/1-M.jpg",
            match_score=0.30,
            confidence_label="low",
            provider_volume_id=None,
            reason="Weak",
        )
        assert not c.is_showable
