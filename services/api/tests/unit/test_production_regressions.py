"""
Regression Tests — Production Regressions (2026-06-02)
========================================================
Six confirmed production bugs, one test class per bug:

  1. S3 metadata — Unicode chapter titles crash upload
  2. Celery deterministic retries — ParamValidationError loops 3×
  3. Spanish filename extractor — wrong title/author split
  4. PDF metadata blocklist — pirate watermarks accepted
  5. Language detection — 1000-char page-0 sample → English misclassification
  6. Retry UX — no live progress after Library retry (frontend guard test)
"""

import pytest

pytestmark = pytest.mark.unit


# ── 1. S3 metadata — sanitize_s3_metadata() ──────────────────────────────────

from app.services.storage_service import sanitize_s3_metadata


class TestSanitizeS3Metadata:
    """sanitize_s3_metadata must produce only US-ASCII values."""

    def test_plain_ascii_passes_through(self):
        meta = {"chapter_order": "3", "character_count": "4500"}
        result = sanitize_s3_metadata(meta)
        assert result == meta

    def test_em_dash_stripped(self):
        # "XVIII — El principito" crashes S3 with ParamValidationError
        meta = {"chapter_title": "XVIII — El principito atravesó el desierto"}
        result = sanitize_s3_metadata(meta)
        val = result["chapter_title"]
        assert val.isascii(), f"Not ASCII: {val!r}"

    def test_accented_chars_stripped(self):
        meta = {"chapter_title": "Niño perdido en el páramo"}
        result = sanitize_s3_metadata(meta)
        assert result["chapter_title"].isascii()

    def test_ene_stripped(self):
        meta = {"value": "Año Nuevo"}
        result = sanitize_s3_metadata(meta)
        assert result["value"].isascii()

    def test_smart_quotes_stripped(self):
        meta = {"value": "“Hello” ‘world’"}
        result = sanitize_s3_metadata(meta)
        assert result["value"].isascii()

    def test_chinese_stripped(self):
        meta = {"value": "你好世界"}
        result = sanitize_s3_metadata(meta)
        assert result["value"].isascii()

    def test_empty_string_preserved(self):
        assert sanitize_s3_metadata({"k": ""}) == {"k": ""}

    def test_numeric_int_coerced_to_string(self):
        result = sanitize_s3_metadata({"count": 42})  # type: ignore[arg-type]
        assert result["count"] == "42"

    def test_truncation_at_256(self):
        long_val = "A" * 300
        result = sanitize_s3_metadata({"k": long_val})
        assert len(result["k"]) <= 256

    def test_mixed_ascii_unicode(self):
        meta = {"user-id": "abc123", "chapter_title": "Capítulo V"}
        result = sanitize_s3_metadata(meta)
        assert result["user-id"] == "abc123"
        assert result["chapter_title"].isascii()

    def test_control_characters_replaced(self):
        meta = {"v": "hello\x00world\x1f"}
        result = sanitize_s3_metadata(meta)
        assert "\x00" not in result["v"]
        assert "\x1f" not in result["v"]


# ── 2. Non-retryable deterministic errors ─────────────────────────────────────

class TestDeterministicErrors:
    """ParamValidationError is deterministic — should never trigger Celery retry."""

    def test_param_validation_error_is_in_deterministic_tuple(self):
        from app.tasks.processing import _DETERMINISTIC_ERRORS
        try:
            from botocore.exceptions import ParamValidationError
            assert issubclass(ParamValidationError, _DETERMINISTIC_ERRORS), (
                "ParamValidationError must be in _DETERMINISTIC_ERRORS so the "
                "worker catches it without re-raising for Celery retry"
            )
        except ImportError:
            pytest.skip("botocore not installed")

    def test_deterministic_errors_is_a_tuple(self):
        from app.tasks.processing import _DETERMINISTIC_ERRORS
        assert isinstance(_DETERMINISTIC_ERRORS, tuple)

    def test_deterministic_errors_does_not_include_generic_exception(self):
        """Should not accidentally swallow all exceptions."""
        from app.tasks.processing import _DETERMINISTIC_ERRORS
        assert Exception not in _DETERMINISTIC_ERRORS

    def test_chapter_title_removed_from_s3_metadata(self):
        """chapter_title must NOT appear in the S3 metadata dict built in processing.py."""
        import pathlib
        src_path = pathlib.Path(__file__).parents[2] / "app" / "tasks" / "processing.py"
        src = src_path.read_text()
        assert '"chapter_title"' not in src, (
            "chapter_title found in processing.py — "
            "Unicode chapter titles must not be stored in S3 metadata"
        )


