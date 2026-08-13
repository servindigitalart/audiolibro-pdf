"""
Unit Tests: TextSegmenter removal (Phase 0E / audit F-7)
========================================================
`TextSegmenter` was 327 lines that no code called.  `DocumentStructureEngine`
imported it and assigned `self.segmenter` in __init__, and nothing ever invoked
`segment_text()` — the worker has always chunked with its own `_chunk_text`.

Phase 0D kept it on the incorrect finding that it was live; the Phase 0 exit
audit re-checked and confirmed the original audit (F-7) was right.

These tests pin the removal so the module cannot drift back, and prove the
engine still constructs and still exposes every detector it actually uses.
"""
import importlib

import pytest

pytestmark = pytest.mark.unit


# ── The module is gone ────────────────────────────────────────────────────────


def test_segmenter_module_no_longer_importable():
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("app.services.document_structure.segmenter")


def test_package_does_not_export_text_segmenter():
    import app.services.document_structure as ds

    assert not hasattr(ds, "TextSegmenter")
    assert "TextSegmenter" not in ds.__all__


def test_no_production_module_references_the_deleted_symbol():
    """
    Repo-wide guard: catches a re-introduced import anywhere under app/, which
    a single-file assertion would miss.
    """
    from pathlib import Path

    app_dir = Path(__file__).resolve().parents[2] / "app"
    offenders = [
        str(py.relative_to(app_dir))
        for py in app_dir.rglob("*.py")
        if "TextSegmenter" in py.read_text(encoding="utf-8")
        or "segment_text" in py.read_text(encoding="utf-8")
    ]
    assert offenders == [], f"dead segmenter references reappeared in: {offenders}"


# ── The engine still works without it ─────────────────────────────────────────


def test_engine_initializes_without_the_segmenter():
    from app.services.document_structure.engine import DocumentStructureEngine

    engine = DocumentStructureEngine()
    assert not hasattr(engine, "segmenter")


def test_engine_still_owns_every_detector_it_uses():
    """Removal must have touched only the dead attribute, nothing else."""
    from app.services.document_structure.engine import DocumentStructureEngine

    engine = DocumentStructureEngine()
    for attr in (
        "toc_extractor",
        "heuristic_detector",
        "structural_analyzer",
        "confidence_scorer",
    ):
        assert getattr(engine, attr) is not None, f"{attr} lost in the deletion"


def test_package_still_exports_the_public_surface():
    """The deletion must not have taken unrelated exports with it."""
    import app.services.document_structure as ds

    for name in (
        "DocumentStructureEngine",
        "DetectedChapter",
        "TextChunk",
        "PageText",
        "TOCEntry",
        "DocumentStructure",
        "SegmentationResult",
    ):
        assert name in ds.__all__
        assert hasattr(ds, name)


# ── The real chunker is untouched ─────────────────────────────────────────────


def test_worker_chunker_is_still_the_only_splitter():
    """
    `_chunk_text` is what actually splits text for TTS.  Phase 0E must not have
    altered it while removing the module that never did.
    """
    from app.tasks.processing import _chunk_text, _TTS_CHUNK_SIZE

    assert _TTS_CHUNK_SIZE <= 5000, "Google TTS hard limit is 5000 chars"

    chunks = _chunk_text("word " * 4000)
    assert len(chunks) > 1
    assert all(len(c) <= _TTS_CHUNK_SIZE for c in chunks)
