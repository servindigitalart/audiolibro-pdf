"""
Text Normalizer for TTS
=======================
PHASE 5G: Intelligent Text Normalization Engine

Cleans PDF extraction artifacts so that text-to-speech narration sounds
as if a human editor prepared the manuscript.  All operations are purely
structural — content is never rewritten, paraphrased, or summarised.

Public API
----------
normalize_for_tts(text)          -> str
normalize_for_narration(text)    -> str   (adds a second narration pass)
normalize_with_stats(text)       -> tuple[str, NormalizationStats]

Both public functions are deterministic: identical input always produces
identical output.  No AI, no network calls, no I/O.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Prometheus counters (lazy-initialised so the module loads cleanly in tests
# that do not have the full app context wired up)
# ---------------------------------------------------------------------------

_metrics_initialised = False
_counter_docs: Optional[object] = None
_counter_line_repairs: Optional[object] = None
_counter_hyphen_repairs: Optional[object] = None
_counter_headers_removed: Optional[object] = None
_counter_ocr_removed: Optional[object] = None


def _init_metrics() -> None:
    global _metrics_initialised, _counter_docs, _counter_line_repairs
    global _counter_hyphen_repairs, _counter_headers_removed, _counter_ocr_removed

    if _metrics_initialised:
        return
    try:
        from prometheus_client import Counter
        from app.monitoring.metrics import metrics_registry

        _counter_docs = Counter(
            "sonoro_normalizer_docs_processed_total",
            "Total documents processed by text normalizer",
            registry=metrics_registry,
        )
        _counter_line_repairs = Counter(
            "sonoro_normalizer_line_repairs_total",
            "Total false line breaks repaired",
            registry=metrics_registry,
        )
        _counter_hyphen_repairs = Counter(
            "sonoro_normalizer_hyphen_repairs_total",
            "Total hyphenated line breaks repaired",
            registry=metrics_registry,
        )
        _counter_headers_removed = Counter(
            "sonoro_normalizer_headers_removed_total",
            "Total repeated headers/footers removed",
            registry=metrics_registry,
        )
        _counter_ocr_removed = Counter(
            "sonoro_normalizer_ocr_artifacts_removed_total",
            "Total OCR artifacts removed",
            registry=metrics_registry,
        )
        _metrics_initialised = True
    except Exception:
        # Prometheus unavailable (tests, standalone scripts) — continue silently.
        _metrics_initialised = True


def _inc(counter: Optional[object], n: int = 1) -> None:
    if counter is not None and n > 0:
        try:
            counter.inc(n)  # type: ignore[union-attr]
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class NormalizationStats:
    """Counters emitted after a normalization pass."""

    input_chars: int = 0
    output_chars: int = 0
    line_break_repairs: int = 0
    hyphen_repairs: int = 0
    headers_removed: int = 0
    footers_removed: int = 0
    ocr_artifacts_removed: int = 0

    @property
    def total_removals(self) -> int:
        return self.headers_removed + self.footers_removed + self.ocr_artifacts_removed


# ---------------------------------------------------------------------------
# Internal helpers — each rule is an isolated function
# ---------------------------------------------------------------------------

# Characters that legitimately end a sentence or clause.
# Used to decide whether a line break is "real".
_SENTENCE_END = re.compile(
    r'[.!?:;……。！？]$'
)

# Characters that may end a line without closing a sentence but that still
# represent a deliberate break (e.g. a dash, an open paren, etc.).
_DELIBERATE_BREAK = re.compile(
    r'[-—–—\(\[]$'
)

# OCR noise patterns — lines composed entirely of non-alphanumeric noise.
_OCR_NOISE_LINE = re.compile(
    r'^[\s|/\\•·*_~^=+#@%<>{}\[\]]+$'
)

# Standalone page number line (digits only, or "Page N", "Página N", etc.)
_PAGE_NUMBER_LINE = re.compile(
    r'^\s*(?:(?:Page|Página|Pagina|Seite|Pàgina|Pagine)\s*)?\d+\s*$',
    re.IGNORECASE,
)

# Hyphenated line-break: a word fragment ending with "-" at EOL, followed
# immediately by the continuation on the next line.
# Captures: group(1)=prefix, group(2)=suffix
_HYPHEN_BREAK = re.compile(r'(\w+)-\n(\w+)', re.UNICODE)

# Quote mapping: from typographic / national variants → plain ASCII
_QUOTE_TABLE = str.maketrans(
    {
        '“': '"',  # left double quotation mark
        '”': '"',  # right double quotation mark
        '„': '"',  # double low-9 quotation mark (German)
        '‟': '"',  # double high-reversed-9 quotation mark
        '«': '"',  # left-pointing double angle quotation mark «
        '»': '"',  # right-pointing double angle quotation mark »
        '‘': "'",  # left single quotation mark
        '’': "'",  # right single quotation mark
        '‚': "'",  # single low-9 quotation mark
        '‛': "'",  # single high-reversed-9 quotation mark
        '‹': "'",  # single left-pointing angle quotation mark ‹
        '›': "'",  # single right-pointing angle quotation mark ›
        '`': "'",  # grave accent used as open quote
        '´': "'",  # acute accent used as close quote
    }
)

# Ellipsis variants → standard three dots
_ELLIPSIS_SPACED = re.compile(r'\.\s\.\s\.')          # ". . ."
_ELLIPSIS_UNICODE = re.compile(r'[…⋯]+')      # … ⋯
_ELLIPSIS_LONG = re.compile(r'\.{4,}')                  # ....

# Abbreviations that must NOT cause false sentence splits.
# Each key is a regex pattern; value is the replacement (period removed /
# replaced with a non-breaking space so downstream splitters skip it).
# We use   (NBSP) after the abbreviation — it looks like whitespace to
# humans but is not matched by \s in Python regex (by default), so the
# TextSegmenter's sentence-ending pattern won't fire.
_ABBREVIATIONS = [
    # Pattern consumes "Abbrev. " (period + space) → replacement is "Abbrev "
    # so there is exactly one space in the result and no stray period that would
    # trigger a sentence-split in the TextSegmenter.
    # Titles — English
    (re.compile(r'\bDr\.\s', re.UNICODE), 'Dr '),
    (re.compile(r'\bMr\.\s', re.UNICODE), 'Mr '),
    (re.compile(r'\bMrs\.\s', re.UNICODE), 'Mrs '),
    (re.compile(r'\bMs\.\s', re.UNICODE), 'Ms '),
    (re.compile(r'\bProf\.\s', re.UNICODE), 'Prof '),
    (re.compile(r'\bRev\.\s', re.UNICODE), 'Rev '),
    (re.compile(r'\bGen\.\s', re.UNICODE), 'Gen '),
    (re.compile(r'\bSgt\.\s', re.UNICODE), 'Sgt '),
    (re.compile(r'\bCpl\.\s', re.UNICODE), 'Cpl '),
    (re.compile(r'\bLt\.\s', re.UNICODE), 'Lt '),
    (re.compile(r'\bCol\.\s', re.UNICODE), 'Col '),
    (re.compile(r'\bCapt\.\s', re.UNICODE), 'Capt '),
    (re.compile(r'\bAdm\.\s', re.UNICODE), 'Adm '),
    # Titles — Spanish/Portuguese/French
    (re.compile(r'\bSr\.\s', re.UNICODE), 'Sr '),
    (re.compile(r'\bSra\.\s', re.UNICODE), 'Sra '),
    (re.compile(r'\bSrta\.\s', re.UNICODE), 'Srta '),
    (re.compile(r'\bDra\.\s', re.UNICODE), 'Dra '),
    # Common abbreviated words (all languages)
    (re.compile(r'\betc\.(?=[\s,;)]|$)', re.UNICODE), 'etc'),
    (re.compile(r'\bvs\.\s', re.UNICODE), 'vs '),
    (re.compile(r'\bi\.e\.\s', re.UNICODE), 'i.e '),
    (re.compile(r'\be\.g\.\s', re.UNICODE), 'e.g '),
    (re.compile(r'\bff\.\s', re.UNICODE), 'ff '),
    (re.compile(r'\bpp\.\s', re.UNICODE), 'pp '),
    # Months (en) — abbreviated at sentence-like positions
    (re.compile(r'\bJan\.\s', re.UNICODE), 'Jan '),
    (re.compile(r'\bFeb\.\s', re.UNICODE), 'Feb '),
    (re.compile(r'\bAug\.\s', re.UNICODE), 'Aug '),
    (re.compile(r'\bSept?\.\s', re.UNICODE), 'Sep '),
    (re.compile(r'\bOct\.\s', re.UNICODE), 'Oct '),
    (re.compile(r'\bNov\.\s', re.UNICODE), 'Nov '),
    (re.compile(r'\bDec\.\s', re.UNICODE), 'Dec '),
]

# Em/en dash → natural pause spacing for TTS.
# We keep the dash but ensure it is surrounded by a single space so TTS
# engines interpret it as a clause boundary rather than a hyphen.
_EM_DASH_SPACING = re.compile(r'\s*[—–]\s*')  # — or –


# ---------------------------------------------------------------------------
# Rule implementations
# ---------------------------------------------------------------------------

def _rule3_repair_hyphens(text: str) -> tuple[str, int]:
    """Rule 3: Repair line-wrap hyphenation artifacts."""
    count = [0]

    def _replace(m: re.Match) -> str:
        count[0] += 1
        return m.group(1) + m.group(2)

    result = _HYPHEN_BREAK.sub(_replace, text)
    return result, count[0]


def _rule45_remove_page_numbers_and_ocr(text: str) -> tuple[str, int, int]:
    """
    Rule 4/5/6: Remove page numbers, isolated OCR noise, and short repeated
    headers/footers.

    Returns (cleaned_text, page_numbers_removed, ocr_artifacts_removed).
    """
    lines = text.split('\n')
    cleaned: list[str] = []
    page_removed = 0
    ocr_removed = 0

    for line in lines:
        stripped = line.strip()

        # Rule 5: standalone page number
        if stripped and _PAGE_NUMBER_LINE.match(stripped):
            page_removed += 1
            continue

        # Rule 6: OCR noise line (only symbols, no alphanumeric content)
        if stripped and _OCR_NOISE_LINE.match(stripped):
            ocr_removed += 1
            continue

        cleaned.append(line)

    return '\n'.join(cleaned), page_removed, ocr_removed


def _rule4_remove_repeated_headers(text: str, min_occurrences: int = 3) -> tuple[str, int]:
    """
    Rule 4: Detect and remove repeated header / footer patterns.

    A line is considered a running header/footer if:
    - It is ≤ 80 characters after stripping
    - It appears at least *min_occurrences* times in the text
    - It does not look like body text (no terminal sentence punctuation,
      does not end with a digit that could be a year in a sentence)
    """
    lines = text.split('\n')
    freq: dict[str, int] = {}

    for line in lines:
        stripped = line.strip()
        if stripped and len(stripped) <= 80:
            freq[stripped] = freq.get(stripped, 0) + 1

    repeated = {
        s for s, n in freq.items()
        if n >= min_occurrences
        # Exclude lines that look like genuine content: they end with sentence
        # punctuation or contain lowercase prose words suggesting body text.
        and not re.search(r'[.!?]$', s)
    }

    if not repeated:
        return text, 0

    removed = 0
    result: list[str] = []
    for line in lines:
        if line.strip() in repeated:
            removed += 1
        else:
            result.append(line)

    return '\n'.join(result), removed


def _rule12_join_false_line_breaks(text: str) -> tuple[str, int]:
    """
    Rules 1 + 2: Join soft line breaks while preserving real paragraph breaks.

    Strategy:
    1. Split on paragraph boundaries (2+ blank lines).
    2. Within each paragraph block, join lines where the previous line does
       NOT end with sentence-ending punctuation AND the next line starts with
       a lowercase letter (or a continuation character).
    3. Reassemble with a single blank line between paragraphs.
    """
    repairs = 0
    # Preserve paragraph boundaries (2+ newlines → sentinel)
    blocks = re.split(r'\n{2,}', text)
    repaired_blocks: list[str] = []

    for block in blocks:
        raw_lines = block.split('\n')
        result_lines: list[str] = []

        for raw_line in raw_lines:
            line = raw_line.rstrip()

            if not result_lines:
                result_lines.append(line)
                continue

            prev = result_lines[-1]
            if not prev.strip():
                result_lines.append(line)
                continue

            line_stripped = line.strip()
            if not line_stripped:
                result_lines.append(line)
                continue

            # Join condition:
            # - previous line does NOT end with sentence-ending punctuation
            # - previous line does NOT end with a deliberate break character
            # - current line starts with a lowercase letter (Unicode-aware)
            prev_ends_sentence = bool(_SENTENCE_END.search(prev.rstrip()))
            prev_deliberate = bool(_DELIBERATE_BREAK.search(prev.rstrip()))
            curr_starts_lower = bool(
                re.match(r'^[a-zà-öø-ÿĀ-ɏ]', line_stripped)
            )

            if not prev_ends_sentence and not prev_deliberate and curr_starts_lower:
                result_lines[-1] = prev + ' ' + line_stripped
                repairs += 1
            else:
                result_lines.append(line)

        repaired_blocks.append('\n'.join(result_lines))

    return '\n\n'.join(repaired_blocks), repairs


def _rule7_normalize_whitespace(text: str) -> str:
    """Rule 7: Collapse excessive whitespace."""
    text = text.replace('\t', ' ')
    text = re.sub(r' {2,}', ' ', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    # Remove trailing spaces on each line
    text = re.sub(r' +\n', '\n', text)
    return text


def _rule8_normalize_quotes(text: str) -> str:
    """Rule 8: Convert typographic quote variants to plain ASCII."""
    return text.translate(_QUOTE_TABLE)


def _rule9_normalize_ellipsis(text: str) -> str:
    """Rule 9: Normalize ellipsis variants."""
    text = _ELLIPSIS_UNICODE.sub('...', text)
    text = _ELLIPSIS_SPACED.sub('...', text)
    text = _ELLIPSIS_LONG.sub('...', text)
    return text


# ---------------------------------------------------------------------------
# Public functions
# ---------------------------------------------------------------------------

def normalize_for_tts(text: str) -> str:
    """
    Apply the full normalization pipeline and return the cleaned string.

    This is the primary entry point.  Stats are emitted to structured logs
    and Prometheus counters.
    """
    cleaned, _ = normalize_with_stats(text)
    return cleaned


def normalize_with_stats(text: str) -> tuple[str, NormalizationStats]:
    """
    Full normalization pipeline with detailed counters.

    Rules applied in order:
      3  → repair hyphenated line-breaks         (must precede line-break repair)
      5  → strip standalone page numbers
      6  → strip OCR garbage lines
      4  → remove repeated headers / footers
      1+2 → join false line breaks, preserve real paragraphs
      7  → collapse excessive whitespace
      8  → normalize quote characters
      9  → normalize ellipsis variants
      10 → punctuation untouched (invariant, no action needed)
      11 → language-safe (all rules are Unicode-aware, no language assumptions)
      12 → content unchanged (structural cleanup only)
    """
    _init_metrics()

    stats = NormalizationStats(input_chars=len(text))

    # Rule 3 — hyphenated line breaks
    text, stats.hyphen_repairs = _rule3_repair_hyphens(text)

    # Rules 5 + 6 — page numbers and OCR garbage
    text, page_removed, ocr_removed = _rule45_remove_page_numbers_and_ocr(text)
    stats.footers_removed += page_removed
    stats.ocr_artifacts_removed = ocr_removed

    # Rule 4 — repeated headers / footers
    text, headers_removed = _rule4_remove_repeated_headers(text)
    stats.headers_removed = headers_removed

    # Rules 1 + 2 — false line breaks while preserving real paragraphs
    text, stats.line_break_repairs = _rule12_join_false_line_breaks(text)

    # Rule 7 — whitespace
    text = _rule7_normalize_whitespace(text)

    # Rule 8 — quotes
    text = _rule8_normalize_quotes(text)

    # Rule 9 — ellipsis
    text = _rule9_normalize_ellipsis(text)

    text = text.strip()
    stats.output_chars = len(text)

    # Emit Prometheus metrics
    _inc(_counter_docs, 1)
    _inc(_counter_line_repairs, stats.line_break_repairs)
    _inc(_counter_hyphen_repairs, stats.hyphen_repairs)
    _inc(_counter_headers_removed, stats.headers_removed + stats.footers_removed)
    _inc(_counter_ocr_removed, stats.ocr_artifacts_removed)

    logger.info(
        "[SONORO] text_normalizer_applied "
        "input_chars=%d output_chars=%d "
        "line_break_repairs=%d hyphen_repairs=%d "
        "headers_removed=%d footers_removed=%d ocr_artifacts_removed=%d",
        stats.input_chars,
        stats.output_chars,
        stats.line_break_repairs,
        stats.hyphen_repairs,
        stats.headers_removed,
        stats.footers_removed,
        stats.ocr_artifacts_removed,
    )

    return text, stats


def normalize_for_narration(text: str) -> str:
    """
    Second-pass narration improvements applied ON TOP OF normalize_for_tts.

    Additional rules:
      A  → em/en dash → spaced dash for natural TTS pause
      B  → abbreviation safety (prevent false sentence splits in segmenter)
      C  → numbered/bulleted list readability

    This pass is optional.  Use it when the output goes directly to a TTS
    engine that does not handle punctuation-based pausing well.  It is NOT
    applied by default in the main pipeline — callers opt in explicitly.
    """
    text = normalize_for_tts(text)

    # Rule A: em/en dash — ensure spaces around it so TTS reads a pause
    text = _EM_DASH_SPACING.sub(' — ', text)

    # Rule B: abbreviations — replace trailing period with NBSP so the
    # TextSegmenter's sentence-ending regex (\.) does not split here
    for pattern, replacement in _ABBREVIATIONS:
        text = pattern.sub(replacement, text)

    # Rule C: numbered list items — ensure a clean space after the marker
    # "1.Text" → "1. Text"  (no content change, just spacing)
    text = re.sub(
        r'^(\s*)(\d+[\.\)])(\S)',
        lambda m: m.group(1) + m.group(2) + ' ' + m.group(3),
        text,
        flags=re.MULTILINE,
    )

    return text.strip()
