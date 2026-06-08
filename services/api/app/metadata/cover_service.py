"""
Cover Intelligence v2 — Cover Lookup Service
=============================================

Accepts a query (title, author, isbn, language) and returns a ranked list
of CoverCandidate objects from Google Books and Open Library.

Scoring weights:
  title_similarity   0.40
  author_similarity  0.30
  isbn_exact         0.20
  language_match     0.05
  image_quality      0.05

Rules:
  - score < 0.45   → reject (not shown)
  - score >= 0.85  → High confidence
  - 0.65 – 0.84   → Medium confidence
  - 0.45 – 0.64   → Low confidence
  - Strong title mismatch (< 0.35) → reject regardless of other scores
  - Strong author mismatch (< 0.25) when author is known → cap score at 0.65
"""

from __future__ import annotations

import asyncio
import logging
import re
import unicodedata
from difflib import SequenceMatcher
from typing import Optional
import urllib.parse

logger = logging.getLogger(__name__)

# Scoring weights — must sum to 1.0
# ISBN is rare in filename-based queries; title+author should be the primary signal.
_W_TITLE   = 0.45
_W_AUTHOR  = 0.30
_W_ISBN    = 0.10
_W_LANG    = 0.10
_W_IMAGE   = 0.05

_MIN_SHOW_SCORE  = 0.45
_HIGH_THRESHOLD  = 0.85
_MEDIUM_THRESHOLD = 0.65

# Hard rejection: title sim below this → reject no matter what
_TITLE_REJECT_THRESHOLD = 0.35
# Author mismatch cap: if author known and sim below this → cap score at 0.65
_AUTHOR_CAP_THRESHOLD = 0.25
_AUTHOR_MISMATCH_CAP  = 0.65

# Provider timeouts
_TIMEOUT = 6.0
_MAX_CANDIDATES = 5
_MAX_PER_PROVIDER = 5

# Allowed domains for SSRF check (mirrors documents router allowlist)
ALLOWED_COVER_DOMAINS = frozenset({
    "books.google.com",
    "googleusercontent.com",
    "lh3.googleusercontent.com",
    "covers.openlibrary.org",
    "archive.org",
    "ia800900.us.archive.org",
})


def _normalize(s: str) -> str:
    if not s:
        return ""
    nfkd = unicodedata.normalize("NFKD", s)
    ascii_str = nfkd.encode("ascii", "ignore").decode("ascii")
    clean = re.sub(r"[^a-z0-9 ]", "", ascii_str.lower())
    return " ".join(clean.split())


def _fuzzy(a: str, b: str) -> float:
    na, nb = _normalize(a), _normalize(b)
    if not na or not nb:
        return 0.0
    return SequenceMatcher(None, na, nb).ratio()


def _last_name_fuzzy(a: str, b: str) -> float:
    a_last = _normalize(a.split()[-1] if a.split() else a)
    b_last = _normalize(b.split()[-1] if b.split() else b)
    if not a_last or not b_last:
        return 0.0
    return SequenceMatcher(None, a_last, b_last).ratio()


def _author_sim(provider_author: Optional[str], query_author: Optional[str]) -> float:
    if not query_author:
        return 0.3  # unknown → no penalty
    if not provider_author:
        return 0.15
    full = _fuzzy(provider_author, query_author)
    last = _last_name_fuzzy(provider_author, query_author)
    return max(full, last)


def _image_quality_score(image_url: str) -> float:
    """Heuristic: prefer larger images over thumbnails."""
    url_lower = image_url.lower()
    if any(k in url_lower for k in ("-xl.", "-l.", "large", "extralarge")):
        return 1.0
    if any(k in url_lower for k in ("-m.", "medium")):
        return 0.6
    if any(k in url_lower for k in ("-s.", "small", "thumbnail", "zoom=1")):
        return 0.3
    return 0.5


def _confidence_label(score: float) -> str:
    if score >= _HIGH_THRESHOLD:
        return "high"
    if score >= _MEDIUM_THRESHOLD:
        return "medium"
    return "low"


