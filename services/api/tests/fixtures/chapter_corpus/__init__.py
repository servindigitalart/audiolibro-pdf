"""
Golden Corpus for the chapter engine
====================================
`CORPUS` is the fixture set; `run_engine` executes the real
`DocumentStructureEngine` against one fixture; `score` turns the result into
precision/recall/F1 against the fixture's expectations.

The engine is run through its public `analyze_document` entry point with a stub
session, not by re-assembling its steps here — a harness that reimplements the
orchestration would stop testing the orchestration.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Sequence
from uuid import uuid4

from tests.fixtures.chapter_corpus.builder import Page, build_pdf, toc_page_lines
from tests.fixtures.chapter_corpus.corpus import (
    CORPUS,
    ExpectedChapter,
    Fixture,
)

__all__ = [
    "CORPUS",
    "ExpectedChapter",
    "Fixture",
    "Page",
    "Result",
    "build_pdf",
    "normalize_title",
    "run_engine",
    "score",
    "toc_page_lines",
]

FALLBACK_METHOD = "length_fallback"


class _StubSession:
    """
    Minimal AsyncSession stand-in — persistence is not what the corpus measures.

    `_persist_chapters` is still exercised (it runs against this), so a change
    that breaks the persistence call shape still fails here.
    """

    def __init__(self) -> None:
        self.added: list = []

    async def execute(self, *_args, **_kwargs):
        return None

    async def flush(self):
        return None

    async def commit(self):
        return None

    async def rollback(self):
        return None

    def add(self, obj):
        self.added.append(obj)


def normalize_title(title: str) -> str:
    """Case-fold and collapse whitespace — see the corpus tolerance policy."""
    return re.sub(r"\s+", " ", (title or "").strip()).lower()


@dataclass
class Result:
    fixture: Fixture
    detected: list
    total_pages: int

    @property
    def is_fallback(self) -> bool:
        return (
            len(self.detected) == 1
            and self.detected[0].detection_method == FALLBACK_METHOD
        )


async def run_engine(fixture: Fixture, tmp_dir) -> Result:
    """Build the fixture PDF and run the real engine over it."""
    from app.services.document_structure.engine import DocumentStructureEngine

    pdf_path = str(tmp_dir / f"{fixture.name}.pdf")
    build_pdf(pdf_path, fixture.pages, fixture.toc)

    engine = DocumentStructureEngine()
    structure = await engine.analyze_document(uuid4(), pdf_path, _StubSession())
    return Result(
        fixture=fixture,
        detected=list(structure.chapters),
        total_pages=structure.total_pages,
    )


@dataclass
class Score:
    true_positives: int
    false_positives: int
    false_negatives: int
    page_coverage: float
    matched: list          # (expected, detected) pairs
    unmatched_expected: list
    unmatched_detected: list

    @property
    def precision(self) -> float:
        denom = self.true_positives + self.false_positives
        return self.true_positives / denom if denom else 0.0

    @property
    def recall(self) -> float:
        denom = self.true_positives + self.false_negatives
        return self.true_positives / denom if denom else 0.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if (p + r) else 0.0


def score(result: Result) -> Score:
    """
    Match detected chapters to expected ones by start page, within tolerance.

    Greedy nearest-start matching: each expected chapter claims at most one
    detection and vice versa, so a detector that emits five chapters where one
    was expected is scored as one hit and four false positives rather than
    being credited five times.
    """
    fixture = result.fixture

    # A fixture whose correct answer IS the full-document chapter scores on
    # that, not on an empty expectation list — otherwise the right behaviour
    # would be reported as a false positive.
    if fixture.expect_fallback:
        correct = result.is_fallback
        return Score(
            true_positives=1 if correct else 0,
            false_positives=0 if correct else len(result.detected),
            false_negatives=0 if correct else 1,
            page_coverage=1.0 if correct else 0.0,
            matched=[], unmatched_expected=[], unmatched_detected=[],
        )

    remaining = list(result.detected)
    matched, unmatched_expected = [], []

    for exp in fixture.expected:
        candidates = [
            d for d in remaining
            if abs(d.start_page - exp.start_page) <= fixture.start_tolerance
        ]
        if candidates:
            best = min(candidates, key=lambda d: abs(d.start_page - exp.start_page))
            remaining.remove(best)
            matched.append((exp, best))
        else:
            unmatched_expected.append(exp)

    covered = set()
    for det in result.detected:
        covered.update(range(det.start_page, det.end_page + 1))
    page_coverage = len(covered) / result.total_pages if result.total_pages else 0.0

    return Score(
        true_positives=len(matched),
        false_positives=len(remaining),
        false_negatives=len(unmatched_expected),
        page_coverage=page_coverage,
        matched=matched,
        unmatched_expected=unmatched_expected,
        unmatched_detected=remaining,
    )


def format_report(rows: Sequence[tuple]) -> str:
    """Render the baseline table.  `rows` is (Result, Score) pairs."""
    header = (
        f"{'fixture':<34}{'exp':>4}{'det':>4}{'TP':>4}{'FP':>4}{'FN':>4}"
        f"{'prec':>7}{'rec':>7}{'F1':>7}{'cov':>7}  methods"
    )
    lines = [header, "-" * len(header)]
    for result, sc in rows:
        expected_n = 1 if result.fixture.expect_fallback else len(result.fixture.expected)
        methods = ",".join(sorted({d.detection_method for d in result.detected}))
        lines.append(
            f"{result.fixture.name:<34}{expected_n:>4}{len(result.detected):>4}"
            f"{sc.true_positives:>4}{sc.false_positives:>4}{sc.false_negatives:>4}"
            f"{sc.precision:>7.2f}{sc.recall:>7.2f}{sc.f1:>7.2f}{sc.page_coverage:>7.2f}"
            f"  {methods[:44]}"
        )
    return "\n".join(lines)
