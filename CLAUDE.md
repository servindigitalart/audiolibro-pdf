# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Sonoro — a PDF/document-to-audiobook SaaS. Three deployables:

| Path | Stack | Deployed to |
|---|---|---|
| `sonoro/` | Astro 4 SSR + React islands + Tailwind | Vercel (`@astrojs/vercel` serverless) |
| `services/api/` | FastAPI (Python 3.11), SQLAlchemy async, Alembic | Railway (`start.sh` → uvicorn) |
| `services/api/` (same code, worker entrypoint) | Celery worker | Railway (`start-worker.sh`) |

Backed by PostgreSQL, Redis (Celery broker + cache), S3-compatible object storage (Cloudflare R2 in prod), Google Cloud TTS, and Stripe.

### Directories that are NOT live code

- **`frontend/`** — a legacy Next.js 14 app. `sonoro/` replaced it (`sonoro/.vercel/` holds the real Vercel project; `frontend/` has no deploy config and no CI job). Work has occasionally landed there by mistake. Do not edit it unless the user explicitly asks for it.
- **`src/lib/api/base.ts`** at the repo root — stray leftover, not imported by anything.
- **`BLOCK_*.md`, `NEXT_STEPS.md`, `START_HERE.md`, `docs/BLOCK_*`, `deploy_block_*.sh`** — historical build-log snapshots from earlier development phases. They are point-in-time and frequently stale.
- **`README.md`** — stale (still describes the Next.js `frontend/` as current). Prefer this file and the code.

## Commands

### Backend (`services/api/`)

Local, no Docker — `conftest.py` at the API root injects the env vars pydantic `Settings` requires at import time, so unit tests run with nothing else running:

```bash
cd services/api
pytest tests/unit/ -m unit                        # fast, no DB / no network
pytest tests/unit/test_cover_service.py -v        # single file
pytest tests/unit/test_cover_service.py::test_name -v
```

Integration tests need PostgreSQL with a `sonoro_test` database (schema is created once per session by `tests/conftest.py`; each test runs in a rolled-back transaction). Redis is faked via an autouse monkeypatch:

```bash
pytest tests/test_auth.py tests/test_health.py tests/integration/ -m integration
```

`pytest.ini` **excludes** four suites from the default run. Run them explicitly:

```bash
pytest tests/performance/ -m performance -s
pytest tests/chaos/       -m chaos -s
pytest tests/test_stripe/ -m stripe -s
pytest tests/test_pricing/ -m pricing -s
```

Lint/format (line length 100):

```bash
ruff check app/ && black app/
```

Docker-based dev (postgres + redis + api + worker + prometheus + grafana) via the root `Makefile`:

```bash
make dev            # docker-compose up -d; API on :8000, docs at /docs
make migrate        # alembic upgrade head inside the api container
make migration msg="add_x"
make logs-api / make logs-worker / make shell-db / make test
```

Migrations are numbered sequentially (`001_…` through `030_…`); head is `030`. `start.sh` runs `alembic upgrade head` on every Railway boot, so a deploy applies migrations automatically.

CI (`.github/workflows/ci.yml`) runs unit tests, then integration tests with `--cov-fail-under=60`, then the full suite with `--cov-fail-under=70`. CI only covers `services/api` — no frontend job exists.

### Frontend (`sonoro/`)

```bash
cd sonoro
npm run dev            # astro dev
npm run build          # astro build && node scripts/patch-runtime.mjs
npm run test           # vitest run (jsdom, src/tests/*)
npm run test -- src/tests/mini-player.test.tsx    # single file
npm run check          # astro check (TS + .astro diagnostics)
```

`scripts/patch-runtime.mjs` rewrites `nodejs18.x` → `nodejs20.x` in the generated `.vc-config.json`; it must stay part of `build` or Vercel rejects the deploy. Node 20 (`.node-version`).

`npm run lint` is declared but there is no ESLint config in `sonoro/` — it will fail. Use `npm run check` instead.

## Architecture

### Frontend data flow (three distinct API paths — pick the right one)

1. **`src/middleware.ts`** reads the `access_token` cookie, guards `/dashboard` + `/onboarding`, bounces authed users off `/login`/`/register`, and stashes the token on `Astro.locals.token`.
2. **`src/lib/api/server.ts`** — SSR only, called from `.astro` frontmatter with `locals.token`. It also **normalizes** backend payloads (e.g. `processing_status` + `upload_status` → a single `status`, `display_title`/`original_filename` → `title`). Pages get the lean `Document`/`AccountOverview` shapes in `src/lib/api/types.ts`, not raw backend JSON.
3. **`src/lib/api/client.ts`** — axios instance for React islands. Injects the JWT from the `access_token` cookie, coalesces concurrent refreshes into one `/auth/refresh` call, retries once on 401, then redirects to `/login`. Cookies are deliberately **not** httpOnly so this interceptor can rotate them client-side.
4. **`src/pages/api/**`** — Astro server endpoints used for mutations that need the cookie plus a redirect (logout, document delete/retry, Google OAuth callback). They proxy straight to FastAPI.

State is nanostores (`src/stores/auth.ts`); there is no React Router — navigation is Astro pages. Audio playback state lives entirely in `src/hooks/useAudioPlayer.ts`, with `components/dashboard/AudioPlayer.tsx` as pure UI over it.

### Backend layout (`services/api/app/`)

`main.py` composes everything: middleware order is RequestID → Metrics → CORS → GZip → BillingEnforcement, then ~20 routers are mounted. Domain packages, not layers:

