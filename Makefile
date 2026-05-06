.PHONY: help dev down logs logs-api logs-worker migrate migration shell-api shell-db redis-cli test lint format clean build restart deploy-block-6b test-block-6b

help:
	@echo "Sonoro - Available Commands"
	@echo "============================"
	@echo ""
	@echo "Development:"
	@echo "  make dev          - Start all services (detached mode)"
	@echo "  make down         - Stop all services"
	@echo "  make restart      - Restart all services"
	@echo "  make build        - Rebuild Docker images"
	@echo ""
	@echo "Logs:"
	@echo "  make logs         - View all logs"
	@echo "  make logs-api     - View API logs"
	@echo "  make logs-worker  - View worker logs"
	@echo ""
	@echo "Database:"
	@echo "  make migrate      - Run database migrations"
	@echo "  make migration    - Create new migration (use: make migration msg='description')"
	@echo "  make shell-db     - Open PostgreSQL shell"
	@echo ""
	@echo "Shell Access:"
	@echo "  make shell-api    - Python shell in API container"
	@echo "  make redis-cli    - Redis CLI"
	@echo ""
	@echo "Testing & Quality:"
	@echo "  make test         - Run tests"
	@echo "  make lint         - Run linters"
	@echo "  make format       - Format code"
	@echo ""
	@echo "BLOCK 6B:"
	@echo "  make deploy-block-6b  - Run BLOCK 6B deployment checks"
	@echo "  make test-block-6b    - Test chapter detection (PDF=path/to/file.pdf)"
	@echo ""
	@echo "Cleanup:"
	@echo "  make clean        - Remove containers and volumes"
	@echo ""

# Development
dev:
	docker-compose up -d
	@echo "✅ Services started!"
	@echo "   API: http://localhost:8000"
	@echo "   Docs: http://localhost:8000/docs"
	@echo "   Health: http://localhost:8000/api/v1/health"

down:
	docker-compose down

restart:
	docker-compose restart

build:
	docker-compose build

# Logs
logs:
	docker-compose logs -f

logs-api:
	docker-compose logs -f api

logs-worker:
	docker-compose logs -f worker

# Database
migrate:
	docker-compose exec api alembic upgrade head

migration:
	@if [ -z "$(msg)" ]; then \
		echo "Error: Please provide a migration message"; \
		echo "Usage: make migration msg='add_user_table'"; \
		exit 1; \
	fi
	docker-compose exec api alembic revision --autogenerate -m "$(msg)"

shell-db:
	docker-compose exec postgres psql -U sonoro -d sonoro

# Shell access
shell-api:
	docker-compose exec api python

redis-cli:
	docker-compose exec redis redis-cli

# Testing
test:
	docker-compose exec api pytest -v

test-cov:
	docker-compose exec api pytest --cov=app --cov-report=html --cov-report=term

# BLOCK 6B: Chapter Detection & Text Segmentation
deploy-block-6b:
	@echo "🚀 Running BLOCK 6B deployment checks..."
	@./deploy_block_6b.sh

test-block-6b:
	@if [ -z "$(PDF)" ]; then \
		echo "❌ Error: Please provide a PDF file path"; \
		echo "Usage: make test-block-6b PDF=/path/to/book.pdf"; \
		exit 1; \
	fi
	@echo "🧪 Testing BLOCK 6B with PDF: $(PDF)"
	@python test_block_6b.py $(PDF)

# Code quality
lint:
	docker-compose exec api ruff check app/

format:
	docker-compose exec api black app/
	docker-compose exec api ruff check --fix app/

# Cleanup
clean:
	docker-compose down -v
	@echo "✅ Cleaned up all containers and volumes"

# First-time setup helper
setup:
	@echo "🚀 Setting up Sonoro development environment..."
	@if [ ! -f .env ]; then \
		cp .env.example .env; \
		echo "✅ Created .env file from .env.example"; \
		echo "⚠️  Please review and update .env with your configuration"; \
	else \
		echo "✅ .env file already exists"; \
	fi
	@echo ""
	@echo "Building Docker images..."
	@make build
	@echo ""
	@echo "Starting services..."
	@make dev
	@echo ""
	@echo "Waiting for database to be ready..."
	@sleep 5
	@echo ""
	@echo "Running migrations..."
	@make migrate
	@echo ""
	@echo "✅ Setup complete!"
	@echo ""
	@echo "🎉 Your development environment is ready!"
	@echo "   Visit: http://localhost:8000/docs"
