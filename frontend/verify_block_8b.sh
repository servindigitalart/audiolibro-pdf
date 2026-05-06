#!/bin/bash
# BLOCK 8B Verification Script
# Verifies the document management UI is working correctly

set -e

echo "🔍 BLOCK 8B: Document Upload & Processing UX Verification"
echo "=========================================================="
echo ""

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

ERRORS=0

# Check if we're in the frontend directory
if [ ! -f "package.json" ]; then
    echo "${RED}❌ Error: Must run from frontend directory${NC}"
    exit 1
fi

echo "📦 Step 1: Checking dependencies..."
if npm list react-dropzone --depth=0 > /dev/null 2>&1; then
    echo "${GREEN}✓${NC} react-dropzone installed"
else
    echo "${RED}✗${NC} react-dropzone missing"
    ERRORS=$((ERRORS + 1))
fi

echo ""
echo "📁 Step 2: Checking files exist..."
FILES=(
    "lib/document-service.ts"
    "lib/document-status.ts"
    "components/documents/document-upload.tsx"
    "components/documents/document-card.tsx"
    "components/documents/status-badge.tsx"
    "components/documents/progress-indicator.tsx"
    "components/documents/chapter-list.tsx"
    "app/(dashboard)/documents/page.tsx"
    "app/(dashboard)/documents/[id]/page.tsx"
    "components/ui/badge.tsx"
    "components/ui/progress.tsx"
    "components/ui/skeleton.tsx"
    "components/ui/alert.tsx"
)

for file in "${FILES[@]}"; do
    if [ -f "$file" ]; then
        echo "${GREEN}✓${NC} $file"
    else
        echo "${RED}✗${NC} $file missing"
        ERRORS=$((ERRORS + 1))
    fi
done

echo ""
echo "🔨 Step 3: Type checking..."
if npx tsc --noEmit > /dev/null 2>&1; then
    echo "${GREEN}✓${NC} TypeScript compilation successful"
else
    echo "${RED}✗${NC} TypeScript errors found"
    ERRORS=$((ERRORS + 1))
fi

echo ""
echo "🏗️  Step 4: Building project..."
if npm run build > /tmp/build.log 2>&1; then
    echo "${GREEN}✓${NC} Build successful"
else
    echo "${RED}✗${NC} Build failed. Check /tmp/build.log for details"
    ERRORS=$((ERRORS + 1))
fi

echo ""
echo "📄 Step 5: Checking documentation..."
DOC_FILES=(
    "../docs/BLOCK_8B_COMPLETE.md"
    "../docs/BLOCK_8B_QUICK_START.md"
    "../docs/BLOCK_8B_SUMMARY.md"
)

for file in "${DOC_FILES[@]}"; do
    if [ -f "$file" ]; then
        echo "${GREEN}✓${NC} $file"
    else
        echo "${RED}✗${NC} $file missing"
        ERRORS=$((ERRORS + 1))
    fi
done

echo ""
echo "=========================================================="
if [ $ERRORS -eq 0 ]; then
    echo "${GREEN}✅ All checks passed! BLOCK 8B is ready.${NC}"
    echo ""
    echo "🚀 Next steps:"
    echo "   1. Start dev server: npm run dev"
    echo "   2. Open http://localhost:3000"
    echo "   3. Navigate to /documents"
    echo "   4. Test document upload"
    echo ""
    exit 0
else
    echo "${RED}❌ $ERRORS check(s) failed${NC}"
    echo ""
    echo "Please review the errors above and fix them."
    exit 1
fi
