"""
Unit tests for chapter detection fusion (ConfidenceScorer).

Regression coverage for F-1: `_group_by_page_overlap` merged every contiguous
chapter into one group, so a 5-chapter book fused down to a single chapter
titled after the first heading ("Chapter 1", "Part 1", "Complete audiobook").
No test asserted on the fused chapter *count*, which is why it survived.

The invariant these tests protect: N contiguous chapters in → N chapters out.
"""

import pytest

from app.services.document_structure.extractors.heuristic_detector import (
    HeuristicDetector,
)
from app.services.document_structure.fusion.confidence_scorer import ConfidenceScorer
from app.services.document_structure.models import DetectedChapter, PageText


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def contiguous_chapters(
    starts: list,
    total_pages: int,
    method: str = "toc",
    confidence: float = 0.95,
) -> list:
    """Build detections the way every detector does: end_page = next start - 1."""
    chapters = []
    for i, start in enumerate(starts):
        end = starts[i + 1] - 1 if i + 1 < len(starts) else total_pages
        chapters.append(
            DetectedChapter(
                title=f"Chapter {i + 1}",
                start_page=start,
                end_page=end,
                confidence=confidence,
                detection_method=method,
            )
        )
    return chapters


@pytest.fixture
def scorer():
    return ConfidenceScorer()


# ---------------------------------------------------------------------------
# F-1: the collapse bug
# ---------------------------------------------------------------------------

class TestContiguousChaptersSurviveFusion:
    """The exact scenarios the audit executed against the real class."""

    def test_five_contiguous_toc_chapters_stay_five(self, scorer):
        detections = contiguous_chapters([1, 11, 21, 31, 41], total_pages=50)

        fused = scorer.fuse_detections([detections], min_confidence=0.5)

        assert len(fused) == 5

    def test_toc_and_heuristic_agreeing_produce_five_not_one(self, scorer):
        toc = contiguous_chapters([1, 11, 21, 31, 41], total_pages=50)
        heuristic = contiguous_chapters(
            [1, 11, 21, 31, 41],
            total_pages=50,
            method="chapter_keyword",
            confidence=0.85,
        )

        fused = scorer.fuse_detections([toc, heuristic], min_confidence=0.5)

        assert len(fused) == 5

    def test_detections_with_gaps_still_stay_separate(self, scorer):
        # Non-contiguous ranges worked before the fix; they must keep working.
        detections = [
            DetectedChapter(
                title=f"Chapter {i}",
                start_page=start,
                end_page=start + 3,
                confidence=0.9,
                detection_method="toc",
            )
            for i, start in enumerate([1, 11, 21, 31, 41], start=1)
        ]

        fused = scorer.fuse_detections([detections], min_confidence=0.5)

        assert len(fused) == 5

    @pytest.mark.parametrize("chapter_count", [2, 3, 8, 20, 57])
    def test_n_contiguous_chapters_fuse_to_n(self, scorer, chapter_count):
        starts = [1 + i * 5 for i in range(chapter_count)]
        detections = contiguous_chapters(starts, total_pages=starts[-1] + 4)

        fused = scorer.fuse_detections([detections], min_confidence=0.5)

        assert len(fused) == chapter_count

    def test_titles_are_not_all_the_first_heading(self, scorer):
        detections = contiguous_chapters([1, 11, 21], total_pages=30)

        fused = scorer.fuse_detections([detections], min_confidence=0.5)

        assert [c.title for c in fused] == ["Chapter 1", "Chapter 2", "Chapter 3"]


# ---------------------------------------------------------------------------
# Cross-detector agreement — the reason a tolerance exists at all
# ---------------------------------------------------------------------------

class TestCrossDetectorAgreement:

    def test_same_page_from_two_detectors_is_one_chapter(self, scorer):
        toc = [DetectedChapter("Chapter 1", 10, 19, 0.95, "toc")]
        heuristic = [DetectedChapter("Chapter 1", 10, 19, 0.85, "chapter_keyword")]

        fused = scorer.fuse_detections([toc, heuristic], min_confidence=0.5)

        assert len(fused) == 1
        assert fused[0].detection_method.startswith("fusion(")

    def test_one_page_disagreement_is_one_chapter(self, scorer):
        # PDF outline points at the chapter page; the heading is found overleaf.
        toc = [DetectedChapter("Chapter 1", 10, 19, 0.95, "toc")]
        heuristic = [DetectedChapter("Chapter 1", 11, 19, 0.85, "chapter_keyword")]

        fused = scorer.fuse_detections([toc, heuristic], min_confidence=0.5)

        assert len(fused) == 1
        assert fused[0].start_page == 10

    def test_agreement_boosts_confidence(self, scorer):
        toc = [DetectedChapter("Chapter 1", 10, 19, 0.90, "toc")]
        structural = [DetectedChapter("Chapter 1", 10, 19, 0.70, "structural")]

        fused = scorer.fuse_detections([toc, structural], min_confidence=0.5)

        assert fused[0].confidence > 0.90

    def test_two_pages_apart_stays_two_chapters(self, scorer):
        toc = [DetectedChapter("Chapter 1", 10, 19, 0.95, "toc")]
        heuristic = [DetectedChapter("Chapter 2", 12, 19, 0.85, "chapter_keyword")]

        fused = scorer.fuse_detections([toc, heuristic], min_confidence=0.5)

        assert len(fused) == 2


