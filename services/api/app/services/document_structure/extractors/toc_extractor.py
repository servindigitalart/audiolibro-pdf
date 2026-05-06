"""
TOC Extractor
=============
BLOCK 6B: Text Segmentation & Chapter Detection Layer

Extracts Table of Contents from PDF metadata/bookmarks.
This is the highest confidence detection method when available.
"""

import logging
from typing import List, Optional

import fitz  # PyMuPDF

from app.services.document_structure.models import TOCEntry, DetectedChapter
from app.services.document_structure.exceptions import PDFExtractionError

logger = logging.getLogger(__name__)


class TOCExtractor:
    """
    Extract chapters from PDF Table of Contents (bookmarks/outline).
    
    PDFs can have embedded TOC metadata that defines the document structure.
    This is the most reliable detection method when available.
    
    Confidence: 0.95 (very high)
    """
    
    CONFIDENCE_SCORE = 0.95
    
    def extract_toc(self, pdf_path: str) -> List[TOCEntry]:
        """
        Extract TOC entries from PDF bookmarks.
        
        Args:
            pdf_path: Path to PDF file
            
        Returns:
            List of TOC entries (empty if no TOC)
            
        Raises:
            PDFExtractionError: If PDF cannot be read
        """
        try:
            doc = fitz.open(pdf_path)
            toc_entries = []
            
            # Get table of contents
            toc = doc.get_toc(simple=False)
            
            if not toc:
                logger.info("No TOC found in PDF")
                return []
            
            for entry in toc:
                # PyMuPDF TOC format: [level, title, page_num, ...]
                level = entry[0]
                title = entry[1]
                page_num = entry[2]
                
                # Skip if no title or invalid page
                if not title or page_num < 1:
                    continue
                
                # Clean title
                title = title.strip()
                if not title:
                    continue
                
                toc_entries.append(
                    TOCEntry(
                        title=title,
                        page_number=page_num,
                        level=level
                    )
                )
            
            doc.close()
            
            logger.info(f"Extracted {len(toc_entries)} TOC entries")
            return toc_entries
            
        except Exception as e:
            logger.error(f"Failed to extract TOC: {str(e)}")
            raise PDFExtractionError(
                message=f"TOC extraction failed: {str(e)}"
            )
    
    def toc_to_chapters(
        self,
        toc_entries: List[TOCEntry],
        total_pages: int
    ) -> List[DetectedChapter]:
        """
        Convert TOC entries to chapter detections.
        
        Args:
            toc_entries: Extracted TOC entries
            total_pages: Total pages in document
            
        Returns:
            List of detected chapters
        """
        if not toc_entries:
            return []
        
        chapters = []
        
        # Filter to level 1 entries (main chapters)
        main_entries = [e for e in toc_entries if e.level == 1]
        
        if not main_entries:
            # If no level 1, use all entries
            main_entries = toc_entries
        
        for i, entry in enumerate(main_entries):
            start_page = entry.page_number
            
            # Determine end page
            if i + 1 < len(main_entries):
                # End at next chapter start - 1
                end_page = main_entries[i + 1].page_number - 1
            else:
                # Last chapter goes to end of document
                end_page = total_pages
            
            # Validate page range
            if end_page < start_page:
                end_page = start_page
            
            chapters.append(
                DetectedChapter(
                    title=entry.title,
                    start_page=start_page,
                    end_page=end_page,
                    confidence=self.CONFIDENCE_SCORE,
                    detection_method="toc"
                )
            )
        
        logger.info(f"Converted {len(chapters)} TOC entries to chapters")
        return chapters
    
    def extract_chapters(
        self,
        pdf_path: str,
        total_pages: int
    ) -> List[DetectedChapter]:
        """
        Extract chapters from PDF TOC (convenience method).
        
        Args:
            pdf_path: Path to PDF file
            total_pages: Total pages in document
            
        Returns:
            List of detected chapters (empty if no TOC)
        """
        toc_entries = self.extract_toc(pdf_path)
        return self.toc_to_chapters(toc_entries, total_pages)
