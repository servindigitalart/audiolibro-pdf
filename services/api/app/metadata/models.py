"""
Metadata models — shared dataclasses used throughout the metadata subsystem.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class MetadataSource(str, Enum):
    """Which system produced the final accepted metadata."""
    LOCAL      = "local"          # filename + PDF embedded metadata only
    GOOGLE     = "google_books"   # Google Books API
    OPEN_LIB   = "open_library"   # Open Library API
    MANUAL     = "manual"         # User edited via UI


@dataclass
class TitleCandidate:
    """A single title hypothesis with its origin and raw string."""
    value: str
    source: str          # e.g. "filename", "pdf_meta", "first_heading"
    weight: float = 1.0  # relative importance (0–1) for scoring


@dataclass
class AuthorCandidate:
    """A single author hypothesis."""
    value: str
    source: str
    weight: float = 1.0


@dataclass
class BookMetadata:
    """
    Final enriched book metadata.  All fields optional — callers must handle
    None gracefully and never block on metadata availability.
    """
    # Core identity
    title: Optional[str]          = None
    subtitle: Optional[str]       = None
    author: Optional[str]         = None
    language: Optional[str]       = None   # ISO 639-1

    # Discovery
    isbn: Optional[str]           = None
    categories: list[str]         = field(default_factory=list)

    # Cover
    cover_url: Optional[str]      = None   # original URL from provider (not stored)
    cover_object_key: Optional[str] = None # path in Sonoro storage after download

    # Provenance
    source: MetadataSource        = MetadataSource.LOCAL
    confidence: float             = 0.0    # 0.0 – 1.0

    # Candidates generated during extraction (not persisted)
    title_candidates: list[TitleCandidate] = field(default_factory=list, compare=False, repr=False)
    author_candidates: list[AuthorCandidate] = field(default_factory=list, compare=False, repr=False)

    # ── Confidence thresholds ────────────────────────────────────────────────

    @property
    def is_high_confidence(self) -> bool:
        """Auto-accept: apply without user confirmation."""
        return self.confidence >= 0.85

    @property
    def is_medium_confidence(self) -> bool:
        """Show as recommendation; user can confirm or reject."""
        return 0.60 <= self.confidence < 0.85

    @property
    def is_low_confidence(self) -> bool:
        """Do not auto-apply; show manual selection UI only."""
        return self.confidence < 0.60

    @property
    def confidence_label(self) -> str:
        if self.is_high_confidence:
            return "high"
        if self.is_medium_confidence:
            return "medium"
        return "low"
