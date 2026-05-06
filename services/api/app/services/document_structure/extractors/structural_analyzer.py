"""
Structural Analyzer
===================
BLOCK 6B: Text Segmentation & Chapter Detection Layer

Analyzes document structure based on:
- Font size changes (larger fonts indicate chapter titles)
- Text density changes (chapters often start with whitespace)
- Page break patterns
"""

import logging
from typing import List, Optional
import statistics

import fitz  # PyMuPDF

from app.services.document_structure.models import DetectedChapter, PageText
from app.services.document_structure.exceptions import PDFExtractionError

logger = logging.getLogger(__name__)


class StructuralAnalyzer:
    """
    Detect chapters using structural analysis of PDF.
    
    Analyzes:
    - Font sizes: Larger fonts typically indicate headings
    - Text density: Chapters often begin with more whitespace
    - Formatting changes: Bold, different fonts, etc.
    
    Confidence: 0.6-0.75 (medium, depends on structural clarity)
    """
    
    def __init__(self):
        """Initialize analyzer."""
        self.base_font_size = 12.0  # Default assumption
    
    def extract_page_structure(self, pdf_path: str) -> List[PageText]:
        """
        Extract text with structural metadata from PDF.
        
        Args:
            pdf_path: Path to PDF file
            
        Returns:
            List of PageText with font size information
            
        Raises:
            PDFExtractionError: If extraction fails
        """
        try:
            doc = fitz.open(pdf_path)
            pages = []
            
            for page_num in range(len(doc)):
                page = doc[page_num]
                
                # Extract text blocks with format information
                blocks = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)
                
                page_text = ""
                font_sizes = []
                
                # Process blocks
                for block in blocks.get("blocks", []):
                    if block.get("type") == 0:  # Text block
                        for line in block.get("lines", []):
                            line_text = ""
                            for span in line.get("spans", []):
                                text = span.get("text", "")
                                size = span.get("size", 12.0)
                                
                                line_text += text
                                if text.strip():
                                    font_sizes.append(size)
                            
                            page_text += line_text + "\n"
                
                pages.append(
                    PageText(
                        page_number=page_num + 1,  # 1-indexed
                        text=page_text,
                        char_count=len(page_text),
                        font_sizes=font_sizes
                    )
                )
            
            doc.close()
            
            # Calculate base font size (most common)
            if pages and any(p.font_sizes for p in pages):
                all_sizes = [s for p in pages for s in p.font_sizes]
                if all_sizes:
                    self.base_font_size = statistics.median(all_sizes)
                    logger.info(f"Base font size: {self.base_font_size:.1f}pt")
            
            return pages
            
        except Exception as e:
            logger.error(f"Failed to extract page structure: {str(e)}")
            raise PDFExtractionError(
                message=f"Structural extraction failed: {str(e)}"
            )
    
    def detect_chapters(
        self,
        pages: List[PageText],
        min_confidence: float = 0.5
    ) -> List[DetectedChapter]:
        """
        Detect chapters using structural analysis.
        
        Args:
            pages: List of pages with structural metadata
            min_confidence: Minimum confidence threshold
            
        Returns:
            List of detected chapters
        """
        detected = []
        
        for i, page in enumerate(pages):
            if not page.font_sizes:
                continue
            
            # Check for large font at page start
            first_line_sizes = page.font_sizes[:10]  # First ~10 spans
            if not first_line_sizes:
                continue
            
            max_size = max(first_line_sizes)
            avg_size = statistics.mean(page.font_sizes) if page.font_sizes else self.base_font_size
            
            # Is this significantly larger than average?
            size_ratio = max_size / self.base_font_size if self.base_font_size > 0 else 1.0
            
            if size_ratio >= 1.3:  # 30% larger = likely a heading
                # Extract title from first lines
                lines = page.text.split('\n')[:3]
                title = ' '.join(l.strip() for l in lines if l.strip())[:200]
                
                if not title:
                    continue
                
                # Confidence based on font size ratio
                confidence = min(0.5 + (size_ratio - 1.3) * 0.5, 0.75)
                
                if confidence < min_confidence:
                    continue
                
                # Determine end page
                start_page = page.page_number
                end_page = pages[-1].page_number if i == len(pages) - 1 else pages[i + 1].page_number - 1
                
                detected.append(
                    DetectedChapter(
                        title=self._clean_title(title),
                        start_page=start_page,
                        end_page=end_page,
                        confidence=confidence,
                        detection_method="structural"
                    )
                )
                
                logger.debug(
                    f"Structural detection on page {start_page}: '{title}' "
                    f"(font ratio: {size_ratio:.2f}, confidence: {confidence:.2f})"
                )
        
        # Refine ranges
        detected = self._refine_chapter_ranges(detected)
        
        logger.info(f"Structural analysis found {len(detected)} chapters")
        return detected
    
    def _clean_title(self, title: str) -> str:
        """Clean chapter title."""
        title = ' '.join(title.split())
        title = title.rstrip(':.,-')
        if len(title) > 200:
            title = title[:197] + "..."
        return title
    
    def _refine_chapter_ranges(
        self,
        chapters: List[DetectedChapter]
    ) -> List[DetectedChapter]:
        """Refine chapter page ranges."""
        if not chapters:
            return chapters
        
        chapters_sorted = sorted(chapters, key=lambda c: c.start_page)
        
        for i in range(len(chapters_sorted) - 1):
            current = chapters_sorted[i]
            next_chapter = chapters_sorted[i + 1]
            current.end_page = next_chapter.start_page - 1
            
            if current.end_page < current.start_page:
                current.end_page = current.start_page
        
        return chapters_sorted