class TestSameDetectorNeverMerges:
    """One detector does not emit two detections for one chapter."""

    def test_consecutive_pages_from_one_detector_are_two_chapters(self, scorer):
        # Short chapters / poetry: headings on page 10 and page 11.
        detections = [
            DetectedChapter("Chapter 1", 10, 10, 0.85, "chapter_keyword"),
            DetectedChapter("Chapter 2", 11, 11, 0.85, "chapter_keyword"),
        ]

        fused = scorer.fuse_detections([detections], min_confidence=0.5)

        assert len(fused) == 2

    def test_keyword_and_roman_numeral_are_the_same_detector(self, scorer):
        # Both come from HeuristicDetector, so nearby hits are distinct chapters.
        detections = [
            DetectedChapter("Chapter 1", 10, 10, 0.85, "chapter_keyword"),
            DetectedChapter("II", 11, 12, 0.85, "roman_numeral"),
        ]

        fused = scorer.fuse_detections([detections], min_confidence=0.5)

        assert len(fused) == 2

    def test_three_consecutive_chapters_do_not_chain(self, scorer):
        # Anchoring on the group start (not the previous detection) is what
        # keeps a run of near-adjacent starts from collapsing.
        detections = [
            DetectedChapter("I", 10, 10, 0.85, "roman_numeral"),
            DetectedChapter("II", 11, 11, 0.85, "roman_numeral"),
            DetectedChapter("III", 12, 12, 0.85, "roman_numeral"),
        ]

        fused = scorer.fuse_detections([detections], min_confidence=0.5)

        assert len(fused) == 3


# ---------------------------------------------------------------------------
# Output shape
# ---------------------------------------------------------------------------

class TestFusedRanges:

    def test_ranges_are_contiguous_and_do_not_overlap(self, scorer):
        # Detectors disagree on ends; max(end) would overlap the next chapter
        # and narrate the same page twice.
        toc = contiguous_chapters([1, 11, 21], total_pages=30)
        heuristic = contiguous_chapters(
            [1, 12, 22], total_pages=30, method="chapter_keyword", confidence=0.85
        )

        fused = scorer.fuse_detections([toc, heuristic], min_confidence=0.5)

        for current, nxt in zip(fused, fused[1:]):
            assert current.end_page == nxt.start_page - 1
        assert all(c.end_page >= c.start_page for c in fused)

    def test_last_chapter_reaches_end_of_document(self, scorer):
        detections = contiguous_chapters([1, 11, 21], total_pages=30)

        fused = scorer.fuse_detections([detections], min_confidence=0.5)

        assert fused[-1].end_page == 30

    def test_sorted_and_indexed_by_position(self, scorer):
        detections = contiguous_chapters([1, 11, 21], total_pages=30)

        fused = scorer.fuse_detections([list(reversed(detections))], min_confidence=0.5)

        assert [c.start_page for c in fused] == [1, 11, 21]
        assert [c.order_index for c in fused] == [0, 1, 2]

    def test_low_confidence_detections_are_dropped(self, scorer):
        detections = [
            DetectedChapter("Chapter 1", 1, 10, 0.90, "toc"),
            DetectedChapter("Chapter 2", 11, 20, 0.40, "structural"),
        ]

        fused = scorer.fuse_detections([detections], min_confidence=0.5)

        assert [c.title for c in fused] == ["Chapter 1"]

    def test_no_detections_returns_empty(self, scorer):
        assert scorer.fuse_detections([]) == []
        assert scorer.fuse_detections([[], []]) == []


# ---------------------------------------------------------------------------
# Detector → fusion, the path the engine actually runs
# ---------------------------------------------------------------------------

class TestHeuristicDetectorThroughFusion:

    CHAPTERS = [
        "Capítulo I\n\nEl comienzo de la historia. Había una vez...",
        "Capítulo II\n\nEl desarrollo de los personajes. La trama avanza...",
        "Capítulo III\n\nEl conflicto principal. Las tensiones aumentan...",
        "Capítulo IV\n\nLa crisis. Todo parece perdido para los protagonistas...",
        "Capítulo V\n\nEl giro inesperado. Nadie podía haberlo imaginado...",
        "Capítulo VI\n\nLa resolución empieza. Los personajes toman decisiones...",
        "Capítulo VII\n\nEl clímax de la narración. El momento decisivo...",
        "Capítulo VIII\n\nEl desenlace final. Todo termina como debe ser...",
    ]

    def _pages(self):
        """One chapter every 3 pages, with body pages in between."""
        pages, page_no = [], 1
        for text in self.CHAPTERS:
            pages.append(PageText(page_number=page_no, text=text, char_count=len(text)))
            for _ in range(2):
                page_no += 1
                body = "El texto continúa en esta página con más narración. " * 5
                pages.append(
                    PageText(page_number=page_no, text=body, char_count=len(body))
                )
            page_no += 1
        return pages

    def test_eight_detected_chapters_survive_fusion(self, scorer):
        detected = HeuristicDetector().detect_chapters(self._pages())
        assert len(detected) == 8, "detector regression, not a fusion regression"

        fused = scorer.fuse_detections([detected], min_confidence=0.5)

        assert len(fused) == 8

    def test_fused_chapters_cover_the_whole_document(self, scorer):
        pages = self._pages()
        detected = HeuristicDetector().detect_chapters(pages)

        fused = scorer.fuse_detections([detected], min_confidence=0.5)

        covered = {p for c in fused for p in range(c.start_page, c.end_page + 1)}
        assert covered == {p.page_number for p in pages}
