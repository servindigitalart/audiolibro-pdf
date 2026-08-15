"""
Unit Tests: heading classification (Phase 1.1)
==============================================
Direct coverage of the two predicates the golden corpus exercises end to end.
The corpus proves the engine gets the right answer; these prove *why*, and
catch a vocabulary or numbering regression at the point it happens rather than
as a mysterious corpus failure three layers up.
"""
import pytest

from app.services.document_structure.classification import (
    describes_same_chapter,
    heading_signature,
    is_non_chapter_heading,
    normalize_heading,
)

pytestmark = pytest.mark.unit


# ── normalize_heading ─────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("  CAPÍTULO   I  ", "capitulo i"),
        ("Chapter 1:", "chapter 1"),
        ("Prólogo.", "prologo"),
        ("", ""),
        (None, ""),
    ],
)
def test_normalize_heading(raw, expected):
    assert normalize_heading(raw) == expected


# ── heading_signature ─────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "title,expected",
    [
        ("Chapter 1", ("chapter", "1")),
        ("CHAPTER IV", ("chapter", "iv")),
        ("Chapter One", ("chapter", "1")),
        ("Capítulo 2", ("chapter", "2")),
        ("CAPÍTULO III", ("chapter", "iii")),
        ("Capítulo dos", ("chapter", "2")),
        ("Chapitre 5", ("chapter", "5")),
        ("Kapitel 7", ("chapter", "7")),
        ("Cap. 3", ("chapter", "3")),
        ("PARTE I", ("part", "i")),
        ("Part Two", ("part", "2")),
        ("Libro 1", ("book", "1")),
        ("IV", ("chapter", "iv")),
        ("12", ("chapter", "12")),
    ],
)
def test_heading_signature_parses_numbered_divisions(title, expected):
    assert heading_signature(title) == expected


@pytest.mark.parametrize(
    "title", ["The Silver Road", "Acknowledgements", "Winter Comes Early", ""]
)
def test_heading_signature_is_none_without_numbering(title):
    """No opinion is not the same as 'not a chapter' — callers must not guess."""
    assert heading_signature(title) is None


def test_chapter_and_part_with_the_same_number_are_different():
    """The whole point: 'Parte I' must never compare equal to 'Capítulo 1'."""
    assert heading_signature("PARTE I") != heading_signature("Capítulo I")


# ── describes_same_chapter ────────────────────────────────────────────────────


def test_same_chapter_across_naming_styles():
    """A PDF outline and a body heading rarely spell it identically."""
    assert describes_same_chapter("Chapter 1", "CHAPTER 1")
    assert describes_same_chapter("Chapter One", "Chapter 1")
    assert describes_same_chapter("Capítulo 2", "CAPITULO 2")


def test_structural_title_with_trailing_body_text_still_matches():
    """StructuralAnalyzer appends the first body lines to the heading."""
    assert describes_same_chapter(
        "Chapter 1",
        "Chapter 1 The road turned north again and the light came slowly",
    )


def test_different_chapters_do_not_match():
    assert not describes_same_chapter("Chapter 1", "Chapter 2")
    assert not describes_same_chapter("Capítulo 1", "Capítulo 3")


def test_part_divider_does_not_match_the_following_chapter():
    """
    The measured Phase 1.1 defect: fusion merged a Part divider on page N with
    the chapter starting on page N+1, so the chapter began a page early and
    took the divider's place in the list.
    """
    assert not describes_same_chapter("PARTE I El camino giraba otra vez", "Capítulo 1")
    assert not describes_same_chapter("PART ONE", "Chapter 1")


def test_front_matter_does_not_match_the_following_chapter():
    assert not describes_same_chapter("Acknowledgements", "Chapter 1")
    assert not describes_same_chapter("A Note on the Text", "Chapter 1")


def test_untitled_headings_never_match():
    assert not describes_same_chapter("", "Chapter 1")
    assert not describes_same_chapter("Chapter 1", "")


# ── is_non_chapter_heading ────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "title",
    [
        "PARTE I", "PART ONE", "Part 2", "Libro 1", "Book Three",
        "Acknowledgements", "Acknowledgments", "Preface", "Foreword",
        "Dedication", "Copyright", "Contents", "Table of Contents",
        "A Note on the Text", "About the Author", "Index", "Bibliography",
        "Glossary", "Appendix", "Afterword",
        "Agradecimientos", "Prólogo", "Índice", "Epílogo", "Bibliografía",
    ],
)
def test_non_chapter_headings_are_recognised(title):
    assert is_non_chapter_heading(title)


@pytest.mark.parametrize(
    "title",
    [
        "Chapter 1", "CAPÍTULO III", "The Silver Road", "Winter Comes Early",
        "The Long Return", "IV", "Chapitre 5",
    ],
)
def test_real_chapters_are_not_flagged(title):
    """A false positive here silently deletes a chapter from the audiobook."""
    assert not is_non_chapter_heading(title)


def test_front_matter_with_trailing_body_text_is_recognised():
    """Structural detections carry body text after the heading."""
    assert is_non_chapter_heading(
        "Acknowledgements The road turned north again and the light came"
    )


def test_a_chapter_merely_mentioning_a_matter_word_is_not_flagged():
    """Matching is anchored at the start, so this must survive."""
    assert not is_non_chapter_heading("The Index of Lost Things")
    assert not is_non_chapter_heading("Notes from a Small Island")
