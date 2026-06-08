"""
Cover candidate model for Cover Intelligence v2.

CoverCandidate is a transient object — it is NOT persisted per candidate.
Only the user-selected candidate is downloaded and stored as cover_object_key.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class CoverCandidate:
    """
    A single cover candidate returned by the cover lookup service.
    Returned as a list to the client so the user can pick one.
    """
    id: str                     # Unique within a response: "{source}_{index}"
    source: str                 # google_books | open_library | generated
    title: Optional[str]        # Book title from provider
    author: Optional[str]       # Author from provider
    isbn_10: Optional[str]
    isbn_13: Optional[str]
    image_url: str              # Full-size image URL (for download when selected)
    thumbnail_url: str          # Smaller URL for the suggestion carousel
    match_score: float          # 0.0 – 1.0
    confidence_label: str       # high | medium | low
    provider_volume_id: Optional[str]  # Google Books volumeId or OL work key
    reason: str                 # Human-readable match explanation

    @property
    def is_showable(self) -> bool:
        return self.match_score >= 0.45


@dataclass
class CoverSuggestionsQuery:
    """Inputs to the cover lookup service."""
    title: Optional[str] = None
    author: Optional[str] = None
    isbn: Optional[str] = None
    language: Optional[str] = None
    filename: Optional[str] = None
