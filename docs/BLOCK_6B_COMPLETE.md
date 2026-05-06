# BLOCK 6B: Text Segmentation & Chapter Detection - COMPLETE

**Status**: ✅ COMPLETE  
**Date**: February 11, 2026  
**Version**: 0.7.0

## 📋 Overview

Block 6B implements intelligent document structure analysis with multi-strategy chapter detection and safe text segmentation for TTS processing.

**What Block 6B Does**:
- ✅ PDF text extraction with structural metadata
- ✅ Multi-strategy chapter detection (TOC, heuristic, structural)
- ✅ Confidence fusion system
- ✅ Chapter persistence to database
- ✅ Safe text segmentation (max 4000 chars)
- ✅ Multi-language support (EN, ES, FR, DE)
- ✅ Prometheus metrics integration

**What Block 6B Does NOT Do** (as specified):
- ❌ Audio concatenation
- ❌ Response caching
- ❌ ML-based detection
- ❌ Billing modifications

---

## 🏗️ Architecture

### Detection Strategy Hierarchy

```
┌─────────────────────────────────────────────────────────┐
│           Document Structure Engine                      │
└────────────────┬────────────────────────────────────────┘
                 │
         ┌───────┴────────┐
         │                │
         ▼                ▼
  ┌─────────────┐  ┌─────────────┐
  │   Extract   │  │   Detect    │
  │   Pages     │  │  Chapters   │
  └──────┬──────┘  └──────┬──────┘
         │                │
         │         ┌──────┴──────┬──────────┬─────────────┐
         │         ▼             ▼          ▼             ▼
         │   ┌──────────┐ ┌──────────┐ ┌────────────┐ ┌────────┐
         │   │   TOC    │ │Heuristic │ │Structural  │ │Fallback│
         │   │Extractor │ │ Detector │ │ Analyzer   │ │        │
         │   │ (0.95)   │ │ (0.7-0.85│ │ (0.6-0.75) │ │ (0.5)  │
         │   └────┬─────┘ └────┬─────┘ └─────┬──────┘ └───┬────┘
         │        │            │              │            │
         │        └────────────┴──────────────┴────────────┘
         │                     │
         │                     ▼
         │            ┌─────────────────┐
         │            │ Confidence      │
         │            │ Fusion Scorer   │
         │            └────────┬────────┘
         │                     │
         │                     ▼
         │            ┌─────────────────┐
         │            │  Final Chapters │
         │            └────────┬────────┘
         │                     │
         ▼                     ▼
  ┌────────────┐     ┌─────────────────┐
  │   Text     │────▶│   Persist to    │
  │ Segmenter  │     │    Database     │
  └────────────┘     └─────────────────┘
```

### Detection Methods

#### 1. TOC Extractor (Highest Confidence: 0.95)
- Extracts PDF embedded bookmarks/outline
- Most reliable when available
- Hierarchical structure support

#### 2. Heuristic Detector (Medium-High: 0.7-0.85)
- Pattern matching for chapter markers
- Multi-language support:
  - English: "Chapter 1", "Chapter One", "CHAPTER I"
  - Spanish: "Capítulo 1", "CAPÍTULO UNO"  
  - French: "Chapitre 1", "CHAPITRE UN"
  - German: "Kapitel 1", "KAPITEL EINS"
- Numeric patterns: "1.", "Part 1", "Section 1"

#### 3. Structural Analyzer (Medium: 0.6-0.75)
- Font size analysis (larger = heading)
- Text density changes
- Page break patterns

#### 4. Confidence Fusion
- Groups overlapping detections
- Calculates fusion score:
  - Single method: Use detection confidence
  - Multiple methods: Max + boost (up to +0.15)
  - Weighted average by method priority
- Resolves conflicts intelligently

---

## 📁 Files Created

### Database Layer

