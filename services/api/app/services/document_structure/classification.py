"""
Heading classification
======================
Two deterministic questions about a heading's *text*, shared by the fusion
layer and the engine.  No model, no network, no new dependency — the signals
here are vocabulary and numbering, both of which are stable across the books
this product actually sees.

1. `heading_signature` — "which chapter does this heading name?"
   Used by fusion to decide whether two detections a page apart describe the
   same chapter or two different ones.

2. `is_non_chapter_heading` — "is this a division marker or front/back matter
   rather than a chapter?"
   Used by the engine to stop Part dividers and Acknowledgements pages from
   being narrated as if they were chapters.

Both were added in Phase 1.1 because the golden corpus measured them: every
false positive in the corpus baseline came from one of these two confusions,
and nothing else in the corpus regressed without them.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Optional, Tuple

# ── Chapter numbering ─────────────────────────────────────────────────────────
# Keyword → canonical family.  Parts and chapters are both *numbered divisions*
# and must share this table, because telling them apart is the entire point:
# "Parte I" and "Capítulo 1" both parse, and they must not compare equal.
_DIVISION_KEYWORDS = {
    "chapter": "chapter", "capitulo": "chapter", "chapitre": "chapter",
    "kapitel": "chapter", "cap": "chapter",
    "part": "part", "parte": "part", "partie": "part", "teil": "part",
    "book": "book", "libro": "book", "livre": "book",
    "section": "section", "seccion": "section",
}

_DIVISION_RE = re.compile(
    r"^(?P<word>[a-z]+)\.?\s+(?P<num>[0-9]+|[ivxlcdm]+|"
    r"one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|"
    r"uno|dos|tres|cuatro|cinco|seis|siete|ocho|nueve|diez|once|doce)\b",
    re.IGNORECASE,
)

# A heading that is nothing but a Roman numeral or an integer.
_BARE_NUMBER_RE = re.compile(r"^(?P<num>[0-9]{1,3}|[ivxlcdm]{1,6})$", re.IGNORECASE)

# ── Front and back matter ─────────────────────────────────────────────────────
# Sections a book contains but a listener did not come for.
#
# Split into two sets by ambiguity, because the cost of the two mistakes is not
# symmetric: flagging a real chapter deletes it from the listener's chapter
# list, while missing a front-matter page merely narrates a page they can skip.
#
# PREFIX — distinctive enough that a real chapter title never starts this way.
# Prefix matching is required because StructuralAnalyzer appends the first
# lines of body text to the heading it finds.
_NON_CHAPTER_PREFIXES = frozenset({
    # English
    "acknowledgements", "acknowledgments", "preface", "foreword",
    "dedication", "copyright", "table of contents", "title page",
    "a note on the text", "note on the text", "author's note", "authors note",
    "about the author", "about the type", "colophon", "half title",
    "frontispiece", "further reading", "works cited", "bibliography",
    # Spanish
    "agradecimientos", "prefacio", "prologo", "dedicatoria",
    "derechos de autor", "nota del autor", "sobre el autor", "bibliografia",
    # French / German — the other languages the detectors already cover
    "remerciements", "avant-propos", "table des matieres",
    "danksagung", "vorwort", "inhaltsverzeichnis",
})

# EXACT — ordinary nouns that also open legitimate book and chapter titles
# ("Notes from a Small Island", "Index of Lost Things").  These only count when
# the heading is nothing else, so a chapter can never be lost to them.
_NON_CHAPTER_EXACT = frozenset({
    "index", "contents", "notes", "endnotes", "appendix", "glossary",
    "epigraph", "afterword", "postscript", "epilogue",
    "indice", "contenido", "notas", "apendice", "glosario", "epilogo",
    "anhang", "register", "annexe",
})

# How much of a heading to consider when prefix-matching.  Long enough to clear
# the heading itself, short enough that body text cannot drag in a false match.
_TITLE_LOOKAHEAD_CHARS = 48


def normalize_heading(title: str) -> str:
    """Case-fold, strip accents, collapse whitespace and trailing punctuation."""
    if not title:
        return ""
    folded = unicodedata.normalize("NFKD", title)
    folded = "".join(c for c in folded if not unicodedata.combining(c))
    folded = re.sub(r"\s+", " ", folded).strip().lower()
    return folded.strip(" .,:;—-")


def heading_signature(title: str) -> Optional[Tuple[str, str]]:
    """
    Parse *title* into (division_family, number) — e.g. ("chapter", "1").

    Returns None when the heading carries no numbering, which is the common
    case for titled chapters ("The Silver Road") and for front matter.  Callers
    must treat None as "no opinion", never as "not a chapter".
    """
    normalized = normalize_heading(title)
    if not normalized:
        return None

    match = _DIVISION_RE.match(normalized)
    if match:
        family = _DIVISION_KEYWORDS.get(match.group("word"))
        if family:
            return family, _canonical_number(match.group("num"))

    bare = _BARE_NUMBER_RE.match(normalized)
    if bare:
        # A bare numeral names a chapter by convention — books do not open a
        # Part with a naked "IV".
        return "chapter", _canonical_number(bare.group("num"))

    return None


def describes_same_chapter(title_a: str, title_b: str) -> bool:
    """
    True when two headings found on nearby pages name the same chapter.

    Fusion needs this because its ±1 page tolerance exists for one specific
    situation — a PDF outline points at the chapter's first page while the
    heading itself is typeset on the next — and for nothing else.  Without a
    text check, that tolerance also merges a Part divider with the chapter
    that follows it, producing a chapter that starts a page early and wears
    the wrong title.
    """
    sig_a, sig_b = heading_signature(title_a), heading_signature(title_b)
    if sig_a and sig_b:
        return sig_a == sig_b

    a, b = normalize_heading(title_a), normalize_heading(title_b)
    if not a or not b:
        return False

    # One heading is the other's opening — the shape produced when a structural
    # detection carries the heading plus trailing body text.
    shorter, longer = sorted((a, b), key=len)
    return longer.startswith(shorter[: min(len(shorter), 24)])


def is_non_chapter_heading(title: str) -> bool:
    """
    True for Part/Book dividers and for front- or back-matter section names.

    These are real pages with real text — the engine folds them into the
    neighbouring chapter rather than dropping them, so nothing goes unnarrated.
    """
    normalized = normalize_heading(title)
    if not normalized:
        return False

    signature = heading_signature(normalized)
    if signature and signature[0] in ("part", "book"):
        return True

    if normalized in _NON_CHAPTER_EXACT:
        return True

    head = normalized[:_TITLE_LOOKAHEAD_CHARS]
    return any(
        head == name or head.startswith(name + " ") or head.startswith(name + ":")
        for name in _NON_CHAPTER_PREFIXES
    )


def _canonical_number(raw: str) -> str:
    """Fold number words to digits so 'Chapter One' and 'Chapter 1' agree."""
    words = {
        "one": "1", "two": "2", "three": "3", "four": "4", "five": "5",
        "six": "6", "seven": "7", "eight": "8", "nine": "9", "ten": "10",
        "eleven": "11", "twelve": "12",
        "uno": "1", "dos": "2", "tres": "3", "cuatro": "4", "cinco": "5",
        "seis": "6", "siete": "7", "ocho": "8", "nueve": "9", "diez": "10",
        "once": "11", "doce": "12",
    }
    lowered = raw.lower()
    return words.get(lowered, lowered)
