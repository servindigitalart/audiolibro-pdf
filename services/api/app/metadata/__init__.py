"""
Book Intelligence Layer
========================
Automatic metadata detection for uploaded documents.

Extracts title, author, cover, language, and confidence scores by combining:
  - Local PDF / filename parsing (always runs)
  - Google Books API (primary external provider)
  - Open Library API (fallback)

The system is non-blocking and fail-safe: audiobook generation always
continues regardless of metadata enrichment outcomes.
"""

from app.metadata.models import BookMetadata, MetadataSource
from app.metadata.service import MetadataService

__all__ = ["BookMetadata", "MetadataSource", "MetadataService"]
