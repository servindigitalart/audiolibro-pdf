"""
Document Structure Engine
==========================
BLOCK 6B: Text Segmentation & Chapter Detection Layer

Main orchestration engine for document structure analysis.
Coordinates all detection strategies and produces final chapter structure.
"""

import logging
import re
import time
from typing import List, Optional
from uuid import UUID

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.chapter import Chapter
from app.services.document_structure.models import (
    DetectedChapter,
    DocumentStructure,
    PageText,
)
from app.services.document_structure.extractors.toc_extractor import TOCExtractor
from app.services.document_structure.extractors.heuristic_detector import HeuristicDetector
from app.services.document_structure.extractors.structural_analyzer import StructuralAnalyzer
from app.services.document_structure.classification import (
    describes_same_chapter,
    is_non_chapter_heading,
)
from app.services.document_structure.fusion.confidence_scorer import ConfidenceScorer
from app.services.document_structure.exceptions import (
    DocumentStructureError,
    PDFExtractionError,
    NoChaptersDetectedError,
)
from app.text.normalizer import normalize_with_stats

logger = logging.getLogger(__name__)


# ── Coverage thresholds ───────────────────────────────────────────────────────
# If total extracted chars is large but the persisted chapter text is tiny,
# the detectors found only a TOC/index stub.  Discard and fall back to the
# full document so the user gets a real audiobook instead of 44 seconds.

# Minimum proportion of document chars that chapters must cover
_MIN_COVERAGE_FRACTION = 0.30   # 30% of total PDF chars

# Hard floor: if total chars is large but chapters are this small, always fall back
_MIN_CHAPTER_CHARS_LARGE_DOC = 10_000

# "Large document" threshold: apply coverage check above this char count
_LARGE_DOC_CHARS_THRESHOLD = 20_000

# Small single-chapter: if the doc has many pages but one tiny chapter, fall back
_SMALL_CHAPTER_CHARS_LIMIT = 10_000
_MIN_PAGES_FOR_SMALL_CHAPTER_CHECK = 10

# ── TOC / Index title patterns ────────────────────────────────────────────────
# A chapter whose title matches these words is almost certainly an index page,
# not a real content chapter.  If it's the ONLY chapter, fall back.

_TOC_TITLE_RE = re.compile(
    r"^\s*(table\s+of\s+contents?|contents?|index|indice|índice|"
    r"contenido|sumario|summary|inhoudsopgave|inhalt|sommaire)\s*$",
    re.IGNORECASE | re.UNICODE,
)


