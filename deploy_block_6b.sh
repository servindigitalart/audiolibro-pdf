#!/bin/bash
# BLOCK 6B Deployment Checklist
# ==============================

set -e

echo "=========================================="
echo "BLOCK 6B DEPLOYMENT CHECKLIST"
echo "=========================================="
echo ""

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Track status
CHECKS_PASSED=0
CHECKS_FAILED=0

check_step() {
    echo -e "${YELLOW}▶ $1${NC}"
}

pass_step() {
    echo -e "${GREEN}✓ $1${NC}"
    CHECKS_PASSED=$((CHECKS_PASSED + 1))
}

fail_step() {
    echo -e "${RED}✗ $1${NC}"
    CHECKS_FAILED=$((CHECKS_FAILED + 1))
}

echo "Starting deployment checks..."
echo ""

# ============================================
# 1. VERIFY FILE STRUCTURE
# ============================================
check_step "1. Verifying file structure..."

FILES=(
    "services/api/app/db/models/chapter.py"
    "services/api/alembic/versions/007_chapters.py"
    "services/api/app/services/document_structure/__init__.py"
    "services/api/app/services/document_structure/models.py"
    "services/api/app/services/document_structure/exceptions.py"
    "services/api/app/services/document_structure/engine.py"
    "services/api/app/services/document_structure/segmenter.py"
    "services/api/app/services/document_structure/extractors/__init__.py"
    "services/api/app/services/document_structure/extractors/toc_extractor.py"
    "services/api/app/services/document_structure/extractors/heuristic_detector.py"
    "services/api/app/services/document_structure/extractors/structural_analyzer.py"
    "services/api/app/services/document_structure/fusion/__init__.py"
    "services/api/app/services/document_structure/fusion/confidence_scorer.py"
)

MISSING_FILES=0
for file in "${FILES[@]}"; do
    if [ -f "$file" ]; then
        echo "  ✓ $file"
    else
        echo "  ✗ $file (MISSING)"
        MISSING_FILES=$((MISSING_FILES + 1))
    fi
done

if [ $MISSING_FILES -eq 0 ]; then
    pass_step "All 13 BLOCK 6B files present"
else
    fail_step "$MISSING_FILES files missing"
fi
echo ""

# ============================================
# 2. CHECK DOCKER STATUS
# ============================================
check_step "2. Checking Docker status..."

if docker ps > /dev/null 2>&1; then
    pass_step "Docker daemon is running"
    
    # Check if containers are up
    if docker-compose ps | grep -q "Up"; then
        pass_step "Docker containers are running"
    else
        fail_step "Docker containers not running. Run: make up"
    fi
else
    fail_step "Docker daemon not running. Start Docker Desktop first."
fi
echo ""

# ============================================
# 3. VERIFY DATABASE MIGRATION
# ============================================
check_step "3. Checking database migration..."

if [ -f "services/api/alembic/versions/007_chapters.py" ]; then
    pass_step "Migration file 007_chapters.py exists"
    
    # Try to check if migration is applied
    if docker-compose exec -T api alembic current 2>/dev/null | grep -q "007"; then
        pass_step "Migration 007 is applied"
    else
        fail_step "Migration 007 not applied. Run: make migrate"
    fi
else
    fail_step "Migration file missing"
fi
echo ""

# ============================================
# 4. CHECK DEPENDENCIES
# ============================================
check_step "4. Checking Python dependencies..."

REQUIRED_DEPS=("pymupdf" "prometheus-client" "celery" "sqlalchemy")
MISSING_DEPS=0

for dep in "${REQUIRED_DEPS[@]}"; do
    if docker-compose exec -T api python -c "import $dep" 2>/dev/null; then
        echo "  ✓ $dep"
    else
        echo "  ✗ $dep (MISSING)"
        MISSING_DEPS=$((MISSING_DEPS + 1))
    fi
done

if [ $MISSING_DEPS -eq 0 ]; then
    pass_step "All Python dependencies installed"
else
    fail_step "$MISSING_DEPS dependencies missing. Rebuild containers: make build"
fi
echo ""

# ============================================
# 5. VERIFY METRICS ENDPOINT
# ============================================
check_step "5. Checking Prometheus metrics..."