def _score_candidate(
    provider_title: Optional[str],
    provider_author: Optional[str],
    provider_isbn: Optional[str],
    provider_language: Optional[str],
    image_url: str,
    query_title: Optional[str],
    query_author: Optional[str],
    query_isbn: Optional[str],
    query_language: Optional[str],
) -> tuple[float, str]:
    """
    Returns (score, rejection_reason).
    rejection_reason is "" when the candidate is accepted.
    """
    # ── Title similarity ──────────────────────────────────────────────────────
    title_sim = 0.0
    if query_title and provider_title:
        title_sim = _fuzzy(provider_title, query_title)
    elif not query_title:
        title_sim = 0.3  # no local title → no penalty

    if title_sim < _TITLE_REJECT_THRESHOLD and query_title:
        return 0.0, f"title_mismatch({title_sim:.2f})"

    # ── Author similarity ─────────────────────────────────────────────────────
    auth_sim = _author_sim(provider_author, query_author)
    author_known = bool(query_author)

    # ── ISBN exact ────────────────────────────────────────────────────────────
    isbn_score = 0.0
    if query_isbn and provider_isbn:
        # Normalize: strip hyphens
        q_clean = re.sub(r"[-\s]", "", query_isbn)
        p_clean = re.sub(r"[-\s]", "", provider_isbn)
        isbn_score = 1.0 if q_clean == p_clean else 0.0

    # ── Language ──────────────────────────────────────────────────────────────
    lang_score = 0.0
    if query_language and provider_language:
        lang_score = 1.0 if query_language.lower()[:2] == provider_language.lower()[:2] else 0.0
    elif not provider_language:
        lang_score = 0.3

    # ── Image quality ─────────────────────────────────────────────────────────
    img_score = _image_quality_score(image_url)

    # ── Weighted total ────────────────────────────────────────────────────────
    raw = (
        title_sim * _W_TITLE
        + auth_sim  * _W_AUTHOR
        + isbn_score * _W_ISBN
        + lang_score * _W_LANG
        + img_score  * _W_IMAGE
    )
    score = max(0.0, min(1.0, raw))

    # Apply author mismatch cap
    if author_known and auth_sim < _AUTHOR_CAP_THRESHOLD:
        score = min(score, _AUTHOR_MISMATCH_CAP)

    # ISBN exact gives a guaranteed minimum floor (not a reject, just a boost)
    if isbn_score == 1.0 and score < 0.55:
        score = 0.55

    return score, ""


# ── Provider queries ──────────────────────────────────────────────────────────

async def _query_google_books(
    title: Optional[str],
    author: Optional[str],
    isbn: Optional[str],
    api_key: str = "",
) -> list[dict]:
    """
    Return raw Google Books volume dicts.
    Uses projection=full to get high-res image links.
    """
    try:
        import httpx
    except ImportError:
        return []

    _API_BASE = "https://www.googleapis.com/books/v1/volumes"
    results: list[dict] = []

    async def _fetch(q: str) -> list[dict]:
        params: dict[str, str] = {
            "q": q,
            "maxResults": str(_MAX_PER_PROVIDER),
            "printType": "books",
            "projection": "full",
        }
        if api_key:
            params["key"] = api_key
        url = f"{_API_BASE}?{urllib.parse.urlencode(params)}"
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                resp = await client.get(url)
                if resp.status_code != 200:
                    return []
                return resp.json().get("items", []) or []
        except Exception as exc:
            logger.debug("[COVER] google_books_fetch_error q=%r err=%s", q, exc)
            return []

    # Strategy 1: ISBN exact if available
    if isbn:
        clean_isbn = re.sub(r"[-\s]", "", isbn)
        items = await _fetch(f"isbn:{clean_isbn}")
        results.extend(items)

    # Strategy 2: title + author
    if title:
        parts = [f'intitle:"{title}"']
        if author:
            parts.append(f'inauthor:"{author}"')
        items = await _fetch(" ".join(parts))
        results.extend(items)

        # Strategy 3: broader title-only fallback
        if not results:
            items = await _fetch(f"intitle:{title}")
            results.extend(items)

    return results[:_MAX_PER_PROVIDER * 2]


async def _query_open_library(
    title: Optional[str],
    author: Optional[str],
    isbn: Optional[str],
) -> list[dict]:
    """Return raw Open Library search doc dicts."""
    try:
        import httpx
    except ImportError:
        return []

    _SEARCH_URL = "https://openlibrary.org/search.json"
    results: list[dict] = []

    async def _fetch(params: dict[str, str]) -> list[dict]:
        params["limit"] = str(_MAX_PER_PROVIDER)
        params["fields"] = "title,author_name,isbn,cover_i,language,key"
        url = f"{_SEARCH_URL}?{urllib.parse.urlencode(params)}"
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                resp = await client.get(url)
                if resp.status_code != 200:
                    return []
                return resp.json().get("docs", []) or []
        except Exception as exc:
            logger.debug("[COVER] open_library_fetch_error params=%r err=%s", params, exc)
            return []

    # Strategy 1: ISBN
    if isbn:
        clean_isbn = re.sub(r"[-\s]", "", isbn)
        docs = await _fetch({"isbn": clean_isbn})
        results.extend(docs)

    # Strategy 2: title + author
    if title:
        params = {"title": title}
        if author:
            params["author"] = author
        docs = await _fetch(params)
        results.extend(docs)

        # Strategy 3: title only fallback
        if not results:
            docs = await _fetch({"title": title})
            results.extend(docs)

    return results[:_MAX_PER_PROVIDER * 2]