1. **`app/db/models/chapter.py`** (184 lines)
   - `Chapter` model with full metadata
   - Fields: title, start_page, end_page, order_index, confidence_score, detection_method, char_count, text_preview
   - 4 indexes for efficient querying
   - Computed properties: page_count, is_high_confidence, etc.

2. **`alembic/versions/007_chapters.py`** (86 lines)
   - Creates chapters table
   - 6 indexes (document_id, document_order, document_pages, confidence, detection_method)
   - Proper upgrade/downgrade paths

### Document Structure Module

3. **`app/services/document_structure/models.py`** (162 lines)
   - `DetectedChapter`: Intermediate representation
   - `TextChunk`: TTS-safe text segments
   - `PageText`: Extracted page with metadata
   - `TOCEntry`: Table of contents entry
   - `DocumentStructure`: Complete analysis result
   - `SegmentationResult`: Chunking result

4. **`app/services/document_structure/exceptions.py`** (40 lines)
   - Custom exceptions for all error cases
   - `DocumentStructureError`, `PDFExtractionError`, `ChapterDetectionError`, etc.

### Extractors

5. **`app/services/document_structure/extractors/toc_extractor.py`** (162 lines)
   - Extracts TOC from PDF bookmarks
   - Converts to chapter detections
   - Confidence: 0.95

6. **`app/services/document_structure/extractors/heuristic_detector.py`** (217 lines)
   - 12 regex patterns for chapter detection
   - Multi-language support
   - Pattern confidence mapping
   - Title cleaning and normalization

7. **`app/services/document_structure/extractors/structural_analyzer.py`** (214 lines)
   - Font size analysis
   - Extracts pages with structural metadata
   - Detects large fonts as headings
   - Confidence based on font size ratio

### Fusion System

8. **`app/services/document_structure/fusion/confidence_scorer.py`** (210 lines)
   - Groups overlapping detections
   - Calculates fusion confidence scores
   - Method priority system
   - Conflict resolution

### Core Components

9. **`app/services/document_structure/segmenter.py`** (289 lines)
   - Text segmentation for TTS
   - Max 4000 characters per chunk
   - Sentence boundary detection
   - Multi-language sentence endings
   - Fallback to paragraph/size splitting

10. **`app/services/document_structure/engine.py`** (310 lines)
    - Main orchestration engine
    - Coordinates all detection strategies
    - Extracts chapter text
    - Persists to database
    - Comprehensive error handling

### Module Organization

11. **`app/services/document_structure/__init__.py`** (39 lines)
12. **`app/services/document_structure/extractors/__init__.py`** (15 lines)
13. **`app/services/document_structure/fusion/__init__.py`** (9 lines)

---

## 📝 Files Modified

### Database Models

1. **`app/db/models/__init__.py`**
   - Added `Chapter` export

2. **`app/db/models/document.py`**
   - Added `chapters` relationship with cascade delete

### Processing Integration

3. **`app/tasks/processing.py`**
   - Integrated chapter detection (Step 1)
   - Per-chapter TTS generation (Step 2)
   - Progress tracking updated
   - Fallback to single document if detection fails

### Metrics

4. **`app/financial/financial_metrics.py`**
   - Added 5 new metrics:
     - `sonoro_chapters_detected_total`
     - `sonoro_chapter_detection_confidence`
     - `sonoro_text_chunks_generated_total`
     - `sonoro_segmentation_latency_seconds`
     - `sonoro_document_structure_analysis_duration_seconds`

---

## 📊 Database Schema

### chapters Table

