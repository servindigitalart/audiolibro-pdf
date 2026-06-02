"""
Abstract base for metadata providers.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ProviderResult:
    """Structured result returned by every provider."""
    title: Optional[str]         = None
    subtitle: Optional[str]      = None
    author: Optional[str]        = None
    language: Optional[str]      = None
    isbn: Optional[str]          = None
    categories: list[str]        = field(default_factory=list)
    cover_url: Optional[str]     = None  # raw provider URL — not yet in Sonoro storage
    raw_score: float             = 0.0   # provider-native quality score 0–1
    provider_name: str           = "unknown"


class BaseMetadataProvider(ABC):
    """All providers implement this interface."""

    name: str = "base"
    timeout_seconds: int = 5

    @abstractmethod
    async def search(
        self,
        title_query: str,
        author_query: Optional[str] = None,
    ) -> list[ProviderResult]:
        """
        Search for a book and return up to 5 candidates.

        Must never raise — return [] on any error.
        Must complete within self.timeout_seconds.
        """
        ...