def _parse_google_book(item: dict) -> Optional[tuple[dict, str, str]]:
    """
    Returns (metadata_dict, image_url, thumbnail_url) or None if no cover.
    """
    info = item.get("volumeInfo", {})
    image_links = info.get("imageLinks", {})

    # Prefer highest resolution
    full_url = (
        image_links.get("extraLarge")
        or image_links.get("large")
        or image_links.get("medium")
        or image_links.get("thumbnail")
        or image_links.get("smallThumbnail")
    )
    thumb_url = (
        image_links.get("thumbnail")
        or image_links.get("smallThumbnail")
        or full_url
    )
    if not full_url:
        return None

    # Upgrade http → https
    def _upgrade(u: str) -> str:
        if u.startswith("http://"):
            u = "https://" + u[7:]
        # Remove edge=curl distortion but keep zoom for thumbnail
        u = re.sub(r"&edge=curl", "", u)
        return u

    full_url = _upgrade(full_url)
    thumb_url = _upgrade(thumb_url)

    # For full_url: maximize resolution by removing zoom restriction
    full_url = re.sub(r"&zoom=\d+", "", full_url)
    # For thumbnail: set zoom=1 (small but fast)
    if "zoom=" not in thumb_url:
        thumb_url = thumb_url + ("&" if "?" in thumb_url else "?") + "zoom=1"

    isbn_10, isbn_13 = None, None
    for iid in info.get("industryIdentifiers", []):
        if iid.get("type") == "ISBN_13":
            isbn_13 = iid.get("identifier")
        elif iid.get("type") == "ISBN_10":
            isbn_10 = iid.get("identifier")

    return {
        "title": (info.get("title") or "").strip() or None,
        "author": ", ".join(info.get("authors", [])) or None,
        "isbn_10": isbn_10,
        "isbn_13": isbn_13,
        "language": (info.get("language") or "").strip() or None,
        "volume_id": item.get("id"),
    }, full_url, thumb_url


def _parse_open_library_doc(doc: dict) -> Optional[tuple[dict, str, str]]:
    """Returns (metadata_dict, image_url, thumbnail_url) or None if no cover."""
    cover_id = doc.get("cover_i")
    if not cover_id:
        # Try ISBN-based cover
        isbns = doc.get("isbn", []) or []
        if not isbns:
            return None
        isbn = re.sub(r"[-\s]", "", str(isbns[0]))
        full_url = f"https://covers.openlibrary.org/b/isbn/{isbn}-L.jpg"
        thumb_url = f"https://covers.openlibrary.org/b/isbn/{isbn}-M.jpg"
    else:
        full_url  = f"https://covers.openlibrary.org/b/id/{cover_id}-L.jpg"
        thumb_url = f"https://covers.openlibrary.org/b/id/{cover_id}-M.jpg"

    isbns = doc.get("isbn", []) or []
    isbn_13 = next((str(i) for i in isbns if len(str(i)) == 13), None)
    isbn_10 = next((str(i) for i in isbns if len(str(i)) == 10), None)

    authors = doc.get("author_name", []) or []

    return {
        "title": (str(doc.get("title", "")) or "").strip() or None,
        "author": ", ".join(authors[:2]) or None,
        "isbn_10": isbn_10,
        "isbn_13": isbn_13,
        "language": None,  # OL language codes need separate parsing; skip for scoring
        "volume_id": doc.get("key"),
    }, full_url, thumb_url


def is_allowed_cover_domain(url: str) -> bool:
    """SSRF guard — only allow known safe provider domains."""
    try:
        parsed = urllib.parse.urlparse(url)
        host = parsed.netloc.lower().split(":")[0]
        # Check exact match or subdomain match
        return any(
            host == domain or host.endswith("." + domain)
            for domain in ALLOWED_COVER_DOMAINS
        )
    except Exception:
        return False


# ── Public interface ──────────────────────────────────────────────────────────

