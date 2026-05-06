# 🚀 SONORO - BLOCK 1: INFRASTRUCTURE FOUNDATION
## Complete Setup Guide

---

## ✅ DELIVERABLES COMPLETED

### 1. **Project Structure** ✓
- Complete folder hierarchy for API and Worker services
- Separation of concerns (core, db, routers, schemas, services)
- Infrastructure configuration in `infra/`
- Documentation in `docs/`

### 2. **Docker Infrastructure** ✓
- PostgreSQL 16 container with health checks
- Redis 7 container with persistence
- API container with FastAPI + Uvicorn (dev) / Gunicorn (prod)
- Worker container (ready for Celery)
- Docker Compose for development and production
- Persistent volumes for data
- Internal networking

### 3. **FastAPI Application** ✓
- Production-grade application structure
- Type-safe configuration with Pydantic Settings
- Structured logging (JSON for prod, colored for dev)
- Async database session management
- Redis connection wrapper
- Health check endpoint with dependency verification
- CORS and GZip middleware
- Global exception handling
- Lifespan events for startup/shutdown

### 4. **Database Layer** ✓
- SQLAlchemy 2.0 async ORM
- Declarative Base model
- Example User model
- Alembic migration system configured
- Connection pooling with health checks
- Environment-based configuration

### 5. **Developer Tools** ✓
- Comprehensive Makefile with 15+ commands
- Testing setup with pytest and pytest-asyncio
- Code quality tools (Black, Ruff, Mypy)
- Example tests for health endpoint
- Environment variable template

### 6. **Documentation** ✓
- Detailed README.md
- Architecture Decision Record
- Inline code documentation
- Setup instructions

---

## 📋 PREREQUISITES

Before starting, ensure you have:

1. **Docker Desktop** installed and running
   - Download: https://www.docker.com/products/docker-desktop
   - Verify: `docker --version` and `docker-compose --version`

2. **Make** (pre-installed on macOS)
   - Verify: `make --version`

3. **Git** (for version control)
   - Verify: `git --version`

---

## 🏁 QUICK START GUIDE

### Step 1: Start Docker Desktop
```bash
# Open Docker Desktop application
# Wait for Docker daemon to start (whale icon in menu bar)
```

### Step 2: Setup Environment
```bash
# Navigate to project
cd /Users/servinemilio/audiolibro-pdf

# Environment file already created (.env)
# Review and modify if needed:
cat .env
```

### Step 3: Build and Start Services
```bash
# Build Docker images
make build

# Start all services (detached mode)
make dev

# Check logs to ensure everything started
make logs
```

### Step 4: Run Database Migrations
```bash
# Create initial migration
make migration msg="initial_setup"

# Apply migrations
make migrate
```

### Step 5: Verify Installation
```bash
# Test health endpoint
curl http://localhost:8000/api/v1/health

# Open API documentation in browser
open http://localhost:8000/docs
```

---

## 🔧 AVAILABLE COMMANDS

### Development
```bash
make dev          # Start all services
make down         # Stop all services
make restart      # Restart all services
make build        # Rebuild Docker images
```

### Logs
```bash
make logs         # View all logs (follow mode)
make logs-api     # View API logs only
make logs-worker  # View worker logs only
```

### Database
```bash
make migrate                        # Run migrations
make migration msg="description"    # Create new migration
make shell-db                       # Open PostgreSQL shell
```

### Development Tools
```bash
make shell-api    # Python shell in API container
make redis-cli    # Redis CLI
make test         # Run tests
make lint         # Run linters
make format       # Format code
```

### Cleanup
```bash
make clean        # Stop and remove containers + volumes
```

---

## 📁 PROJECT STRUCTURE

```
sonoro/
├── .env                          # Environment variables (not in git)
├── .env.example                  # Environment template
├── .gitignore                    # Git ignore rules
├── docker-compose.yml            # Development environment
├── Makefile                      # Command shortcuts
├── README.md                     # Main documentation
│
├── docs/
│   └── adr/                      # Architecture Decision Records
│       └── 001-infrastructure-foundation.md
│
├── infra/
│   ├── docker-compose.prod.yml   # Production environment
│   ├── docker/
│   │   ├── api.Dockerfile        # API container image
│   │   └── worker.Dockerfile     # Worker container image
│   ├── nginx/                    # Nginx config (future)
│   └── scripts/                  # Deployment scripts (future)
│
└── services/
    ├── api/                      # FastAPI Application
    │   ├── requirements.txt      # Python dependencies
    │   ├── pyproject.toml        # Project configuration
    │   ├── alembic.ini           # Alembic configuration
    │   ├── alembic/              # Database migrations
    │   │   ├── env.py            # Migration environment
    │   │   ├── script.py.mako    # Migration template
    │   │   └── versions/         # Migration files
    │   ├── app/
    │   │   ├── main.py           # Application entry point
    │   │   ├── core/             # Core functionality
    │   │   │   ├── config.py     # Configuration management
    │   │   │   ├── logging_config.py  # Logging setup
    │   │   │   └── redis.py      # Redis client
    │   │   ├── db/               # Database layer
    │   │   │   ├── session.py    # DB session management
    │   │   │   └── models/       # SQLAlchemy models
    │   │   │       └── user.py   # User model (example)
    │   │   ├── routers/          # API endpoints
    │   │   │   └── health.py     # Health check routes
    │   │   ├── schemas/          # Pydantic models (future)
    │   │   ├── services/         # Business logic (future)
    │   │   └── utils/            # Utilities (future)
    │   └── tests/                # API tests
    │       ├── conftest.py       # Test configuration
    │       └── test_health.py    # Health endpoint tests
    │
    └── worker/                   # Background Worker Service
        ├── requirements.txt      # Python dependencies
        └── worker/
            ├── __init__.py       # Worker initialization
            └── tasks/            # Celery tasks (future)
```