if curl -s http://localhost:8000/metrics > /dev/null 2>&1; then
    METRICS_CONTENT=$(curl -s http://localhost:8000/metrics)
    
    NEW_METRICS=(
        "sonoro_chapters_detected_total"
        "sonoro_chapter_detection_confidence"
        "sonoro_text_chunks_generated_total"
        "sonoro_segmentation_latency_seconds"
        "sonoro_document_structure_analysis_duration_seconds"
    )
    
    MISSING_METRICS=0
    for metric in "${NEW_METRICS[@]}"; do
        if echo "$METRICS_CONTENT" | grep -q "$metric"; then
            echo "  ✓ $metric"
        else
            echo "  ✗ $metric (MISSING)"
            MISSING_METRICS=$((MISSING_METRICS + 1))
        fi
    done
    
    if [ $MISSING_METRICS -eq 0 ]; then
        pass_step "All 5 BLOCK 6B metrics exposed"
    else
        fail_step "$MISSING_METRICS metrics not found. Restart API: make restart"
    fi
else
    fail_step "Cannot reach metrics endpoint at http://localhost:8000/metrics"
fi
echo ""

# ============================================
# 6. CHECK DATABASE SCHEMA
# ============================================
check_step "6. Verifying database schema..."

if docker-compose exec -T db psql -U postgres -d sonoro -c "\d chapters" > /dev/null 2>&1; then
    pass_step "Chapters table exists in database"
    
    # Check columns
    COLUMNS=$(docker-compose exec -T db psql -U postgres -d sonoro -c "\d chapters" | grep -c "id\|document_id\|title\|start_page\|end_page\|order_index\|confidence_score\|detection_method\|char_count\|text_preview\|created_at")
    
    if [ $COLUMNS -ge 10 ]; then
        pass_step "All chapter columns present"
    else
        fail_step "Missing chapter columns"
    fi
else
    fail_step "Chapters table does not exist. Run: make migrate"
fi
echo ""

# ============================================
# 7. TEST IMPORTS
# ============================================
check_step "7. Testing Python imports..."

IMPORT_TEST="
from app.services.document_structure import DocumentStructureEngine
from app.services.document_structure.extractors import TOCExtractor, HeuristicDetector, StructuralAnalyzer
from app.services.document_structure.fusion import ConfidenceScorer
from app.db.models.chapter import Chapter
print('OK')
"

if docker-compose exec -T api python -c "$IMPORT_TEST" 2>/dev/null | grep -q "OK"; then
    pass_step "All BLOCK 6B modules import successfully"
else
    fail_step "Import errors detected. Check logs: make logs-api"
fi
echo ""

# ============================================
# 8. CHECK CELERY WORKER
# ============================================
check_step "8. Checking Celery worker..."

if docker-compose ps | grep -q "worker.*Up"; then
    pass_step "Celery worker is running"
    
    # Check if task is registered
    if docker-compose exec -T worker celery -A app.celery_app inspect registered 2>/dev/null | grep -q "process_document_job"; then
        pass_step "process_document_job task registered"
    else
        fail_step "Task not registered. Restart worker: docker-compose restart worker"
    fi
else
    fail_step "Celery worker not running"
fi
echo ""

# ============================================
# SUMMARY
# ============================================
echo ""
echo "=========================================="
echo "DEPLOYMENT CHECK SUMMARY"
echo "=========================================="
echo -e "Checks Passed: ${GREEN}${CHECKS_PASSED}${NC}"
echo -e "Checks Failed: ${RED}${CHECKS_FAILED}${NC}"
echo ""

if [ $CHECKS_FAILED -eq 0 ]; then
    echo -e "${GREEN}✅ ALL CHECKS PASSED!${NC}"
    echo ""
    echo "BLOCK 6B is ready for testing."
    echo ""
    echo "Next steps:"
    echo "  1. Test with sample PDF:"
    echo "     python test_block_6b.py /path/to/book.pdf"
    echo ""
    echo "  2. Upload a document via API:"
    echo "     curl -X POST http://localhost:8000/api/v1/documents/upload \\"
    echo "       -H \"Authorization: Bearer YOUR_TOKEN\" \\"
    echo "       -F \"file=@book.pdf\""
    echo ""
    echo "  3. Monitor metrics:"
    echo "     curl http://localhost:8000/metrics | grep sonoro_chapters"
    echo ""
    exit 0
else
    echo -e "${RED}❌ DEPLOYMENT CHECKS FAILED${NC}"
    echo ""
    echo "Please fix the issues above before proceeding."
    echo ""
    echo "Common fixes:"
    echo "  - Start Docker: Open Docker Desktop"
    echo "  - Start containers: make up"
    echo "  - Run migration: make migrate"
    echo "  - Rebuild containers: make build"
    echo "  - Restart services: make restart"
    echo ""
    exit 1
fi