class DocumentStructureEngine:
    """
    Main engine for document structure analysis.

    Orchestrates:
    1. PDF text extraction
    2. Multiple chapter detection strategies
    3. Confidence fusion
    4. Coverage validation (NEW: rejects tiny/TOC-only results)
    5. Chapter persistence

    Splitting chapter text into TTS-sized chunks is NOT done here — the worker
    owns that (`_chunk_text` in `app/tasks/processing.py`), because the chunk
    ceiling is a property of the TTS provider, not of the document.
    """

    def __init__(self):
        """Initialize engine with all detectors."""
        self.toc_extractor = TOCExtractor()
        self.heuristic_detector = HeuristicDetector()
        self.structural_analyzer = StructuralAnalyzer()
        self.confidence_scorer = ConfidenceScorer()

    async def analyze_document(
        self,
        document_id: UUID,
        pdf_path: str,
        db: AsyncSession
    ) -> DocumentStructure:
        """
        Analyze document structure and persist chapters.

        Returns DocumentStructure with detected chapters.
        Raises DocumentStructureError if analysis fails completely.
        """
        start_time = time.time()

        logger.info("[SONORO] chapter_detection_started document_id=%s", document_id)

        try:
            # Step 1: Extract full text with structure
            pages = await self._extract_pages(pdf_path)
            total_pages = len(pages)
            total_chars = sum(p.char_count for p in pages)
            doc_text, page_offsets = _build_document_text(pages)

            logger.info(
                "[SONORO] pdf_extracted document_id=%s pages=%d chars=%d",
                document_id, total_pages, total_chars,
            )

            # Step 2: Run all detection strategies
            detection_results = await self._run_detections(pdf_path, pages, total_pages)

            # Step 3: Fuse detections
            fused_chapters = self.confidence_scorer.fuse_detections(
                detections=detection_results,
                min_confidence=0.5
            )

            if not fused_chapters:
                logger.warning(
                    "[SONORO] chapter_detection_no_results document_id=%s — length_fallback",
                    document_id,
                )
                fused_chapters = self._create_fallback_chapter(total_pages, len(doc_text))
                fallback_reason = "no_detections"
            else:
                fused_chapters = self._absorb_non_chapters(fused_chapters, document_id)
                methods = {c.detection_method for c in fused_chapters}
                avg_conf = sum(c.confidence for c in fused_chapters) / len(fused_chapters)
                logger.info(
                    "[SONORO] chapters_fused document_id=%s count=%d methods=%s avg_conf=%.2f",
                    document_id, len(fused_chapters), sorted(methods), avg_conf,
                )
                fallback_reason = None

            # Step 4: Extract text for each chapter
            chapters_with_text = self._extract_chapter_text(
                fused_chapters, doc_text, page_offsets
            )

            # Step 5: Coverage validation — discard weak detections that cover only
            # a tiny fraction of the document (e.g. TOC-only, index page).
            chapters_with_text, fallback_reason = self._validate_coverage(
                chapters=chapters_with_text,
                total_chars=total_chars,
                total_pages=total_pages,
                doc_text=doc_text,
                existing_fallback_reason=fallback_reason,
            )

            # Step 6: Persist chapters to database
            await self._persist_chapters(document_id, chapters_with_text, db)

            # Emit extraction coverage metrics
            persisted_chars = sum(ch.char_count for ch in chapters_with_text)
            coverage_pct = (persisted_chars / total_chars) if total_chars > 0 else 0.0
            logger.info(
                "[SONORO] chapter_extraction_coverage "
                "document_id=%s extracted=%d persisted=%d pct=%.3f "
                "page_count=%d chapter_count=%d fallback=%s reason=%s",
                document_id,
                total_chars,
                persisted_chars,
                coverage_pct,
                total_pages,
                len(chapters_with_text),
                fallback_reason is not None,
                fallback_reason or "none",
            )

            structure = DocumentStructure(
                document_id=document_id,
                total_pages=total_pages,
                total_chars=total_chars,
                chapters=chapters_with_text,
                detection_methods_used=self._get_methods_used(detection_results)
            )

            duration = time.time() - start_time
            logger.info(
                "[SONORO] analysis_complete document_id=%s chapters=%d "
                "coverage_pct=%.3f duration_s=%.2f avg_conf=%.2f",
                document_id,
                len(structure.chapters),
                coverage_pct,
                duration,
                structure.average_confidence,
            )

            return structure

        except Exception as e:
            logger.error(
                "[SONORO] analysis_failed document_id=%s error=%s",
                document_id, str(e), exc_info=True,
            )
            raise DocumentStructureError(
                message=f"Analysis failed: {str(e)}",
                document_id=str(document_id)
            )

    # ── Non-chapter absorption ────────────────────────────────────────────────

    def _absorb_non_chapters(
        self,
        chapters: List[DetectedChapter],
        document_id: UUID,
    ) -> List[DetectedChapter]:
        """
        Fold Part dividers and front/back matter into the neighbouring chapter.

        A "PARTE II" divider page and an "Acknowledgements" page are typeset
        exactly like a chapter opening, so the structural detector finds them
        and they arrive here as chapters.  Listing them as chapters gives the
        listener a five-second track called "PARTE II" between real chapters.

        They are absorbed rather than dropped: the pages hold real text, and
        losing text silently is worse than narrating a divider.  The pages join
        the *following* chapter (dividers and front matter introduce what comes
        next), or the preceding one when nothing follows (back matter).

        If every chapter looks like a non-chapter, the list is returned intact —
        an empty chapter list is never an improvement.
        """
        # Identity, not equality: DetectedChapter is a plain dataclass, so two
        # chapters with the same fields compare equal and `in` would drop the
        # wrong one.
        keep_ids = {
            id(c) for c in chapters if not is_non_chapter_heading(c.title)
        }
        if not keep_ids or len(keep_ids) == len(chapters):
            return chapters

        keep = [c for c in chapters if id(c) in keep_ids]
        absorbed = [c for c in chapters if id(c) not in keep_ids]

        # Targets are chosen from the ORIGINAL start pages.  Reading start_page
        # live would let the first absorption move a chapter backwards and so
        # disqualify it as the target for the second, pushing that one onto the
        # chapter after it and producing overlapping ranges.
        original_start = {id(c): c.start_page for c in chapters}

        for chapter in absorbed:
            following = [
                c for c in keep
                if original_start[id(c)] > original_start[id(chapter)]
            ]
            if following:
                target = min(following, key=lambda c: original_start[id(c)])
                target.start_page = min(target.start_page, chapter.start_page)
            else:
                target = max(keep, key=lambda c: original_start[id(c)])
                target.end_page = max(target.end_page, chapter.end_page)

        keep.sort(key=lambda c: c.start_page)

        logger.info(
            "[SONORO] non_chapters_absorbed document_id=%s count=%d titles=%s",
            document_id, len(absorbed), [c.title[:40] for c in absorbed],
        )
        return keep

    # ── Coverage validation ───────────────────────────────────────────────────

    def _validate_coverage(
        self,
        chapters: List[DetectedChapter],
        total_chars: int,
        total_pages: int,
        doc_text: str,
        existing_fallback_reason: Optional[str],
    ) -> tuple[List[DetectedChapter], Optional[str]]:
        """
        Check whether detected chapters actually cover the document text.

        Three discard conditions (any one triggers full-document fallback):

          1. Large-doc coverage:  total_chars > 20k  AND  chapter_chars < 30% of total
          2. Tiny single chapter: page_count > 10    AND  1 chapter     AND  chars < 10k
          3. TOC-only detection:  sole chapter title is an index/TOC keyword

        Returns the final chapter list and the fallback reason (None if no fallback).
        """
        if existing_fallback_reason:
            # Already using a fallback — nothing to validate
            return chapters, existing_fallback_reason

        persisted_chars = sum(ch.char_count for ch in chapters)
        fallback_reason: Optional[str] = None

        # Condition 1: coverage too low for large documents
        if (
            total_chars > _LARGE_DOC_CHARS_THRESHOLD
            and persisted_chars < total_chars * _MIN_COVERAGE_FRACTION
        ):
            fallback_reason = (
                f"low_coverage_fraction "
                f"(persisted={persisted_chars} "
                f"total={total_chars} "
                f"pct={persisted_chars/total_chars:.3f})"
            )

        # Condition 2: single chapter with tiny text for a multi-page document
        elif (
            total_pages >= _MIN_PAGES_FOR_SMALL_CHAPTER_CHECK
            and len(chapters) == 1
            and persisted_chars < _SMALL_CHAPTER_CHARS_LIMIT
        ):
            fallback_reason = (
                f"single_chapter_too_small "
                f"(chars={persisted_chars} pages={total_pages})"
            )

        # Condition 3: the sole chapter's title looks like a TOC / index
        elif (
            len(chapters) == 1
            and _TOC_TITLE_RE.match(chapters[0].title or "")
        ):
            fallback_reason = f"toc_only_detection (title={chapters[0].title!r})"

        if fallback_reason:
            logger.warning(
                "[SONORO] chapter_coverage_fallback document_id=N/A "
                "reason=%s — creating full-document chapter",
                fallback_reason,
            )
            fallback = self._create_fallback_chapter(total_pages, len(doc_text))
            normalized, _ = normalize_with_stats(doc_text)
            fallback[0].text_content = normalized
            fallback[0].char_count = len(normalized)
            logger.info(
                "[SONORO] fallback_chapter_text chars=%d (normalized from raw=%d)",
                fallback[0].char_count, len(doc_text),
            )
            return fallback, fallback_reason

        return chapters, None

    # ── Page extraction ───────────────────────────────────────────────────────

    async def _extract_pages(self, pdf_path: str) -> List[PageText]:
        """Extract pages with structural metadata."""
        try:
            return self.structural_analyzer.extract_page_structure(pdf_path)
        except Exception as e:
            logger.error(f"Page extraction failed: {str(e)}")
            raise PDFExtractionError(f"Failed to extract pages: {str(e)}")

    async def _run_detections(
        self,
        pdf_path: str,
        pages: List[PageText],
        total_pages: int
    ) -> List[List[DetectedChapter]]:
        """Run all detection strategies."""
        results = []

        # Strategy 1: TOC extraction
        try:
            toc_chapters = self.toc_extractor.extract_chapters(pdf_path, total_pages)
            if toc_chapters:
                results.append(toc_chapters)
                logger.info(f"TOC detection: {len(toc_chapters)} chapters")
        except Exception as e:
            logger.warning(f"TOC extraction failed: {str(e)}")

        # Strategy 2: Heuristic detection
        try:
            heuristic_chapters = self.heuristic_detector.detect_chapters(pages)
            if heuristic_chapters:
                results.append(heuristic_chapters)
                logger.info(f"Heuristic detection: {len(heuristic_chapters)} chapters")
        except Exception as e:
            logger.warning(f"Heuristic detection failed: {str(e)}")

        # Strategy 3: Structural analysis
        try:
            structural_chapters = self.structural_analyzer.detect_chapters(pages)
            if structural_chapters:
                results.append(structural_chapters)
                logger.info(f"Structural detection: {len(structural_chapters)} chapters")
        except Exception as e:
            logger.warning(f"Structural analysis failed: {str(e)}")

        return results

    def _extract_chapter_text(
        self,
        chapters: List[DetectedChapter],
        doc_text: str,
        page_offsets: List[int],
    ) -> List[DetectedChapter]:
        """
        Give every chapter its text, sliced at character boundaries.

        A chapter's extent used to be a page range, which forced two untruths:
        a chapter that opens halfway down a page had to swallow whatever came
        before it, and two chapters that open on the *same* page both claimed
        that page — so its text was narrated twice.  Boundaries are characters
        now: each chapter starts where its heading is printed and ends where
        the next one starts, so the slices tile the document exactly once.

        Page numbers are untouched; they remain the reader-facing location.
        """
        if not chapters:
            return chapters

        # Later chapters cannot start before earlier ones: a heading search that
        # lands badly must not invert the document.
        floor = 0
        for chapter in chapters:
            chapter.start_char = max(_locate_heading(chapter, doc_text, page_offsets), floor)
            floor = chapter.start_char

        for i, chapter in enumerate(chapters):
            chapter.end_char = (
                chapters[i + 1].start_char if i + 1 < len(chapters) else len(doc_text)
            )

            raw_text = doc_text[chapter.start_char:chapter.end_char].strip()
            normalized, norm_stats = normalize_with_stats(raw_text)
            chapter.text_content = normalized
            chapter.char_count = len(normalized)

            logger.info(
                "[SONORO] chapter_normalized chapter=%s "
                "start_char=%d end_char=%d "
                "raw_chars=%d normalized_chars=%d "
                "line_repairs=%d hyphen_repairs=%d "
                "headers_removed=%d ocr_removed=%d",
                chapter.title,
                chapter.start_char,
                chapter.end_char,
                norm_stats.input_chars,
                norm_stats.output_chars,
                norm_stats.line_break_repairs,
                norm_stats.hyphen_repairs,
                norm_stats.headers_removed,
                norm_stats.ocr_artifacts_removed,
            )

            if chapter.text_content:
                preview = chapter.text_content[:500]
                if len(chapter.text_content) > 500:
                    preview += "..."
                chapter.text_preview = preview

        return chapters

    async def _persist_chapters(
        self,
        document_id: UUID,
        chapters: List[DetectedChapter],
        db: AsyncSession
    ):
        """Persist chapters to database (idempotent)."""
        from sqlalchemy.exc import IntegrityError

        try:
            await db.execute(delete(Chapter).where(Chapter.document_id == document_id))
            await db.flush()   # ensure DELETE is visible before INSERT
            for i, chapter in enumerate(chapters):
                db.add(Chapter(
                    document_id=document_id,
                    title=chapter.title,
                    start_page=chapter.start_page,
                    end_page=chapter.end_page,
                    order_index=i,
                    confidence_score=chapter.confidence,
                    detection_method=chapter.detection_method,
                    char_count=chapter.char_count,
                    text_preview=getattr(chapter, 'text_preview', None)
                ))
            await db.commit()
        except IntegrityError:
            await db.rollback()
            # Retry once with explicit flush to beat the constraint
            await db.execute(delete(Chapter).where(Chapter.document_id == document_id))
            await db.flush()
            for i, chapter in enumerate(chapters):
                db.add(Chapter(
                    document_id=document_id,
                    title=chapter.title,
                    start_page=chapter.start_page,
                    end_page=chapter.end_page,
                    order_index=i,
                    confidence_score=chapter.confidence,
                    detection_method=chapter.detection_method,
                    char_count=chapter.char_count,
                    text_preview=getattr(chapter, 'text_preview', None)
                ))
            await db.commit()

        logger.info(
            "[SONORO] chapters_persisted document_id=%s count=%d",
            document_id, len(chapters),
        )

    def _create_fallback_chapter(
        self,
        total_pages: int,
        total_chars: int,
    ) -> List[DetectedChapter]:
        """
        Create a single chapter covering the entire document.
        Labeled 'Complete audiobook' (not 'Full Document') for a better UX.
        """
        logger.warning(
            "[SONORO] using_full_document_fallback pages=%d", total_pages
        )
        return [
            DetectedChapter(
                title="Complete audiobook",
                start_page=1,
                end_page=total_pages,
                confidence=0.5,
                detection_method="length_fallback",
                start_char=0,
                end_char=total_chars,
            )
        ]

    def _get_methods_used(
        self,
        detection_results: List[List[DetectedChapter]]
    ) -> List[str]:
        """Get list of detection methods that found chapters."""
        methods: set[str] = set()
        for result in detection_results:
            if result:
                methods.update(ch.detection_method for ch in result)
        return sorted(methods)


