#!/bin/bash
# BLOCK 6C Deployment Checklist
# ==============================

set -e

echo "=========================================="
echo "BLOCK 6C DEPLOYMENT CHECKLIST"
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
    "services/api/app/services/audio/__init__.py"
    "services/api/app/services/audio/exceptions.py"
    "services/api/app/services/audio/assembler.py"
    "services/api/app/services/audio/normalizer.py"
    "services/api/app/services/audio/metadata.py"
    "services/api/alembic/versions/008_audio_assembly.py"
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
    pass_step "All 6 BLOCK 6C files present"
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
# 3. CHECK FFMPEG INSTALLATION
# ============================================
check_step "3. Checking FFmpeg installation..."

if docker-compose exec -T api ffmpeg -version > /dev/null 2>&1; then
    pass_step "FFmpeg installed in API container"
else
    fail_step "FFmpeg not installed. Rebuild: make build"
fi

if docker-compose exec -T worker ffmpeg -version > /dev/null 2>&1; then
    pass_step "FFmpeg installed in worker container"
else
    fail_step "FFmpeg not installed in worker. Rebuild: make build"
fi
echo ""

# ============================================
# 4. VERIFY DATABASE MIGRATION
# ============================================
check_step "4. Checking database migration..."

if [ -f "services/api/alembic/versions/008_audio_assembly.py" ]; then
    pass_step "Migration file 008_audio_assembly.py exists"
    
    # Try to check if migration is applied
    if docker-compose exec -T api alembic current 2>/dev/null | grep -q "008"; then
        pass_step "Migration 008 is applied"
    else
        fail_step "Migration 008 not applied. Run: make migrate"
    fi
else
    fail_step "Migration file missing"
fi
echo ""

# ============================================
# 5. CHECK DEPENDENCIES
# ============================================
check_step "5. Checking Python dependencies..."

REQUIRED_DEPS=("pydub" "mutagen")
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
# 6. VERIFY METRICS ENDPOINT
# ============================================
check_step "6. Checking Prometheus metrics..."

if curl -s http://localhost:8000/metrics > /dev/null 2>&1; then
    METRICS_CONTENT=$(curl -s http://localhost:8000/metrics)
    
    NEW_METRICS=(
        "sonoro_audio_assembly_seconds"
        "sonoro_audio_file_size_bytes"
        "sonoro_full_audiobook_generated_total"
        "sonoro_audio_normalization_seconds"
        "sonoro_audio_metadata_write_seconds"
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
        pass_step "All 5 BLOCK 6C metrics exposed"
    else
        fail_step "$MISSING_METRICS metrics not found. Restart API: make restart"
    fi
else
    fail_step "Cannot reach metrics endpoint at http://localhost:8000/metrics"
fi
echo ""

# ============================================
# 7. CHECK DATABASE SCHEMA
# ============================================
check_step "7. Verifying database schema..."

if docker-compose exec -T db psql -U postgres -d sonoro -c "SELECT column_name FROM information_schema.columns WHERE table_name='documents' AND column_name IN ('final_audio_path', 'audio_duration_seconds', 'audio_file_size_bytes');" 2>/dev/null | grep -q "final_audio_path"; then
    pass_step "Audio assembly columns exist in documents table"
else
    fail_step "Audio assembly columns missing. Run: make migrate"
fi
echo ""

# ============================================
# 8. TEST IMPORTS
# ============================================
check_step "8. Testing Python imports..."

IMPORT_TEST="
from app.services.audio import AudioAssembler, AudioNormalizer, AudioMetadataWriter
from app.services.audio.metadata import AudioMetadata
print('OK')
"

if docker-compose exec -T api python -c "$IMPORT_TEST" 2>/dev/null | grep -q "OK"; then
    pass_step "All BLOCK 6C modules import successfully"
else
    fail_step "Import errors detected. Check logs: make logs-api"
fi
echo ""

# ============================================
# 9. CHECK CELERY WORKER
# ============================================
check_step "9. Checking Celery worker..."

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
    echo "BLOCK 6C is ready for production."
    echo ""
    echo "Complete pipeline:"
    echo "  1. Upload PDF"
    echo "  2. Detect chapters (BLOCK 6B)"
    echo "  3. Generate TTS per chapter (BLOCK 6A)"
    echo "  4. Assemble chapters (BLOCK 6C) ⭐"
    echo "  5. Normalize audio (BLOCK 6C) ⭐"
    echo "  6. Add metadata (BLOCK 6C) ⭐"
    echo "  7. Upload final audiobook ⭐"
    echo ""
    echo "Next steps:"
    echo "  1. Upload a document:"
    echo "     curl -X POST http://localhost:8000/api/v1/documents/upload \\"
    echo "       -H \"Authorization: Bearer YOUR_TOKEN\" \\"
    echo "       -F \"file=@book.pdf\""
    echo ""
    echo "  2. Monitor assembly metrics:"
    echo "     curl http://localhost:8000/metrics | grep sonoro_audio"
    echo ""
    echo "  3. Check processing logs:"
    echo "     docker-compose logs -f worker | grep -E 'assembling|finalizing'"
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