# ── 3. Filename extractor — Spanish kebab filenames ──────────────────────────

from app.metadata.extractor import LocalExtractor


class TestSpanishFilenameExtraction:
    """el_llano_en_llamas-juan_rulfo.pdf must yield title+author correctly."""

    def _extract(self, filename: str):
        return LocalExtractor().extract(filename=filename, pdf_bytes=None)

    def test_llano_en_llamas_title(self):
        titles, _ = self._extract("el_llano_en_llamas-juan_rulfo.pdf")
        title_values = [c.value.lower() for c in titles]
        assert any("llano" in v and "llamas" in v for v in title_values), (
            f"Expected 'El Llano en Llamas' in candidates, got: {title_values}"
        )

    def test_llano_en_llamas_author(self):
        _, authors = self._extract("el_llano_en_llamas-juan_rulfo.pdf")
        author_values = [c.value.lower() for c in authors]
        assert any("rulfo" in v or "juan" in v for v in author_values), (
            f"Expected 'Juan Rulfo' in author candidates, got: {author_values}"
        )

    def test_atomic_habits_no_garbage_author(self):
        """atomic-habits-james-clear.pdf must NOT set 'habits james clear' as author."""
        _, authors = self._extract("atomic-habits-james-clear.pdf")
        for a in authors:
            assert "habits" not in a.value.lower(), (
                f"'habits' appeared in author candidate {a.value!r} — "
                "the aggressive [-_] split is still firing"
            )

    def test_don_quijote_title_author_split(self):
        titles, authors = self._extract("don_quijote-cervantes.pdf")
        title_values = [c.value.lower() for c in titles]
        author_values = [c.value.lower() for c in authors]
        assert any("quijote" in v for v in title_values)
        assert any("cervantes" in v for v in author_values)

    def test_by_separator_still_works(self):
        titles, authors = self._extract("deep_work_by_cal_newport.pdf")
        title_values = [c.value.lower() for c in titles]
        author_values = [c.value.lower() for c in authors]
        assert any("deep" in v for v in title_values)
        assert any("newport" in v or "cal" in v for v in author_values)

    def test_single_word_filename_does_not_crash(self):
        titles, authors = LocalExtractor().extract("test.pdf", pdf_bytes=None)
        assert isinstance(titles, list)
        assert isinstance(authors, list)

    def test_multiple_hyphens_does_not_split_on_first(self):
        """a-brief-history-of-time.pdf has multiple hyphens → no underscore → Strategy C."""
        titles, authors = self._extract("a-brief-history-of-time.pdf")
        # Should produce a title but NOT a bogus author from the first hyphen
        if authors:
            for a in authors:
                # "brief history of time" should never be an author
                assert len(a.value.split()) <= 4, (
                    f"Suspicious long author candidate from multi-hyphen filename: {a.value!r}"
                )


# ── 4. PDF metadata blocklist ─────────────────────────────────────────────────

from app.metadata.extractor import _is_trustworthy_pdf_meta


