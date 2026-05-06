FROM python:3.11-slim

LABEL maintainer="Sonoro Team"
LABEL description="Celery worker container for Sonoro (BLOCK 5B)"

# Set working directory
WORKDIR /app

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONPATH=/app/api:/app/worker

# Install system dependencies
# BLOCK 6C: Added ffmpeg for audio processing
RUN apt-get update && apt-get install -y \
    curl \
    libmagic1 \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements from both worker and api
COPY requirements.txt /app/worker/requirements.txt
RUN pip install --upgrade pip && \
    pip install -r /app/worker/requirements.txt

# Copy application code (handled by volume mounts in docker-compose)
# This allows for hot-reloading during development

# Health check
HEALTHCHECK --interval=30s --timeout=10s --retries=3 --start-period=10s \
    CMD celery -A app.celery_app inspect ping || exit 1

# Default command for Celery worker
CMD ["celery", "-A", "app.celery_app", "worker", "--loglevel=info", "--concurrency=2"]
