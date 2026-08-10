"""
Unit tests for heuristic chapter detection.

Covers:
- Spanish book with Roman numeral chapters I–VIII (the original bug)
- "Capítulo N" numeric and word variants
- English "Chapter N" / "CHAPTER N" / bare Roman numerals
- Standalone Roman numerals as chapter headings
- False-positive prevention: TOC pages, numbered list items, paragraph text
- Fallback to single chapter when nothing is detected
"""

import pytest

from app.services.document_structure.extractors.heuristic_detector import (
    HeuristicDetector,
    _find_chapter_heading,
    _is_toc_page,
    _is_toc_line,
    _ROMAN_CHAPTER_SET,
)
from app.services.document_structure.models import PageText


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_page(page_number: int, text: str) -> PageText:
    return PageText(page_number=page_number, text=text, char_count=len(text))


def make_pages(*texts: str) -> list:
    """Create a list of PageText objects, one per argument, 1-indexed."""
    return [make_page(i + 1, t) for i, t in enumerate(texts)]


def nonempty(text: str):
    return [l for l in text.split("\n") if l.strip()]


# ---------------------------------------------------------------------------
# Core: the original bug — Spanish book, Roman numeral chapters
# ---------------------------------------------------------------------------

class TestSpanishRomanNumeralChapters:
    """A book whose chapters are headed 'Capítulo I' … 'Capítulo VIII'."""

    CHAPTER_TEXTS = [
        "Capítulo I\n\nEl comienzo de la historia. Había una vez...",
        "Capítulo II\n\nEl desarrollo de los personajes. La trama avanza...",
        "Capítulo III\n\nEl conflicto principal. Las tensiones aumentan...",
        "Capítulo IV\n\nLa crisis. Todo parece perdido para los protagonistas...",
        "Capítulo V\n\nEl giro inesperado. Nadie podía haberlo imaginado...",
        "Capítulo VI\n\nLa resolución empieza. Los personajes toman decisiones...",
        "Capítulo VII\n\nEl clímax de la narración. El momento decisivo...",
        "Capítulo VIII\n\nEl desenlace final. Todo termina como debe ser...",
    ]

    def test_detects_all_eight_chapters(self):
        pages = make_pages(*self.CHAPTER_TEXTS)
        detector = HeuristicDetector()
        chapters = detector.detect_chapters(pages)

        assert len(chapters) == 8, (
            f"Expected 8 chapters, got {len(chapters)}: {[c.title for c in chapters]}"
        )

    def test_chapter_titles_contain_numeral(self):
        pages = make_pages(*self.CHAPTER_TEXTS)
        detector = HeuristicDetector()
        chapters = detector.detect_chapters(pages)

        for ch in chapters:
            assert any(
                roman in ch.title.upper()
                for roman in ("I", "II", "III", "IV", "V", "VI", "VII", "VIII")
            ), f"Unexpected title: {ch.title}"

    def test_chapters_in_correct_order(self):
        pages = make_pages(*self.CHAPTER_TEXTS)
        detector = HeuristicDetector()
        chapters = detector.detect_chapters(pages)

        start_pages = [c.start_page for c in chapters]
        assert start_pages == sorted(start_pages)

    def test_detection_method_is_chapter_keyword(self):
        pages = make_pages(*self.CHAPTER_TEXTS)
        detector = HeuristicDetector()
        chapters = detector.detect_chapters(pages)

        for ch in chapters:
            assert ch.detection_method == "chapter_keyword", (
                f"Unexpected detection_method: {ch.detection_method}"
            )

    def test_confidence_is_high(self):
        pages = make_pages(*self.CHAPTER_TEXTS)
        detector = HeuristicDetector()
        chapters = detector.detect_chapters(pages)

        for ch in chapters:
            assert ch.confidence >= 0.80, (
                f"Low confidence {ch.confidence} for '{ch.title}'"
            )


# ---------------------------------------------------------------------------
# Standalone Roman numerals (bare heading, no keyword)
# ---------------------------------------------------------------------------

