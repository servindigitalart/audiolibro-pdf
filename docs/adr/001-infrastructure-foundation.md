# Architecture Decision Record: Phase 0 Infrastructure Foundation

**Status:** Accepted  
**Date:** 2026-02-11  
**Decision Makers:** Chief Technical Architect

## Context

Sonoro requires a production-grade infrastructure foundation that supports:
- Local development with Docker
- VPS deployment readiness
- Async database operations
- Message queue infrastructure
- Scalability without premature optimization

## Decision

We will implement a Docker-based infrastructure using:

### Core Technologies
- **Python 3.11+**: Modern type hints, performance improvements
- **FastAPI**: High-performance async API framework
- **PostgreSQL 16**: Robust relational database with async support
- **Redis 7**: Cache and message broker
- **SQLAlchemy 2.0**: Modern async ORM
- **Alembic**: Database migration management

### Architecture Principles
1. **Async-first**: All I/O operations use async/await
2. **Type-safe**: Pydantic for validation, type hints throughout
3. **Environment-based config**: No hardcoded values
4. **Separation of concerns**: Clean layering (routes → services → models)
5. **Health monitoring**: Comprehensive health checks for all dependencies

### Deployment Strategy
- **Development**: Docker Compose with hot-reload
- **Production**: Same Docker Compose, but with Gunicorn workers
- **VPS-ready**: All configuration supports single-server deployment

## Consequences

### Positive
- ✅ Production-grade from day one
- ✅ Easy local development setup
- ✅ Type safety reduces bugs
- ✅ Async improves performance under load
- ✅ VPS deployment without code changes
- ✅ Clear path to scaling (add more workers/containers)

### Negative
- ❌ More complex than synchronous approach
- ❌ Requires Docker knowledge
- ❌ Async debugging can be harder

### Neutral
- 🔄 Future Celery integration is straightforward
- 🔄 Can add Nginx reverse proxy easily
- 🔄 Database migrations are version-controlled

## Alternatives Considered

1. **Synchronous SQLAlchemy**: Rejected - limits scalability
2. **MongoDB**: Rejected - relational data model fits better
3. **Django**: Rejected - FastAPI is more modern and performant
4. **Separate dev/prod setups**: Rejected - increases maintenance

## Implementation

See `README.md` for setup instructions.

Key files:
- `docker-compose.yml`: Development environment
- `infra/docker-compose.prod.yml`: Production environment
- `app/core/config.py`: Configuration management
- `app/db/session.py`: Async database session
- `app/main.py`: Application entrypoint

## Validation

Success criteria:
- [x] `make dev` starts all services
- [x] Health endpoint verifies DB and Redis
- [x] Alembic migrations work
- [x] Tests pass
- [x] No hardcoded secrets
