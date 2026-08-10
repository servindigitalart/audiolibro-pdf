"""
Heuristic Chapter Detector
===========================
BLOCK 6B: Text Segmentation & Chapter Detection Layer

Detects chapters using per-line regex pattern matching and structural heuristics.

Detection methods produced:
- chapter_keyword  — matched a language keyword (Chapter, Capítulo, etc.)
- roman_numeral    — bare Roman numeral line (I, II … VIII, etc.)

Key behaviours vs. v1:
- Scans first 15 *non-empty* lines per page (was 5 total lines incl. blanks)
- Per-line matching — each line is tested individually so anchored patterns
  cannot accidentally skip lines inside the joined block
- Standalone Roman numerals are detected with context-based confidence
- TOC pages and TOC-filler lines are skipped to avoid false positives
- Spanish coverage expanded: Roman numerals + words seis-doce
- numeric_dot requires a capital word after the dot (not a mid-sentence digit)
"""

import logging
import re
from typing import List, Optional, Tuple

from app.services.document_structure.models import DetectedChapter, PageText

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Roman numeral tables
# ---------------------------------------------------------------------------

# Explicit set of valid Roman chapter numbers 1–30 (uppercase)
_ROMAN_CHAPTER_SET: frozenset = frozenset({
    "I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X",
    "XI", "XII", "XIII", "XIV", "XV", "XVI", "XVII", "XVIII", "XIX", "XX",
    "XXI", "XXII", "XXIII", "XXIV", "XXV", "XXVI", "XXVII", "XXVIII", "XXIX", "XXX",
})

# Single-character Romans are ambiguous (I = English pronoun, V/X = abbreviations)
_ROMAN_AMBIGUOUS: frozenset = frozenset({"I", "V", "X"})


# ---------------------------------------------------------------------------
# TOC filters
# ---------------------------------------------------------------------------

# A line that ends with "....3" or "  3" after several dots/dashes = TOC entry
_TOC_PAGE_NUM_RE = re.compile(r"[.·–—\s]{3,}\d+\s*$")
# Long stretch of filler characters anywhere in line
_TOC_FILLER_RE = re.compile(r"[.·–—]{5,}")


# ---------------------------------------------------------------------------
# Keyword patterns (tested per line with re.IGNORECASE | re.UNICODE)
# (pattern_string, base_confidence, detection_method)
# ---------------------------------------------------------------------------

_LINE_PATTERNS: List[Tuple[str, str, float]] = [
    # ── English ──────────────────────────────────────────────────────────────
    (r"^chapter\s+(\d+)", "chapter_keyword", 0.85),
    (r"^chapter\s+(one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)", "chapter_keyword", 0.85),
    (r"^chapter\s+([ivxlcdm]+)", "chapter_keyword", 0.85),
    (r"^CHAPTER\s+(\d+|[IVXLCDM]+)", "chapter_keyword", 0.88),
    (r"^part\s+(\d+|[ivxlcdm]+)", "chapter_keyword", 0.75),
    (r"^PART\s+(\d+|[IVXLCDM]+)", "chapter_keyword", 0.75),

    # ── Spanish ──────────────────────────────────────────────────────────────
    # Numbers
    (r"^cap[ií]tulo\s+(\d+)", "chapter_keyword", 0.88),
    # Roman numerals (the main gap fixed here)
    (r"^cap[ií]tulo\s+([ivxlcdm]+)", "chapter_keyword", 0.88),
    # Spanish words (uno–doce, expanded from cinco)
    (
        r"^cap[ií]tulo\s+"
        r"(uno|dos|tres|cuatro|cinco|seis|siete|ocho|nueve|diez|once|doce)",
        "chapter_keyword",
        0.88,
    ),
    # All-caps variants (CAPÍTULO / CAPITULO)
    (r"^CAP[IÍ]TULO\s+(\d+)", "chapter_keyword", 0.88),
    (r"^CAP[IÍ]TULO\s+([IVXLCDM]+)", "chapter_keyword", 0.88),
    (
        r"^CAP[IÍ]TULO\s+"
        r"(UNO|DOS|TRES|CUATRO|CINCO|SEIS|SIETE|OCHO|NUEVE|DIEZ|ONCE|DOCE)",
        "chapter_keyword",
        0.88,
    ),
    # Abbreviated forms: Cap. I, Cap. 1
    (r"^cap\.\s*(\d+|[ivxlcdm]+)", "chapter_keyword", 0.78),

    # ── French ───────────────────────────────────────────────────────────────
    (r"^chapitre\s+(\d+|[ivxlcdm]+)", "chapter_keyword", 0.85),
    (r"^CHAPITRE\s+(\d+|[IVXLCDM]+)", "chapter_keyword", 0.88),

    # ── German ───────────────────────────────────────────────────────────────
    (r"^kapitel\s+(\d+|[ivxlcdm]+)", "chapter_keyword", 0.85),

    # ── Generic ──────────────────────────────────────────────────────────────
    (r"^section\s+(\d+)", "chapter_keyword", 0.70),
    # Numbered heading: "3. Title word" — requires a capital letter after dot
    (r"^(\d{1,2})[.)]\s+[A-ZÁÉÍÓÚÜÑ\w]", "chapter_keyword", 0.62),
]

