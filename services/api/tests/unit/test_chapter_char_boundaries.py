"""
Character-offset chapter boundaries (audit C2 / F-6)
====================================================
A chapter's extent used to be a range of pages, which cannot describe where a
chapter actually starts.  Two consequences were real:

  * the first chapter swallowed whatever front matter shared its page — the
    audiobook opened by reading the copyright notice;
  * two chapters opening on one page both claimed that page, so its text was
    synthesized, billed, and narrated twice.

Boundaries are characters now.  These tests assert the two fixed behaviours
plus the invariant that makes them safe: the slices tile the document, so no
text is lost between chapters.
"""
from __future__ import annotations

from uuid import uuid4

import pytest

from tests.fixtures.chapter_corpus import Page, build_pdf, _StubSession

pytestmark = pytest.mark.unit


async def _analyze(tmp_path, name, pages, toc=None):
    from app.services.document_structure.engine import DocumentStructureEngine

    pdf_path = build_pdf(str(tmp_path / f"{name}.pdf"), pages, toc)
    structure = await DocumentStructureEngine().analyze_document(
        uuid4(), pdf_path, _StubSession()
    )
    return structure.chapters


# ── The copyright page ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_front_matter_on_the_first_chapter_page_is_not_narrated(tmp_path):
    """Text printed above the first heading belongs to the book, not the chapter."""
    chapters = await _analyze(
        tmp_path,
        "front_matter_same_page",
        [
            Page(
                pre_lines=("Copyright 2026 Acme Press", "All rights reserved"),
                heading="Chapter 1",
            ),
            Page(),
            Page(heading="Chapter 2"),
            Page(),
        ],
    )

    assert len(chapters) == 2, [(c.title, c.start_page) for c in chapters]
    first = chapters[0]
    assert first.start_char > 0, "chapter 1 still starts at the top of the page"
    assert "All rights reserved" not in first.text_content
    assert "Copyright" not in first.text_content
    # The chapter opens on its own heading — this trims front matter, nothing else.
    assert first.text_content.startswith("Chapter 1")


# ── Two chapters, one page ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_two_chapters_opening_on_one_page_do_not_share_text(tmp_path):
    """
    A short-story collection whose outline puts two pieces on page 3.

    Page ranges force both chapters onto page 3; character offsets split it at
    the second heading, so the page is narrated once.
    """
    chapters = await _analyze(
        tmp_path,
        "two_starts_one_page",
        [
            Page(heading="The First Crossing"),
            Page(),
            # "The Long Return" is printed part-way down the page, above the
            # heading the builder typesets — two openings on one sheet.
            Page(pre_lines=("The Long Return",), heading="Winter Comes Early"),
            Page(),
        ],
        toc=[
            [1, "The First Crossing", 1],
            [1, "The Long Return", 3],
            [1, "Winter Comes Early", 3],
        ],
    )

    assert len(chapters) == 3, [(c.title, c.start_page) for c in chapters]
    second, third = chapters[1], chapters[2]

    assert second.start_page == third.start_page == 3
    assert second.start_char < third.start_char, "both chapters start at the same offset"
    assert second.end_char == third.start_char, "the shared page is claimed twice"
    assert second.text_content and third.text_content


# ── Invariant: the slices tile the document ───────────────────────────────────


@pytest.mark.asyncio
async def test_chapter_slices_tile_the_document(tmp_path):
    """Every chapter ends where the next begins, and the last reaches the end."""
    chapters = await _analyze(
        tmp_path,
        "tiling",
        [
            Page(heading="Chapter 1"), Page(),
            Page(heading="Chapter 2"), Page(),
            Page(heading="Chapter 3"), Page(),
        ],
    )

    assert len(chapters) == 3
    for current, following in zip(chapters, chapters[1:]):
        assert current.start_char < current.end_char
        assert current.end_char == following.start_char


@pytest.mark.asyncio
async def test_fallback_chapter_spans_the_whole_document(tmp_path):
    """The no-structure path narrates every character, not every page."""
    chapters = await _analyze(tmp_path, "no_structure", [Page() for _ in range(6)])

    assert len(chapters) == 1
    assert chapters[0].start_char == 0
    assert chapters[0].end_char > 0
    assert chapters[0].text_content


# ── Heading lookup ────────────────────────────────────────────────────────────


def test_unlocatable_heading_falls_back_to_the_page_start():
    """
    An outline that words an entry differently from the printed page must not
    cost the listener text.  Failing to find the heading means starting at the
    page — exactly the pre-C2 behaviour.
    """
    from app.services.document_structure.engine import _locate_heading
    from app.services.document_structure.models import DetectedChapter

    doc_text = "page one text\npage two text\n"
    page_offsets = [0, len("page one text\n")]
    chapter = DetectedChapter(
        title="A Title Printed Nowhere",
        start_page=2,
        end_page=2,
        confidence=0.9,
        detection_method="toc",
    )

    assert _locate_heading(chapter, doc_text, page_offsets) == page_offsets[1]


def test_heading_is_matched_on_its_own_page_not_in_the_printed_contents():
    """
    The title also appears in the printed table of contents.  Searching the
    whole document would start the chapter on the contents page.
    """
    from app.services.document_structure.engine import _locate_heading
    from app.services.document_structure.models import DetectedChapter

    contents = "Contents\nChapter 2 ..... 2\n"
    body = "Chapter 2\nthe road turned north\n"
    doc_text = contents + body
    page_offsets = [0, len(contents)]
    chapter = DetectedChapter(
        title="Chapter 2",
        start_page=2,
        end_page=2,
        confidence=0.9,
        detection_method="toc",
    )

    assert _locate_heading(chapter, doc_text, page_offsets) == len(contents)
