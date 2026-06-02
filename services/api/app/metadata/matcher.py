"""
Metadata Matcher & Scorer
==========================
Scores each provider result against the extracted local candidates
to pick the best match and compute a confidence score.

Scoring components (each 0.0–1.0, then weighted):
  title_similarity   0.40  — fuzzy match between provider title and filename/PDF title
  author_similarity  0.25  — fuzzy match on author name
  isbn_bonus         0.10  — bonus when ISBN is present (trustworthy signal)
  language_match     0.10  — bonus when detected language matches provider language
  provider_quality   0.10  — provider's own quality signal (rating, completeness)
  cover_bonus        0.05  — bonus when a cover image URL is available

Final confidence is the weighted sum, clamped to [0.0, 1.0].
"""

from __future__ import annotations

import logging
import re
import unicodedata
from difflib import SequenceMatcher
from typing import Optional

from app.metadata.models import TitleCandidate, AuthorCandidate, BookMetadata, MetadataSource
from app.metadata.providers.base import ProviderResult

logger = logging.getLogger(__name__)

# Scoring weights (must sum to 1.0)
_W_TITLE    = 0.40
_W_AUTHOR   = 0.25
_W_ISBN     = 0.10
_W_LANG     = 0.10
_W_QUALITY  = 0.10
_W_COVER    = 0.05

assert abs(sum([_W_TITLE, _W_AUTHOR, _W_ISBN, _W_LANG, _W_QUALITY, _W_COVER]) - 1.0) < 1e-9


def _normalize(s: str) -> str:
    """
    Normalize a string for fuzzy comparison:
    - Lowercase
    - Remove accents (NFKD + ASCII encode)
    - Remove punctuation except spaces
    - Collapse whitespace
    """
    if not s:
        return ""
    # NFKD decompose + strip non-ASCII
    nfkd = unicodedata.normalize("NFKD", s)
    ascii_str = nfkd.encode("ascii", "ignore").decode("ascii")
    # Keep letters, digits, spaces
    clean = re.sub(r"[^a-z0-9 ]", "", ascii_str.lower())
    return " ".join(clean.split())


def _fuzzy_ratio(a: str, b: str) -> float:
    """
    SequenceMatcher ratio for normalized strings.
    Returns 0.0–1.0.  Handles empty strings.
    """
    na, nb = _normalize(a), _normalize(b)
    if not na or not nb:
        return 0.0
    return SequenceMatcher(None, na, nb).ratio()


def score_result(
    result: ProviderResult,
    title_candidates: list[TitleCandidate],
    author_candidates: list[AuthorCandidate],
    detected_language: Optional[str] = None,
) -> float:
    """
    Compute a 0.0–1.0 confidence score for a single provider result.

    Uses the best-matching local candidate for title and author.
    """
    # ── Title similarity ──────────────────────────────────────────────────────
    title_sim = 0.0
    if result.title and title_candidates:
        ratios = [
            _fuzzy_ratio(result.title, c.value) * c.weight
            for c in title_candidates
        ]
        title_sim = max(ratios)

    # ── Author similarity ─────────────────────────────────────────────────────
    author_sim = 0.0
    if result.author and author_candidates:
        ratios = []
        for c in author_candidates:
            # Also try matching individual parts of the name
            r = max(
                _fuzzy_ratio(result.author, c.value),
                _last_name_ratio(result.author, c.value),
            ) * c.weight
            ratios.append(r)
        author_sim = max(ratios) if ratios else 0.0
    elif not author_candidates:
        # No author info locally — don't penalise (author unknown)
        author_sim = 0.3

    # ── ISBN bonus ────────────────────────────────────────────────────────────
    isbn_score = 0.8 if result.isbn else 0.0

    # ── Language match ────────────────────────────────────────────────────────
    lang_score = 0.0
    if detected_language and result.language:
        lang_score = 1.0 if detected_language.lower().startswith(result.language.lower()[:2]) else 0.0
    elif not result.language:
        lang_score = 0.3  # no info — no penalty

    # ── Provider quality ──────────────────────────────────────────────────────
    quality_score = float(result.raw_score or 0.0)

    # ── Cover bonus ───────────────────────────────────────────────────────────
    cover_score = 1.0 if result.cover_url else 0.0

    # ── Weighted total ────────────────────────────────────────────────────────
    total = (
        title_sim  * _W_TITLE
        + author_sim * _W_AUTHOR
        + isbn_score * _W_ISBN
        + lang_score * _W_LANG
        + quality_score * _W_QUALITY
        + cover_score * _W_COVER
    )
    return max(0.0, min(1.0, total))


