#!/bin/bash
# BLOCK 6A Deployment Script
# Run this script to deploy TTS integration

set -e

echo "🚀 BLOCK 6A: TTS Provider Integration Deployment"
echo "================================================"
echo ""

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Check if we're in the right directory
if [ ! -f "docker-compose.yml" ]; then
    echo -e "${RED}❌ Error: docker-compose.yml not found${NC}"
    echo "Please run this script from the project root directory"
    exit 1
fi

echo -e "${BLUE}Step 1: Checking environment configuration...${NC}"
if [ ! -f ".env" ]; then
    echo -e "${RED}❌ .env file not found${NC}"
    echo "Please create .env file with required variables"
    exit 1
fi

# Check for Google TTS configuration
if ! grep -q "GOOGLE_TTS_" .env; then
    echo -e "${RED}⚠️  Warning: Google TTS configuration not found in .env${NC}"
    echo ""
    echo "Please add the following to your .env file:"
    echo ""
    echo "# Google Cloud TTS (BLOCK 6A)"
    echo "GOOGLE_TTS_CREDENTIALS_JSON=/app/service-account.json"
    echo "GOOGLE_TTS_PROJECT_ID=your-project-id"
    echo "GOOGLE_TTS_DEFAULT_VOICE=en-US-Neural2-A"
    echo "GOOGLE_TTS_DEFAULT_LANGUAGE=en-US"
    echo ""
    read -p "Continue anyway? (y/N) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

echo -e "${GREEN}✅ Environment configuration check complete${NC}"
echo ""

echo -e "${BLUE}Step 2: Stopping existing services...${NC}"
docker-compose down

echo -e "${GREEN}✅ Services stopped${NC}"
echo ""

echo -e "${BLUE}Step 3: Building new containers with TTS dependencies...${NC}"
docker-compose build --no-cache api worker

echo -e "${GREEN}✅ Containers built${NC}"
echo ""

echo -e "${BLUE}Step 4: Starting services...${NC}"
docker-compose up -d

echo ""
echo -e "${BLUE}Step 5: Waiting for services to be ready...${NC}"
sleep 10

echo ""
echo -e "${BLUE}Step 6: Running database migrations...${NC}"
docker-compose exec -T api alembic upgrade head

echo -e "${GREEN}✅ Migrations complete${NC}"
echo ""

echo -e "${BLUE}Step 7: Checking service health...${NC}"
echo ""

# Check API
echo -n "  • API: "
if curl -s -f http://localhost:8000/health > /dev/null 2>&1; then
    echo -e "${GREEN}✅ Running${NC}"
else
    echo -e "${RED}❌ Not responding${NC}"
fi

# Check worker
echo -n "  • Worker: "
if docker-compose ps worker | grep -q "Up"; then
    echo -e "${GREEN}✅ Running${NC}"
else
    echo -e "${RED}❌ Not running${NC}"
fi

# Check Redis
echo -n "  • Redis: "
if docker-compose ps redis | grep -q "Up"; then
    echo -e "${GREEN}✅ Running${NC}"
else
    echo -e "${RED}❌ Not running${NC}"
fi

# Check Postgres
echo -n "  • Postgres: "
if docker-compose ps postgres | grep -q "Up"; then
    echo -e "${GREEN}✅ Running${NC}"
else
    echo -e "${RED}❌ Not running${NC}"
fi

echo ""
echo -e "${BLUE}Step 8: Checking TTS initialization...${NC}"
sleep 5
if docker-compose logs worker | grep -q "TTS Service initialized"; then
    echo -e "${GREEN}✅ TTS Service initialized successfully${NC}"
else
    echo -e "${RED}⚠️  TTS Service initialization not detected in logs${NC}"
    echo "Check logs with: docker-compose logs worker | grep TTS"
fi

echo ""
echo "=========================================="
echo -e "${GREEN}✅ BLOCK 6A DEPLOYMENT COMPLETE${NC}"
echo "=========================================="
echo ""
echo "Next steps:"
echo "  1. Check worker logs: docker-compose logs -f worker"
echo "  2. Test the API: See docs/BLOCK_6A_QUICK_START.md"
echo "  3. Monitor metrics: curl http://localhost:8000/metrics | grep tts"
echo ""
echo "Useful commands:"
echo "  • View all logs: docker-compose logs -f"
echo "  • Restart worker: docker-compose restart worker"
echo "  • Check service status: docker-compose ps"
echo ""