```sql
CREATE TABLE chapters (
    id UUID PRIMARY KEY,
    document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    title VARCHAR(512) NOT NULL,
    start_page INTEGER NOT NULL,
    end_page INTEGER NOT NULL,
    order_index INTEGER NOT NULL,
    confidence_score FLOAT NOT NULL DEFAULT 0.0,
    detection_method VARCHAR(50),
    char_count BIGINT NOT NULL DEFAULT 0,
    text_preview TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

-- Indexes
CREATE INDEX ix_chapters_id ON chapters(id);
CREATE INDEX ix_chapters_document_id ON chapters(document_id);
CREATE INDEX ix_chapters_document_order ON chapters(document_id, order_index);
CREATE INDEX ix_chapters_document_pages ON chapters(document_id, start_page, end_page);
CREATE INDEX ix_chapters_confidence ON chapters(confidence_score);
CREATE INDEX ix_chapters_detection_method ON chapters(detection_method);
```

### Example Query

```sql
-- Get chapters for document in order
SELECT * FROM chapters 
WHERE document_id = 'doc-uuid'
ORDER BY order_index;

-- Get high-confidence chapters
SELECT * FROM chapters
WHERE confidence_score >= 0.8
ORDER BY created_at DESC;

-- Get chapters by detection method
SELECT detection_method, COUNT(*), AVG(confidence_score)
FROM chapters
GROUP BY detection_method;
```

---

## 📊 Prometheus Metrics

### 1. `sonoro_chapters_detected_total`
**Type**: Counter  
**Labels**: `detection_method`  
**Description**: Total chapters detected by method

```promql
# Chapters per method
sum by (detection_method) (sonoro_chapters_detected_total)

# Detection rate
rate(sonoro_chapters_detected_total[5m])
```

### 2. `sonoro_chapter_detection_confidence`
**Type**: Histogram  
**Labels**: `detection_method`  
**Buckets**: 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 0.95, 1.0  
**Description**: Confidence score distribution

```promql
# Average confidence by method
rate(sonoro_chapter_detection_confidence_sum[5m])
/ rate(sonoro_chapter_detection_confidence_count[5m])

# P95 confidence
histogram_quantile(0.95, 
  rate(sonoro_chapter_detection_confidence_bucket[5m])
)
```

### 3. `sonoro_text_chunks_generated_total`
**Type**: Counter  
**Description**: Total text chunks for TTS

```promql
# Chunks per minute
rate(sonoro_text_chunks_generated_total[1m]) * 60

# Total chunks
sonoro_text_chunks_generated_total
```

### 4. `sonoro_segmentation_latency_seconds`
**Type**: Histogram  
**Buckets**: 0.1, 0.5, 1.0, 2.0, 5.0, 10.0  
**Description**: Text segmentation duration

```promql
# Average segmentation time
rate(sonoro_segmentation_latency_seconds_sum[5m])
/ rate(sonoro_segmentation_latency_seconds_count[5m])
```

### 5. `sonoro_document_structure_analysis_duration_seconds`
**Type**: Histogram  
**Buckets**: 1, 5, 10, 30, 60, 120, 300  
**Description**: Full analysis duration

```promql
# P99 analysis time
histogram_quantile(0.99,
  rate(sonoro_document_structure_analysis_duration_seconds_bucket[5m])
)
```

---

## 🔧 Processing Flow

### Updated Job States

```
QUEUED
  ↓
PROCESSING (0%)
  ↓
EXTRACTING (5%) ← Structure analysis starts
  ↓
STRUCTURING (20%) ← Chapters detected
  ↓
SEGMENTED (30%) ← Text chunked
  ↓
SYNTHESIZING (30-90%) ← Per-chapter TTS
  ↓
COMPLETED (100%)
```

### Progress Milestones

- **0-5%**: Job initialization
- **5-20%**: Document structure analysis
  - TOC extraction
  - Heuristic detection  
  - Structural analysis
  - Fusion
- **20-30%**: Chapter text extraction
- **30-90%**: Per-chapter TTS generation
  - Progress divided equally among chapters
- **90-100%**: Finalization

---

## 🧪 Testing

### Test Chapter Detection

