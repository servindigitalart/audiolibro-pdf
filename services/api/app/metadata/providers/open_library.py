"""
Open Library Provider
======================
Open Library Search API — completely free, no key required.

Search: https://openlibrary.org/search.json
Covers: https://covers.openlibrary.org/b/id/<cover_id>-L.jpg
"""

from __future__ import annotations

import asyncio
import logging
import urllib.parse
from typing import Optional

from app.metadata.providers.base import BaseMetadataProvider, ProviderResult

logger = logging.getLogger(__name__)

_SEARCH_URL = "https://openlibrary.org/search.json"
_COVER_BASE  = "https://covers.openlibrary.org/b/id"
_MAX_RESULTS = 5


class OpenLibraryProvider(BaseMetadataProvider):
    """Open Library Search API provider."""

    name = "open_library"
    timeout_seconds = 5

    async def search(
        self,
        title_query: str,
        author_query: Optional[str] = None,
    ) -> list[ProviderResult]:
        try:
            return await asyncio.wait_for(
                self._do_search(title_query, author_query),
                timeout=self.timeout_seconds,
            )
        except asyncio.TimeoutError:
            logger.warning("[METADATA] open_library timeout query=%r", title_query)
            return []
        except Exception as exc:
            logger.warning("[METADATA] open_library error query=%r error=%s", title_query, exc)
            return []

    async def _do_search(
        self,
        title_query: str,
        author_query: Optional[str] = None,
    ) -> list[ProviderResult]:
        try:
            import httpx
        except ImportError:
            logger.warning("[METADATA] httpx not installed; open_library provider disabled")
            return []

        params: dict[str, str] = {
            "title": title_query,
            "limit": str(_MAX_RESULTS),
            "fields": "title,author_name,isbn,cover_i,language,subject,first_publish_year",
        }
        if author_query:
            params["author"] = author_query

        url = f"{_SEARCH_URL}?{urllib.parse.urlencode(params)}"
        logger.debug("[METADATA] open_library url=%s", url[:120])

        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            response = await client.get(url)
            response.raise_for_status()
            data = response.json()

        docs = data.get("docs", [])
        results: list[ProviderResult] = []
        for doc in docs[:_MAX_RESULTS]:
            result = self._parse_doc(doc)
            results.append(result)

        logger.debug(
            "[METADATA] open_library found=%d for query=%r",
            len(results), title_query,
        )
        return results

    @staticmethod
    def _parse_doc(doc: dict) -> ProviderResult:
        title   = str(doc.get("title", "") or "").strip() or None

        authors = doc.get("author_name", []) or []
        author  = ", ".join(authors[:3]) if authors else None

        # ISBN: prefer ISBN-13 (13 chars)
        isbns = doc.get("isbn", []) or []
        isbn = None
        for i in isbns:
            if len(str(i)) == 13:
                isbn = str(i)
                break
        if not isbn and isbns:
            isbn = str(isbns[0])

        # Cover: use cover_i (cover ID) to build URL
        cover_id = doc.get("cover_i")
        cover_url = f"{_COVER_BASE}/{cover_id}-L.jpg" if cover_id else None

        # Language: Open Library returns BCP-47 codes like "eng", convert to ISO 639-1
        langs = doc.get("language", []) or []
        language = _ol_lang_to_iso(langs[0] if langs else "")

        categories = (doc.get("subject", []) or [])[:5]

        # Open Library doesn't provide ratings; use a fixed baseline
        raw_score = 0.4

        return ProviderResult(
            title=title,
            author=author,
            language=language,
            isbn=isbn,
            categories=categories,
            cover_url=cover_url,
            raw_score=raw_score,
            provider_name="open_library",
        )


_OL_LANG_MAP = {
    "eng": "en", "spa": "es", "fre": "fr", "por": "pt",
    "ger": "de", "ita": "it", "dut": "nl", "pol": "pl",
    "rus": "ru", "jpn": "ja", "kor": "ko", "chi": "zh",
    "zho": "zh",
}


def _ol_lang_to_iso(ol_code: str) -> Optional[str]:
    """Convert Open Library 3-letter lang code to ISO 639-1 2-letter code."""
    return _OL_LANG_MAP.get(ol_code.lower()[:3])
