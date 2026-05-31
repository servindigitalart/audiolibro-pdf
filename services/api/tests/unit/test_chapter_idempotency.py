"""
Regression tests for chapter idempotency.

Covers the MultipleResultsFound bug: _persist_chapters must be safe to call
multiple times for the same document (Celery retry scenario) and must never
produce more than one row per (document_id, order_index) pair.

Test structure
--------------
- Pure unit tests (no DB): logic-level assertions that do not need PostgreSQL.
- DB integration tests: use the db_session fixture (requires sonoro_test DB).
  These are skipped automatically when the DB is unavailable.

Scenarios covered
-----------------
1. Calling _persist_chapters twice produces the same row count (retry safety).
2. Direct duplicate INSERT raises IntegrityError (constraint present).
3. Single-chapter document: no duplicates after two calls.
4. Multi-chapter document: no duplicates after two calls.
5. Re-running with different chapter data replaces old rows entirely.
"""

import pytest
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.db.models.chapter import Chapter
from app.services.document_structure.engine import DocumentStructureEngine
from app.services.document_structure.models import DetectedChapter


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_detected(title: str, start: int, end: int, index: int = 0) -> DetectedChapter:
    return DetectedChapter(
        title=title,
        start_page=start,
        end_page=end,
        confidence=0.9,
        detection_method="chapter_keyword",
        text_content=f"Body of {title}",
    )


def _make_chapters(n: int) -> list[DetectedChapter]:
    return [_make_detected(f"Chapter {i + 1}", i + 1, i + 1, i) for i in range(n)]


# ---------------------------------------------------------------------------
# Pure unit tests — no database required
# ---------------------------------------------------------------------------

class TestPersistChaptersUnit:
    """
    Verify _persist_chapters behaviour using an async mock session.
    These tests run without PostgreSQL.
    """

    def _make_engine(self) -> DocumentStructureEngine:
        engine = DocumentStructureEngine.__new__(DocumentStructureEngine)
        return engine

    @pytest.mark.asyncio
    async def test_delete_called_before_insert(self):
        """_persist_chapters must execute a DELETE before any db.add() calls."""
        engine = self._make_engine()
        doc_id = uuid.uuid4()
        chapters = _make_chapters(3)

        call_order = []

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(side_effect=lambda *a, **kw: call_order.append("execute"))
        mock_session.add = MagicMock(side_effect=lambda *a, **kw: call_order.append("add"))
        mock_session.commit = AsyncMock()

        await engine._persist_chapters(doc_id, chapters, mock_session)

        # The DELETE (execute) must come before any add()
        assert call_order[0] == "execute", (
            f"Expected execute (DELETE) first, got: {call_order}"
        )
        add_calls = [c for c in call_order if c == "add"]
        assert len(add_calls) == 3

    @pytest.mark.asyncio
    async def test_commit_called_once(self):
        """A single commit flushes the DELETE + all INSERTs atomically."""
        engine = self._make_engine()
        doc_id = uuid.uuid4()

        mock_session = AsyncMock()
        mock_session.add = MagicMock()

        await engine._persist_chapters(doc_id, _make_chapters(2), mock_session)

        mock_session.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_empty_chapter_list_only_deletes(self):
        """Calling with an empty list deletes existing rows and commits — no INSERTs."""
        engine = self._make_engine()
        doc_id = uuid.uuid4()

        mock_session = AsyncMock()
        mock_session.add = MagicMock()

        await engine._persist_chapters(doc_id, [], mock_session)

        mock_session.execute.assert_awaited_once()  # the DELETE
        mock_session.add.assert_not_called()
        mock_session.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_order_index_matches_list_position(self):
        """Each chapter must be persisted with order_index == its list position."""
        engine = self._make_engine()
        doc_id = uuid.uuid4()
        chapters = _make_chapters(4)

        added_objects = []
        mock_session = AsyncMock()
        mock_session.add = MagicMock(side_effect=lambda obj: added_objects.append(obj))

        await engine._persist_chapters(doc_id, chapters, mock_session)

        for expected_idx, obj in enumerate(added_objects):
            assert obj.order_index == expected_idx, (
                f"Chapter at list position {expected_idx} got order_index={obj.order_index}"
            )


# ---------------------------------------------------------------------------
# DB integration tests — skipped when PostgreSQL is unavailable
# ---------------------------------------------------------------------------

pytestmark_db = pytest.mark.asyncio


@pytest.mark.asyncio
async def test_persist_chapters_twice_no_duplicates(db_session):
    """Calling _persist_chapters twice for the same document must yield exactly
    N rows — not 2*N — so that scalar_one_or_none() never sees multiple rows."""
    doc_id = uuid.uuid4()
    chapters = _make_chapters(3)
    engine = DocumentStructureEngine.__new__(DocumentStructureEngine)

    await engine._persist_chapters(doc_id, chapters, db_session)
    # Simulate a Celery retry: same document, same chapters
    await engine._persist_chapters(doc_id, chapters, db_session)

    result = await db_session.execute(
        select(Chapter).where(Chapter.document_id == doc_id)
    )
    rows = result.scalars().all()
    assert len(rows) == 3, (
        f"Expected 3 rows after two persist calls, got {len(rows)}. "
        "Duplicate rows indicate _persist_chapters is not idempotent."
    )