# ── Document text ─────────────────────────────────────────────────────────────
# One string for the whole document, plus where each page begins in it.  The
# detectors already read these pages; reusing their text (rather than reopening
# the PDF) keeps the text a chapter is narrated from identical to the text its
# heading was found in, and saves a second full read of a file that can be 50 MB.

_PAGE_SEPARATOR = "\n"


def _build_document_text(pages: List[PageText]) -> tuple[str, List[int]]:
    """Return the concatenated document text and each page's start offset."""
    offsets: List[int] = []
    cursor = 0
    for page in pages:
        offsets.append(cursor)
        cursor += len(page.text) + len(_PAGE_SEPARATOR)
    return _PAGE_SEPARATOR.join(p.text for p in pages), offsets


def _locate_heading(
    chapter: DetectedChapter,
    doc_text: str,
    page_offsets: List[int],
) -> int:
    """
    Character offset where *chapter* begins in *doc_text*.

    The heading is searched for only within the chapter's own start page: a
    chapter title also appears in the printed table of contents, and a
    document-wide search would find that copy instead of the chapter.

    Falls back to the start of the page — the pre-C2 behaviour — when the
    printed heading cannot be matched, which happens whenever a PDF outline
    words an entry differently from the page it points at.
    """
    index = chapter.start_page - 1
    if not 0 <= index < len(page_offsets):
        return 0

    page_start = page_offsets[index]
    page_end = (
        page_offsets[index + 1] if index + 1 < len(page_offsets) else len(doc_text)
    )

    cursor = page_start
    for line in doc_text[page_start:page_end].splitlines(keepends=True):
        if line.strip() and describes_same_chapter(line, chapter.title):
            return cursor
        cursor += len(line)

    return page_start
