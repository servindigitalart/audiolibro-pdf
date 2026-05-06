# BLOCK 6B: Quick Reference Guide

## 🚀 Deployment Commands

```bash
# 1. Make deployment script executable
chmod +x deploy_block_6b.sh

# 2. Run deployment checks
./deploy_block_6b.sh

# 3. If Docker not running, start it
# Open Docker Desktop or: open -a Docker

# 4. Start all services
make up

# 5. Run database migration
make migrate

# 6. Rebuild containers (if needed)
make build

# 7. Restart services
make restart
```

## 📊 Monitor Metrics

### View All BLOCK 6B Metrics
```bash
curl http://localhost:8000/metrics | grep sonoro_chapters
curl http://localhost:8000/metrics | grep sonoro_text_chunks
curl http://localhost:8000/metrics | grep sonoro_segmentation
curl http://localhost:8000/metrics | grep sonoro_document_structure
```

### Prometheus Queries
```promql
# Total chapters detected by method
sum(sonoro_chapters_detected_total) by (detection_method)

# Average chapter detection confidence
avg(sonoro_chapter_detection_confidence) by (detection_method)

# Text chunks generated per minute
rate(sonoro_text_chunks_generated_total[1m])

# 95th percentile segmentation latency
histogram_quantile(0.95, sonoro_segmentation_latency_seconds_bucket)

# Average document structure analysis duration
avg(sonoro_document_structure_analysis_duration_seconds)
```

## 🧪 Testing

### Test Individual Extractors
```python
# Test TOC extraction
from app.services.document_structure.extractors import TOCExtractor

extractor = TOCExtractor()
chapters = await extractor.extract_chapters("/path/to/book.pdf")
for ch in chapters:
    print(f"{ch.title} (pages {ch.start_page}-{ch.end_page})")
```

### Test Full Pipeline
```bash
# Using test script
python test_block_6b.py /path/to/book.pdf

# Or with Docker
docker-compose exec api python test_block_6b.py /tmp/book.pdf
```

### Test via API
```bash
# 1. Get auth token
TOKEN=$(curl -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"test@example.com","password":"password"}' \
  | jq -r '.access_token')

# 2. Upload document
curl -X POST http://localhost:8000/api/v1/documents/upload \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@book.pdf"

# 3. Get document ID from response, then check chapters
DOC_ID="YOUR_DOCUMENT_ID"
curl http://localhost:8000/api/v1/documents/$DOC_ID/chapters \
  -H "Authorization: Bearer $TOKEN"
```

## 🗄️ Database Queries

### Check Chapters Table
```sql
-- Connect to database
docker-compose exec db psql -U postgres -d sonoro

-- View table schema
\d chapters

-- Count chapters by detection method
SELECT detection_method, COUNT(*), AVG(confidence_score)
FROM chapters
GROUP BY detection_method;

-- Find high-confidence chapters
SELECT title, start_page, end_page, confidence_score, detection_method
FROM chapters
WHERE confidence_score >= 0.80
ORDER BY start_page;

-- Documents with most chapters
SELECT d.original_filename, COUNT(c.id) as chapter_count
FROM documents d
LEFT JOIN chapters c ON c.document_id = d.id
GROUP BY d.id, d.original_filename
ORDER BY chapter_count DESC;
```

## 📝 Logs

### View Service Logs
```bash
# API logs
make logs-api

# Worker logs (Celery)
docker-compose logs -f worker

# All logs
docker-compose logs -f

# Filter for chapter detection
docker-compose logs api | grep "chapter"
docker-compose logs worker | grep "structure"
```

### Enable Debug Logging
```python
# In app/services/document_structure/engine.py
import logging
logging.getLogger('app.services.document_structure').setLevel(logging.DEBUG)
```

## 🔍 Troubleshooting

### Issue: Migration fails
```bash
# Check current migration
docker-compose exec api alembic current

# Check migration history
docker-compose exec api alembic history

# Stamp migration manually if needed
docker-compose exec api alembic stamp 007
```

### Issue: Chapters not detected
```bash
# Check PDF accessibility
docker-compose exec api ls -la /path/to/pdf

# Test PyMuPDF directly
docker-compose exec api python -c "
import fitz
doc = fitz.open('/path/to/pdf')
print(f'Pages: {len(doc)}')
print(f'TOC: {doc.get_toc()}')
"

# Check logs for detection failures
docker-compose logs api | grep "chapter.*failed"
```

### Issue: Import errors
```bash
# Verify module structure
docker-compose exec api find /app -name "*.py" -path "*/document_structure/*"

# Test imports
docker-compose exec api python -c "
from app.services.document_structure import DocumentStructureEngine
print('OK')
"

# Reinstall if needed
docker-compose exec api pip install -e .
```

