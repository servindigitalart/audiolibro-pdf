# Sonoro - Professional Document-to-Audiobook SaaS

A production-grade platform for converting long-form documents into high-quality audiobooks with intelligent chapter segmentation.

## 🎯 Latest: BLOCK 8A - Frontend Foundation

**Version**: 1.0.0 (Frontend) | **Status**: ✅ Production Ready

### What's New
- ⚛️ **Next.js 14**: Modern React framework with App Router
- 🔐 **Complete Auth**: Login, register, JWT management, protected routes
- 🎨 **Shadcn UI**: Beautiful, responsive component library
- 🌓 **Dark Mode**: Theme toggle with system preference detection
- 🔄 **API Client**: Axios with JWT interceptor and auto-refresh
- 📱 **Responsive**: Mobile-first design with sidebar navigation

**Quick Start**: See [`BLOCK_8A_QUICK_START.md`](BLOCK_8A_QUICK_START.md)  
**Full Docs**: [`docs/BLOCK_8A_COMPLETE.md`](docs/BLOCK_8A_COMPLETE.md)

## 💳 Previous: BLOCK 7 - Billing & Monetization Layer

**Version**: 0.9.0 | **Status**: ✅ Ready for Production

### What's New
- 💳 **Stripe Integration**: Complete subscription & payment processing
- 🔐 **Webhook Security**: Production-grade signature verification
- 💰 **Revenue Metrics**: Track MRR, churn, conversions in Prometheus
- 🔄 **Subscription Management**: Create, update, cancel, reactivate
- 🎟️ **Customer Portal**: Self-service billing management
- 📊 **13 New Metrics**: Revenue, active subs, trial conversions, payment failures

**Quick Deploy**: See [`BLOCK_7_SUMMARY.md`](BLOCK_7_SUMMARY.md)  
**Full Docs**: [`docs/BLOCK_7_COMPLETE.md`](docs/BLOCK_7_COMPLETE.md)

## 🎵 Previous: BLOCK 6C - Audio Assembly & Output Layer

**Version**: 0.8.0 | **Status**: ✅ Ready for Deployment

### What's New
- 🎵 **Audio Assembly**: Concatenate chapter MP3s into single audiobook
- 📊 **Loudness Normalization**: Consistent -20.0 dBFS across all audiobooks
- ✂️ **Silence Trimming**: Remove dead air from start/end
- 🏷️ **ID3 Metadata**: Professional tags (title, author, language, date)
- 📈 **5 New Metrics**: Assembly time, file size, normalization performance
- 💾 **Final Storage**: Track audio path, duration, and file size

**Quick Deploy**: See [`BLOCK_6C_SUMMARY.md`](BLOCK_6C_SUMMARY.md)  
**Full Docs**: [`docs/BLOCK_6C_COMPLETE.md`](docs/BLOCK_6C_COMPLETE.md)

## 🎯 Previous: BLOCK 6B - Chapter Detection & Text Segmentation

**Version**: 0.7.0

### Features
- 🔍 **Three-Strategy Chapter Detection**: TOC extraction, heuristic patterns, structural analysis
- 🌍 **Multi-Language Support**: EN, ES, FR, DE chapter patterns
- 🧮 **Confidence Fusion**: Intelligent scoring with method priority weighting
- ✂️ **Smart Text Segmentation**: 4000-char chunks with sentence boundary detection
- 📊 **5 Prometheus Metrics**: Track detection rates and performance
- 🗄️ **Chapters Database**: Full persistence with 6 optimized indexes

**Deploy**: `./deploy_block_6b.sh`  
**Docs**: [`BLOCK_6B_DEPLOY.md`](BLOCK_6B_DEPLOY.md)

// ...existing code...nal Document-to-Audiobook SaaS

A production-grade platform for converting long-form documents into high-quality audiobooks with intelligent chapter segmentation.

## 🎯 Latest: BLOCK 6B - Chapter Detection & Text Segmentation

**Version**: 0.7.0 | **Status**: ✅ Ready for Deployment

### What's New
- 🔍 **Three-Strategy Chapter Detection**: TOC extraction, heuristic patterns, structural analysis
- 🌍 **Multi-Language Support**: EN, ES, FR, DE chapter patterns
- 🧮 **Confidence Fusion**: Intelligent scoring with method priority weighting
- ✂️ **Smart Text Segmentation**: 4000-char chunks with sentence boundary detection
- 📊 **5 New Prometheus Metrics**: Track detection rates and performance
- 🗄️ **Chapters Database**: Full persistence with 6 optimized indexes