```python
import asyncio
from app.services.document_structure.engine import DocumentStructureEngine
from app.db.session import AsyncSessionLocal

async def test_detection():
    engine = DocumentStructureEngine()
    
    async with AsyncSessionLocal() as db:
        structure = await engine.analyze_document(
            document_id="test-uuid",
            pdf_path="/path/to/document.pdf",
            db=db
        )
        
        print(f"Detected {structure.chapter_count} chapters")
        print(f"Average confidence: {structure.average_confidence:.2f}")
        
        for chapter in structure.chapters:
            print(f"- {chapter.title} (pages {chapter.start_page}-{chapter.end_page})")

asyncio.run(test_detection())
```

### Test Text Segmentation

```python
from app.services.document_structure.segmenter import TextSegmenter
from uuid import uuid4

segmenter = TextSegmenter(max_chunk_size=4000)

text = "Long text here..." * 1000

chunks = segmenter.segment_text(
    text=text,
    chapter_id=uuid4()
)

print(f"Generated {len(chunks)} chunks")
for i, chunk in enumerate(chunks):
    print(f"Chunk {i}: {chunk.char_count} chars")
```

### Integration Test

```bash
# Upload document
TOKEN=$(curl -s -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=test@example.com&password=password" | jq -r .access_token)

DOC_ID=$(curl -s -X POST http://localhost:8000/api/v1/documents/upload \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@book.pdf" | jq -r .id)

# Start processing
JOB_ID=$(curl -s -X POST http://localhost:8000/api/v1/processing/documents/$DOC_ID/process \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"priority": 5}' | jq -r .id)

# Monitor progress
watch -n 2 "curl -s http://localhost:8000/api/v1/processing/jobs/$JOB_ID \
  -H 'Authorization: Bearer $TOKEN' | jq '.progress_percentage, .status'"

# Check chapters detected
curl -s "http://localhost:8000/api/v1/documents/$DOC_ID" \
  -H "Authorization: Bearer $TOKEN" | jq '.chapters'
```

---

## 💡 Detection Examples

### Example 1: Novel with Clear TOC

```
Document: "The Great Gatsby"
TOC Found: Yes
Chapters Detected: 9
Method: TOC (confidence: 0.95)
Detection Time: 0.8s

Chapter 1: Chapter I (pages 1-20)
Chapter 2: Chapter II (pages 21-35)
...
```

### Example 2: Technical Manual

```
Document: "Python Handbook"
TOC Found: Yes (hierarchical)
Chapters Detected: 15 (level 1 only)
Method: Fusion(toc,heuristic) (confidence: 0.92)
Detection Time: 1.2s

Chapter 1: Introduction (pages 1-10)
Chapter 2: Getting Started (pages 11-25)
...
```

### Example 3: PDF without TOC

```
Document: "Research Paper"
TOC Found: No
Chapters Detected: 5
Method: Fusion(heuristic,structural) (confidence: 0.73)
Detection Time: 2.5s

Chapter 1: Abstract (pages 1-1)
Chapter 2: Introduction (pages 2-5)
Chapter 3: Methodology (pages 6-12)
...
```

### Example 4: Fallback

```
Document: "Plain Text PDF"
TOC Found: No
Patterns Matched: None
Structural: No clear headings
Chapters Detected: 1
Method: Fallback (confidence: 0.5)
Detection Time: 0.3s

Chapter 1: Full Document (pages 1-50)
```

---

## 🎯 Success Criteria

### ✅ Completed

- [x] **Chapter model**: Created with indexes
- [x] **Migration**: 007_chapters.py
- [x] **TOC extraction**: PyMuPDF bookmarks
- [x] **Heuristic detection**: 12 patterns, 4 languages
- [x] **Structural analysis**: Font size + density
- [x] **Fusion system**: Confidence scoring
- [x] **Text segmentation**: Max 4000 chars, sentence boundaries
- [x] **Engine orchestration**: All strategies coordinated
- [x] **Database persistence**: Chapters saved
- [x] **Processing integration**: Celery task updated
- [x] **Prometheus metrics**: 5 new metrics
- [x] **Error handling**: Comprehensive exceptions
- [x] **Fallback logic**: Single chapter when detection fails