### Issue: Metrics not appearing
```bash
# Check metrics endpoint
curl http://localhost:8000/metrics

# Verify metrics are registered
docker-compose exec api python -c "
from app.financial.financial_metrics import chapters_detected_total
print(chapters_detected_total._name)
"

# Restart Prometheus
docker-compose restart prometheus
```

### Issue: Low detection confidence
Check the detection strategies:

1. **TOC Missing** (highest confidence)
   - PDF has no embedded bookmarks
   - Use heuristic/structural fallback

2. **Patterns Not Matching** (medium confidence)
   - Add new patterns to `heuristic_detector.py`
   - Check language support

3. **Structural Analysis Failing** (lower confidence)
   - PDF has inconsistent formatting
   - Font size analysis not reliable

**Solution**: Adjust confidence thresholds or add custom patterns

## 📈 Performance Benchmarks

### Expected Performance
| Metric | Target | Typical |
|--------|--------|---------|
| Structure analysis | < 5s | 2-3s |
| TOC extraction | < 0.5s | 0.1-0.2s |
| Heuristic detection | < 2s | 0.5-1s |
| Structural analysis | < 3s | 1-2s |
| Segmentation (per chapter) | < 0.1s | 0.01-0.05s |

### Monitor Performance
```bash
# Check analysis duration
curl http://localhost:8000/metrics | grep structure_analysis_duration

# Calculate average from histogram
# 95th percentile should be < 5s
```

## 🔄 Processing Flow

```
1. Document Upload → QUEUED (0%)
2. Structure Analysis → EXTRACTING (5%)
   - Extract pages with fonts
   - Run TOC extractor
   - Run heuristic detector
   - Run structural analyzer
3. Confidence Fusion → STRUCTURING (20%)
   - Merge detections
   - Calculate confidence scores
   - Persist chapters to DB
4. Text Segmentation → SEGMENTED (30%)
   - Chunk text (max 4000 chars)
   - Respect sentence boundaries
5. TTS Generation → SYNTHESIZING (30-90%)
   - Generate audio per chapter
   - Store as separate files
6. Complete → COMPLETED (100%)
```

## 🎯 Success Criteria

- ✅ All 13 files created
- ✅ Migration 007 applied
- ✅ 5 metrics exposed
- ✅ Chapters table has data
- ✅ Processing task integrated
- ✅ No import errors
- ✅ Multi-language patterns working
- ✅ Confidence scoring accurate

## 📚 Multi-Language Support

### Supported Patterns

**English**:
- `Chapter 1`, `CHAPTER ONE`, `Chapter I`
- `Part 1`, `Section 1`

**Spanish**:
- `Capítulo 1`, `CAPÍTULO UNO`

**French**:
- `Chapitre 1`, `CHAPITRE UN`

**German**:
- `Kapitel 1`, `KAPITEL EINS`

**Generic**:
- `1.`, `I.`

### Add New Language
Edit `app/services/document_structure/extractors/heuristic_detector.py`:

```python
self.patterns = [
    # ... existing patterns ...
    
    # Italian
    (r'Capitolo\s+(\d+)', 0.80),
    (r'CAPITOLO\s+UNO', 0.75),
]
```

## 🛠️ Configuration

### Adjust Chunk Size
Edit `app/services/document_structure/segmenter.py`:

```python
class TextSegmenter:
    def __init__(self, max_chunk_size: int = 4000):
        # Reduce for shorter TTS chunks
        # Increase (max 5000) for longer chunks
```

### Adjust Confidence Thresholds
Edit `app/services/document_structure/models.py`:

```python
@property
def is_high_confidence(self) -> bool:
    return self.confidence >= 0.80  # Adjust threshold

@property
def is_medium_confidence(self) -> bool:
    return 0.60 <= self.confidence < 0.80  # Adjust range
```

## 🎨 Example Output

```
Document Structure Analyzed:
  📖 Total Chapters: 15
  📊 Average Confidence: 0.87
  ⭐ High Confidence: 12
  ⚠️ Medium Confidence: 3
  ❌ Low Confidence: 0

Chapters:
  1. Introduction (pages 1-5, confidence: 0.95, toc)
  2. Getting Started (pages 6-20, confidence: 0.85, heuristic)
  3. Advanced Topics (pages 21-45, confidence: 0.78, fusion)
  ...
```

## 📞 Support

### Need Help?
1. Check logs: `make logs-api`
2. Run deployment checks: `./deploy_block_6b.sh`
3. Review documentation: `docs/BLOCK_6B_COMPLETE.md`
4. Test with sample PDF: `python test_block_6b.py book.pdf`

### Common Issues
- **Docker not running**: Start Docker Desktop
- **Migration fails**: Check database connection
- **No chapters detected**: Verify PDF has structure
- **Low confidence**: Add patterns or adjust thresholds
- **Import errors**: Rebuild containers with `make build`

---

**Version**: 0.7.0 (BLOCK 6B)  
**Status**: ✅ Production Ready  
**Last Updated**: 2026-02-11
