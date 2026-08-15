"""
Golden Corpus — fixtures and expected results
=============================================
Twelve fixtures, each isolating one structure the chapter engine has to get
right.  Small on purpose: the audit asked for ~8-12 highly representative
documents rather than dozens of mediocre ones, and small fixtures keep the
whole suite under a second.

TOLERANCE POLICY
----------------
start_page: EXACT.  A chapter that begins on the wrong page narrates the wrong
    text — the listener hears the tail of the previous chapter, or loses the
    first page of this one.  There is no defensible slack here.

end_page: ±1.  Where a chapter ends is genuinely ambiguous when the next one
    begins part-way down a page, and the fusion layer derives every non-final
    end_page as `next.start_page - 1` anyway.  The tolerance exists for the
    final chapter, where "the last narratable page" depends on whether back
    matter is present.

title: substring match against a normalized (case-folded, whitespace-collapsed)
    title, never equality.  The engine legitimately appends a subtitle to a
    bare heading ("CAPÍTULO I — El camino"), and pinning exact strings would
    make the corpus a change-detector rather than a correctness test.

ABSORBED DIVIDERS
-----------------
Part dividers and front/back matter are not chapters, but their pages hold
real text.  The engine folds them into the neighbouring chapter instead of
dropping them, so a chapter that follows a "PARTE I" page starts on the
divider page, not on its own heading page.  Expected start pages below reflect
that: it is a deliberate product choice (narrate everything, list only real
chapters), not a tolerance.

Expected values are the PRODUCT requirement, written before the engine was
measured against them.  They are not a transcript of current behaviour.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence

from tests.fixtures.chapter_corpus.builder import Page, toc_page_lines


@dataclass(frozen=True)
class ExpectedChapter:
    title_contains: str
    start_page: int
    end_page: int


@dataclass(frozen=True)
class Fixture:
    name: str
    represents: str
    pages: Sequence[Page]
    expected: Sequence[ExpectedChapter] = ()
    toc: Optional[Sequence] = None
    #: True when the correct answer is the single full-document chapter.
    expect_fallback: bool = False
    start_tolerance: int = 0
    end_tolerance: int = 1


def _body(n: int = 3, spanish: bool = False) -> Page:
    return Page(body_paragraphs=n, spanish=spanish)


def _chapter(heading: str, spanish: bool = False, pt: float = 22.0) -> Page:
    return Page(heading=heading, spanish=spanish, heading_pt=pt)


# ── 1. Simple chaptered English prose, no outline ─────────────────────────────

SIMPLE_ENGLISH = Fixture(
    name="simple_english_prose",
    represents="Chapter 1/2/3 headings in body text, no PDF outline",
    pages=[
        _chapter("Chapter 1"), _body(),
        _chapter("Chapter 2"), _body(),
        _chapter("Chapter 3"), _body(),
    ],
    expected=[
        ExpectedChapter("chapter 1", 1, 2),
        ExpectedChapter("chapter 2", 3, 4),
        ExpectedChapter("chapter 3", 5, 6),
    ],
)

# ── 2. Spanish CAPÍTULO with Roman numerals ───────────────────────────────────

SPANISH_CAPITULO = Fixture(
    name="spanish_capitulo_roman",
    represents="CAPÍTULO I/II/III — accented Spanish keyword + Roman numeral",
    pages=[
        _chapter("CAPÍTULO I", spanish=True), _body(spanish=True),
        _chapter("CAPÍTULO II", spanish=True), _body(spanish=True),
        _chapter("CAPÍTULO III", spanish=True), _body(spanish=True),
    ],
    expected=[
        ExpectedChapter("capítulo i", 1, 2),
        ExpectedChapter("capítulo ii", 3, 4),
        ExpectedChapter("capítulo iii", 5, 6),
    ],
)

# ── 3. Bare Roman numerals as headings ────────────────────────────────────────

ROMAN_NUMERALS = Fixture(
    name="roman_numeral_headings",
    represents="Standalone Roman numerals (II, III, IV) as the only chapter mark",
    pages=[
        _chapter("II"), _body(),
        _chapter("III"), _body(),
        _chapter("IV"), _body(),
    ],
    expected=[
        ExpectedChapter("ii", 1, 2),
        ExpectedChapter("iii", 3, 4),
        ExpectedChapter("iv", 5, 6),
    ],
)

# ── 4. Part → Chapter hierarchy in the outline ────────────────────────────────
# The F-5 case: level 1 is the Parts, so a level-1 read yields 2 "chapters".

PART_CHAPTER_TOC = Fixture(
    name="part_chapter_hierarchy_toc",
    represents="PARTE I/II over Capítulo 1-4 — outline level 1 is Parts, not chapters",
    pages=[
        _chapter("PARTE I", spanish=True),
        _chapter("Capítulo 1", spanish=True), _body(spanish=True),
        _chapter("Capítulo 2", spanish=True), _body(spanish=True),
        _chapter("PARTE II", spanish=True),
        _chapter("Capítulo 3", spanish=True), _body(spanish=True),
        _chapter("Capítulo 4", spanish=True), _body(spanish=True),
    ],
    toc=[
        [1, "PARTE I", 1],
        [2, "Capítulo 1", 2], [2, "Capítulo 2", 4],
        [1, "PARTE II", 6],
        [2, "Capítulo 3", 7], [2, "Capítulo 4", 9],
    ],
    expected=[
        # Capítulo 1 absorbs the PARTE I divider on p1; Capítulo 3 absorbs
        # PARTE II on p6.  Neither Part appears as a chapter of its own.
        ExpectedChapter("capítulo 1", 1, 3),
        ExpectedChapter("capítulo 2", 4, 5),
        ExpectedChapter("capítulo 3", 6, 8),
        ExpectedChapter("capítulo 4", 9, 10),
    ],
)

# ── 5. Outline and body headings agreeing ─────────────────────────────────────

TOC_PLUS_BODY = Fixture(
    name="toc_plus_body_headings",
    represents="PDF outline and body headings agree — detectors must fuse, not double",
    pages=[
        Page(pre_lines=toc_page_lines([("Chapter 1", 2), ("Chapter 2", 4), ("Chapter 3", 6)]),
             body_paragraphs=0),
        _chapter("Chapter 1"), _body(),
        _chapter("Chapter 2"), _body(),
        _chapter("Chapter 3"), _body(),
    ],
    toc=[[1, "Chapter 1", 2], [1, "Chapter 2", 4], [1, "Chapter 3", 6]],
    expected=[
        ExpectedChapter("chapter 1", 2, 3),
        ExpectedChapter("chapter 2", 4, 5),
        ExpectedChapter("chapter 3", 6, 7),
    ],
)

# ── 6. Three-level outline: Part → Chapter → Section ──────────────────────────

TOC_WITH_SUBSECTIONS = Fixture(
    name="toc_with_subsections",
    represents="Part/Chapter/Section outline — must pick chapters, not parts or sections",
    pages=[
        _chapter("PART ONE"),
        _chapter("Chapter 1"), _body(), _body(),
        _chapter("Chapter 2"), _body(), _body(),
        _chapter("Chapter 3"), _body(), _body(),
    ],
    toc=[
        [1, "PART ONE", 1],
        [2, "Chapter 1", 2], [3, "1.1 Beginnings", 2], [3, "1.2 The Road", 3],
        [2, "Chapter 2", 5], [3, "2.1 Winter", 5], [3, "2.2 The Pass", 6],
        [2, "Chapter 3", 8], [3, "3.1 Return", 8], [3, "3.2 After", 9],
    ],
    expected=[
        ExpectedChapter("chapter 1", 1, 4),   # absorbs the PART ONE divider
        ExpectedChapter("chapter 2", 5, 7),
        ExpectedChapter("chapter 3", 8, 10),
    ],
)

# ── 7. No outline at all ──────────────────────────────────────────────────────

NO_TOC = Fixture(
    name="no_toc_body_only",
    represents="No PDF outline — heuristic and structural detection only",
    pages=[
        _chapter("Chapter One"), _body(), _body(),
        _chapter("Chapter Two"), _body(), _body(),
        _chapter("Chapter Three"), _body(), _body(),
    ],
    expected=[
        ExpectedChapter("chapter one", 1, 3),
        ExpectedChapter("chapter two", 4, 6),
        ExpectedChapter("chapter three", 7, 9),
    ],
)

# ── 8. Chapters starting on consecutive pages ─────────────────────────────────
# The exact shape the old fusion bug collapsed: every start is group_end + 1.

CONSECUTIVE_PAGES = Fixture(
    name="consecutive_chapter_pages",
    represents="One-page chapters back to back — the F-1 collapse shape",
    pages=[
        _chapter("Chapter 1", pt=22.0),
        _chapter("Chapter 2", pt=22.0),
        _chapter("Chapter 3", pt=22.0),
        _chapter("Chapter 4", pt=22.0),
        _chapter("Chapter 5", pt=22.0),
    ],
    expected=[
        ExpectedChapter("chapter 1", 1, 1),
        ExpectedChapter("chapter 2", 2, 2),
        ExpectedChapter("chapter 3", 3, 3),
        ExpectedChapter("chapter 4", 4, 4),
        ExpectedChapter("chapter 5", 5, 5),
    ],
)

# ── 9. Short chapters with an outline ─────────────────────────────────────────

SHORT_CHAPTERS = Fixture(
    name="short_chapters_with_toc",
    represents="Very short chapters (1 page each) declared in the outline",
    pages=[
        _chapter("Chapter 1"), _chapter("Chapter 2"), _chapter("Chapter 3"),
        _chapter("Chapter 4"), _chapter("Chapter 5"), _chapter("Chapter 6"),
    ],
    toc=[[1, f"Chapter {i}", i] for i in range(1, 7)],
    expected=[ExpectedChapter(f"chapter {i}", i, i) for i in range(1, 7)],
)

# ── 10. No chapter structure at all ───────────────────────────────────────────

NO_CHAPTERS = Fixture(
    name="no_chapters_continuous_prose",
    represents="Uniform prose, no headings, no outline — must use the full-document path",
    pages=[_body(4) for _ in range(6)],
    expect_fallback=True,
)

# ── 11. Front matter that looks like chapters ─────────────────────────────────
# Typographically identical to a chapter opening; semantically not a chapter.

DECORATIVE_HEADINGS = Fixture(
    name="decorative_front_matter",
    represents="Acknowledgements/Preface set like chapter openings — must not become chapters",
    pages=[
        _chapter("Acknowledgements"),
        _chapter("A Note on the Text"),
        _chapter("Chapter 1"), _body(),
        _chapter("Chapter 2"), _body(),
    ],
    expected=[
        # Chapter 1 absorbs both front-matter pages.  Narrating them is not
        # ideal — skippable front matter needs a per-chapter flag, which is
        # audit item C6 and a schema change this phase does not make — but it
        # beats listing them as two chapters or losing their text.
        ExpectedChapter("chapter 1", 1, 4),
        ExpectedChapter("chapter 2", 5, 6),
    ],
)

# ── 12. Typography is the only chapter signal ─────────────────────────────────

TYPOGRAPHY_ONLY = Fixture(
    name="typography_only_headings",
    represents="Titled chapters with no keyword — structural (font-ratio) detection carries it",
    pages=[
        _chapter("The Silver Road"), _body(),
        _chapter("Winter Comes Early"), _body(),
        _chapter("The Long Return"), _body(),
    ],
    expected=[
        ExpectedChapter("the silver road", 1, 2),
        ExpectedChapter("winter comes early", 3, 4),
        ExpectedChapter("the long return", 5, 6),
    ],
)


CORPUS: tuple[Fixture, ...] = (
    SIMPLE_ENGLISH,
    SPANISH_CAPITULO,
    ROMAN_NUMERALS,
    PART_CHAPTER_TOC,
    TOC_PLUS_BODY,
    TOC_WITH_SUBSECTIONS,
    NO_TOC,
    CONSECUTIVE_PAGES,
    SHORT_CHAPTERS,
    NO_CHAPTERS,
    DECORATIVE_HEADINGS,
    TYPOGRAPHY_ONLY,
)