---

## 🔍 TESTING THE SETUP

### 1. Check Service Health
```bash
# All services should be running
docker-compose ps

# Expected output:
# NAME                  STATUS
# sonoro-api           Up (healthy)
# sonoro-postgres      Up (healthy)
# sonoro-redis         Up (healthy)
# sonoro-worker        Up
```

### 2. Test Database Connection
```bash
# Connect to PostgreSQL
make shell-db

# Inside psql:
\dt              # List tables (should show 'users' after migration)
\q               # Exit
```

### 3. Test Redis Connection
```bash
# Connect to Redis
make redis-cli

# Inside redis-cli:
PING             # Should return PONG
SET test "hello"
GET test
QUIT
```

### 4. Test API Endpoints
```bash
# Health check (comprehensive)
curl http://localhost:8000/api/v1/health | jq

# Expected response:
# {
#   "status": "healthy",
#   "environment": "development",
#   "debug": true,
#   "services": {
#     "database": {
#       "status": "healthy",
#       "type": "postgresql"
#     },
#     "redis": {
#       "status": "healthy",
#       "type": "redis"
#     }
#   }
# }

# Root endpoint
curl http://localhost:8000/api/v1/ | jq
```

### 5. Run Tests
```bash
# Run all tests
make test

# Run with coverage
docker-compose exec api pytest --cov=app --cov-report=term
```

---

## 🐛 TROUBLESHOOTING

### Issue: Docker daemon not running
```bash
# Solution: Start Docker Desktop application
# Wait for the whale icon to appear in the menu bar
```

### Issue: Port already in use
```bash
# Check what's using port 8000
lsof -i :8000

# Stop the conflicting process or change port in .env
# API_PORT=8001
```

### Issue: Database connection failed
```bash
# Check PostgreSQL logs
make logs | grep postgres

# Restart PostgreSQL
docker-compose restart postgres

# Verify health
docker-compose exec postgres pg_isready -U sonoro
```

### Issue: Redis connection failed
```bash
# Check Redis logs
make logs | grep redis

# Restart Redis
docker-compose restart redis

# Test connection
docker-compose exec redis redis-cli ping
```

### Issue: Migration fails
```bash
# Check database is accessible
make shell-db

# Drop and recreate database (⚠️ DESTROYS DATA)
docker-compose down -v
docker-compose up -d postgres
sleep 5
make migrate
```

### Issue: API won't start
```bash
# Check detailed logs
docker-compose logs api

# Common causes:
# 1. Syntax error in Python code
# 2. Missing dependency in requirements.txt
# 3. Database not ready yet (wait 10s and try again)

# Rebuild API container
docker-compose build api
docker-compose up -d api
```

---

## 🔐 SECURITY NOTES

### Development Environment
- Default passwords are used (acceptable for local dev)
- CORS allows all origins (acceptable for local dev)
- Debug mode is enabled (verbose errors)

### Production Environment
⚠️ **Before deploying to production:**

1. **Change all passwords**
   ```bash
   # Generate secure passwords
   openssl rand -base64 32
   ```

2. **Update SECRET_KEY**
   ```bash
   # Generate new secret key
   openssl rand -hex 32
   ```

3. **Configure CORS properly**
   ```bash
   # Only allow your frontend domain
   API_CORS_ORIGINS=https://yourdomain.com
   ```

4. **Disable debug mode**
   ```bash
   DEBUG=false
   ```

5. **Use environment-specific .env**
   ```bash
   # Never commit production .env to git
   ```

---

## 📊 HEALTH CHECK ENDPOINTS

### `/api/v1/health` (Comprehensive)
Returns detailed health status of all services:
- Database connection
- Redis connection
- Application status

**Response (Healthy):**
```json
{
  "status": "healthy",
  "environment": "development",
  "debug": true,
  "services": {
    "database": {
      "status": "healthy",
      "type": "postgresql"
    },
    "redis": {
      "status": "healthy",
      "type": "redis"
    }
  }
}
```

**Response (Unhealthy):**
Returns HTTP 503 with error details.

### `/api/v1/` (Quick Check)
Simple status check without dependency verification.

---

## 🎯 NEXT STEPS (FUTURE PHASES)

This infrastructure foundation is ready for:

### Phase 1: Authentication
- User registration and login
- JWT token management
- Password hashing
- Email verification

### Phase 2: Document Upload
- PDF file upload
- S3 storage integration
- File validation
- Metadata extraction

### Phase 3: Chapter Detection
- Multi-stage chapter detection
- TOC extraction
- Heuristic pattern matching
- Confidence scoring

### Phase 4: TTS Integration
- Multi-provider TTS
- Fragment caching
- Audio generation pipeline
- Cost tracking

### Phase 5: Audio Player
- Web-based player
- Chapter navigation
- Progress tracking
- Download functionality

---

## 📞 SUPPORT

For issues or questions:
1. Check this SETUP.md first
2. Review logs with `make logs`
3. Check Docker is running
4. Verify all services are healthy

---

## ✅ SUCCESS CRITERIA

Your infrastructure is correctly set up if:

- ✅ `docker-compose ps` shows all services running
- ✅ `curl http://localhost:8000/api/v1/health` returns `"status": "healthy"`
- ✅ `make test` passes all tests
- ✅ API documentation accessible at http://localhost:8000/docs
- ✅ Database migrations run successfully with `make migrate`
- ✅ No hardcoded secrets in codebase

---

**Infrastructure Foundation: COMPLETE ✓**

Ready for Phase 1 implementation.