**Quick Deploy**: `./deploy_block_6b.sh`  
**Full Docs**: [`BLOCK_6B_DEPLOY.md`](BLOCK_6B_DEPLOY.md)

## 🚀 Quick Start

### Prerequisites

- Docker & Docker Compose
- Python 3.11+ (for local development without Docker)
- Make (should be pre-installed on macOS)

### Setup

1. **Clone and setup environment:**
   ```bash
   git clone <repository-url>
   cd audiolibro-pdf
   cp .env.example .env
   ```

2. **Start development environment:**
   ```bash
   make dev
   ```

3. **Run database migrations:**
   ```bash
   make migrate
   ```

4. **Access the application:**
   - API: http://localhost:8000
   - API Docs: http://localhost:8000/docs
   - Health Check: http://localhost:8000/api/v1/health

## 📋 Available Commands

```bash
make dev          # Start all services (API, PostgreSQL, Redis)
make down         # Stop all services
make logs         # View logs from all services
make logs-api     # View API logs only
make migrate      # Run database migrations
make migration    # Create a new migration (msg="description")
make shell-api    # Open Python shell in API container
make shell-db     # Open PostgreSQL shell
make redis-cli    # Open Redis CLI
make test         # Run tests
make lint         # Run linters
make format       # Format code
make clean        # Clean up containers and volumes
```

## 🏗️ Architecture

```
┌─────────────────────────────────────┐
│         Nginx (Future)              │
│         Port 80/443                 │
└─────────────┬───────────────────────┘
              │
┌─────────────▼───────────────────────┐
│         FastAPI Application          │
│         Port 8000                    │
│    (Uvicorn in dev, Gunicorn prod)  │
└─────┬───────────────────┬───────────┘
      │                   │
┌─────▼─────┐      ┌─────▼─────┐
│PostgreSQL │      │   Redis   │
│  Port     │      │   Port    │
│  5432     │      │   6379    │
└───────────┘      └───────────┘
```

## 📁 Project Structure

```
services/
├── api/                    # FastAPI application
│   ├── app/
│   │   ├── core/          # Core functionality (config, logging, etc.)
│   │   ├── db/            # Database models and session
│   │   ├── routers/       # API endpoints
│   │   ├── schemas/       # Pydantic models
│   │   ├── services/      # Business logic
│   │   └── main.py        # Application entry point
│   ├── alembic/           # Database migrations
│   └── tests/             # API tests
│
└── worker/                # Background workers (future)
    └── worker/
        └── tasks/

infra/
├── docker/                # Dockerfiles
├── nginx/                 # Nginx configuration
└── scripts/               # Deployment scripts
```

## 🔧 Development

### Local Development (with Docker)

```bash
# Start services
make dev

# View logs
make logs-api

# Run migrations
make migrate

# Access database
make shell-db
```

### Creating Database Migrations

```bash
# Auto-generate migration from model changes
make migration msg="add_user_table"

# Apply migrations
make migrate

# View migration history
docker-compose exec api alembic history
```

## 🧪 Testing

```bash
# Run all tests
make test

# Run specific test file
docker-compose exec api pytest tests/test_health.py -v
```

## 📊 Database

PostgreSQL 16 with async support via `asyncpg`.

**Connection details (development):**
- Host: localhost
- Port: 5432
- Database: sonoro
- User: sonoro
- Password: sonoro_dev_password

## 🔐 Security

- Never commit `.env` file
- Rotate `SECRET_KEY` in production
- Use strong passwords for database
- Enable SSL/TLS in production
- Follow principle of least privilege

## 📝 Environment Variables

See `.env.example` for all available configuration options.

Key variables:
- `DATABASE_URL`: PostgreSQL connection string
- `REDIS_URL`: Redis connection string
- `SECRET_KEY`: Application secret key
- `DEBUG`: Enable/disable debug mode

## 🚢 Deployment

### Production Deployment (DigitalOcean VPS)

```bash
# On VPS
git clone <repository-url>
cd audiolibro-pdf
cp .env.example .env
# Edit .env with production values
docker-compose -f infra/docker-compose.prod.yml up -d
```

## 📖 API Documentation

Interactive API documentation available at:
- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

## 🤝 Contributing

1. Create a feature branch
2. Make your changes
3. Run tests and linters
4. Submit a pull request

## 📄 License

Proprietary - All rights reserved

## 🆘 Support

For issues and questions, please open a GitHub issue.