- `routers/` — HTTP surface. `documents.py` is the largest (upload, status, chapters, retry/cancel, metadata edit, cover suggestions/select, audio URLs).
- `services/` — business logic: `document_service`, `processing_service`, `storage_service` (S3-compatible), `preflight_service`, `tts/` (Google provider + narration styles), `audio/` (assembler, normalizer, ID3 `metadata.py`), `document_structure/` (chapter detection engine + extractors + fusion + segmenter), `language/`.
- `financial/` — `quota/`, `cost/` (per-action cost tracking + caps), `abuse/`, `rate_limit/`. Cost caps and emergency shutdown are config-driven.
- `billing/` + `routers/billing.py` — Stripe. `pricing/` — plan tiers and unit economics.
- `metadata/` — Book Intelligence: local PDF extraction + Google Books/Open Library providers + matcher/scorer + `cover_service.py` (cover candidates, SSRF domain allowlist).
- `analytics/`, `affiliate/`, `monitoring/` (Prometheus metrics + Sentry), `observability/`.

### Processing pipeline

Upload creates a `Document` + `ProcessingJob`, then enqueues `process_document_job` (`app/tasks/processing.py`). Celery routes by numeric priority into `high_priority` (1–3) / `normal` (4–7, the upload default) / `low_priority` (8–10); the worker consumes all three.

Stages, written to `job.current_stage` / `job.progress_percentage` and mirrored onto `document.processing_status` — **this pair is the contract the frontend polls for progress**:

`analyzing` (5%) → `chapter_detection` (15%) → `tts_generation` → `final_assembly` → `upload_finalize` → COMPLETED

Non-obvious conventions in the worker, all deliberate — preserve them:

- **Heavy imports are deferred inside `_process_job_async`.** Module-level imports of ffmpeg/pydub/google-cloud-tts would crash worker startup silently instead of surfacing as a task failure.
- **A fresh async engine is created per task** inside `asyncio.run` — a pool inherited across `fork()` raises "Future attached to a different loop".
- **Cancellation** is cooperative: `_check_cancelled()` re-reads the job between stages and raises `_JobCancelledError` when the API set status to CANCELLED.
- **Deterministic failures** (`_DETERMINISTIC_ERRORS`) are not retried — the job is left FAILED and the Celery task returns normally.
- **The PDF is downloaded from object storage by key**, never read from a local path. API and worker are separate containers/hosts; `STORAGE_BACKEND=local` therefore only works when both run on one filesystem.
- Text is chunked to ≤4500 chars for Google TTS (hard limit 5000), splitting on paragraph → sentence → hard cut.
- Chapter MP3s are concatenated with the **ffmpeg concat demuxer** (no audio in RAM), then loudness-normalized and ID3-tagged (cover art embedded from `cover_object_key`).

### Config and flags

`app/core/config.py` is a pydantic `BaseSettings` with required fields validated at import time: `SECRET_KEY`, `DATABASE_URL`, `DATABASE_ASYNC_URL`, `REDIS_URL`, `CELERY_BROKER_URL`, `CELERY_RESULT_BACKEND`. Importing any `app.*` module without them raises — hence the root `conftest.py` and the env blocks in the CI workflows.

All `feature_*` flags (upload, TTS, Stripe billing, rate limiting, abuse detection, billing enforcement) **default to False**. `STRIPE_MODE` defaults to `mock`; `real` requires the secret key, webhook secret, and all six price IDs.

### Database conventions

Enum columns are stored as **VARCHAR, not native PG enums** — `Enum(X, native_enum=False, values_callable=lambda obj: [e.value for e in obj])`. Migrations 012/013/014 exist to undo native enums after asyncpg serialized member *names* (`"PENDING"`) instead of *values* (`"pending"`). Follow this pattern for any new enum column. Plan tiers are stored uppercase (`FREE`/`BASIC`/`PRO`/`ENTERPRISE`) per migration 013.

### Logging

Production debugging leans on grep-able structured lines: `logger.info("[SONORO] event_name key=%s", value)`. Every registered route is logged at startup so Railway logs prove which routers mounted. Keep the `[SONORO]` prefix for anything you expect to search for in deploy logs.

## Product Vision

Sonoro is not a generic PDF-to-speech tool.

The goal is to become the best platform for transforming long-form documents into premium audiobook experiences.

The product should feel closer to Audible than to a text-to-speech utility.

Every feature should be evaluated according to:

- Better listening experience
- Lower friction
- Lower operating cost
- Better perceived quality
- Better long-term maintainability

## Development Philosophy

Before implementing any feature:

1. Audit the existing implementation.
2. Understand the architecture.
3. Identify root causes.
4. Design before coding.
5. Implement incrementally.
6. Add automated tests.
7. Produce a concise delivery summary.

Never introduce unnecessary dependencies.

Prefer replacing complexity with better architecture.

## Provider Philosophy

External providers should always be replaceable.

Google TTS, Google Books, Open Library, Stripe and object storage are implementations, not architectural requirements.

New providers should be added behind interfaces.

Avoid vendor lock-in whenever possible.

## Cost Awareness

Every feature that introduces external API usage should explicitly answer:

- What is the expected cost?
- Can the result be cached?
- Can duplicate requests be avoided?
- Can work be cancelled?
- Can retries increase costs?
- Can the user see the estimated cost?

Cost observability is a first-class concern.

## Architectural Changes

Large architectural changes should never start with code.

The expected workflow is:

Repository Audit
↓

Architecture Proposal
↓

Discussion
↓

Approval
↓

Implementation
↓

Testing
↓

Documentation