class TestStandaloneRomanNumerals:
    """Chapter pages that have only a Roman numeral as heading."""

    def test_standalone_viii_detected(self):
        page = make_page(5, "VIII\n\nLos soldados marcharon al amanecer...")
        result = _find_chapter_heading(nonempty(page.text), page.page_number)
        assert result is not None
        method, title, confidence = result
        assert method == "roman_numeral"
        assert confidence >= 0.82

    def test_standalone_unambiguous_multi_char_all_detected(self):
        """Every unambiguous multi-character Roman 1–10 should fire."""
        for roman in ("II", "III", "IV", "VI", "VII", "VIII", "IX"):
            page = make_page(1, f"{roman}\n\nParagraph text follows here.")
            result = _find_chapter_heading(nonempty(page.text), page.page_number)
            assert result is not None, f"Failed to detect standalone '{roman}'"
            assert result[0] == "roman_numeral"

    def test_standalone_roman_sparse_page_high_confidence(self):
        """A sparse page with just a Roman numeral gets a confidence boost."""
        page = make_page(3, "VII")  # Only one line — classic separator page
        result = _find_chapter_heading(nonempty(page.text), page.page_number)
        assert result is not None
        _, _, confidence = result
        assert confidence >= 0.87  # base 0.82 + top-position 0.05 + sparse 0.08

    def test_eight_standalone_roman_chapters_produce_eight_chapters(self):
        texts = [
            f"{r}\n\nContent of chapter {r}. Lorem ipsum dolor sit amet..."
            for r in ("I", "II", "III", "IV", "V", "VI", "VII", "VIII")
        ]
        pages = make_pages(*texts)
        detector = HeuristicDetector()
        chapters = detector.detect_chapters(pages)
        assert len(chapters) == 8, (
            f"Expected 8 chapters, got {len(chapters)}"
        )


# ---------------------------------------------------------------------------
# English patterns
# ---------------------------------------------------------------------------

class TestEnglishPatterns:

    def test_chapter_number(self):
        result = _find_chapter_heading(
            ["Chapter 1", "", "The beginning of the story."], 1
        )
        assert result is not None
        assert result[0] == "chapter_keyword"

    def test_chapter_word(self):
        result = _find_chapter_heading(
            ["Chapter One", "", "Once upon a time..."], 1
        )
        assert result is not None
        assert result[0] == "chapter_keyword"

    def test_chapter_roman(self):
        result = _find_chapter_heading(
            ["Chapter VIII", "", "The battle began at dawn."], 1
        )
        assert result is not None
        assert result[0] == "chapter_keyword"

    def test_uppercase_chapter_roman(self):
        result = _find_chapter_heading(
            ["CHAPTER IV", "", "The storm arrived."], 1
        )
        assert result is not None

    def test_eight_english_chapters(self):
        texts = [f"Chapter {i}\n\nBody text for chapter {i}." for i in range(1, 9)]
        pages = make_pages(*texts)
        detector = HeuristicDetector()
        chapters = detector.detect_chapters(pages)
        assert len(chapters) == 8


# ---------------------------------------------------------------------------
# Spanish patterns — expanded variants
# ---------------------------------------------------------------------------

class TestSpanishPatterns:

    def test_capitulo_numeric(self):
        result = _find_chapter_heading(["Capítulo 3", "La aventura continúa."], 1)
        assert result is not None and result[0] == "chapter_keyword"

    def test_capitulo_roman_upper(self):
        result = _find_chapter_heading(["Capítulo VIII", "El final."], 1)
        assert result is not None and result[0] == "chapter_keyword"

    def test_capitulo_word_ocho(self):
        result = _find_chapter_heading(["Capítulo ocho", "El final."], 1)
        assert result is not None and result[0] == "chapter_keyword"

    def test_capitulo_word_seis(self):
        result = _find_chapter_heading(["capítulo seis", "Continuación."], 1)
        assert result is not None and result[0] == "chapter_keyword"

    def test_capitulo_upper_all_caps(self):
        result = _find_chapter_heading(["CAPÍTULO VI", "El desenlace."], 1)
        assert result is not None and result[0] == "chapter_keyword"

    def test_capitulo_upper_ascii(self):
        # CAPITULO without tilde accent
        result = _find_chapter_heading(["CAPITULO III", "Texto."], 1)
        assert result is not None and result[0] == "chapter_keyword"


# ---------------------------------------------------------------------------
# Heading buried past line 5 (original scanning bug)
# ---------------------------------------------------------------------------

class TestHeadingBeyondFirstFiveLines:

    def test_heading_on_line_eight(self):
        """Heading appearing after 7 blank/header lines must still be found."""
        text = "\n".join([
            "Running Header",  # line 1
            "",
            "",
            "",
            "",
            "",
            "",
            "Capítulo IV",     # line 8 (non-empty line 2)
            "",
            "La historia comienza aquí con más detalles.",
        ])
        result = _find_chapter_heading(nonempty(text), 5)
        assert result is not None, "Heading after many blank lines was not detected"
        assert result[0] == "chapter_keyword"


# ---------------------------------------------------------------------------
# False positive prevention
# ---------------------------------------------------------------------------

