"""
Unit tests for TOC outline level selection.

Regression coverage for F-5: `toc_to_chapters` hardcoded `level == 1`, so a
"Part I → Chapter 1..8 → Part II → Chapter 9..16" outline produced two
chapters named "Part I" and "Part II" — the second, independent source of the
"Part 1" symptom users reported.
"""

import pytest

from app.services.document_structure.extractors.toc_extractor import (
    TOCExtractor,
    _select_chapter_level,
)
from app.services.document_structure.models import TOCEntry


def entries(*specs) -> list:
    """Build TOC entries from (title, page, level) triples."""
    return [TOCEntry(title=t, page_number=p, level=lv) for t, p, lv in specs]


@pytest.fixture
def extractor():
    return TOCExtractor()


# ---------------------------------------------------------------------------
# Level selection
# ---------------------------------------------------------------------------

class TestSelectChapterLevel:

    def test_flat_outline_uses_level_one(self):
        toc = entries(*[(f"Chapter {i}", i * 10, 1) for i in range(1, 13)])

        assert _select_chapter_level(toc, total_pages=300) == 1

    def test_parts_are_skipped_for_the_chapter_level(self):
        # Part I → Chapter 1..8, Part II → Chapter 9..16
        toc = entries(("Part I", 1, 1))
        toc += entries(*[(f"Chapter {i}", 1 + i * 15, 2) for i in range(1, 9)])
        toc += entries(("Part II", 130, 1))
        toc += entries(*[(f"Chapter {i}", 130 + i * 15, 2) for i in range(9, 17)])

        assert _select_chapter_level(toc, total_pages=300) == 2

    def test_three_parts_are_too_coarse_to_be_chapters(self):
        # 3 parts clears the entry-count floor but each is 100 pages.
        toc = entries(("Part I", 1, 1), ("Part II", 101, 1), ("Part III", 201, 1))
        toc += entries(*[(f"Chapter {i}", i * 10, 2) for i in range(1, 31)])

        assert _select_chapter_level(toc, total_pages=300) == 2

    def test_does_not_descend_into_subsections(self):
        # Level 1 already holds real chapters — 60 subsections would over-split.
        toc = entries(*[(f"Chapter {i}", i * 25, 1) for i in range(1, 13)])
        toc += entries(*[(f"Section {i}", i * 5, 2) for i in range(1, 61)])

        assert _select_chapter_level(toc, total_pages=300) == 1

    def test_falls_back_to_shallowest_level_when_nothing_qualifies(self):
        toc = entries(("Foreword", 1, 1), ("Afterword", 200, 1))

        assert _select_chapter_level(toc, total_pages=300) == 1

    def test_unknown_page_count_ignores_the_density_check(self):
        toc = entries(("Part I", 1, 1), ("Part II", 101, 1), ("Part III", 201, 1))

        assert _select_chapter_level(toc, total_pages=0) == 1


# ---------------------------------------------------------------------------
# toc_to_chapters
# ---------------------------------------------------------------------------

class TestTocToChapters:

    def test_part_outline_yields_chapters_not_parts(self, extractor):
        toc = entries(("Part I", 1, 1))
        toc += entries(*[(f"Chapter {i}", 1 + i * 15, 2) for i in range(1, 9)])
        toc += entries(("Part II", 130, 1))
        toc += entries(*[(f"Chapter {i}", 130 + i * 15, 2) for i in range(9, 17)])

        chapters = extractor.toc_to_chapters(toc, total_pages=300)

        assert len(chapters) == 16
        assert not any(c.title.startswith("Part") for c in chapters)

    def test_flat_outline_is_unchanged(self, extractor):
        toc = entries(*[(f"Chapter {i}", i * 10, 1) for i in range(1, 13)])

        chapters = extractor.toc_to_chapters(toc, total_pages=130)

        assert len(chapters) == 12
        assert chapters[0].detection_method == "toc"
        assert chapters[0].confidence == TOCExtractor.CONFIDENCE_SCORE

    def test_ranges_are_contiguous_to_the_last_page(self, extractor):
        toc = entries(("One", 1, 1), ("Two", 11, 1), ("Three", 21, 1))

        chapters = extractor.toc_to_chapters(toc, total_pages=30)

        assert [(c.start_page, c.end_page) for c in chapters] == [
            (1, 10), (11, 20), (21, 30),
        ]

    def test_empty_toc_returns_empty(self, extractor):
        assert extractor.toc_to_chapters([], total_pages=100) == []

    def test_entries_sharing_a_page_do_not_invert_ranges(self, extractor):
        toc = entries(("One", 5, 1), ("Two", 5, 1), ("Three", 9, 1))

        chapters = extractor.toc_to_chapters(toc, total_pages=20)

        assert all(c.end_page >= c.start_page for c in chapters)
