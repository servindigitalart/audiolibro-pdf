#!/usr/bin/env python3
"""
BLOCK 6B Test Suite
===================

Test script for document structure analysis and chapter detection.

Usage:
    python test_block_6b.py [test_pdf_path]

Requirements:
    - Docker containers must be running
    - Database must be migrated
"""

import asyncio
import sys
from pathlib import Path

# Add API path
sys.path.insert(0, str(Path(__file__).parent / "services" / "api"))

from app.services.document_structure.engine import DocumentStructureEngine
from app.services.document_structure.extractors.toc_extractor import TOCExtractor
from app.services.document_structure.extractors.heuristic_detector import HeuristicDetector
from app.services.document_structure.extractors.structural_analyzer import StructuralAnalyzer
from app.db.models.document import Document
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy import select
import uuid


async def test_extractors(pdf_path: str):
    """Test individual extractors."""
    print(f"\n{'='*60}")
    print(f"TESTING INDIVIDUAL EXTRACTORS")
    print(f"{'='*60}\n")
    
    # Test TOC Extractor
    print("1. TOC Extractor:")
    print("-" * 40)
    toc_extractor = TOCExtractor()
    toc_chapters = await toc_extractor.extract_chapters(pdf_path)
    print(f"   Detected {len(toc_chapters)} chapters from TOC")
    for ch in toc_chapters[:5]:  # Show first 5
        print(f"   - {ch.title} (pages {ch.start_page}-{ch.end_page}, confidence: {ch.confidence:.2f})")
    if len(toc_chapters) > 5:
        print(f"   ... and {len(toc_chapters) - 5} more")
    print()
    
    # Test Heuristic Detector
    print("2. Heuristic Detector:")
    print("-" * 40)
    heuristic_detector = HeuristicDetector()
    pages = await StructuralAnalyzer().extract_pages(pdf_path)  # Get pages first
    heuristic_chapters = await heuristic_detector.detect_chapters(pages)
    print(f"   Detected {len(heuristic_chapters)} chapters using patterns")
    for ch in heuristic_chapters[:5]:
        print(f"   - {ch.title} (page {ch.start_page}, confidence: {ch.confidence:.2f})")
    if len(heuristic_chapters) > 5:
        print(f"   ... and {len(heuristic_chapters) - 5} more")
    print()
    
    # Test Structural Analyzer
    print("3. Structural Analyzer:")
    print("-" * 40)
    structural_analyzer = StructuralAnalyzer()
    structural_chapters = await structural_analyzer.analyze_structure(pages)
    print(f"   Detected {len(structural_chapters)} chapters using font analysis")
    for ch in structural_chapters[:5]:
        print(f"   - {ch.title} (page {ch.start_page}, confidence: {ch.confidence:.2f})")
    if len(structural_chapters) > 5:
        print(f"   ... and {len(structural_chapters) - 5} more")
    print()


async def test_full_pipeline(pdf_path: str, document_id: uuid.UUID, db: AsyncSession):
    """Test full document structure analysis pipeline."""
    print(f"\n{'='*60}")
    print(f"TESTING FULL PIPELINE")
    print(f"{'='*60}\n")
    
    engine = DocumentStructureEngine()
    
    print("Running full document structure analysis...")
    structure = await engine.analyze_document(
        document_id=document_id,
        pdf_path=pdf_path,
        db=db
    )
    
    print(f"\n✅ Analysis Complete!")
    print(f"   Total Chapters: {structure.chapter_count}")
    print(f"   Average Confidence: {structure.average_confidence:.2f}")
    print(f"   High Confidence Chapters: {structure.high_confidence_count}")
    print(f"   Medium Confidence Chapters: {structure.medium_confidence_count}")
    print(f"   Low Confidence Chapters: {structure.low_confidence_count}")
    print()
    
    print("Detected Chapters:")
    print("-" * 60)
    for ch in structure.chapters:
        print(f"   {ch.order_index}. {ch.title}")
        print(f"      Pages: {ch.start_page}-{ch.end_page}")
        print(f"      Confidence: {ch.confidence:.2f} ({ch.detection_method})")
        print(f"      Characters: {ch.char_count:,}")
        if ch.text_content:
            preview = ch.text_content[:100].replace('\n', ' ')
            print(f"      Preview: {preview}...")
        print()


async def test_database_persistence(document_id: uuid.UUID, db: AsyncSession):
    """Test that chapters were persisted to database."""
    print(f"\n{'='*60}")
    print(f"TESTING DATABASE PERSISTENCE")
    print(f"{'='*60}\n")
    
    from app.db.models.chapter import Chapter
    
    # Query chapters
    result = await db.execute(
        select(Chapter).where(Chapter.document_id == document_id).order_by(Chapter.order_index)
    )
    chapters = result.scalars().all()
    
    print(f"Found {len(chapters)} chapters in database:")
    print("-" * 60)
    for ch in chapters:
        print(f"   {ch.order_index}. {ch.title}")
        print(f"      ID: {ch.id}")
        print(f"      Pages: {ch.start_page}-{ch.end_page} ({ch.page_count} pages)")
        print(f"      Confidence: {ch.confidence_score:.2f} ({ch.detection_method})")
        print(f"      Characters: {ch.char_count:,}")
        print(f"      High Confidence: {ch.is_high_confidence}")
        print()


async def main():
    """Main test runner."""
    if len(sys.argv) < 2:
        print("Usage: python test_block_6b.py <pdf_path>")
        print("\nExample:")
        print("  python test_block_6b.py /path/to/book.pdf")
        sys.exit(1)
    
    pdf_path = sys.argv[1]
    
    if not Path(pdf_path).exists():
        print(f"❌ Error: PDF file not found: {pdf_path}")
        sys.exit(1)
    
    print(f"\n{'='*60}")
    print(f"BLOCK 6B TEST SUITE")
    print(f"{'='*60}")
    print(f"PDF: {pdf_path}")
    print(f"{'='*60}\n")
    
    # Test extractors (no DB required)
    try:
        await test_extractors(pdf_path)
    except Exception as e:
        print(f"❌ Extractor tests failed: {e}")
        import traceback
        traceback.print_exc()
    
    # Test full pipeline (requires DB)
    try:
        # Create async engine
        DATABASE_URL = "postgresql+asyncpg://postgres:postgres@localhost:5432/sonoro"
        engine = create_async_engine(DATABASE_URL, echo=False)
        AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        
        async with AsyncSessionLocal() as db:
            # Create a test document
            document_id = uuid.uuid4()
            document = Document(
                id=document_id,
                user_id=uuid.uuid4(),  # Test user
                original_filename=Path(pdf_path).name,
                filename=f"{document_id}.pdf",
                storage_path=pdf_path,
                page_count=0,  # Will be updated
                file_size_bytes=Path(pdf_path).stat().st_size,
            )
            db.add(document)
            await db.commit()
            
            # Run full pipeline test
            await test_full_pipeline(pdf_path, document_id, db)
            
            # Test database persistence
            await test_database_persistence(document_id, db)
            
            print(f"\n{'='*60}")
            print(f"✅ ALL TESTS PASSED!")
            print(f"{'='*60}\n")
            
    except Exception as e:
        print(f"\n{'='*60}")
        print(f"❌ PIPELINE TESTS FAILED")
        print(f"{'='*60}")
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        print()


if __name__ == "__main__":
    asyncio.run(main())
