"""
Golden Corpus regression suite (Phase 1.1 / audit C8)
=====================================================
The audit's finding after Phase 0A was that fixing the fusion collapse (F-1)
unmasked the detectors for the first time — their real accuracy had never been
observed, because every book collapsed to one chapter before anyone could see
it.  This suite is the measurement that was missing.

Run the baseline table with:

    pytest tests/unit/test_chapter_golden_corpus.py -m unit -s -k baseline

Everything else here is a hard assertion: per-fixture accuracy, plus the
engine-wide invariants from the Phase 1.1 quality contract.
"""
from __future__ import annotations

import pytest

from tests.fixtures.chapter_corpus import (
    CORPUS,
    FALLBACK_METHOD,
    format_report,
    normalize_title,
    run_engine,
    score,
)

pytestmark = pytest.mark.unit


@pytest.fixture(scope="module")
def corpus_dir(tmp_path_factory):
    return tmp_path_factory.mktemp("chapter_corpus")


async def _results(corpus_dir):
    out = []
    for fixture in CORPUS:
        result = await run_engine(fixture, corpus_dir)
        out.append((result, score(result)))
    return out


# ── Baseline report ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_baseline_report(corpus_dir, capsys):
    """Reproducible accuracy table.  Prints under -s; always asserts the total."""
    rows = await _results(corpus_dir)
    report = format_report(rows)
    with capsys.disabled():
        print("\n" + report + "\n")

    macro_f1 = sum(sc.f1 for _, sc in rows if not _.fixture.expect_fallback)
    graded = sum(1 for r, _ in rows if not r.fixture.expect_fallback)
    assert macro_f1 / graded >= 0.95, f"macro F1 regressed:\n{report}"


# ── Per-fixture accuracy ──────────────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize("fixture", CORPUS, ids=lambda f: f.name)
async def test_fixture_chapter_count(fixture, corpus_dir):
    result = await run_engine(fixture, corpus_dir)

    if fixture.expect_fallback:
        assert result.is_fallback, (
            f"{fixture.name}: expected the full-document path, got "
            f"{[(c.title, c.start_page) for c in result.detected]}"
        )
        return

    assert not result.is_fallback, f"{fixture.name}: fell back instead of detecting"
    assert len(result.detected) == len(fixture.expected), (
        f"{fixture.name}: expected {len(fixture.expected)} chapters, got "
        f"{[(c.title, c.start_page, c.end_page) for c in result.detected]}"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "fixture", [f for f in CORPUS if not f.expect_fallback], ids=lambda f: f.name
)
async def test_fixture_boundaries_and_titles(fixture, corpus_dir):
    result = await run_engine(fixture, corpus_dir)
    sc = score(result)

    assert sc.false_negatives == 0, (
        f"{fixture.name}: missed {[e.title_contains for e in sc.unmatched_expected]}"
    )
    assert sc.false_positives == 0, (
        f"{fixture.name}: spurious "
        f"{[(d.title, d.start_page) for d in sc.unmatched_detected]}"
    )

    for exp, det in sc.matched:
        assert abs(det.end_page - exp.end_page) <= fixture.end_tolerance, (
            f"{fixture.name}: '{exp.title_contains}' end_page {det.end_page} "
            f"outside ±{fixture.end_tolerance} of {exp.end_page}"
        )
        assert exp.title_contains in normalize_title(det.title), (
            f"{fixture.name}: title {det.title!r} does not contain "
            f"{exp.title_contains!r}"
        )