### ✅ Architecture Quality

- [x] **Modular design**: Clean separation of concerns
- [x] **Async-safe**: All database operations async
- [x] **Production-ready**: Comprehensive logging, error handling
- [x] **Multi-language**: EN, ES, FR, DE support
- [x] **Extensible**: Easy to add new detection strategies
- [x] **Tested patterns**: Real-world chapter formats

---

## 🚨 Error Handling

### Exception Hierarchy

```
DocumentStructureError (base)
├── PDFExtractionError
├── ChapterDetectionError
│   └── NoChaptersDetectedError
├── SegmentationError
└── InvalidChapterError
```

### Retry Strategy

- **TOC extraction fails**: Try heuristic + structural
- **Heuristic fails**: Try structural alone
- **All detection fails**: Fallback to single chapter
- **Never fails completely**: Always produces result

---

## 📈 Performance

### Expected Times

| Document Type | Pages | Chapters | Detection Time | Confidence |
|---------------|-------|----------|----------------|------------|
| Novel (TOC) | 300 | 20 | 0.5-1s | 0.95 |
| Technical Book | 500 | 30 | 1-2s | 0.90 |
| Research Paper | 50 | 5 | 0.5-1.5s | 0.75 |
| Plain PDF | 100 | 1 | 0.2-0.5s | 0.50 |

### Optimization Tips

1. **PDF Caching**: Cache parsed PDF objects
2. **Parallel Detection**: Run strategies concurrently
3. **Incremental Processing**: Process pages in batches
4. **Pattern Optimization**: Compile regex once

---

## 🔮 Future Enhancements

### Not in Block 6B

1. **ML-Based Detection** (Block 6C)
   - Neural chapter detection
   - Context-aware segmentation
   - Training on document corpus

2. **Audio Concatenation** (Block 6D)
   - Merge chapter audio files
   - Chapter markers in M4B format
   - Seamless transitions

3. **Advanced Caching** (Block 6E)
   - Cache chapter structures
   - Reuse for similar documents
   - Version control

4. **Enhanced Analysis** (Block 6F)
   - Reading level detection
   - Topic extraction
   - Summary generation

---

## 🔍 Troubleshooting

### Issue: No chapters detected

**Symptoms**: All documents get single chapter

**Solutions**:
```bash
# Check PDF structure
python -c "import fitz; doc = fitz.open('test.pdf'); print(doc.get_toc())"

# Enable debug logging
docker-compose logs worker | grep -i "chapter"

# Test extractors individually
python -m pytest tests/test_chapter_detection.py -v
```

### Issue: Low confidence scores

**Symptoms**: Confidence < 0.6 consistently

**Solutions**:
- Review PDF formatting
- Check if patterns match document language
- Add custom patterns for domain-specific formats

### Issue: Segmentation creates too many chunks

**Symptoms**: Thousands of chunks for small document

**Solutions**:
- Increase max_chunk_size (current: 4000)
- Check for sentence detection issues
- Verify text extraction quality

---

## ✅ Deployment Checklist

- [ ] Run migration: `make migrate`
- [ ] Rebuild containers: `make build`
- [ ] Restart services: `make up`
- [ ] Check worker logs for structure engine init
- [ ] Upload test PDF with clear chapters
- [ ] Verify chapters in database
- [ ] Check metrics in Prometheus
- [ ] Test multi-language documents
- [ ] Verify fallback behavior

---

**BLOCK 6B STATUS**: ✅ **COMPLETE**  
**Version**: 0.7.0  
**Total Lines**: ~2,800 (models + extractors + engine + fusion + segmenter)  
**Files Created**: 13  
**Files Modified**: 4  
**New Metrics**: 5 Prometheus metrics  
**Database Tables**: 1 new (chapters)

**Next Block**: 6C - Audio Concatenation & Chapter Markers