@pytest.mark.asyncio
async def test_persist_single_chapter_document_no_duplicate(db_session):
    """Single-chapter documents must also be safe to reprocess."""
    doc_id = uuid.uuid4()
    chapters = _make_chapters(1)
    engine = DocumentStructureEngine.__new__(DocumentStructureEngine)

    await engine._persist_chapters(doc_id, chapters, db_session)
    await engine._persist_chapters(doc_id, chapters, db_session)

    result = await db_session.execute(
        select(Chapter).where(Chapter.document_id == doc_id)
    )
    rows = result.scalars().all()
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_persist_multi_chapter_document_no_duplicate(db_session):
    """A document with many chapters must not accumulate on retry."""
    doc_id = uuid.uuid4()
    chapters = _make_chapters(8)
    engine = DocumentStructureEngine.__new__(DocumentStructureEngine)

    for _ in range(3):  # three runs (initial + two retries)
        await engine._persist_chapters(doc_id, chapters, db_session)

    result = await db_session.execute(
        select(Chapter).where(Chapter.document_id == doc_id)
    )
    rows = result.scalars().all()
    assert len(rows) == 8, (
        f"Expected 8 rows after 3 persist calls, got {len(rows)}"
    )


@pytest.mark.asyncio
async def test_rerun_replaces_chapters_with_new_data(db_session):
    """If re-analysis produces different chapters (e.g. different detection run),
    the old set is fully replaced — no stale rows remain."""
    doc_id = uuid.uuid4()
    engine = DocumentStructureEngine.__new__(DocumentStructureEngine)

    # First run: 5 chapters
    await engine._persist_chapters(doc_id, _make_chapters(5), db_session)

    # Second run (retry): 3 chapters (detection produced a different result)
    new_chapters = _make_chapters(3)
    await engine._persist_chapters(doc_id, new_chapters, db_session)

    result = await db_session.execute(
        select(Chapter).where(Chapter.document_id == doc_id)
    )
    rows = result.scalars().all()
    assert len(rows) == 3, (
        f"Expected 3 rows after replacement, got {len(rows)}"
    )
    titles = {r.title for r in rows}
    assert titles == {"Chapter 1", "Chapter 2", "Chapter 3"}


@pytest.mark.asyncio
async def test_scalar_one_or_none_safe_after_retry(db_session):
    """Regression test for the exact failure path: querying by (document_id,
    order_index) after a retry must return exactly one row, never raise
    MultipleResultsFound."""
    from sqlalchemy.exc import MultipleResultsFound

    doc_id = uuid.uuid4()
    chapters = _make_chapters(4)
    engine = DocumentStructureEngine.__new__(DocumentStructureEngine)

    # Simulate two full persist runs (initial run + one retry)
    await engine._persist_chapters(doc_id, chapters, db_session)
    await engine._persist_chapters(doc_id, chapters, db_session)

    # This is the exact query from processing.py line 644-650
    for i in range(4):
        ch_result = await db_session.execute(
            select(Chapter).where(
                Chapter.document_id == doc_id,
                Chapter.order_index == i,
            )
        )
        try:
            db_ch = ch_result.scalar_one_or_none()
        except MultipleResultsFound:
            pytest.fail(
                f"scalar_one_or_none() raised MultipleResultsFound for order_index={i}. "
                "Duplicate chapter rows were not cleaned up on retry."
            )
        assert db_ch is not None, f"Chapter with order_index={i} not found"
        assert db_ch.order_index == i


@pytest.mark.asyncio
async def test_unique_constraint_rejects_direct_duplicate_insert(db_session):
    """The DB constraint itself must reject a direct duplicate INSERT even if
    application code fails to call _persist_chapters (belt-and-suspenders)."""
    doc_id = uuid.uuid4()

    ch1 = Chapter(
        document_id=doc_id,
        title="Intro",
        start_page=1,
        end_page=5,
        order_index=0,
        confidence_score=0.9,
        detection_method="chapter_keyword",
        char_count=100,
    )
    ch2 = Chapter(
        document_id=doc_id,
        title="Intro (duplicate)",
        start_page=1,
        end_page=5,
        order_index=0,  # same order_index — must be rejected
        confidence_score=0.9,
        detection_method="chapter_keyword",
        char_count=100,
    )

    db_session.add(ch1)
    await db_session.flush()

    db_session.add(ch2)
    with pytest.raises(IntegrityError):
        await db_session.flush()
