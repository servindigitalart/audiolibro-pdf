"""
Metadata Service
=================
Main orchestrator for the Book Intelligence Layer.

Pipeline:
  1. LocalExtractor   → title / author candidates (instant, never fails)
  2. GoogleBooks      → up to 5 results (primary, async, 5-second timeout)
  3. OpenLibrary      → up to 5 results (fallback, async, 5-second timeout)
  4. Matcher          → score and pick best result
  5. CoverPipeline    → if confidence >= 0.60, download + store cover image
  6. Persist          → write metadata fields to document DB row

The entire pipeline is fire-and-forget from the caller's perspective:
  - Never raises
  - Never blocks audiobook generation
  - Total wall time: ≤ 6 seconds (API calls run in parallel)
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.metadata.extractor import LocalExtractor
from app.metadata.matcher import Matcher
from app.metadata.models import BookMetadata, MetadataSource
from app.metadata.providers.base import ProviderResult
from app.metadata.providers.google_books import GoogleBooksProvider
from app.metadata.providers.open_library import OpenLibraryProvider

logger = logging.getLogger(__name__)

# Minimum confidence to attempt cover download
_COVER_MIN_CONFIDENCE = 0.60

# Analytics event names
_EVT_DETECTED = "metadata_detected"
_EVT_ACCEPTED = "metadata_accepted"
_EVT_COVER_FOUND = "cover_found"
_EVT_COVER_MISSING = "cover_missing"


class MetadataService:
    """
    Orchestrates the full metadata enrichment pipeline.

    Usage:
        meta = await MetadataService.enrich(
            document_id=doc.id,
            user_id=user.id,
            filename=doc.original_filename,
            pdf_bytes=raw_bytes,         # optional but recommended
            detected_language=doc.language_detected,
            db=session,
            api_key="",                  # optional Google Books key
        )
    """

    @staticmethod
    async def enrich(
        document_id: UUID,
        user_id: UUID,
        filename: str,
        pdf_bytes: Optional[bytes],
        detected_language: Optional[str],
        db: AsyncSession,
        api_key: str = "",
    ) -> BookMetadata:
        """
        Run the full enrichment pipeline and persist results to the document row.

        Always returns a BookMetadata (never raises).
        """
        try:
            meta = await MetadataService._run_pipeline(
                filename=filename,
                pdf_bytes=pdf_bytes,
                detected_language=detected_language,
                api_key=api_key,
            )

            # Download + store cover if confidence is sufficient
            if meta.cover_url and meta.confidence >= _COVER_MIN_CONFIDENCE:
                meta = await MetadataService._download_cover(
                    meta=meta,
                    user_id=user_id,
                    document_id=document_id,
                )

            # Persist
            await MetadataService._persist(meta, document_id, db)

            # Analytics
            await MetadataService._track_analytics(meta, document_id, user_id, db)

            logger.info(
                "[METADATA] enrichment_complete document_id=%s source=%s confidence=%.2f "
                "title=%r author=%r cover=%s",
                document_id, meta.source.value, meta.confidence,
                meta.title, meta.author, bool(meta.cover_object_key),
            )
            return meta

        except Exception as exc:
            logger.exception(
                "[METADATA] enrichment_failed document_id=%s error=%s",
                document_id, exc,
            )
            # Return a bare local-only result so callers have something
            return BookMetadata(source=MetadataSource.LOCAL, confidence=0.0)

    # ── Pipeline steps ────────────────────────────────────────────────────────

    @staticmethod
    async def _run_pipeline(
        filename: str,
        pdf_bytes: Optional[bytes],
        detected_language: Optional[str],
        api_key: str,
    ) -> BookMetadata:
        # Step 1: local extraction
        extractor = LocalExtractor()
        title_candidates, author_candidates = extractor.extract(
            filename=filename,
            pdf_bytes=pdf_bytes,
        )
        logger.debug(
            "[METADATA] local_extraction titles=%d authors=%d",
            len(title_candidates), len(author_candidates),
        )

        # If we couldn't extract anything, return early
        if not title_candidates:
            return BookMetadata(source=MetadataSource.LOCAL, confidence=0.0)

        # Step 2: query providers in parallel
        best_title_query  = title_candidates[0].value
        best_author_query = author_candidates[0].value if author_candidates else None

        google_task  = asyncio.create_task(
            GoogleBooksProvider(api_key=api_key).search(best_title_query, best_author_query)
        )
        ol_task = asyncio.create_task(
            OpenLibraryProvider().search(best_title_query, best_author_query)
        )

        google_results, ol_results = await asyncio.gather(
            google_task, ol_task, return_exceptions=True
        )

        # Flatten provider results — label each with its source
        all_results: list[tuple[str, ProviderResult]] = []
        if isinstance(google_results, list):
            all_results.extend(("google_books", r) for r in google_results)
        if isinstance(ol_results, list):
            all_results.extend(("open_library", r) for r in ol_results)

        logger.debug(
            "[METADATA] provider_results google=%d open_library=%d",
            len(google_results) if isinstance(google_results, list) else 0,
            len(ol_results)     if isinstance(ol_results, list) else 0,
        )

        # Step 3: match + score
        matcher = Matcher()
        meta = matcher.pick_best(
            provider_results=all_results,
            title_candidates=title_candidates,
            author_candidates=author_candidates,
            detected_language=detected_language,
        )

        return meta or BookMetadata(source=MetadataSource.LOCAL, confidence=0.0)

    @staticmethod
    async def _download_cover(
        meta: BookMetadata,
        user_id: UUID,
        document_id: UUID,
    ) -> BookMetadata:
        """
        Download, validate, and store the cover image from meta.cover_url.
        Returns meta unchanged if download fails.
        """
        if not meta.cover_url:
            return meta
        try:
            import httpx
            from app.services.storage_service import get_storage_service

            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.get(meta.cover_url, follow_redirects=True)
                if response.status_code != 200:
                    logger.warning(
                        "[METADATA] cover_download_failed url=%s status=%d",
                        meta.cover_url[:80], response.status_code,
                    )
                    return meta

                image_bytes = response.content

            # Validate: minimum size and magic bytes
            if len(image_bytes) < 100:
                logger.warning("[METADATA] cover_too_small url=%s", meta.cover_url[:80])
                return meta

            # Detect extension from Content-Type or magic bytes
            content_type = response.headers.get("content-type", "").split(";")[0].strip()
            ext = _content_type_to_ext(content_type) or _magic_ext(image_bytes) or "jpg"

            storage = get_storage_service()
            object_key = await storage.upload_image(
                image_data=image_bytes,
                user_id=user_id,
                document_id=document_id,
                ext=ext,
            )

            meta.cover_object_key = object_key
            logger.info(
                "[METADATA] cover_stored document_id=%s object_key=%s size_bytes=%d",
                document_id, object_key, len(image_bytes),
            )

        except ImportError:
            logger.debug("[METADATA] httpx not installed; cover download skipped")
        except Exception as exc:
            logger.warning("[METADATA] cover_download_error url=%s error=%s", meta.cover_url[:80], exc)

        return meta

    @staticmethod
    async def _persist(meta: BookMetadata, document_id: UUID, db: AsyncSession) -> None:
        """Write metadata fields to the document row."""
        from app.db.models.document import Document as DocModel

        result = await db.execute(
            select(DocModel).where(DocModel.id == document_id)
        )
        doc = result.scalar_one_or_none()
        if not doc:
            logger.warning("[METADATA] persist_skip document_id=%s not found", document_id)
            return

        # Only overwrite display_title if the user hasn't already set one
        if meta.title and not getattr(doc, "display_title", None):
            doc.display_title = meta.title

        # Always write these metadata fields
        if meta.author:
            doc.author = meta.author
        if meta.subtitle:
            doc.subtitle = meta.subtitle
        if meta.isbn:
            doc.isbn = meta.isbn
        if meta.cover_object_key and not getattr(doc, "cover_object_key", None):
            doc.cover_object_key = meta.cover_object_key

        doc.metadata_source     = meta.source.value
        doc.metadata_confidence = meta.confidence

        await db.commit()
        logger.debug("[METADATA] persisted document_id=%s", document_id)

    @staticmethod
    async def _track_analytics(
        meta: BookMetadata,
        document_id: UUID,
        user_id: UUID,
        db: AsyncSession,
    ) -> None:
        try:
            from app.analytics.analytics_service import AnalyticsService

            await AnalyticsService.record_event(
                db=db,
                user_id=user_id,
                event_type=_EVT_DETECTED,
                document_id=document_id,
                properties={
                    "source":     meta.source.value,
                    "confidence": round(meta.confidence, 3),
                    "has_title":  bool(meta.title),
                    "has_author": bool(meta.author),
                    "has_cover":  bool(meta.cover_object_key),
                    "has_isbn":   bool(meta.isbn),
                },
            )

            cover_evt = _EVT_COVER_FOUND if meta.cover_object_key else _EVT_COVER_MISSING
            await AnalyticsService.record_event(
                db=db,
                user_id=user_id,
                event_type=cover_evt,
                document_id=document_id,
                properties={"source": meta.source.value},
            )
        except Exception as exc:
            logger.debug("[METADATA] analytics_error error=%s", exc)

    # ── Manual override ───────────────────────────────────────────────────────

    @staticmethod
    async def apply_manual_override(
        document_id: UUID,
        user_id: UUID,
        title: Optional[str] = None,
        author: Optional[str] = None,
        db: Optional[AsyncSession] = None,
    ) -> None:
        """
        Apply user-edited metadata and mark source as MANUAL.
        Called from the PATCH /documents/{id}/metadata endpoint.
        """
        if db is None:
            return
        from app.db.models.document import Document as DocModel
        from app.analytics.analytics_service import AnalyticsService

        result = await db.execute(select(DocModel).where(DocModel.id == document_id))
        doc = result.scalar_one_or_none()
        if not doc:
            return

        if title is not None:
            doc.display_title = title.strip()
            doc.author = (author or "").strip() or doc.author
        if author is not None:
            doc.author = author.strip()

        doc.metadata_source = MetadataSource.MANUAL.value
        await db.commit()

        try:
            await AnalyticsService.record_event(
                db=db,
                user_id=user_id,
                event_type="metadata_edited",
                document_id=document_id,
                properties={
                    "title_changed":  title is not None,
                    "author_changed": author is not None,
                },
            )
        except Exception:
            pass


# ── Helpers ───────────────────────────────────────────────────────────────────

def _content_type_to_ext(ct: str) -> Optional[str]:
    _MAP = {
        "image/jpeg": "jpg",
        "image/png":  "png",
        "image/webp": "webp",
        "image/gif":  "jpg",  # convert to jpg proxy
    }
    return _MAP.get(ct.lower())


def _magic_ext(data: bytes) -> Optional[str]:
    if data[:3] == b"\xff\xd8\xff":
        return "jpg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return None
