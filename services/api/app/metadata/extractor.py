"""
Local Metadata Extractor
=========================
Derives title and author candidates purely from the uploaded document —
no network I/O, always succeeds.

Sources tried (in order):
  1. PDF embedded metadata (XMP / Info dictionary: Title, Author, Subject)
  2. Filename parsing (snake_case, kebab-case, CamelCase, spaces)
  3. First-page text: first heading-like line (large font on first page)

Returns a list of ranked TitleCandidate and AuthorCandidate objects.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# ── PDF embedded metadata keys ────────────────────────────────────────────────

_PDF_META_TITLE_KEYS  = ("title",)
_PDF_META_AUTHOR_KEYS = ("author", "creator")

# ── Pirate / scanner publisher blocklist ─────────────────────────────────────
#
# Pirated ebooks stamp their own branding in the PDF Title / Author fields.
# These values are useless (or actively harmful) as book-metadata candidates.
# Pattern is matched against the raw string (case-insensitive, anywhere).

_PIRATE_META_RE = re.compile(
    r"iafabooks|epub\s*libre|epublibre|biblioteca\s*digital|internet\s*archive|"
    r"epubcorrector|ebookcorrector|calibre|scannedpdfs|mobileread|"
    r"pdfbooks|libros?\s*en\s*red|booksxx|freeditorial|"
    r"manybooks|loyalbooks|epubmania",
    re.IGNORECASE,
)

# Publisher-watermark pattern: "XYZ 2007: Person Name" — a known pirate stamp
_PIRATE_STAMP_RE = re.compile(r"^\w{3,20}\s+\d{4}:\s+[A-Z]", re.ASCII)


def _is_trustworthy_pdf_meta(value: str) -> bool:
    """Return False when a PDF metadata value looks like a pirate/scanner watermark."""
    if _PIRATE_META_RE.search(value):
        return False
    if _PIRATE_STAMP_RE.match(value):
        return False
    # Reject anything shorter than 3 chars (not a real title/author)
    return len(value.strip()) >= 3


# ── Filename patterns ─────────────────────────────────────────────────────────

# Matches " by " after stem is normalized to spaces.
# Works for: "Deep Work by Cal Newport", "deep_work_by_cal_newport",
#            "deep-work-by-cal-newport" (all convert _ and - to spaces first).
_BY_PATTERN = re.compile(r"\s+by\s+", re.IGNORECASE)

# Minimum title length to be considered valid
_MIN_TITLE_LEN = 3

# Noise words that appear in filenames but not in real titles
_NOISE_WORDS = {
    "pdf", "epub", "doc", "docx", "ebook", "book", "the", "final",
    "v1", "v2", "v3", "copy", "draft", "original", "scan", "english",
    "download", "full", "complete", "official",
}


# ── Public API ────────────────────────────────────────────────────────────────

from app.metadata.models import TitleCandidate, AuthorCandidate


class LocalExtractor:
    """
    Fast, synchronous local metadata extraction.
    Never raises — all failures return empty lists.
    """

    def extract(
        self,
        filename: str,
        pdf_bytes: Optional[bytes] = None,
    ) -> tuple[list[TitleCandidate], list[AuthorCandidate]]:
        """
        Return (title_candidates, author_candidates), best first.

        Args:
            filename:   Original upload filename.
            pdf_bytes:  Raw PDF bytes (already read during upload).
                        None → skip PDF-specific extraction.
        """
        title_candidates:  list[TitleCandidate]  = []
        author_candidates: list[AuthorCandidate] = []

        # 1. PDF embedded metadata (most authoritative local source — when trusted)
        if pdf_bytes:
            tc, ac = self._from_pdf_metadata(pdf_bytes)
            title_candidates.extend(tc)
            author_candidates.extend(ac)

        # 2. Filename parsing
        tc, ac = self._from_filename(filename)
        title_candidates.extend(tc)
        author_candidates.extend(ac)

        # 3. First-page heading (if PDF available)
        if pdf_bytes:
            tc = self._from_first_page(pdf_bytes)
            title_candidates.extend(tc)

        # De-duplicate keeping first occurrence
        seen_titles: set[str] = set()
        unique_titles: list[TitleCandidate] = []
        for c in title_candidates:
            norm = c.value.lower().strip()
            if norm not in seen_titles and len(norm) >= _MIN_TITLE_LEN:
                seen_titles.add(norm)
                unique_titles.append(c)

        seen_authors: set[str] = set()
        unique_authors: list[AuthorCandidate] = []
        for c in author_candidates:
            norm = c.value.lower().strip()
            if norm not in seen_authors and len(norm) >= 2:
                seen_authors.add(norm)
                unique_authors.append(c)

        return unique_titles, unique_authors

    # ── Private helpers ───────────────────────────────────────────────────────

    def _from_pdf_metadata(
        self, pdf_bytes: bytes
    ) -> tuple[list[TitleCandidate], list[AuthorCandidate]]:
        titles:  list[TitleCandidate]  = []
        authors: list[AuthorCandidate] = []
        try:
            import fitz  # PyMuPDF
            doc = fitz.open(stream=pdf_bytes, filetype="pdf")
            meta = doc.metadata or {}
            doc.close()

            raw_title = meta.get("title", "").strip()
            if raw_title and _is_trustworthy_pdf_meta(raw_title):
                titles.append(TitleCandidate(
                    value=_clean_title(raw_title),
                    source="pdf_metadata",
                    weight=0.9,
                ))
            elif raw_title:
                logger.debug(
                    "[METADATA] pdf_metadata_title_rejected value=%r (pirate/watermark)",
                    raw_title[:60],
                )

            for key in _PDF_META_AUTHOR_KEYS:
                raw_author = meta.get(key, "").strip()
                if raw_author and _is_trustworthy_pdf_meta(raw_author):
                    authors.append(AuthorCandidate(
                        value=_clean_author(raw_author),
                        source=f"pdf_metadata_{key}",
                        weight=0.9,
                    ))
                    break  # take first found author key

        except Exception as exc:
            logger.debug("[METADATA] pdf_metadata_extraction_failed error=%s", exc)
        return titles, authors

    def _from_filename(
        self, filename: str
    ) -> tuple[list[TitleCandidate], list[AuthorCandidate]]:
        titles:  list[TitleCandidate]  = []
        authors: list[AuthorCandidate] = []

        # Strip extension
        stem = Path(filename).stem

        # Normalize separators to spaces for pattern matching (reverting after
        # splitting on "by" so the individual parts are still processed via
        # _normalize_filename_part).
        # e.g. "deep_work_by_cal_newport" → "deep work by cal newport"
        stem_spaced = re.sub(r"[-_]", " ", stem)

        # ── Strategy A: explicit " by " separator (most reliable) ──────────────
        # Works for both: "deep work by cal newport" and "Deep Work by Cal Newport"
        by_parts = _BY_PATTERN.split(stem_spaced, maxsplit=1)
        if len(by_parts) == 2:
            t_raw = _normalize_filename_part(by_parts[0])
            a_raw = _normalize_filename_part(by_parts[1])
            if len(t_raw) >= _MIN_TITLE_LEN:
                titles.append(TitleCandidate(value=t_raw, source="filename_by", weight=0.85))
            if len(a_raw) >= 2:
                authors.append(AuthorCandidate(value=a_raw, source="filename_by", weight=0.85))
            # Full stem as fallback title candidate even when by-split fires
            full_title = _normalize_filename_part(stem)
            if len(full_title) >= _MIN_TITLE_LEN:
                titles.append(TitleCandidate(value=full_title, source="filename_full", weight=0.4))
            return titles, authors

        # ── Strategy B: "title-author" separated by a SINGLE hyphen ────────────
        # Heuristic for common Latin-American ebook naming convention:
        #   el_llano_en_llamas-juan_rulfo  →  "El Llano en Llamas" + "Juan Rulfo"
        #   don_quijote-cervantes          →  "Don Quijote" + "Cervantes"
        #
        # Detection rule: stem contains underscores AND exactly one hyphen,
        # and the hyphen is NOT at the start or end.
        hyphen_count = stem.count("-")
        has_underscores = "_" in stem
        if has_underscores and hyphen_count == 1:
            hyp_idx = stem.index("-")
            if 0 < hyp_idx < len(stem) - 1:
                before = _normalize_filename_part(stem[:hyp_idx])
                after  = _normalize_filename_part(stem[hyp_idx + 1:])
                if len(before) >= _MIN_TITLE_LEN:
                    titles.append(TitleCandidate(
                        value=before, source="filename_hyphen_split", weight=0.75,
                    ))
                if len(after) >= 2:
                    authors.append(AuthorCandidate(
                        value=after, source="filename_hyphen_split", weight=0.75,
                    ))
                # Also add full-stem candidate in case the split was wrong
                full_title = _normalize_filename_part(stem)
                if len(full_title) >= _MIN_TITLE_LEN:
                    titles.append(TitleCandidate(
                        value=full_title, source="filename_full", weight=0.5,
                    ))
                return titles, authors

        # ── Strategy C: full stem as title (no author detected) ─────────────────
        full_title = _normalize_filename_part(stem)
        if len(full_title) >= _MIN_TITLE_LEN:
            titles.append(TitleCandidate(
                value=full_title, source="filename_full", weight=0.6,
            ))

        # Try extracting partial known pattern like "AtomicHabits-JamesClear"
        # where the last word(s) could be an author surname — but ONLY for
        # CamelCase filenames with no underscores (they're genuinely "AuthorTitle")
        words = full_title.split()
        if len(words) >= 4 and "_" not in stem:
            candidate_author = " ".join(words[-2:])
            candidate_title  = " ".join(words[:-2])
            if len(candidate_title) >= _MIN_TITLE_LEN and len(candidate_author) >= 4:
                titles.append(TitleCandidate(
                    value=candidate_title,
                    source="filename_split_last2",
                    weight=0.4,
                ))
                authors.append(AuthorCandidate(
                    value=candidate_author,
                    source="filename_split_last2",
                    weight=0.3,
                ))

        return titles, authors

    def _from_first_page(self, pdf_bytes: bytes) -> list[TitleCandidate]:
        candidates: list[TitleCandidate] = []
        try:
            import fitz
            doc = fitz.open(stream=pdf_bytes, filetype="pdf")
            if doc.page_count == 0:
                doc.close()
                return candidates

            page = doc[0]

            # Use dict extraction to get font sizes
            blocks = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)
            doc.close()

            # Collect (font_size, text) pairs
            texts_by_size: list[tuple[float, str]] = []
            for block in blocks.get("blocks", []):
                for line in block.get("lines", []):
                    for span in line.get("spans", []):
                        text = span.get("text", "").strip()
                        size = float(span.get("size", 0))
                        if text and size > 0 and len(text) >= _MIN_TITLE_LEN:
                            texts_by_size.append((size, text))

            if not texts_by_size:
                return candidates

            # The largest font text is likely the title
            texts_by_size.sort(key=lambda x: x[0], reverse=True)
            max_size = texts_by_size[0][0]

            # Gather all text spans with the largest (or very close) font size
            title_parts: list[str] = []
            for size, text in texts_by_size:
                if size >= max_size * 0.85:  # within 15% of max
                    cleaned = _clean_title(text)
                    if cleaned and cleaned.lower() not in _NOISE_WORDS and _is_trustworthy_pdf_meta(cleaned):
                        title_parts.append(cleaned)
                else:
                    break

            if title_parts:
                combined = " ".join(title_parts[:3]).strip()
                if len(combined) >= _MIN_TITLE_LEN:
                    candidates.append(TitleCandidate(
                        value=combined,
                        source="first_page_largest_font",
                        weight=0.75,
                    ))

        except Exception as exc:
            logger.debug("[METADATA] first_page_extraction_failed error=%s", exc)
        return candidates


# ── Text normalization helpers ─────────────────────────────────────────────────

def _normalize_filename_part(raw: str) -> str:
    """
    Convert filename segment to human-readable title.
    Handles: kebab-case, snake_case, CamelCase, spaces, dots.
    """
    # Replace separators with spaces
    s = re.sub(r"[-_.]", " ", raw)

    # Split CamelCase: "AtomicHabits" → "Atomic Habits"
    s = re.sub(r"([a-z])([A-Z])", r"\1 \2", s)
    s = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", s)

    # Collapse whitespace
    s = " ".join(s.split())

    # Title-case, dropping noise words (but keep if only ≤2 words remain)
    words = s.split()
    clean_words = [w for w in words if w.lower() not in _NOISE_WORDS or len(words) <= 2]
    if not clean_words:
        return ""
    return " ".join(w.capitalize() for w in clean_words)


def _clean_title(raw: str) -> str:
    """Normalize a title string: strip noise, fix casing if all-caps."""
    t = raw.strip()
    t = re.sub(r"\s*\([^)]*\)\s*$", "", t)  # remove trailing (parenthetical)
    t = re.sub(r"\s*-\s*\d{4}\s*$", "", t)   # remove trailing year "- 2020"
    if t == t.upper() and len(t.split()) > 2:
        t = t.title()
    return t.strip()


def _clean_author(raw: str) -> str:
    """Normalize author string."""
    a = raw.strip()
    # Some PDFs store "LastName, FirstName" — invert
    if re.match(r"^[^,]+,\s*[^,]+$", a):
        parts = a.split(",", 1)
        a = f"{parts[1].strip()} {parts[0].strip()}"
    return a.strip()


def _title_from_filename(filename: str) -> str:
    """Quick single-value extraction for use in simple contexts."""
    extractor = LocalExtractor()
    candidates, _ = extractor.extract(filename=filename)
    return candidates[0].value if candidates else Path(filename).stem
