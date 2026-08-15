"""
Golden Corpus — deterministic PDF builder
=========================================
Synthesizes the corpus PDFs with PyMuPDF (already a production dependency —
the detectors themselves read PDFs with it), so no binary fixtures live in the
repository and every byte of every fixture is reviewable as code.

Determinism matters more than realism here: the same fixture spec must produce
byte-identical page text and font sizes on every run, or the corpus cannot
serve as a regression baseline.  Everything below is therefore seeded from the
spec alone — no randomness, no timestamps, no external files.
"""
from __future__ import annotations

import textwrap
from dataclasses import dataclass, field
from typing import Optional, Sequence

import fitz  # PyMuPDF

# Layout constants.  Body at 11pt against a 22pt heading gives a font ratio of
# 2.0, comfortably over the StructuralAnalyzer's 1.3 threshold, which is what
# makes "typography only" detection testable at all.
_PAGE_W, _PAGE_H = 612.0, 792.0
_MARGIN_X = 72.0
_HEADING_Y = 108.0
_BODY_Y = 168.0
_BODY_LEADING = 14.0
_BODY_PT = 11.0
_HEADING_PT = 22.0
_FONT = "helv"

# Deterministic filler.  Two languages so Spanish fixtures read as Spanish to
# anything that samples the text (the language detector is not under test here,
# but a fixture that claims to be Spanish should actually be Spanish).
_FILLER_EN = (
    "The road turned north again and the light came slowly over the hills. "
    "He walked without hurry and counted the miles by the shape of the fences. "
    "Nothing moved in the fields except the wind and the slow drift of cloud. "
)
_FILLER_ES = (
    "El camino giraba otra vez hacia el norte y la luz llegaba despacio. "
    "Caminaba sin prisa y contaba las millas por la forma de las cercas. "
    "Nada se movía en los campos salvo el viento y la lenta deriva de nubes. "
)


@dataclass(frozen=True)
class Page:
    """One page of a corpus fixture."""

    heading: Optional[str] = None
    #: Lines rendered before the heading — used for front matter and TOC pages.
    pre_lines: Sequence[str] = field(default_factory=tuple)
    #: Repetitions of the filler paragraph; controls char_count per page.
    body_paragraphs: int = 3
    heading_pt: float = _HEADING_PT
    spanish: bool = False


def build_pdf(path: str, pages: Sequence[Page], toc: Optional[Sequence] = None) -> str:
    """
    Write *pages* to a PDF at *path*, optionally with a PDF outline (*toc*).

    `toc` uses PyMuPDF's own shape: [[level, title, page_number_1_indexed], …].
    """
    doc = fitz.open()

    for spec in pages:
        page = doc.new_page(width=_PAGE_W, height=_PAGE_H)
        y = _HEADING_Y - _BODY_LEADING * (len(spec.pre_lines) + 1)

        for line in spec.pre_lines:
            page.insert_text((_MARGIN_X, y), line, fontsize=_BODY_PT, fontname=_FONT)
            y += _BODY_LEADING

        if spec.heading:
            page.insert_text(
                (_MARGIN_X, _HEADING_Y),
                spec.heading,
                fontsize=spec.heading_pt,
                fontname=_FONT,
            )

        filler = _FILLER_ES if spec.spanish else _FILLER_EN
        y = _BODY_Y
        for _ in range(spec.body_paragraphs):
            # Wrapped so the text layer holds real line breaks, the way a
            # typeset book does — the detectors read lines, not paragraphs.
            for line in textwrap.wrap(filler, 78):
                page.insert_text((_MARGIN_X, y), line, fontsize=_BODY_PT, fontname=_FONT)
                y += _BODY_LEADING
            y += _BODY_LEADING

    if toc:
        doc.set_toc([list(entry) for entry in toc])

    doc.save(path)
    doc.close()
    return path


def toc_page_lines(entries: Sequence[tuple]) -> list[str]:
    """
    Render printed table-of-contents lines: "Chapter 1 ........ 3".

    This is the *printed* TOC on a page, which is a different thing from the
    PDF outline — a real book usually has both, and the heuristic detector is
    supposed to skip these pages rather than mine them for chapters.
    """
    return ["Contents"] + [
        f"{title} {'.' * max(4, 46 - len(title))} {page}" for title, page in entries
    ]
