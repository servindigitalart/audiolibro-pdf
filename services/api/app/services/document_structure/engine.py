"""
Document Structure Engine
==========================
BLOCK 6B: Text Segmentation & Chapter Detection Layer

Main orchestration engine for document structure analysis.
Coordinates all detection strategies and produces final chapter structure.
"""

import logging
import time
from typing import List, Optional
from uuid import UUID

import fitz  # PyMuPDF
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.chapter import Chapter
from app.services.document_structure.models import (
    DetectedChapter,
    DocumentStructure,
    PageText,
)
from app.services.document_structure.extractors.toc_extractor import TOCExtractor
from app.services.document_structure.extractors.heuristic_detector import HeuristicDetector
from app.services.document_structure.extractors.structural_analyzer import StructuralAnalyzer
from app.services.document_structure.fusion.confidence_scorer import ConfidenceScorer
from app.services.document_structure.segmenter import TextSegmenter
from app.services.document_structure.exceptions import (
    DocumentStructureError,
    PDFExtractionError,
    NoChaptersDetectedError,
)

logger = logging.getLogger(__name__)


class DocumentStructureEngine:
    """
    Main engine for document structure analysis.
    
    Orchestrates:
    1. PDF text extraction
    2. Multiple chapter detection strategies
    3. Confidence fusion
    4. Chapter persistence
    5. Text segmentation
    
    Usage:
        engine = DocumentStructureEngine()
        structure = await engine.analyze_document(
            document_id=doc_id,
            pdf_path="/path/to/doc.pdf",
            db=session
        )
    """
    
    def __init__(self):
        """Initialize engine with all detectors."""
        self.toc_extractor = TOCExtractor()
        self.heuristic_detector = HeuristicDetector()
        self.structural_analyzer = StructuralAnalyzer()
        self.confidence_scorer = ConfidenceScorer()
        self.segmenter = TextSegmenter()
    
    async def analyze_document(
        self,
        document_id: UUID,
        pdf_path: str,
        db: AsyncSession
    ) -> DocumentStructure:
        """
        Analyze document structure and persist chapters.
        
        Args:
            document_id: Document UUID
            pdf_path: Path to PDF file
            db: Database session
            
        Returns:
            DocumentStructure with detected chapters
            
        Raises:
            DocumentStructureError: If analysis fails
            NoChaptersDetectedError: If no chapters found
        """
        start_time = time.time()
        
        logger.info(f"Starting document structure analysis for {document_id}")
        
        try:
            # Step 1: Extract full text with structure
            pages = await self._extract_pages(pdf_path)
            total_pages = len(pages)
            total_chars = sum(p.char_count for p in pages)
            
            logger.info(
                f"Extracted {total_pages} pages, {total_chars} characters"
            )
            
            # Step 2: Run all detection strategies
            detection_results = await self._run_detections(pdf_path, pages, total_pages)
            
            # Step 3: Fuse detections
            fused_chapters = self.confidence_scorer.fuse_detections(
                detections=detection_results,
                min_confidence=0.5
            )
            
            if not fused_chapters:
                logger.warning("No chapters detected, creating single chapter")
                fused_chapters = self._create_fallback_chapter(pages, total_pages)
            
            # Step 4: Extract text for each chapter
            chapters_with_text = await self._extract_chapter_text(
                fused_chapters,
                pdf_path
            )
            
            # Step 5: Persist chapters to database
            await self._persist_chapters(document_id, chapters_with_text, db)
            
            # Create result structure
            structure = DocumentStructure(
                document_id=document_id,
                total_pages=total_pages,
                total_chars=total_chars,
                chapters=chapters_with_text,
                detection_methods_used=self._get_methods_used(detection_results)
            )
            
            duration = time.time() - start_time
            logger.info(
                f"Document structure analysis complete: "
                f"{len(structure.chapters)} chapters detected in {duration:.2f}s "
                f"(avg confidence: {structure.average_confidence:.2f})"
            )
            
            return structure
            
        except Exception as e:
            logger.error(f"Document structure analysis failed: {str(e)}", exc_info=True)
            raise DocumentStructureError(
                message=f"Analysis failed: {str(e)}",
                document_id=str(document_id)
            )
    
    async def _extract_pages(self, pdf_path: str) -> List[PageText]:
        """Extract pages with structural metadata."""
        try:
            return self.structural_analyzer.extract_page_structure(pdf_path)
        except Exception as e:
            logger.error(f"Page extraction failed: {str(e)}")
            raise PDFExtractionError(f"Failed to extract pages: {str(e)}")
    
    async def _run_detections(
        self,
        pdf_path: str,
        pages: List[PageText],
        total_pages: int
    ) -> List[List[DetectedChapter]]:
        """Run all detection strategies."""
        results = []
        
        # Strategy 1: TOC extraction
        try:
            toc_chapters = self.toc_extractor.extract_chapters(pdf_path, total_pages)
            if toc_chapters:
                results.append(toc_chapters)
                logger.info(f"TOC detection: {len(toc_chapters)} chapters")
        except Exception as e:
            logger.warning(f"TOC extraction failed: {str(e)}")
        
        # Strategy 2: Heuristic detection
        try:
            heuristic_chapters = self.heuristic_detector.detect_chapters(pages)
            if heuristic_chapters:
                results.append(heuristic_chapters)
                logger.info(f"Heuristic detection: {len(heuristic_chapters)} chapters")
        except Exception as e:
            logger.warning(f"Heuristic detection failed: {str(e)}")
        
        # Strategy 3: Structural analysis
        try:
            structural_chapters = self.structural_analyzer.detect_chapters(pages)
            if structural_chapters:
                results.append(structural_chapters)
                logger.info(f"Structural detection: {len(structural_chapters)} chapters")
        except Exception as e:
            logger.warning(f"Structural analysis failed: {str(e)}")
        
        return results
    
    async def _extract_chapter_text(
        self,
        chapters: List[DetectedChapter],
        pdf_path: str
    ) -> List[DetectedChapter]:
        """Extract full text for each chapter."""
        try:
            doc = fitz.open(pdf_path)
            
            for chapter in chapters:
                # Extract text from chapter's page range
                text = ""
                for page_num in range(chapter.start_page - 1, chapter.end_page):
                    if page_num < len(doc):
                        page = doc[page_num]
                        text += page.get_text()
                
                chapter.text_content = text.strip()
                chapter.char_count = len(chapter.text_content)
                
                # Generate preview (first 500 chars)
                if chapter.text_content:
                    preview = chapter.text_content[:500]
                    if len(chapter.text_content) > 500:
                        preview += "..."
                    # Store preview in a temporary attribute
                    chapter.text_preview = preview
            
            doc.close()
            return chapters
            
        except Exception as e:
            logger.error(f"Chapter text extraction failed: {str(e)}")
            # Continue without text if extraction fails
            return chapters
    
    async def _persist_chapters(
        self,
        document_id: UUID,
        chapters: List[DetectedChapter],
        db: AsyncSession
    ):
        """Persist chapters to database."""
        for i, chapter in enumerate(chapters):
            db_chapter = Chapter(
                document_id=document_id,
                title=chapter.title,
                start_page=chapter.start_page,
                end_page=chapter.end_page,
                order_index=i,
                confidence_score=chapter.confidence,
                detection_method=chapter.detection_method,
                char_count=chapter.char_count,
                text_preview=getattr(chapter, 'text_preview', None)
            )
            db.add(db_chapter)
        
        await db.commit()
        logger.info(f"Persisted {len(chapters)} chapters for document {document_id}")
    
    def _create_fallback_chapter(
        self,
        pages: List[PageText],
        total_pages: int
    ) -> List[DetectedChapter]:
        """Create fallback chapter when no detection succeeds."""
        return [
            DetectedChapter(
                title="Full Document",
                start_page=1,
                end_page=total_pages,
                confidence=0.5,
                detection_method="fallback"
            )
        ]
    
    def _get_methods_used(
        self,
        detection_results: List[List[DetectedChapter]]
    ) -> List[str]:
        """Get list of detection methods that found chapters."""
        methods = set()
        for result in detection_results:
            if result:
                methods.update(ch.detection_method for ch in result)
        return sorted(methods)
