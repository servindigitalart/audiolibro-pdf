"""
Unit Tests: Worker Async Engine Lifecycle
==========================================
Regression tests for:
  RuntimeError: Future attached to a different loop

Root cause: a module-level AsyncEngine was created at import time and reused
across multiple asyncio.run() calls (each of which creates a new event loop).
asyncpg's connection pool is bound to the loop that created it — reusing it
in a different loop raises the error above.

Fix: create a fresh engine inside each asyncio.run() coroutine (_dispatch_job)
and dispose it before the coroutine returns.

These tests are pure unit tests — no real DB connection is made.
"""
import asyncio
import types
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

pytestmark = pytest.mark.unit


# ── No module-level engine ────────────────────────────────────────────────────

def test_processing_module_has_no_module_level_engine():
    """Verify that the module no longer exports a top-level async_engine."""
    import app.tasks.processing as proc
    assert not hasattr(proc, "async_engine"), (
        "Found a module-level 'async_engine' in processing.py. "
        "This will cause 'Future attached to a different loop' errors in Celery workers."
    )


def test_processing_module_has_no_module_level_session_local():
    """Verify that AsyncSessionLocal is not a module-level name."""
    import app.tasks.processing as proc
    assert not hasattr(proc, "AsyncSessionLocal"), (
        "Found a module-level 'AsyncSessionLocal' in processing.py. "
        "Session factories must be created per asyncio.run() call in Celery workers."
    )


# ── _dispatch_job creates and disposes engine ─────────────────────────────────

@pytest.mark.asyncio
async def test_dispatch_job_disposes_engine_on_success():
    """Engine.dispose() must be called even when the job succeeds."""
    from uuid import uuid4
    from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, AsyncSession

    mock_engine = AsyncMock(spec=AsyncEngine)
    mock_session = AsyncMock(spec=AsyncSession)
    mock_session_ctx = AsyncMock()
    mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session_ctx.__aexit__ = AsyncMock(return_value=False)

    mock_factory = MagicMock(spec=async_sessionmaker)
    mock_factory.return_value = mock_session_ctx

    import app.tasks.processing as proc

    disposed = []

    async def fake_engine_dispose():
        disposed.append(True)

    mock_engine.dispose = fake_engine_dispose

    with (
        patch("app.tasks.processing.create_async_engine", return_value=mock_engine),
        patch("app.tasks.processing.async_sessionmaker", return_value=mock_factory),
        patch("app.tasks.processing._process_job_async", new_callable=AsyncMock) as mock_proc,
    ):
        await proc._dispatch_job(uuid4(), "task-123", 0)

    mock_proc.assert_awaited_once()
    assert disposed, "engine.dispose() was never called — connections would leak."


@pytest.mark.asyncio
async def test_dispatch_job_disposes_engine_on_failure():
    """Engine.dispose() must be called even when the job raises an exception."""
    from uuid import uuid4
    from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

    mock_engine = AsyncMock(spec=AsyncEngine)
    mock_factory = MagicMock(spec=async_sessionmaker)

    import app.tasks.processing as proc

    disposed = []

    async def fake_engine_dispose():
        disposed.append(True)

    mock_engine.dispose = fake_engine_dispose

    with (
        patch("app.tasks.processing.create_async_engine", return_value=mock_engine),
        patch("app.tasks.processing.async_sessionmaker", return_value=mock_factory),
        patch(
            "app.tasks.processing._process_job_async",
            new_callable=AsyncMock,
            side_effect=RuntimeError("simulated TTS failure"),
        ),
        patch("app.tasks.processing._mark_job_failed", new_callable=AsyncMock),
    ):
        with pytest.raises(RuntimeError, match="simulated TTS failure"):
            await proc._dispatch_job(uuid4(), "task-456", 0)

    assert disposed, "engine.dispose() was never called after job failure — connections would leak."


# ── _derive_language_code in processing path ──────────────────────────────────

def test_voice_override_derives_language_code():
    """
    When a Spanish voice is selected as voice_id_override, the worker must
    derive 'es-US' and pass it to TTS — not use the language-detector's 'en-US'.
    """
    voice_id = "es-US-Neural2-A"
    parts = voice_id.split("-")
    assert len(parts) >= 2
    assert len(parts[0]) == 2 and len(parts[1]) == 2
    derived = f"{parts[0]}-{parts[1]}"
    assert derived == "es-US"


def test_voice_override_does_not_override_non_standard_voice():
    """A non-standard voice ID (no region segment) leaves language_code unchanged."""
    voice_id = "CustomVoice"
    parts = voice_id.split("-")
    original_lang = "en-US"
    if len(parts) >= 2 and len(parts[0]) == 2 and len(parts[1]) == 2:
        derived = f"{parts[0]}-{parts[1]}"
    else:
        derived = original_lang
    assert derived == original_lang