async def get_cover_suggestions(
    title: Optional[str],
    author: Optional[str],
    isbn: Optional[str] = None,
    language: Optional[str] = None,
    api_key: str = "",
    max_results: int = _MAX_CANDIDATES,
) -> list:
    """
    Return a ranked list of CoverCandidate objects.

    Never raises — returns [] on failure.
    """
    from app.metadata.cover_models import CoverCandidate

    if not title and not isbn:
        logger.debug("[COVER] no title or isbn — skipping suggestions")
        return []

    try:
        google_task = asyncio.create_task(_query_google_books(title, author, isbn, api_key))
        ol_task     = asyncio.create_task(_query_open_library(title, author, isbn))
        google_items, ol_docs = await asyncio.gather(
            google_task, ol_task, return_exceptions=True
        )
    except Exception as exc:
        logger.warning("[COVER] provider_gather_failed error=%s", exc)
        return []

    candidates: list[CoverCandidate] = []
    seen_image_urls: set[str] = set()

    # Process Google Books
    if isinstance(google_items, list):
        for i, item in enumerate(google_items):
            parsed = _parse_google_book(item)
            if not parsed:
                continue
            meta, image_url, thumb_url = parsed

            if not is_allowed_cover_domain(image_url):
                continue

            # Deduplication: skip near-identical image base URLs
            base_key = re.sub(r"[?&].*", "", image_url)
            if base_key in seen_image_urls:
                continue
            seen_image_urls.add(base_key)

            score, rejection = _score_candidate(
                provider_title=meta["title"],
                provider_author=meta["author"],
                provider_isbn=meta["isbn_13"] or meta["isbn_10"],
                provider_language=meta["language"],
                image_url=image_url,
                query_title=title,
                query_author=author,
                query_isbn=isbn,
                query_language=language,
            )

            if rejection or score < _MIN_SHOW_SCORE:
                logger.debug(
                    "[COVER] google_rejected title=%r score=%.2f reason=%s",
                    meta["title"], score, rejection or "score_too_low",
                )
                continue

            reason = f"Google Books match (score {score:.0%})"
            if meta["isbn_13"]:
                reason = f"ISBN match via Google Books"
            elif score >= 0.85:
                reason = "High-confidence Google Books match"

            candidates.append(CoverCandidate(
                id=f"google_{i}",
                source="google_books",
                title=meta["title"],
                author=meta["author"],
                isbn_10=meta["isbn_10"],
                isbn_13=meta["isbn_13"],
                image_url=image_url,
                thumbnail_url=thumb_url,
                match_score=round(score, 3),
                confidence_label=_confidence_label(score),
                provider_volume_id=meta["volume_id"],
                reason=reason,
            ))

    # Process Open Library
    if isinstance(ol_docs, list):
        for i, doc in enumerate(ol_docs):
            parsed = _parse_open_library_doc(doc)
            if not parsed:
                continue
            meta, image_url, thumb_url = parsed

            if not is_allowed_cover_domain(image_url):
                continue

            base_key = re.sub(r"[?&].*", "", image_url)
            if base_key in seen_image_urls:
                continue
            seen_image_urls.add(base_key)

            score, rejection = _score_candidate(
                provider_title=meta["title"],
                provider_author=meta["author"],
                provider_isbn=meta["isbn_13"] or meta["isbn_10"],
                provider_language=meta["language"],
                image_url=image_url,
                query_title=title,
                query_author=author,
                query_isbn=isbn,
                query_language=language,
            )

            if rejection or score < _MIN_SHOW_SCORE:
                logger.debug(
                    "[COVER] ol_rejected title=%r score=%.2f reason=%s",
                    meta["title"], score, rejection or "score_too_low",
                )
                continue

            reason = f"Open Library match (score {score:.0%})"
            if score >= 0.85:
                reason = "High-confidence Open Library match"

            candidates.append(CoverCandidate(
                id=f"ol_{i}",
                source="open_library",
                title=meta["title"],
                author=meta["author"],
                isbn_10=meta["isbn_10"],
                isbn_13=meta["isbn_13"],
                image_url=image_url,
                thumbnail_url=thumb_url,
                match_score=round(score, 3),
                confidence_label=_confidence_label(score),
                provider_volume_id=meta["volume_id"],
                reason=reason,
            ))

    # Sort by score descending, deduplicate after sort, cap count
    candidates.sort(key=lambda c: c.match_score, reverse=True)
    final = candidates[:max_results]

    logger.info(
        "[COVER] suggestions title=%r author=%r candidates=%d",
        title, author, len(final),
    )
    return final
