# ── Stage 1: builder — compile wheels so the runtime image stays slim ─────────
FROM python:3.11-slim AS builder

WORKDIR /build

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
# Resolve full dependency graph (no --no-deps) so every transitive wheel
# (including PyMuPDFb, which PyMuPDF 1.23+ delegates its binary layer to)
# is collected.  The builder stage has internet; the base stage does not.
RUN pip install --upgrade pip && \
    pip wheel --wheel-dir /wheels -r requirements.txt


# ── Stage 2: base — shared runtime layer ─────────────────────────────────────
FROM python:3.11-slim AS base

LABEL maintainer="Sonoro Team"
LABEL description="FastAPI application container for Sonoro"

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ffmpeg \
    libpq5 \
    libmagic1 \
    && rm -rf /var/lib/apt/lists/*

# Non-root user for production security
RUN groupadd --gid 1001 sonoro && \
    useradd --uid 1001 --gid sonoro --shell /bin/bash --create-home sonoro

WORKDIR /app

# Install pre-built wheels — no compiler, no network, fully reproducible
COPY --from=builder /wheels /wheels
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-index --find-links /wheels -r /tmp/requirements.txt && \
    rm -rf /wheels /tmp/requirements.txt

HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8000/api/v1/health || exit 1

EXPOSE 8000


# ── Stage 3: dev — hot-reload for local development ──────────────────────────
FROM base AS dev

# Dev runs as root so bind-mounted source edits work without permission issues
COPY . .

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]


# ── Stage 4: production — gunicorn + non-root user ───────────────────────────
FROM base AS production

COPY --chown=sonoro:sonoro . .

USER sonoro

CMD ["gunicorn", "app.main:app", \
     "--worker-class", "uvicorn.workers.UvicornWorker", \
     "--workers", "4", \
     "--bind", "0.0.0.0:8000", \
     "--timeout", "120", \
     "--graceful-timeout", "30", \
     "--access-logfile", "-", \
     "--error-logfile", "-"]