class TestFalsePositives:

    def test_toc_page_is_skipped(self):
        """A typical TOC page must not produce any chapter detections."""
        toc_text = "\n".join([
            "Tabla de Contenidos",
            "Capítulo I ............... 3",
            "Capítulo II .............. 15",
            "Capítulo III ............. 28",
            "Capítulo IV .............. 41",
            "Capítulo V ............... 57",
        ])
        pages = [make_page(1, toc_text)]
        detector = HeuristicDetector()
        chapters = detector.detect_chapters(pages)
        assert chapters == [], f"TOC page should produce no chapters, got: {chapters}"

    def test_toc_page_detection(self):
        lines = [
            "Contents",
            "Chapter I ............... 5",
            "Chapter II .............. 18",
            "Chapter III ............. 31",
            "Chapter IV .............. 44",
        ]
        assert _is_toc_page(lines) is True

    def test_toc_line_detection(self):
        assert _is_toc_line("Capítulo I ............... 3") is True
        assert _is_toc_line("Capítulo I") is False

    def test_roman_in_paragraph_not_detected(self):
        """A Roman numeral that is not the start of a line should NOT fire."""
        text = (
            "The Roman Empire, also known as the Empire (I), lasted for centuries. "
            "During phase II of the campaign, the legions advanced northward. "
            "By III century AD, the empire was declining rapidly."
        )
        result = _find_chapter_heading(nonempty(text), 1)
        # If it does match, it should not match as roman_numeral
        if result is not None:
            assert result[0] != "roman_numeral"

    def test_numbered_list_item_not_chapter(self):
        """A line like '3. Mix the ingredients' is not a chapter heading."""
        text = (
            "Instrucciones:\n"
            "1. Primero prepare los ingredientes\n"
            "2. Mezcle todo con cuidado\n"
            "3. Hornee durante 30 minutos\n"
        )
        # numeric_dot pattern requires capital letter — "Primero" qualifies but
        # this is deep in instruction text, not a chapter; the first line
        # 'Instrucciones:' should be the heading candidate at most
        result = _find_chapter_heading(nonempty(text), 1)
        # If something fires, it must NOT produce chapter 2 or 3 (only first match matters)
        # The key assertion: the whole page is not wrongly treated as 8 chapters
        pages = [make_page(1, text)]
        detector = HeuristicDetector()
        chapters = detector.detect_chapters(pages)
        assert len(chapters) <= 1  # at most one (the first line), never one per list item

    def test_page_number_line_not_chapter(self):
        """A standalone digit (page number) must not trigger numeric_dot."""
        text = "\n42\n\nBody text of the page continues here at length."
        result = _find_chapter_heading(nonempty(text), 42)
        # "42" alone has no dot so numeric_dot won't fire; Roman check won't fire
        if result is not None:
            assert result[0] != "roman_numeral"


# ---------------------------------------------------------------------------
# Page ranges
# ---------------------------------------------------------------------------

class TestChapterRanges:
    """Every page of the document must belong to a chapter."""

    def test_last_chapter_runs_to_the_end_of_the_document(self):
        # Chapter heading on page 1, body pages 2-5: the chapter is pages 1-5,
        # not page 1 alone.
        pages = make_pages(
            "Chapter 1\n\nThe story begins here with the opening scene...",
            *["The narrative continues on this page. " * 5] * 4,
        )

        chapters = HeuristicDetector().detect_chapters(pages)

        assert len(chapters) == 1
        assert (chapters[0].start_page, chapters[0].end_page) == (1, 5)

    def test_chapters_cover_every_page(self):
        pages = make_pages(
            "Chapter 1\n\nOpening scene of the first chapter of the book...",
            "Continuing the first chapter with more narrative text here. " * 3,
            "Chapter 2\n\nThe second chapter starts and the plot thickens...",
            "Continuing the second chapter with more narrative text here. " * 3,
            "Still inside the second chapter, approaching the end now. " * 3,
        )

        chapters = HeuristicDetector().detect_chapters(pages)

        covered = {p for c in chapters for p in range(c.start_page, c.end_page + 1)}
        assert covered == {1, 2, 3, 4, 5}


# ---------------------------------------------------------------------------
# Roman numeral set completeness
# ---------------------------------------------------------------------------

def test_roman_set_includes_i_through_viii():
    for r in ("I", "II", "III", "IV", "V", "VI", "VII", "VIII"):
        assert r in _ROMAN_CHAPTER_SET


def test_roman_set_goes_to_xxx():
    assert "XXX" in _ROMAN_CHAPTER_SET
    assert len(_ROMAN_CHAPTER_SET) == 30
