"""
Heuristic Chapter Detector
===========================
BLOCK 6B: Text Segmentation & Chapter Detection Layer

Detects chapters using regex patterns and heuristics.
Supports multiple languages and common chapter formats.
"""

import logging
import re
from typing import List, Optional, Tuple

from app.services.document_structure.models import DetectedChapter, PageText
from app.services.document_structure.exceptions import ChapterDetectionError

logger = logging.getLogger(__name__)


class HeuristicDetector:
    """
    Detect chapters using heuristic pattern matching.
    
    Patterns include:
    - English: "Chapter 1", "Chapter One", "CHAPTER I"
    - Spanish: "Capítulo 1", "CAPÍTULO UNO"
    - French: "Chapitre 1", "CHAPITRE UN"
    - German: "Kapitel 1", "KAPITEL EINS"
    - Numeric: "1.", "Part 1", "Section 1"
    
    Confidence: 0.7-0.85 (medium-high, depends on pattern strength)
    """
    
    # Chapter patterns (multi-language)
    PATTERNS = {
        # English
        'en_chapter_num': r'^chapter\s+(\d+)',
        'en_chapter_word': r'^chapter\s+(one|two|three|four|five|six|seven|eight|nine|ten)',
        'en_chapter_roman': r'^chapter\s+([ivxlcdm]+)',
        'en_part': r'^part\s+(\d+|one|two|three|four|five)',
        
        # Spanish
        'es_capitulo': r'^cap[ií]tulo\s+(\d+|uno|dos|tres|cuatro|cinco)',
        
        # French
        'fr_chapitre': r'^chapitre\s+(\d+|un|deux|trois|quatre|cinq)',
        
        # German
        'de_kapitel': r'^kapitel\s+(\d+|eins|zwei|drei|vier|fünf)',
        
        # Generic numeric patterns
        'numeric_dot': r'^(\d+)\.',
        'section': r'^section\s+(\d+)',
        
        # Uppercase variations
        'uppercase_chapter': r'^CHAPTER\s+(\d+)',
        'uppercase_part': r'^PART\s+(\d+)',
    }
    
    # Pattern confidence scores
    PATTERN_CONFIDENCE = {
        'en_chapter_num': 0.85,
        'en_chapter_word': 0.85,
        'en_chapter_roman': 0.80,
        'en_part': 0.75,
        'es_capitulo': 0.85,
        'fr_chapitre': 0.85,
        'de_kapitel': 0.85,
        'numeric_dot': 0.60,  # Lower confidence (could be list items)
        'section': 0.70,
        'uppercase_chapter': 0.85,
        'uppercase_part': 0.75,
    }
    
    def __init__(self):
        """Compile regex patterns."""
        self.compiled_patterns = {
            name: re.compile(pattern, re.IGNORECASE | re.MULTILINE)
            for name, pattern in self.PATTERNS.items()
        }
    
    def detect_chapters(
        self,
        pages: List[PageText],
        min_confidence: float = 0.6
    ) -> List[DetectedChapter]:
        """
        Detect chapters using pattern matching.
        
        Args:
            pages: List of extracted page texts
            min_confidence: Minimum confidence threshold
            
        Returns:
            List of detected chapters
        """
        detected = []
        
        for i, page in enumerate(pages):
            # Get first few lines of page (where chapter titles usually are)
            lines = page.text.split('\n')[:5]
            page_start_text = '\n'.join(lines).strip()
            
            if not page_start_text:
                continue
            
            # Try each pattern
            for pattern_name, pattern in self.compiled_patterns.items():
                match = pattern.search(page_start_text)
                
                if match:
                    confidence = self.PATTERN_CONFIDENCE.get(pattern_name, 0.7)
                    
                    if confidence < min_confidence:
                        continue
                    
                    # Extract title (first line or matched text)
                    title = lines[0].strip() if lines else page_start_text[:100]
                    
                    # Clean title
                    title = self._clean_title(title)
                    
                    # Determine end page (will be refined later)
                    start_page = page.page_number
                    end_page = pages[-1].page_number if i == len(pages) - 1 else pages[i + 1].page_number - 1
                    
                    detected.append(
                        DetectedChapter(
                            title=title,
                            start_page=start_page,
                            end_page=end_page,
                            confidence=confidence,
                            detection_method="heuristic"
                        )
                    )
                    
                    logger.debug(
                        f"Detected chapter on page {start_page}: '{title}' "
                        f"(pattern: {pattern_name}, confidence: {confidence})"
                    )
                    
                    break  # Stop after first match on this page
        
        # Refine end pages
        detected = self._refine_chapter_ranges(detected)
        
        logger.info(f"Heuristic detection found {len(detected)} chapters")
        return detected
    
    def _clean_title(self, title: str) -> str:
        """
        Clean and normalize chapter title.
        
        Args:
            title: Raw title text
            
        Returns:
            Cleaned title
        """
        # Remove extra whitespace
        title = ' '.join(title.split())
        
        # Remove trailing punctuation
        title = title.rstrip(':.,-')
        
        # Capitalize properly if all uppercase
        if title.isupper() and len(title) > 10:
            title = title.title()
        
        # Limit length
        if len(title) > 200:
            title = title[:197] + "..."
        
        return title
    
    def _refine_chapter_ranges(
        self,
        chapters: List[DetectedChapter]
    ) -> List[DetectedChapter]:
        """
        Refine end page numbers based on next chapter's start.
        
        Args:
            chapters: List of detected chapters
            
        Returns:
            Refined chapters with corrected page ranges
        """
        if not chapters:
            return chapters
        
        # Sort by start page
        chapters_sorted = sorted(chapters, key=lambda c: c.start_page)
        
        for i in range(len(chapters_sorted) - 1):
            current = chapters_sorted[i]
            next_chapter = chapters_sorted[i + 1]
            
            # Current chapter ends one page before next chapter starts
            current.end_page = next_chapter.start_page - 1
            
            # Validate
            if current.end_page < current.start_page:
                current.end_page = current.start_page
        
        return chapters_sorted