# Compile once at import time
_COMPILED_PATTERNS = [
    (re.compile(pat, re.IGNORECASE | re.UNICODE), method, conf)
    for pat, method, conf in _LINE_PATTERNS
]


# ---------------------------------------------------------------------------
# Detector
# ---------------------------------------------------------------------------


class HeuristicDetector:
    """
    Detect chapters using heuristic pattern matching.

    Produces DetectedChapter objects with detection_method in:
      "chapter_keyword" | "roman_numeral"
    """

    def detect_chapters(
        self,
        pages: List[PageText],
        min_confidence: float = 0.6,
    ) -> List[DetectedChapter]:
        """
        Scan each page's leading non-empty lines for chapter headings.

        Args:
            pages: Extracted page texts (with page_number, text, font_sizes)
            min_confidence: Detections below this threshold are discarded

        Returns:
            List of DetectedChapters sorted by start_page
        """
        detected: List[DetectedChapter] = []

        logger.info(
            "[SONORO] chapter_detection_started method=heuristic pages=%d",
            len(pages),
        )

        for page_idx, page in enumerate(pages):
            all_lines = page.text.split("\n")
            nonempty = [l for l in all_lines if l.strip()]

            if not nonempty:
                continue

            # Skip table-of-contents pages
            if _is_toc_page(nonempty):
                logger.debug(
                    "[SONORO] toc_page_skipped page=%d",
                    page.page_number,
                )
                continue

            result = _find_chapter_heading(nonempty, page.page_number)
            if result is None:
                continue

            pattern_name, title, confidence = result

            if confidence < min_confidence:
                continue

            start_page = page.page_number
            end_page = (
                pages[-1].page_number
                if page_idx == len(pages) - 1
                else pages[page_idx + 1].page_number - 1
            )

            chapter = DetectedChapter(
                title=title,
                start_page=start_page,
                end_page=end_page,
                confidence=confidence,
                detection_method=pattern_name,
            )
            detected.append(chapter)

            logger.debug(
                "[SONORO] chapter_candidate page=%d line=%r method=%s confidence=%.2f",
                page.page_number,
                title[:60],
                pattern_name,
                confidence,
            )

        detected = _refine_chapter_ranges(detected)

        # The final chapter runs to the end of the document, not to the page
        # after its heading.
        if detected:
            detected[-1].end_page = max(
                pages[-1].page_number, detected[-1].start_page
            )

        avg_conf = (
            sum(c.confidence for c in detected) / len(detected) if detected else 0.0
        )
        logger.info(
            "[SONORO] chapters_detected count=%d method=heuristic avg_confidence=%.2f",
            len(detected),
            avg_conf,
        )
        return detected


