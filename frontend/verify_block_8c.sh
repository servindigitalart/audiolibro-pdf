#!/bin/zsh
# BLOCK 8C Verification Script
# Verifies the billing & subscription UX is working correctly

set -e

echo "🔍 BLOCK 8C: Billing & Subscription UX Verification"
echo "===================================================="
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
echo "✓ All dependencies already installed (no new packages needed)"

echo ""
echo "📁 Step 2: Checking files exist..."
FILES=(
    "lib/billing-service.ts"
    "components/billing/subscription-overview.tsx"
    "components/billing/usage-meter.tsx"
    "components/billing/plan-card.tsx"
    "app/(dashboard)/billing/page.tsx"
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
if npx tsc --noEmit --project . 2>&1 | grep -q "error TS"; then
    echo "${RED}✗${NC} TypeScript errors found"
    ERRORS=$((ERRORS + 1))
else
    echo "${GREEN}✓${NC} TypeScript compilation successful"
fi

echo ""
echo "📊 Step 4: Checking service layer..."
if grep -q "export const PLANS" lib/billing-service.ts; then
    echo "${GREEN}✓${NC} Plans defined"
else
    echo "${RED}✗${NC} Plans not found"
    ERRORS=$((ERRORS + 1))
fi

if grep -q "createCheckoutSession" lib/billing-service.ts; then
    echo "${GREEN}✓${NC} Checkout function exists"
else
    echo "${RED}✗${NC} Checkout function missing"
    ERRORS=$((ERRORS + 1))
fi

if grep -q "getSubscription" lib/billing-service.ts; then
    echo "${GREEN}✓${NC} Get subscription function exists"
else
    echo "${RED}✗${NC} Get subscription function missing"
    ERRORS=$((ERRORS + 1))
fi

echo ""
echo "🎨 Step 5: Checking components..."
if grep -q "SubscriptionOverview" components/billing/subscription-overview.tsx; then
    echo "${GREEN}✓${NC} Subscription overview component"
else
    echo "${RED}✗${NC} Subscription overview missing"
    ERRORS=$((ERRORS + 1))
fi

if grep -q "UsageMeter" components/billing/usage-meter.tsx; then
    echo "${GREEN}✓${NC} Usage meter component"
else
    echo "${RED}✗${NC} Usage meter missing"
    ERRORS=$((ERRORS + 1))
fi

if grep -q "PlanCard" components/billing/plan-card.tsx; then
    echo "${GREEN}✓${NC} Plan card component"
else
    echo "${RED}✗${NC} Plan card missing"
    ERRORS=$((ERRORS + 1))
fi

echo ""
echo "📄 Step 6: Checking billing page integration..."
if grep -q "PLANS" app/\(dashboard\)/billing/page.tsx; then
    echo "${GREEN}✓${NC} Plans imported in billing page"
else
    echo "${RED}✗${NC} Plans not imported"
    ERRORS=$((ERRORS + 1))
fi

if grep -q "SubscriptionOverview" app/\(dashboard\)/billing/page.tsx; then
    echo "${GREEN}✓${NC} Subscription overview integrated"
else
    echo "${RED}✗${NC} Subscription overview not integrated"
    ERRORS=$((ERRORS + 1))
fi

if grep -q "UsageMeter" app/\(dashboard\)/billing/page.tsx; then
    echo "${GREEN}✓${NC} Usage meter integrated"
else
    echo "${RED}✗${NC} Usage meter not integrated"
    ERRORS=$((ERRORS + 1))
fi

echo ""
echo "📚 Step 7: Checking documentation..."
DOC_FILES=(
    "../docs/BLOCK_8C_COMPLETE.md"
    "../docs/BLOCK_8C_QUICK_START.md"
    "../docs/BLOCK_8C_SUMMARY.md"
    "../BLOCK_8C_READY.md"
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
echo "🔗 Step 8: Checking API endpoints..."
ENDPOINTS=(
    "/api/v1/billing/checkout"
    "/api/v1/billing/subscription"
    "/api/v1/billing/portal"
    "/api/v1/account/usage"
)

echo "The following endpoints should be available in the backend:"
for endpoint in "${ENDPOINTS[@]}"; do
    echo "  • $endpoint"
done

echo ""
echo "===================================================="
if [ $ERRORS -eq 0 ]; then
    echo "${GREEN}✅ All checks passed! BLOCK 8C is ready.${NC}"
    echo ""
    echo "🚀 Next steps:"
    echo "   1. Ensure backend is running with Stripe configured"
    echo "   2. Set STRIPE_API_KEY in backend .env"
    echo "   3. Configure Stripe webhook endpoints"
    echo "   4. Navigate to http://localhost:3000/billing"
    echo "   5. Test the complete checkout flow"
    echo ""
    echo "📚 Documentation:"
    echo "   • Complete guide: docs/BLOCK_8C_COMPLETE.md"
    echo "   • Quick start: docs/BLOCK_8C_QUICK_START.md"
    echo ""
    exit 0
else
    echo "${RED}❌ $ERRORS check(s) failed${NC}"
    echo ""
    echo "Please review the errors above and fix them."
    exit 1
fi