# ── Invariants (Phase 1.1 quality contract) ───────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize("fixture", CORPUS, ids=lambda f: f.name)
async def test_invariant_ranges_do_not_overlap(fixture, corpus_dir):
    """Invariant 1 — overlapping ranges narrate the same pages twice."""
    result = await run_engine(fixture, corpus_dir)
    for a, b in zip(result.detected, result.detected[1:]):
        assert a.end_page < b.start_page, (
            f"{fixture.name}: '{a.title}' ({a.start_page}-{a.end_page}) overlaps "
            f"'{b.title}' ({b.start_page}-{b.end_page})"
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("fixture", CORPUS, ids=lambda f: f.name)
async def test_invariant_ranges_stay_inside_the_document(fixture, corpus_dir):
    """Invariant 2 — a range outside the document extracts no text."""
    result = await run_engine(fixture, corpus_dir)
    for ch in result.detected:
        assert 1 <= ch.start_page <= result.total_pages
        assert ch.start_page <= ch.end_page <= result.total_pages


@pytest.mark.asyncio
@pytest.mark.parametrize("fixture", CORPUS, ids=lambda f: f.name)
async def test_invariant_order_is_monotonic(fixture, corpus_dir):
    """Invariant 3 — chapters are narrated in the order they are returned."""
    result = await run_engine(fixture, corpus_dir)
    starts = [c.start_page for c in result.detected]
    assert starts == sorted(starts), f"{fixture.name}: out of order {starts}"


@pytest.mark.asyncio
@pytest.mark.parametrize("fixture", CORPUS, ids=lambda f: f.name)
async def test_invariant_final_chapter_reaches_the_end(fixture, corpus_dir):
    """Invariant 6 — anything after the last chapter would never be narrated."""
    result = await run_engine(fixture, corpus_dir)
    assert result.detected, f"{fixture.name}: no chapters at all"
    assert result.detected[-1].end_page == result.total_pages, (
        f"{fixture.name}: last chapter ends at {result.detected[-1].end_page}, "
        f"document has {result.total_pages} pages"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("fixture", CORPUS, ids=lambda f: f.name)
async def test_invariant_no_gaps_after_the_first_chapter(fixture, corpus_dir):
    """
    From the first chapter to the end of the document, every page belongs to
    exactly one chapter — a gap in the middle is text the listener never hears.

    Pages *before* the first chapter are allowed to be uncovered: that is where
    the printed table of contents and the title page live, and narrating them
    is worse than skipping them.  This is pre-existing behaviour, unchanged by
    Phase 1.1.
    """
    result = await run_engine(fixture, corpus_dir)
    first_page = result.detected[0].start_page
    covered = [p for ch in result.detected for p in range(ch.start_page, ch.end_page + 1)]
    assert sorted(covered) == list(range(first_page, result.total_pages + 1)), (
        f"{fixture.name}: coverage {sorted(covered)} != "
        f"{first_page}..{result.total_pages}"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("fixture", CORPUS, ids=lambda f: f.name)
async def test_invariant_deterministic(fixture, corpus_dir):
    """Invariant 10 — same document twice, same structure."""
    first = await run_engine(fixture, corpus_dir)
    second = await run_engine(fixture, corpus_dir)

    shape = lambda r: [  # noqa: E731 — a name would not make this clearer
        (c.title, c.start_page, c.end_page, round(c.confidence, 6), c.detection_method)
        for c in r.detected
    ]
    assert shape(first) == shape(second), f"{fixture.name}: non-deterministic output"


@pytest.mark.asyncio
async def test_invariant_no_chapter_document_uses_fallback(corpus_dir):
    """Invariant 7 — a document with no credible structure narrates whole."""
    fixture = next(f for f in CORPUS if f.expect_fallback)
    result = await run_engine(fixture, corpus_dir)

    assert len(result.detected) == 1
    assert result.detected[0].detection_method == FALLBACK_METHOD
    assert result.detected[0].start_page == 1
    assert result.detected[0].end_page == result.total_pages


@pytest.mark.asyncio
async def test_invariant_parts_do_not_replace_chapters(corpus_dir):
    """
    Invariant 8 — the F-5 regression.  A Part/Chapter outline must yield the
    chapters; returning 2 "PARTE" chapters for an 4-chapter book is the exact
    failure the audit named.
    """
    fixture = next(f for f in CORPUS if f.name == "part_chapter_hierarchy_toc")
    result = await run_engine(fixture, corpus_dir)

    titles = [normalize_title(c.title) for c in result.detected]
    assert len(result.detected) == 4, f"expected 4 chapters, got {titles}"
    assert not any(t.startswith("parte") for t in titles), (
        f"Parts leaked into the chapter list: {titles}"
    )
