#!/bin/bash
#
# First-time setup script for Sonoro development environment
# This script automates the entire setup process
#

set -e  # Exit on any error

echo "🚀 Sonoro - First-Time Setup Script"
echo "===================================="
echo ""

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Check if Docker is running
echo "1️⃣  Checking Docker..."
if ! docker info > /dev/null 2>&1; then
    echo -e "${RED}❌ Docker is not running${NC}"
    echo "   Please start Docker Desktop and try again"
    exit 1
fi
echo -e "${GREEN}✅ Docker is running${NC}"
echo ""

# Check if .env exists
echo "2️⃣  Checking environment configuration..."
if [ ! -f .env ]; then
    echo "   Creating .env from .env.example..."
    cp .env.example .env
    echo -e "${GREEN}✅ .env file created${NC}"
    echo -e "${YELLOW}⚠️  Please review .env and update if needed${NC}"
else
    echo -e "${GREEN}✅ .env file exists${NC}"
fi
echo ""

# Build Docker images
echo "3️⃣  Building Docker images..."
docker-compose build
echo -e "${GREEN}✅ Images built successfully${NC}"
echo ""

# Start services
echo "4️⃣  Starting services..."
docker-compose up -d
echo -e "${GREEN}✅ Services started${NC}"
echo ""

# Wait for services to be ready
echo "5️⃣  Waiting for services to be ready..."
sleep 10

# Check if services are healthy
echo "   Checking PostgreSQL..."
if docker-compose exec -T postgres pg_isready -U sonoro > /dev/null 2>&1; then
    echo -e "${GREEN}   ✅ PostgreSQL is ready${NC}"
else
    echo -e "${RED}   ❌ PostgreSQL is not ready${NC}"
    exit 1
fi

echo "   Checking Redis..."
if docker-compose exec -T redis redis-cli ping > /dev/null 2>&1; then
    echo -e "${GREEN}   ✅ Redis is ready${NC}"
else
    echo -e "${RED}   ❌ Redis is not ready${NC}"
    exit 1
fi
echo ""

# Run migrations
echo "6️⃣  Running database migrations..."
docker-compose exec -T api alembic upgrade head
echo -e "${GREEN}✅ Migrations completed${NC}"
echo ""

# Test health endpoint
echo "7️⃣  Testing API health..."
sleep 3
HEALTH_RESPONSE=$(curl -s http://localhost:8000/api/v1/health || echo "failed")
if echo "$HEALTH_RESPONSE" | grep -q "healthy"; then
    echo -e "${GREEN}✅ API is healthy${NC}"
else
    echo -e "${YELLOW}⚠️  API health check returned unexpected response${NC}"
    echo "   Response: $HEALTH_RESPONSE"
fi
echo ""

# Success message
echo "================================================================"
echo -e "${GREEN}🎉 Setup Complete!${NC}"
echo "================================================================"
echo ""
echo "Your Sonoro development environment is ready!"
echo ""
echo "📚 Quick Links:"
echo "   • API Documentation: http://localhost:8000/docs"
echo "   • Health Check:      http://localhost:8000/api/v1/health"
echo "   • ReDoc:             http://localhost:8000/redoc"
echo ""
echo "🔧 Useful Commands:"
echo "   • View logs:         make logs"
echo "   • Stop services:     make down"
echo "   • Run tests:         make test"
echo "   • Open DB shell:     make shell-db"
echo "   • Open Redis CLI:    make redis-cli"
echo ""
echo "📖 For more information, see:"
echo "   • README.md - Project overview"
echo "   • SETUP.md  - Detailed setup guide"
echo ""
echo "Happy coding! 🚀"