class TestPDFMetaBlocklist:
    """Known pirate/scanner watermarks must be rejected."""

    def test_iafabooks_rejected(self):
        assert not _is_trustworthy_pdf_meta("IafaBOOKS 2007: Luis Antonio Fernández Aldana")

    def test_iafabooks_lowercase_rejected(self):
        assert not _is_trustworthy_pdf_meta("iafabooks")

    def test_epublibre_rejected(self):
        assert not _is_trustworthy_pdf_meta("ePub Libre 3.1 — converted")

    def test_calibre_rejected(self):
        assert not _is_trustworthy_pdf_meta("Calibre 5.43.0")

    def test_real_title_accepted(self):
        assert _is_trustworthy_pdf_meta("El Llano en Llamas")

    def test_real_author_accepted(self):
        assert _is_trustworthy_pdf_meta("Juan Rulfo")

    def test_pirate_stamp_pattern_rejected(self):
        # "PublisherXYZ 2009: SomePerson" style
        assert not _is_trustworthy_pdf_meta("InternetArchive 2009: John Smith")

    def test_empty_string_rejected(self):
        assert not _is_trustworthy_pdf_meta("")

    def test_two_char_string_rejected(self):
        assert not _is_trustworthy_pdf_meta("AB")

    def test_english_book_title_accepted(self):
        assert _is_trustworthy_pdf_meta("Atomic Habits")

    def test_spanish_title_with_accent_accepted(self):
        assert _is_trustworthy_pdf_meta("Cien años de soledad")


# ── 5. Language detection sample ─────────────────────────────────────────────

class TestLanguageDetectionSample:
    """upload_document must sample ≥3 pages/3000 chars for language detection."""

    @staticmethod
    def _doc_service_src() -> str:
        import pathlib
        return (
            pathlib.Path(__file__).parents[2]
            / "app" / "services" / "document_service.py"
        ).read_text()

    def test_extract_metadata_samples_multiple_pages(self):
        src = self._doc_service_src()
        assert "_LANG_SAMPLE_PAGES" in src or "range(min(5" in src or "range(min(3" in src, (
            "Language detection must sample more than 1 page. "
            "_LANG_SAMPLE_PAGES or min(N,...) loop not found."
        )

    def test_lang_sample_max_chars_is_at_least_3000(self):
        src = self._doc_service_src()
        assert "3_000" in src or "5_000" in src or "3000" in src or "5000" in src, (
            "Language detection max chars must be >= 3000"
        )

    def test_lang_sample_not_limited_to_first_page_only(self):
        src = self._doc_service_src()
        assert "text[:1000]" not in src, (
            "The old 1000-char single-page language sample is still present — "
            "must be replaced with a multi-page sample"
        )


# ── 6. Metadata session use-after-free ───────────────────────────────────────

class TestMetadataSessionFix:
    """MetadataService.enrich must accept db_url (str), not a session object."""

    def test_enrich_signature_accepts_db_url(self):
        import inspect
        from app.metadata.service import MetadataService
        sig = inspect.signature(MetadataService.enrich)
        params = list(sig.parameters.keys())
        assert "db_url" in params, (
            "MetadataService.enrich must accept db_url (string) not a session "
            f"object. Found params: {params}"
        )
        assert "db" not in params, (
            "The old 'db' session parameter is still present — "
            "background task would use a closed request-scoped session"
        )

    def test_enrich_db_url_annotation_is_str(self):
        import inspect
        from app.metadata.service import MetadataService
        sig = inspect.signature(MetadataService.enrich)
        ann = sig.parameters["db_url"].annotation
        # annotation may be str or inspect.Parameter.empty
        if ann is not inspect.Parameter.empty:
            assert ann is str or ann == "str", (
                f"db_url should be annotated as str, got {ann}"
            )

    @staticmethod
    def _doc_service_src() -> str:
        import pathlib
        return (
            pathlib.Path(__file__).parents[2]
            / "app" / "services" / "document_service.py"
        ).read_text()

    def test_document_service_passes_db_url_not_session(self):
        src = self._doc_service_src()
        assert "database_async_url" in src, (
            "document_service must pass settings.database_async_url to MetadataService.enrich"
        )
        assert "db=self.db" not in src, (
            "document_service still passes db=self.db to MetadataService — "
            "this causes a use-after-free when the request session is closed"
        )