def _last_name_ratio(a: str, b: str) -> float:
    """
    Compare the last name component of two name strings.
    Handles "James Clear" vs "Clear, James" variants.
    """
    a_last = _normalize(a.split()[-1] if a.split() else a)
    b_last = _normalize(b.split()[-1] if b.split() else b)
    if not a_last or not b_last:
        return 0.0
    return SequenceMatcher(None, a_last, b_last).ratio()


class Matcher:
    """
    Matches provider results against local candidates and picks the best.
    """

    def pick_best(
        self,
        provider_results: list[tuple[str, ProviderResult]],  # [(source_name, result), ...]
        title_candidates: list[TitleCandidate],
        author_candidates: list[AuthorCandidate],
        detected_language: Optional[str] = None,
    ) -> Optional[BookMetadata]:
        """
        Score all results, return the highest-confidence BookMetadata,
        or None if no result exceeds 0.0 (should never happen in practice).

        When provider_results is empty, builds a LOCAL result from candidates.
        """
        if not provider_results:
            return self._local_only(title_candidates, author_candidates)

        best_score   = -1.0
        best_result  = None
        best_source  = MetadataSource.LOCAL

        for source_name, result in provider_results:
            s = score_result(
                result, title_candidates, author_candidates, detected_language
            )
            logger.debug(
                "[METADATA] scored source=%s title=%r score=%.3f",
                source_name, result.title, s,
            )
            if s > best_score:
                best_score  = s
                best_result = result
                best_source = (
                    MetadataSource.GOOGLE
                    if source_name == "google_books"
                    else MetadataSource.OPEN_LIB
                )

        if best_result is None:
            return self._local_only(title_candidates, author_candidates)

        # Blend: if local extraction has a good title candidate but the API
        # has a slightly better one, use the API title only if the score is
        # sufficiently high; otherwise fall back to local.
        final_title = (
            best_result.title
            if best_score >= 0.5 and best_result.title
            else (title_candidates[0].value if title_candidates else None)
        )
        final_author = (
            best_result.author
            if best_score >= 0.5 and best_result.author
            else (author_candidates[0].value if author_candidates else None)
        )

        return BookMetadata(
            title=final_title,
            subtitle=best_result.subtitle,
            author=final_author,
            language=best_result.language or detected_language,
            isbn=best_result.isbn,
            categories=best_result.categories,
            cover_url=best_result.cover_url,
            source=best_source,
            confidence=best_score,
            title_candidates=title_candidates,
            author_candidates=author_candidates,
        )

    @staticmethod
    def _local_only(
        title_candidates: list[TitleCandidate],
        author_candidates: list[AuthorCandidate],
    ) -> Optional[BookMetadata]:
        """Build a metadata result from local extraction only."""
        title  = title_candidates[0].value  if title_candidates  else None
        author = author_candidates[0].value if author_candidates else None
        # Local-only: low confidence (can't verify against authoritative DB)
        confidence = 0.35 if title else 0.0
        return BookMetadata(
            title=title,
            author=author,
            source=MetadataSource.LOCAL,
            confidence=confidence,
            title_candidates=title_candidates,
            author_candidates=author_candidates,
        )