# ---------------------------------------------------------------------------
# Module-level helpers (no self needed)
# ---------------------------------------------------------------------------


def _find_chapter_heading(
    nonempty_lines: List[str],
    page_number: int,
) -> Optional[Tuple[str, str, float]]:
    """
    Scan the first 15 non-empty lines for a chapter heading.

    Returns (detection_method, title, confidence) or None.
    """
    lines_to_check = nonempty_lines[:15]

    for line_idx, line in enumerate(lines_to_check):
        stripped = line.strip()
        if not stripped:
            continue

        # Skip TOC-filler lines
        if _is_toc_line(stripped):
            continue

        # 1. Keyword patterns
        for compiled_re, method, base_confidence in _COMPILED_PATTERNS:
            if compiled_re.match(stripped):
                title = _build_title(stripped, line_idx, lines_to_check)
                return method, title, base_confidence

        # 2. Standalone Roman numeral
        upper = stripped.upper()
        if upper in _ROMAN_CHAPTER_SET:
            confidence = _roman_context_confidence(upper, line_idx, nonempty_lines)
            if confidence >= 0.6:
                title = _build_title(stripped, line_idx, lines_to_check)
                return "roman_numeral", title, confidence

    return None


def _roman_context_confidence(
    roman: str,
    line_idx: int,
    nonempty_lines: List[str],
) -> float:
    """
    Context-adjusted confidence for a standalone Roman numeral.

    Multi-character Romans (VIII, VII, etc.) start at 0.82.
    Single-character Romans (I, V, X) start at 0.65 — still detectable
    but only above min_confidence when boosted by context.
    """
    base = 0.65 if roman in _ROMAN_AMBIGUOUS else 0.82

    # Position bonus: higher if at the very top of the page
    if line_idx == 0:
        base += 0.05
    elif line_idx == 1:
        base += 0.02

    # Density bonus: sparse pages look like chapter separator pages
    total = len(nonempty_lines)
    if total <= 3:
        base += 0.08
    elif total <= 6:
        base += 0.04

    return min(base, 0.95)


def _build_title(
    matched_line: str,
    line_idx: int,
    lines: List[str],
) -> str:
    """
    Build a chapter title from the matched line.

    For short headings (Roman numerals, bare "Chapter I"), includes the
    next non-empty line as a subtitle when it looks like a title.
    """
    title = matched_line.strip()

    if len(title) <= 20 and line_idx + 1 < len(lines):
        next_line = lines[line_idx + 1].strip()
        if (
            next_line
            and len(next_line) <= 120
            and not _is_toc_line(next_line)
            and next_line.upper() not in _ROMAN_CHAPTER_SET
        ):
            title = f"{title} — {next_line}"

    return _clean_title(title)


def _clean_title(title: str) -> str:
    title = " ".join(title.split())
    title = title.rstrip(":.,-")
    if len(title) > 200:
        title = title[:197] + "..."
    return title


def _is_toc_page(nonempty_lines: List[str]) -> bool:
    """Return True when the page looks like a table of contents."""
    if len(nonempty_lines) < 4:
        return False
    hits = sum(
        1
        for line in nonempty_lines[:30]
        if _TOC_PAGE_NUM_RE.search(line.strip())
    )
    return hits >= 4


def _is_toc_line(line: str) -> bool:
    """Return True when the line looks like a TOC entry."""
    return bool(_TOC_PAGE_NUM_RE.search(line)) or bool(_TOC_FILLER_RE.search(line))


def _refine_chapter_ranges(
    chapters: List[DetectedChapter],
) -> List[DetectedChapter]:
    """Set each chapter's end_page to one before the next chapter starts."""
    if not chapters:
        return chapters

    chapters_sorted = sorted(chapters, key=lambda c: c.start_page)

    for i in range(len(chapters_sorted) - 1):
        current = chapters_sorted[i]
        nxt = chapters_sorted[i + 1]
        current.end_page = nxt.start_page - 1
        if current.end_page < current.start_page:
            current.end_page = current.start_page

    return chapters_sorted
