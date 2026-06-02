"""
Google Books API v1 Provider
=============================
Queries the Google Books volumes endpoint.

No API key required for basic searches (1000 req/day anonymous quota).
Set GOOGLE_BOOKS_API_KEY in environment for higher limits (1000 req/100 sec).

API docs: https://developers.google.com/books/docs/v1/reference/volumes/list
"""

from __future__ import annotations

import asyncio
import logging
import urllib.parse
from typing import Optional

from app.metadata.providers.base import BaseMetadataProvider, ProviderResult

logger = logging.getLogger(__name__)

_API_BASE = "https://www.googleapis.com/books/v1/volumes"
_MAX_RESULTS = 5


class GoogleBooksProvider(BaseMetadataProvider):
    """Google Books API v1 metadata provider."""

    name = "google_books"
    timeout_seconds = 5

    def __init__(self, api_key: str = "") -> None:
        self._api_key = api_key

    async def search(
        self,
        title_query: str,
        author_query: Optional[str] = None,
    ) -> list[ProviderResult]:
        """Search Google Books and return up to _MAX_RESULTS candidates."""
        try:
            return await asyncio.wait_for(
                self._do_search(title_query, author_query),
                timeout=self.timeout_seconds,
            )
        except asyncio.TimeoutError:
            logger.warning("[METADATA] google_books timeout query=%r", title_query)
            return []
        except Exception as exc:
            logger.warning("[METADATA] google_books error query=%r error=%s", title_query, exc)
            return []

    async def _do_search(
        self,
        title_query: str,
        author_query: Optional[str] = None,
    ) -> list[ProviderResult]:
        try:
            import httpx
        except ImportError:
            logger.warning("[METADATA] httpx not installed; google_books provider disabled")
            return []

        # Build query string
        # Use intitle: and inauthor: filters for better precision
        q_parts = [f'intitle:"{title_query}"']
        if author_query:
            q_parts.append(f'inauthor:"{author_query}"')
        q = " ".join(q_parts)

        params: dict[str, str] = {
            "q": q,
            "maxResults": str(_MAX_RESULTS),
            "printType": "books",
            "projection": "lite",  # smaller payload — we only need core metadata
        }
        if self._api_key:
            params["key"] = self._api_key

        url = f"{_API_BASE}?{urllib.parse.urlencode(params)}"
        logger.debug("[METADATA] google_books query=%r url=%s", title_query, url[:120])

        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            response = await client.get(url)
            response.raise_for_status()
            data = response.json()

        items = data.get("items", [])
        if not items:
            # Fallback: try broader query without quotes
            params["q"] = title_query
            url = f"{_API_BASE}?{urllib.parse.urlencode(params)}"
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                response = await client.get(url)
                if response.status_code == 200:
                    data = response.json()
                    items = data.get("items", [])

        results: list[ProviderResult] = []
        for item in items[:_MAX_RESULTS]:
            info = item.get("volumeInfo", {})
            result = self._parse_volume(info)
            results.append(result)

        logger.debug(
            "[METADATA] google_books found=%d for query=%r",
            len(results), title_query,
        )
        return results

    @staticmethod
    def _parse_volume(info: dict) -> ProviderResult:
        title    = info.get("title", "").strip() or None
        subtitle = info.get("subtitle", "").strip() or None
        authors  = info.get("authors", [])
        author   = ", ".join(authors) if authors else None
        language = info.get("language", "").strip() or None

        # ISBN: prefer ISBN-13
        isbn = None
        for iid in info.get("industryIdentifiers", []):
            if iid.get("type") == "ISBN_13":
                isbn = iid.get("identifier")
                break
        if not isbn:
            for iid in info.get("industryIdentifiers", []):
                if iid.get("type") == "ISBN_10":
                    isbn = iid.get("identifier")
                    break

        # Cover: prefer the largest available image
        image_links = info.get("imageLinks", {})
        cover_url = (
            image_links.get("extraLarge")
            or image_links.get("large")
            or image_links.get("medium")
            or image_links.get("thumbnail")
            or None
        )
        # Google Books thumbnail URLs use http:// — upgrade to https
        if cover_url and cover_url.startswith("http://"):
            cover_url = cover_url.replace("http://", "https://", 1)
        # Strip zoom restriction from thumbnail URL for higher resolution
        if cover_url and "zoom=" in cover_url:
            cover_url = cover_url.split("&zoom=")[0]

        categories = info.get("categories", [])

        # Provider-native quality signal: averageRating (0–5) / 5
        rating = float(info.get("averageRating", 0) or 0)
        raw_score = min(1.0, rating / 5.0) if rating > 0 else 0.5

        return ProviderResult(
            title=title,
            subtitle=subtitle,
            author=author,
            language=language,
            isbn=isbn,
            categories=categories,
            cover_url=cover_url,
            raw_score=raw_score,
            provider_name="google_books",
        )
