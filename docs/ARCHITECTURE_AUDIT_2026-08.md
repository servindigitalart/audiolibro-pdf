# Sonoro — Master Architecture Audit & Strategic Roadmap

**Date:** 2026-08-03
**Scope:** Full repository audit at commit `03ad72b` (Cover Intelligence v2)
**Method:** Direct source inspection of `services/api/app/**` (31.7k LOC), `sonoro/src/**` (14.3k LOC), `services/api/tests/**` (19.8k LOC, 1,348 test functions), infra and CI config. Every finding below cites the file and line that produced it. One finding (F-1) was verified by executing the production code path, not by reading it.

---

# 1. Executive Summary

Sonoro is further along than most products at this stage. The domain decomposition in `services/api/app/` is genuinely good, the financial subsystem is unusually sophisticated for a pre-scale SaaS, the frontend is fast and tasteful, and 1,348 backend tests is real engineering discipline. **The foundation does not need to be rebuilt.**

However, the audit surfaced **four defects that are individually severe and collectively explain most of the symptoms you described** — unreliable chapters, and Google costs that "accumulated faster than expected." Three of them are cheap to fix.

### The four findings that matter most

| # | Finding | Evidence | Impact |
|---|---|---|---|
| **F-1** | **The chapter fusion layer collapses every contiguous chapter set into a single chapter.** This is not a fallback — it is an off-by-one in a merge condition. It fires on virtually every book. | `fusion/confidence_scorer.py:124` — verified by execution: 5 detected chapters in → **1** chapter out | This *is* the "Complete audiobook / Part 1" bug. Chapter detection has effectively never worked in production. |
| **F-2** | **Every job failure triggers up to 3 automatic full re-syntheses of the entire book**, and no failed attempt consumes quota. | `tasks/processing.py:190` (`autoretry_for=(Exception,)`), `:841` (quota charged only on success) | A 540k-char book that fails at 95% costs **$34.56** instead of $8.64. Worst-case FREE-tier user: **$16/mo** against a modeled ceiling of $0.80. This is the cost leak. |
| **F-3** | **The cost circuit breaker exists, is tested, and is not plugged in.** `RevenueProtectionService` is never called from any router, service or worker. `hard_cost_limit_enabled` defaults `False` and is only *displayed*, never enforced. | `pricing/protection.py:87` (no callers), `core/config.py:83`, `routers/admin_financial.py:375` | Nothing in the system can stop runaway spend. |
| **F-4** | **The admin cost dashboard is structurally blind to the money you actually lost.** It sums `ProcessingJob.estimated_cost_usd`, which is only written on *successful* completion. Failed and retried spend is invisible. | `analytics/dashboard_service.py:106-110` vs `tasks/processing.py:876` | You were surprised by the bill because the dashboard cannot show this class of spend by construction. |

F-2 + F-3 + F-4 compose into a single systemic failure: **spend amplification with no brake and no gauge.** Fixing all three is roughly 4–6 engineer-days.

### Strategic conclusions

1. **Fix F-1 through F-4 before building anything on the roadmap.** ~1.5 weeks total. F-1 alone converts the product from "PDF to one long audio file" into "chapter-aware audiobook platform," which is your core differentiator and is currently non-functional.
2. **Google Cloud TTS should become one provider behind an interface, not *the* engine.** Not because Google is bad — Neural2 at $16/1M is mid-market reasonable — but because you have zero routing flexibility today, and the single highest-leverage cost move available (self-hosted Kokoro for free-tier and previews) is a **40–150× reduction in cost per audio hour**. See §7.
3. **The metadata and cover subsystems are over-engineered relative to their accuracy.** Two separate, divergent scoring systems (`metadata/matcher.py` and `metadata/cover_service.py`) with different weights compute similar things. The fix is consolidation plus one missing signal (ISBN extracted from the PDF's own copyright page), not a rewrite and not an LLM.
4. **A lightweight LLM is genuinely justified in exactly one place** — chapter-boundary adjudication on ambiguous documents (§ Priority C) — and is *not* justified for metadata extraction, where deterministic ISBN lookup dominates on both accuracy and cost.
5. **The legacy `frontend/` Next.js app is an active hazard.** Commit `86e9dc6` (second-most-recent) shipped a chapter-navigation feature into the dead tree. Delete it.

### What I recommend you do first

```
Week 1     F-1 chapter fusion fix + F-2 retry containment       ← restores the product
Week 2     F-3 wire the circuit breaker + F-4 cost truth        ← stops the bleeding
Week 3-4   Chapter Engine V2 (Priority C)                       ← makes it good
Week 5-6   Speech Engine abstraction + Kokoro pilot (Priority F) ← makes it cheap
Then       Metadata V3 / Cover V3 / Processing UX / Marketplace / Formats
```

---

# 2. Technical Audit

## 2.1 Chapter Engine — **Grade: F (broken), architecture C+**

**Current architecture.** `DocumentStructureEngine` (`services/document_structure/engine.py:70`) orchestrates three detectors — `TOCExtractor` (PDF outline, conf 0.95), `HeuristicDetector` (per-line regex, conf 0.62–0.88), `StructuralAnalyzer` (font-size ratio, conf 0.5–0.75) — then fuses them via `ConfidenceScorer`, validates coverage, and persists `Chapter` rows.

### F-1 — Fusion collapses all chapters into one (CRITICAL)

`ConfidenceScorer._group_by_page_overlap()` groups two detections when:

```python
# fusion/confidence_scorer.py:124
if detection.start_page <= group_end + 1:   # "Allow 1 page gap"
```

Every detector emits **contiguous** page ranges — each sets `end_page = next.start_page - 1` (`heuristic_detector.py:345`, `structural_analyzer.py:199`, `toc_extractor.py:124`). For contiguous chapters, `next.start_page == group_end + 1` is *always* true, so the condition is always satisfied and every chapter merges into one group. `_fuse_group()` then returns a single `DetectedChapter` spanning `min(start) … max(end)`, titled after the highest-priority detection.

Verified by executing the real class:

```
TOC only (5 contiguous chapters):  input=5  → fused=1   'Chapter 1' pages 1-50
TOC + heuristic agreeing:          input=10 → fused=1   'Chapter 1' pages 1-50
Detections with gaps ≥2 pages:     input=5  → fused=5   (correct)
```

**This means chapter detection has never produced more than one chapter for a normal book.** The single output chapter then passes coverage validation (it covers 100% of the document), so `_validate_coverage` never fires — the user sees one chapter titled whatever the first heading was: "Chapter 1", "Part 1", "Contents", or — when detection genuinely fails — "Complete audiobook" (`engine.py:447`).

*Fix:* the merge predicate must compare against the *same* chapter, not adjacency. Group only when ranges genuinely overlap by more than a boundary page, or better — key the grouping on `start_page` proximity (±1) rather than range overlap. ~0.5 day including regression tests.

### F-5 — TOC extractor discards sub-level entries (HIGH)

`toc_extractor.py:112` filters to `level == 1` only, falling back to all entries *only* when there are zero level-1 entries. For any book whose outline is `Part I → Chapter 1..8 → Part II → …`, level 1 is the **Parts**, so an 8-chapter book yields 2 "chapters" named "Part I" and "Part II". This is the second, independent source of the "Part 1" symptom.

*Fix:* choose the outline depth whose entry count best matches an expected chapter distribution (e.g. the deepest level with 3–200 entries), rather than hardcoding level 1.

### F-6 — Page-granular boundaries (MEDIUM, architectural)

Chapters are bounded by **page numbers only** (`models.py` `DetectedChapter.start_page/end_page`), and text is extracted whole-page (`engine.py:348-350`). A chapter that begins mid-page inherits the tail of the previous chapter, and `HeuristicDetector` can only ever return **one heading per page** (`_find_chapter_heading` returns on first match, `heuristic_detector.py:249`) — so short chapters, story collections, and poetry are structurally undetectable.

### F-7 — Dead segmentation module (LOW, debt)

`TextSegmenter` (327 lines, `segmenter.py`) is instantiated at `engine.py:89` and never called. The worker uses its own `_chunk_text()` (`tasks/processing.py:73`). Two chunking implementations, one of them dead, with `text/normalizer.py` comments referencing the dead one.

| | |
|---|---|
| **Strengths** | Multi-strategy design is right. Coverage validation (`_validate_coverage`) is a thoughtful safety net. Spanish/French/German patterns show real domain care. Idempotent persistence with `IntegrityError` retry. |
| **Weaknesses** | F-1, F-5, F-6, F-7. Structural analyzer's `size_ratio >= 1.3` against a *global* median font misfires on documents with per-section styling. No validation that chapter count is plausible for page count. |
| **Hidden risk** | Because F-1 masks everything downstream, the three detectors have effectively never been evaluated on real output. Their true accuracy is **unknown**. Fixing F-1 will expose latent detector bugs — budget for that. |
| **Scalability** | `_extract_pages` loads all page text into memory (`PageText.text` per page). A 1,000-page book ≈ 2–4 MB — acceptable. `fitz.open()` called 3× on the same PDF (structural, TOC, chapter-text) — wasteful but not dangerous. |

## 2.2 Processing Pipeline & Worker — **Grade: C**

**Current architecture.** `process_document_job` (Celery, `tasks/processing.py:203`) → `_dispatch_job` creates a fresh `AsyncEngine` per task (correct fork-safety handling, well documented at `:243-254`) → `_process_job_async` runs 7 stages, committing `job.current_stage` / `progress_percentage` at each boundary.

### F-2 — Retry storm re-synthesizes the entire book (CRITICAL, cost)

```python
# tasks/processing.py:190
class ProcessingTask(Task):
    autoretry_for = (Exception,)
    retry_kwargs  = {"max_retries": 3}
```

`_dispatch_job` marks the job FAILED then **re-raises** (`:286`), and Celery retries. There is no checkpoint: the retry restarts at Step 1 and re-synthesizes every chunk. Chapter MP3s from the failed attempt are already durably in S3 (`:669`) and are simply ignored.

Compounding it:
- **No per-chunk retry.** A single transient Google 503 in chunk 97 of 120 discards 96 chunks of paid audio.
- **Quota is charged only on success** (`:841`, comment: *"Charge only on successful completion so retried jobs are never double-counted"*). The intent is user-fair; the effect is that real spend is invisible to the enforcement mechanism.
- `_DETERMINISTIC_ERRORS` is only `botocore.ParamValidationError` (`:57`). Genuinely permanent failures (corrupt PDF, unsupported voice, text too long) all retry 3×.

### F-8 — TTS is fully sequential (HIGH, scalability + UX)

`tasks/processing.py:632` — one chunk at a time, `await`ed, with a **DB commit per chunk** (`:652`). A 540k-char book = 120 chunks × (1–3 s API + commit) ≈ 6–12 minutes of pure serial latency, on a worker with `--concurrency=2` (`start-worker.sh`). Two users converting simultaneously saturate the entire fleet. This is the throughput ceiling and the reason processing "feels mechanical" (Priority D) — it genuinely is slow.

Google TTS has no rate problem with 8–16 concurrent requests. Parallelizing chunk synthesis within a chapter is the single biggest wall-clock win available.

### F-9 — No audio mastering, and the modules that would do it are dead (MEDIUM)

`AudioAssembler` (292 lines) and `AudioNormalizer` (290 lines, `-20.0 dBFS`) are **never imported by the pipeline**. The worker uses `_ffmpeg_concat` with `-c copy` (`:135`). Consequences:

- **No loudness normalization** — chapter-to-chapter volume drift; the README's "-20.0 dBFS consistent" claim is no longer true.
- **No silence trimming**, no inter-chapter gap insertion — chapters butt together abruptly.
- `-c copy` concatenation of separately-encoded MP3s can produce frame-boundary artifacts (clicks) and imprecise duration metadata.
- **No ID3 `CHAP`/`CTOC` chapter frames** in the downloaded MP3 — so the file a user downloads has *no* chapter navigation in Apple Books, Audible-compatible players, or any podcast app. For an "Audible-comparable" product this is a significant gap.

`AudioMetadataWriter` *is* used (`:743`) and correctly embeds cover art.

| | |
|---|---|
| **Strengths** | Fork-safety and event-loop handling are exemplary and well-documented. Deferred heavy imports (`:305-330`) is the right call. Cooperative cancellation (`_check_cancelled`) is clean. Streaming to disk — no PCM in RAM — is correct for long books. |
| **Debt** | `_process_job_async` is a **643-line function** with 7 responsibilities, 25 deferred imports, and interleaved DB commits. It is the least testable code in the repo. The task docstring still says *"THIS IS A PLACEHOLDER... No actual TTS processing happens here"* (`:207`). |
| **Hidden risk** | `task_time_limit = 3600` (`celery_app.py:57`). A 1,000-page book at current serial speed will exceed 60 minutes and be **hard-killed mid-synthesis** — paid characters, no product, then 3 retries. |

## 2.3 Cost & Financial Governance — **Grade: D (design B+, wiring F)**

The financial layer is the most sophisticated code in the repo and is **substantially disconnected**.

- **F-3 (CRITICAL):** `RevenueProtectionService` (`pricing/protection.py:87`) implements per-user daily/monthly cost caps, negative-margin throttling, and abuse flags against Redis. `grep` finds **no caller** outside `__init__.py` exports and tests. `TIER_CATALOG`'s carefully-reasoned `max_daily_cost_usd` / `max_monthly_cost_usd` (`pricing/tiers.py`) are consumed only by `pricing/experiments.py` and `pricing/upgrade.py` (copy-to-variant and CTA copy). **No cost cap is enforced anywhere in the request or worker path.**
- **F-3b:** `settings.hard_cost_limit_enabled` (default `False`), `global_monthly_cost_cap`, `user_monthly_cost_cap`, `emergency_shutdown_mode` are read **only** by `routers/admin_financial.py:352-375` — to *display* them.
- **F-4 (HIGH):** `dashboard_service.get_kpis()` computes `monthly_cost` from `ProcessingJob.estimated_cost_usd` (`:106`), set only at `tasks/processing.py:876` on success. `CostEvent` — which *is* written per synthesis call by `TTSService` (`services/tts/tts_service.py:197`) and therefore *does* capture failed spend — is never read by any dashboard.
- **F-10 (HIGH, cost model):** `unit_economics.py:196` assumes FREE/BASIC use **Standard voices at $4/1M**. The pipeline has no tier→voice routing whatsoever: `VOICE_MAP` (`services/language/detector.py`) is Neural2 for every major language, and `config.py:165` defaults to `en-US-Neural2-A`. **Every tier pays the $16/1M Neural2 rate.** The FREE and BASIC margin models are wrong by 4×.
- **F-11 (MEDIUM):** `CostEvent` has no `document_id` or `job_id` column (`financial/cost/cost_models.py`) — only a free-form JSON `metadata` blob, which `TTSService` populates *without* the document id. **Cost-per-document — your #1 requested metric — is not computable from the data model today.**
- **F-12 (MEDIUM):** `GoogleTTSProvider.COST_PER_CHARACTER` is hardcoded to `16.0/1_000_000` for all voices (`google_provider.py:51`). Chirp 3 HD ($30/1M) and Studio ($160/1M) would be undercounted by 1.9× and 10×.

## 2.4 Metadata Pipeline (Book Intelligence) — **Grade: B−**

**Architecture.** `MetadataService.enrich()` (`metadata/service.py:66`) runs `LocalExtractor` → parallel Google Books + Open Library → `Matcher.pick_best` → conditional cover download → persist. Fire-and-forget from upload via `asyncio.create_task` with its own engine (`document_service.py:354`) — a correct solution to the request-scoped-session problem.

**Strengths.** The pirate/scanner/software blocklists (`extractor.py:39-63`) are excellent, hard-won domain knowledge. Filename strategies (A: `by`, B: LatAm `title-author` hyphen convention, C: CamelCase) are pragmatic and well-tested. Never raises, never blocks generation.

**Weaknesses:**

| ID | Finding | Location |
|---|---|---|
| F-13 | **No ISBN is ever extracted from the document.** `query_isbn` can only come from a provider *response*, so the highest-precision lookup key available in almost every real book (the copyright page) is never used. | `metadata/` — absent |
| F-14 | **`isbn_bonus` and `cover_bonus` reward provider completeness, not match quality.** `isbn_score = 0.8 if result.isbn else 0.0` — every Google Books result has an ISBN, so 0.08 + 0.05 is a flat additive bonus to *all* candidates. ~13% of the score is noise. | `matcher.py:108,121` |
| F-15 | **No hard title floor in the metadata matcher** — while `cover_service.py:146` correctly rejects `title_sim < 0.35`. Two scorers, different rules, different weights (0.40/0.25 vs 0.45/0.30). | `matcher.py:124` vs `cover_service.py:38-42` |
| F-16 | **Low-confidence author/subtitle/ISBN are persisted unconditionally.** `_persist` gates only the cover on `confidence >= 0.60`; `doc.author = meta.author` runs at any confidence, including 0.35 local-only guesses. | `service.py:265-272` |
| F-17 | **Language is structurally unavailable at enrichment time.** Enrichment runs at upload with `detected_language=doc.language_detected`, but language detection happens later, in the worker (`tasks/processing.py:461`). The 0.10 language weight is dead on arrival. | `document_service.py:360` |
| F-18 | **Exactly one query shape, no fallback ladder, no caching.** Only `title_candidates[0]` is queried. If the best candidate is wrong, the pipeline never tries the second. No Redis cache — identical books re-query providers forever. | `service.py:152-160` |

## 2.5 Cover Intelligence v2 — **Grade: B**

Genuinely the best-engineered new subsystem. `_score_candidate` has a real rejection ladder, an author-mismatch cap, ISBN floor, and dedup by base URL. `select_cover_suggestion` (`routers/documents.py:992`) has proper SSRF defense: domain allowlist, HTTPS-only, redirect cap, 5 MB limit, magic-byte validation. That is production-grade.

**Weaknesses:**

| ID | Finding | Location |
|---|---|---|
| F-19 | **Image "quality" is inferred from the URL string**, never from the image. `-L.jpg` scores 1.0 even when Open Library returns a 1×1 placeholder or 404s. Nothing verifies dimensions, aspect ratio, or that the bytes are an image, until the user has already selected it. | `cover_service.py:104-113` |
| F-20 | **No caching.** Up to 6 provider HTTP calls per suggestion request (3 Google + 3 OL), and `CoverSuggestions` auto-loads on upload (`UploadZone.tsx`). Every view of the same book re-queries. | `cover_service.py:428` |
| F-21 | **Only 2 providers; no edition consolidation.** Google Books and Open Library often return 5 editions of one book — dedup is by image URL, so 5 near-identical covers can occupy all 5 slots. | `cover_service.py:452` |
| F-22 | Open Library language is hardcoded `None` (`:387`), so `lang_score` silently takes the 0.3 "no info" path for every OL candidate — biasing scores against Google results that *do* report language. | `cover_service.py:387` |

## 2.6 TTS / Speech Layer — **Grade: C+ (clean, but single-vendor)**

`TTSProvider` ABC exists (`services/tts/base.py`) and `TTSService` accepts injection (`tts_service.py:108`) — the seam for multi-provider is *already there*, which makes Priority F much cheaper than it looks. But `TTSService.__init__` hardcodes `GoogleTTSProvider()` as the default, `CostProvider.GOOGLE if name == "google" else INTERNAL` (`:203`) assumes two providers, and there is no registry, no routing policy, no fallback, no circuit breaker.

`narration_profiles.py` (478 lines) maps 30+ Google voice IDs to trait tuples, and `prepare_text_for_profile` applies rate/pitch. Note the **frontend `NARRATION_STYLES` matches voices by ElevenLabs voice names** — `rachel`, `bella`, `matilda`, `charlie`, `domi` (`UploadZone.tsx:33-39`) — against a Google-only catalog. Those keyword matches can never hit; `bestVoiceForStyle` always returns `null`. Vestigial code from an abandoned ElevenLabs integration.

Voice preview (`routers/voices.py`) caches synthesized samples in a **per-process dict** (`:48`) — lost on every Railway restart/scale event, and unbounded.

## 2.7 Frontend & UX Architecture — **Grade: B+**

Astro SSR + React islands is the right call for an SEO-sensitive product with app-like surfaces; the marketing/landing pages (`ai-audiobook-generator.astro`, `spanish-pdf-to-audio.astro`, etc.) prove the value. `middleware.ts` auth gating is clean. `server.ts` normalization insulates pages from backend drift — good boundary.

| ID | Finding | Location |
|---|---|---|
| F-23 | **`UploadZone.tsx` is 1,481 lines** and owns upload, preflight, metadata polling, cover suggestions, voice/style selection, job polling, progress interpolation, completion, retry, error mapping, and the paywall. Untestable as a unit; the 887-line test file compensates. | `UploadZone.tsx` |
| F-24 | **Processing state is component-local.** A refresh during a 12-minute conversion loses the entire progress view; the document detail page (`[id].astro`) renders a player, not progress. No cross-tab sync, no background continuation. | `UploadZone.tsx:328` |
| F-25 | **Polling never backs off and never pauses.** `setInterval(poll, 2500)` regardless of tab visibility → ~290 requests per 12-minute job per open tab. | `UploadZone.tsx:407` |
| F-26 | **Presigned audio URLs expire in 1 hour** (`PRESIGNED_URL_EXPIRY = 3600`) while audiobooks routinely run 5–15 hours. A long listening session — or a resumed one — will hit **403 mid-playback** when the browser issues a fresh range request. No refresh-on-expiry logic exists in `useAudioPlayer`. | `storage_service.py:223` |
| F-27 | Auth tokens are deliberately non-`httpOnly` (`client.ts:9`) so the axios interceptor can rotate them. This is a documented tradeoff, but it means **any XSS is full account takeover**, and there is no CSP. Comment says access token is 15 min; cookie is set to `expires: 1/48` = 30 min (`client.ts:338`). | `client.ts` |
| F-28 | Legacy `frontend/` (Next.js 14) still receives commits — `86e9dc6` shipped `chapter-navigation.tsx`, `use-processing-progress.ts`, and an `audio-player` update into the dead tree. | `frontend/` |

**Player** (`AudioPlayer.tsx`, 1,326 lines + `useAudioPlayer.ts`): genuinely premium. Media Session API is wired (`:912-962`) so lock-screen controls work. 60-bar waveform, drag-seek, speed pills, immersive mode, keyboard shortcuts. `usePlaybackProgress` persists to user-scoped `localStorage`. Gaps: no PWA/offline (`public/` has only `favicon.svg`), no download-for-offline, progress is device-local (not synced server-side), `preload="metadata"` means no aggressive buffering for long chapters.

## 2.8 API Design, Database, Storage — **Grade: B**

**API.** ~20 routers, consistent `/api/v1` prefix, Pydantic schemas, OpenAPI docs. `documents.py` at **1,501 lines / 20 endpoints** is doing too much (upload, list, get, delete, metadata patch, cover suggestions, cover select, cover upload, chapters, retry, cancel, job status, audio URLs) and mixes routing with business logic (the whole cover-download flow lives in the handler). Middleware order (RequestID → Metrics → CORS → GZip → Billing) is correct.

**Database.** 30 sequential migrations, all applied at boot by `start.sh` — good. The `native_enum=False` + `values_callable` convention (migrations 012/013/014) is a correct and well-documented workaround. Chapter has a unique constraint (026) and idempotent persistence.
*Risks:* migrations run on **every deploy with 5 retries** and no lock — two Railway instances booting concurrently can race Alembic. No `document_id` on `CostEvent` (F-11). `estimated_cost_usd` on `ProcessingJob` conflates estimate with actuals.

**Storage.** Clean `LocalStorageService` / `S3StorageService` split with a `get_storage_service()` factory. `sanitize_s3_metadata` correctly strips non-ASCII (learned from a real bug). *Gaps:* no lifecycle policy — chapter MP3s **and** the assembled MP3 are both retained forever (≈2× storage per book, permanently); no CDN in front of R2 for audio delivery; 1-hour presign (F-26).

## 2.9 Testing, CI/CD, Observability — **Grade: B− / C / C+**

**Testing.** 1,348 backend test functions, marker-segmented (`unit`/`integration`/`performance`/`chaos`/`stripe`/`pricing`) with performance/chaos/stripe/pricing excluded from default runs. Chaos suite with fault injectors and financial invariants is unusually mature. 180 frontend tests.
*Gap:* **no test caught F-1.** `tests/unit/test_chapter_detection.py` (337 lines) tests detectors in isolation and never asserts on end-to-end fused chapter *count* for a contiguous multi-chapter book. That is the highest-value missing test in the repo. `tests/conftest.py.bak`, `.bak2`, `test_auth.py.bak`, `tests_backup/` should be deleted.

**CI/CD.** `ci.yml` gates unit → integration (60% cov) → full (70% cov) — solid, but **backend only**; `sonoro/`'s 180 vitest tests never run in CI. `deploy-staging.yml` deploys via SSH to a **DigitalOcean VPS** that is not the production topology (Railway + Vercel). Production deploys come from the platforms' git integrations, so **nothing in `.github/workflows` gates a production release** — a red CI run still ships. `DEPLOY_TRIGGER.txt` (a file whose only purpose is forcing redeploys) is a symptom of this.

**Observability.** Prometheus metrics are comprehensive (HTTP, TTS, cost, chapters, revenue), Sentry is wired with env/release/traces, structured `[SONORO]` logging is grep-optimized and genuinely well done, `alerts.yml` covers error rate/latency, and `AlertEngine` covers billing anomalies.
*Gaps:* Prometheus/Grafana are defined in `docker-compose`/`infra/monitoring` for a **VPS deployment that isn't production** — on Railway, `/metrics` is exposed but nothing scrapes it. So in practice you have logs + Sentry and **no metrics, no dashboards, and no alerting in production.** No alert exists for cost, TTS failure rate, or queue depth.

## 2.10 Security — **Grade: B−**

Good: bcrypt + JWT with refresh rotation, ownership checks on every document endpoint, magic-byte upload validation, SSRF allowlist on cover fetch, S3 metadata sanitization, presigned URLs (no public buckets), Stripe webhook signature verification, `RoleChecker(["admin"])` on admin routes.

| ID | Finding |
|---|---|
| F-29 | **Rate limiting is off by default** (`feature_rate_limiting=False`) and applied **only** to `/auth/register` and `/auth/login` (`routers/auth.py:74,133`). `/documents/upload` — the endpoint that spends money — has no rate limit. Only the monthly job quota bounds it. |
| F-30 | Non-`httpOnly` tokens + no CSP (F-27). |
| F-31 | `MAX_FILE_SIZE_BYTES = 50 MB` (`utils/file_validation.py:19`) but the frontend dropzone allows **100 MB** (`UploadZone.tsx`) and `config.py` has its own `max_upload_size_mb` — three sources of truth. |
| F-32 | No PDF bomb / encrypted-PDF guard before `fitz.open()` in the worker; a 50 MB adversarial PDF can exhaust worker memory or wedge a slot for the full 3600 s time limit. |
| F-33 | Global exception handler returns generic 500s (good), but `_mark_job_failed` writes raw exception strings to `job.error_message`, which is surfaced to the frontend (`documents.py:1301`) — potential internal detail leakage. |

---

# 3. Product & UX Audit

Benchmarks: Linear (state clarity), Notion (import feedback), Figma (perceived speed), Dropbox (upload trust), Arc (delight), Audible (listening craft).

### Journey map with friction points

| Stage | What happens today | Friction | Severity |
|---|---|---|---|
| **Upload** | Dropzone → progress % → preflight card | Frontend allows 100 MB, backend rejects >50 MB — the user waits through a full upload to be told no. No client-side page-count/size preview. | High |
| **Preflight** | Language, voice, chapters, duration, quota impact | Estimated chapters comes from a **page-count heuristic** (`preflight_service.py:201`) that has nothing to do with actual detection — it promises "12 chapters" and (per F-1) delivers 1. Actively erodes trust. **No cost or credit-consumption preview** beyond raw character counts. | High |
| **Metadata** | Polled 3.5 s after preflight, up to 4 attempts | If enrichment is slow, the card silently never appears — no "still looking" state, no manual "search again". Detected title/author land with **no confidence indication** to the user, despite `metadata_confidence` being computed and returned. | Medium |
| **Cover** | `CoverSuggestions` carousel, auto-loads | Strong. But no "no covers found" recovery path other than upload-your-own; no generated-cover fallback preview at this step. | Low |
| **Voice** | `VoicePicker` + narration styles | **One voice per language** (`preflight_service.py:151`). Five narration styles exist but `bestVoiceForStyle` matches against ElevenLabs names that don't exist in the catalog — style selection cannot change the voice. Preview requires auth and a live TTS round-trip. | High |
| **Conversion** | 5-step timeline, rAF-interpolated %, confident ETA, stuck-detection | Genuinely good — better than most. But it is **only on the upload page**: refresh, tab close, or navigating to the library abandons the view (F-24). No job history. | High |
| **Progress honesty** | `weightedProgress` maps stages to bands; monotonic clamp | Well-designed. The 25→85% band is driven by real chunk counts — honest. Weak point: `analyzing` is capped at 14% and can sit there for a long time on big PDFs with no sub-progress. | Medium |
| **Retry** | Library → Retry → redirected to upload page with `?retryDocumentId` | Reasonable, but the user is sent to the *upload* page to watch a retry — conceptually wrong place. No indication of what failed or whether a retry is likely to help. | Medium |
| **Library** | Card grid, covers, continue-listening, 30 s clock refresh | No search, no sort, no filter, no folders/collections. Fine at 10 books, unusable at 100. | Medium |
| **Player** | Waveform, drag-seek, speed, immersive, Media Session | Best part of the product. Gaps: chapter list is useless while F-1 stands; no sleep timer; no bookmarks/notes; no variable-speed persistence across documents; progress is device-local. | Medium |
| **Download** | Presigned MP3 | Single MP3 with **no embedded chapter markers** (F-9) — imports into Apple Books/podcast apps as one 9-hour track. No M4B option (the audiobook-native format). No per-chapter download despite per-chapter files existing in S3. | High |
| **Lock screen** | Media Session metadata + prev/next/play/pause | Works. Missing `seekbackward`/`seekforward`/`seekto` handlers and `positionState`, so scrubbing from the lock screen/CarPlay is unavailable. | Medium |
| **Mobile** | Bottom nav, responsive, mini-player | Solid. But no PWA manifest, no install prompt, no offline playback — the three things that make a listening app feel native. | High |

### Where premium is won

1. **Never lose the job.** Processing must be a first-class, resumable, cross-device object (see Priority D). Dropbox's magic is that closing the tab is safe and obvious.
2. **Truthful anticipation.** Replace the fake chapter estimate with a real one; show cost/credits *before* conversion; show confidence on detected metadata.
3. **The download must be an audiobook, not an MP3.** Chapter markers + M4B is the difference between "TTS tool" and "Audible alternative."
4. **Offline + PWA.** The core use case (commute, gym, walk) is offline. This is the highest-ROI UX investment after chapters work.
5. **Library as a library.** Search, collections, "finished," reading streaks.

---

# 4. Architecture Review

**What is right and should be preserved:**
- Domain-package backend layout (`financial/`, `billing/`, `pricing/`, `metadata/`, `analytics/`) over technical layering. This ages well.
- The `TTSProvider` ABC, `StorageService` factory, and `metadata.providers.base` — three real seams already in place.
- Astro SSR + islands for a SEO-critical product.
- Fresh-engine-per-task Celery pattern; deferred heavy imports.
- Structured `[SONORO]` logging.

**What is architecturally wrong:**

| Issue | Assessment |
|---|---|
| **Business logic in Celery task bodies** | `_process_job_async` (643 lines) *is* the pipeline. It should be a thin orchestrator over `PipelineStage` objects (analyze → detect → synthesize → assemble → publish), each independently testable and independently retryable. This single refactor unlocks checkpointing (F-2), parallelism (F-8), and progress fidelity (Priority D). **This is the highest-leverage structural change in the codebase.** |
| **Two scoring engines for one problem** | `metadata/matcher.py` and `metadata/cover_service.py` both fuzzy-match title/author with different weights and different rejection rules. Should be one `MatchScorer` with configurable weight profiles. |
| **Built-but-unplugged subsystems** | `RevenueProtectionService`, `AudioAssembler`, `AudioNormalizer`, `TextSegmenter`, `_stripe_service_deprecated.py` (635 lines). ~1,500 lines of tested, dead code. Either wire it or delete it — dead code that *looks* live is worse than no code, because it makes the system appear safer than it is (F-3 is exactly this failure mode). |
| **No provider abstraction where it matters most** | Storage and metadata have provider seams. TTS — the entire cost center — effectively does not. |
| **Estimate/actual conflation** | `estimated_cost_usd` on jobs, `character_estimate` on documents, `CostEvent.total_cost` as actuals. Three overlapping notions of spend, no reconciliation. |
| **Frontend duplication** | Two complete frontends in one repo. |

**Vendor lock-in inventory:** Google TTS — **high** (the whole product, though the ABC softens it). Stripe — medium (already abstracted via `billing/stripe/{mock,real}.py`, good). R2/S3 — low. Railway/Vercel — low (Docker + Astro adapter). PyMuPDF (AGPL) — **⚠️ license risk worth a lawyer's five minutes**: PyMuPDF is AGPL-3.0 unless commercially licensed, and it is central to a commercial SaaS.

---

# 5. Risk Assessment

| ID | Risk | Likelihood | Impact | Exposure | Mitigation |
|---|---|---|---|---|---|
| R1 | Cost runaway from retry storm (F-2 + F-3) | **Occurring now** | High | Unbounded | Disable `autoretry_for`, wire `RevenueProtectionService` |
| R2 | Chapters never work; core differentiator absent (F-1) | **Certain** | Critical | Product positioning | 0.5-day fix |
| R3 | Cost invisible in dashboards (F-4) → repeat surprise | **Occurring now** | High | Financial | Read `CostEvent`, add `document_id` |
| R4 | No metrics/alerting in production | **Occurring now** | High | Blind ops | Managed Prometheus or Sentry-based cost alerts |
| R5 | Long books hard-killed at Celery 3600 s limit | High for 800+ pages | High | Paid chars, no product | Parallelize + checkpoint |
| R6 | Playback 403 after 1 h (F-26) | High for long books | Medium | Trust | Refresh-on-401/403 in player; longer presign |
| R7 | XSS → account takeover (F-27) | Low | Critical | All accounts | CSP; consider BFF session cookies |
| R8 | Upload endpoint unrated-limited (F-29) | Medium | High | Cost/abuse | Per-user + per-IP limits on upload/retry |
| R9 | PyMuPDF AGPL in commercial SaaS | Medium | High | Legal | Verify license posture; `pypdfium2` is a BSD alternative |
| R10 | Concurrent Alembic on multi-instance boot | Low | High | DB corruption | Advisory lock or separate release step |
| R11 | Work landing in dead `frontend/` (F-28) | **Occurred** | Medium | Wasted effort | Delete the directory |
| R12 | Single TTS vendor: price change or quota suspension halts the product | Low | Critical | Existential | Provider abstraction + a warm second provider |

---

# 6. Cost Assessment

### Verified current rates (Aug 2026)

| Voice class | $/1M chars | $/audio-hour¹ |
|---|---|---|
| Google Standard / WaveNet | $4 | $0.20 |
| **Google Neural2 (what you actually use)** | **$16** | **$0.80** |
| Google Chirp 3: HD | $30 | $1.50 |
| Google Studio | $160 | $8.00 |

¹ Using your own `CHARS_PER_LISTENING_HOUR = 50_000` (`pricing/unit_economics.py:65`).

### Where the money actually went

For a typical 300-page book (~540k chars):

| Scenario | Cost |
|---|---|
| Clean run | **$8.64** |
| One failure at 95% + 3 auto-retries (F-2) | **$34.56** |
| Plus a user-initiated retry (also 4 attempts) | **$69.12** |

Per-tier exposure, comparing your model to reality:

| Tier | Price | Monthly chars | Modeled TTS cost | **Actual** (Neural2) | Worst case w/ retries (4×) |
|---|---|---|---|---|---|
| FREE | $0 | 50k | $0.20 | **$0.80** | **$16.00** (5 jobs × 4 attempts) |
| BASIC | $9 | 100k | $0.40 | **$1.60** | **$6.40** |
| PRO | $29 | 500k | $8.00 | $8.00 | **$32.00** |
| ENTERPRISE | $99 | 5M | $80.00 | $80.00 | **$320.00** |

Two structural problems are visible immediately: **ENTERPRISE has a $19 gross margin before Stripe fees, storage, and infra** — it is a loss-leader at full utilization on the *happy path*. And FREE's real ceiling is 20× the modeled one.

### Cost intelligence gaps (what Priority E must close)

| Metric requested | Computable today? | Blocker |
|---|---|---|
| Cost per document | ❌ | `CostEvent` has no `document_id` (F-11) |
| Cost per user | ✅ | `CostTracker.get_user_monthly_cost` |
| Cost per provider | ⚠️ | Enum exists; only one provider |
| Cost per voice | ⚠️ | In JSON metadata; not indexed/queryable |
| Cost per retry | ❌ | No attempt attribution |
| Cost per character | ✅ | Hardcoded, wrong for non-Neural2 (F-12) |
| Cost per audiobook | ❌ | Same as per-document |
| Cost per worker | ❌ | Not tracked |
| Storage cost | ❌ | Never measured; rates exist in the model only |
| Estimated cost pre-conversion | ⚠️ | Computable; not surfaced in preflight |
| Actual cost post-conversion | ⚠️ | On `ProcessingJob`, success-only (F-4) |

### The savings opportunity

| Lever | Saving | Effort |
|---|---|---|
| Kill retry amplification (F-2) | **~50–75% of current real spend** | 2 d |
| Route FREE tier to Standard voices or self-hosted | 75–97% of free-tier cost | 1 d / 10 d |
| Cache TTS by `sha256(text + voice + rate + pitch)` — retries and duplicate books become free | 20–40% | 3 d |
| Self-host Kokoro for bulk volume (§7) | **40–150× on routed traffic** | 10–15 d |
| Storage lifecycle: drop chapter MP3s after N days | ~50% of storage | 1 d |

---

# 7. AI Speech Research Report

## 7.1 Commercial APIs

| Provider | $/1M chars | $/audio-hr | Quality | Spanish | Streaming | Cloning | Notes |
|---|---|---|---|---|---|---|---|
| Google Standard/WaveNet | $4 | $0.20 | Fair | Good | ✓ | ✗ | Robotic for long-form; fine for previews |
| **Google Neural2** *(current)* | $16 | $0.80 | Good | Good | ✓ | ✗ | Solid baseline, unremarkable prosody |
| Google Chirp 3: HD | $30 | $1.50 | Very good | Very good | ✓ | Gated | Best Google option for narration; cloning is allow-listed |
| Google Studio | $160 | $8.00 | Excellent | Limited | ✓ | ✗ | Priced out of audiobooks |
| Amazon Polly Neural | $16 | $0.80 | Good | Good | ✓ | ✗ | Direct Neural2 peer |
| Polly Generative | $30 | $1.50 | Very good | Good | ✓ | ✗ | Credible second source |
| Polly Long-Form | $100 | $5.00 | Excellent | Limited | ✓ | ✗ | Purpose-built for narration; expensive |
| Azure Neural | ~$16 | ~$0.80 | Good | Very good | ✓ | Custom (paid) | Strongest enterprise SLA story |
| OpenAI TTS | $15 | $0.75 | Very good | Good | ✓ | ✗ | Simple API, few voices, no SSML |
| Deepgram Aura | $15 | $0.75 | Good | Limited | ✓ | ✗ | Latency-optimized for agents, not narration |
| Cartesia Sonic | $50 | $2.50 | Excellent | Very good | ✓ (<100 ms) | ✓ | Latency leader; overkill for batch |
| **ElevenLabs** | $66–$300 | $3.30–$15 | **Best in class** | **Excellent** | ✓ | ✓ | The quality benchmark; only viable as a paid premium tier |

## 7.2 Open-source / self-hostable

| Model | License | Params | VRAM | Speed | Spanish | Commercial? | Verdict for Sonoro |
|---|---|---|---|---|---|---|---|
| **Kokoro-82M** | **Apache 2.0** | 82M | <2–4 GB | **~210× RT (4090)** | Yes (54 voices incl. es) | ✅ | **Best fit.** Cheapest credible narration at scale. No cloning. |
| **Chatterbox / Turbo** | **MIT** | 0.35–0.5B | 8 GB+ | Sub-200 ms | 17 langs (Turbo) | ✅ | Beat ElevenLabs in a vendor blind test (65.3% vs 24.5%). Watermarked. Best quality-per-dollar self-host. |
| VibeVoice | Open | — | High | Moderate | Partial | ⚠️ verify | Purpose-built long-form/expressive — worth a pilot |
| Fish/OpenAudio S1 | Open | — | 8 GB+ | Fast | Multilingual | ⚠️ verify | Strong multilingual cloning |
| StyleTTS2 | MIT | — | 4 GB+ | Fast | Limited | ✅ | Best prosody for narration; English-centric |
| XTTS-v2 | **CPML (non-commercial)** | — | 6 GB+ | Moderate | Excellent (17 langs) | ❌ | Excellent, unusable — and unmaintained since the 2024 Coqui shutdown |
| F5-TTS | **CC-BY-NC 4.0** | — | 8 GB+ | Fast | Good | ❌ | Research only |
| Piper | MIT | Tiny | CPU | Very fast | Fair | ✅ | Too robotic for a premium product |
| Bark / Parler / Dia2 | Apache/MIT | — | 8–16 GB | Slow | Varies | ✅ | Dia2 is interesting for multi-speaker dialogue later |
| Spark-TTS / CosyVoice / Seed-TTS / NeMo | Varies | — | 8–24 GB | Varies | Varies | ⚠️ each differs | Verify licenses individually before any pilot |
| Edge TTS | *(unofficial)* | — | — | Fast | Good | ❌ | Unofficial Microsoft endpoint — **ToS risk, never ship it** |

**Self-hosting economics.** Published figures put naive single-stream deployments at $0.30–$2.40 per audio-hour — no better than Google. The win comes entirely from **batching**: an A100 (~$1.04/hr) sustains 50+ concurrent Kokoro streams at <0.1 RTF. At 50 audio-hours produced per GPU-hour, that is **≈$0.02 per audio-hour — 40× cheaper than Neural2**; at 210× realtime on a 4090, better still. Realistically, budget $0.02–$0.10/audio-hour at healthy utilization, plus ~10–15 engineer-days of build and ongoing ops.

The honest caveat: this only pays off with **steady batch volume**. A GPU idling at 5% utilization costs more than Google. Self-hosting should follow demand, not precede it.

## 7.3 Recommendation

**Do not migrate off Google. Demote it to one provider among several, behind a routing policy.**

| Question | Answer |
|---|---|
| Should Sonoro migrate? | **No wholesale migration.** Google Neural2 is a reasonable default and the switching risk is unjustified. |
| Multiple providers? | **Yes — this is the key decision.** The `TTSProvider` ABC already exists; the marginal cost is low and it removes an existential single-vendor risk (R12). |
| Hybrid routing? | **Yes**, by tier and job class. |
| Google as fallback only? | **Eventually** — as the reliability fallback once a cheaper primary is proven. Not on day one. |
| Would self-hosting cut costs enough? | **Yes, dramatically** — but only with batching and utilization. Stage it behind the abstraction; pilot on previews and free-tier where quality tolerance is highest. |

**Target routing policy:**

```
Voice previews        → Kokoro (self-hosted)     ~$0.00   quality tolerance: high
FREE tier             → Kokoro or Google Standard $0.02–0.20/hr
BASIC / PRO (default) → Google Neural2            $0.80/hr   ← today's behavior
PRO (premium voices)  → Google Chirp 3 HD         $1.50/hr
"Studio narration"    → ElevenLabs (paid add-on)  $3.30/hr   priced through to the user
Any provider failure  → automatic fallback down the chain
```

**Architecture to build today** (not tomorrow):

```
TTSService
  └── ProviderRegistry            resolve(voice_id) → provider instance
        ├── GoogleTTSProvider     (exists)
        ├── KokoroProvider        (self-hosted HTTP, phase 2)
        └── ElevenLabsProvider    (premium tier, phase 3)
  ├── RoutingPolicy               tier + voice + job class → provider
  ├── SynthesisCache              sha256(text|voice|rate|pitch) → S3 key
  ├── CircuitBreaker              per provider, with automatic fallback
  └── CostLedger                  per-call, per-provider, real rates
```

The `SynthesisCache` alone justifies the refactor: it makes retries nearly free, which independently mitigates F-2.

---

# 8. Future-Proof Architecture Proposal

### Target: a staged pipeline, not a monolithic task

```
ProcessingOrchestrator (Celery)
  │  loads Job → resolves stage plan → executes → checkpoints after each stage
  │
  ├── 1. IngestStage       format adapter (PDF|EPUB|DOCX|…) → NormalizedDocument
  ├── 2. StructureStage    chapter detection → ChapterPlan   [checkpoint]
  ├── 3. EnrichStage       metadata + cover (idempotent, cached)
  ├── 4. SynthesisStage    parallel chunk TTS via TTSService [checkpoint per chunk]
  ├── 5. MasterStage       normalize → gap insert → concat → ID3 CHAP/CTOC
  └── 6. PublishStage      upload, durations, chapter rows, events
```

**Non-negotiable properties:**

1. **Checkpointed** — a `JobCheckpoint` table records completed stages and per-chunk S3 keys. Retry resumes; it never re-synthesizes paid audio. Kills F-2 permanently.
2. **Parallel where safe** — chunk synthesis fans out with bounded concurrency (8–16).
3. **Provider-agnostic** — ingest, TTS, and metadata all go through registries.
4. **Metered** — every stage emits duration + cost to one ledger keyed by `(job_id, document_id, stage, provider)`.
5. **Observable** — stage transitions are the progress contract the frontend already consumes; no frontend rewrite needed.

### Supporting changes

- **`CostLedger`** replaces scattered cost writes: `cost_events` gains `document_id`, `job_id`, `attempt_number`, `provider`, `voice_id`, `stage` as real indexed columns.
- **`ProcessingSession`** — server-side, resumable, cross-tab job state (Priority D) exposed via SSE instead of 2.5 s polling.
- **Delete** `frontend/`, `_stripe_service_deprecated.py`, `AudioAssembler`, `AudioNormalizer`, `TextSegmenter`, `tests_backup/`, `*.bak`, 30 root `BLOCK_*.md` files. ~1,500 lines of dead code and ~250 KB of misleading docs.

---

# 9. Prioritized Roadmap

Effort in engineer-days. ROI is 5-year weighted.

### Phase 0 — Stop the bleeding (Week 1–2, ~9 d) — **do this before anything else**

| # | Item | Purpose | User impact | Tech impact | Complexity | Depends | Effort | ROI |
|---|---|---|---|---|---|---|---|---|
| 0.1 | **Fix fusion grouping (F-1)** | Chapters actually work | **Transformative** | Low | Low | — | 0.5 d | ★★★★★ |
| 0.2 | **Regression test: N contiguous chapters → N** | Prevent recurrence | — | Low | Low | 0.1 | 0.5 d | ★★★★★ |
| 0.3 | **TOC level selection (F-5)** | Kills "Part 1" | High | Low | Low | 0.1 | 1 d | ★★★★★ |
| 0.4 | **Disable blanket `autoretry_for` (F-2)** | Stop 4× spend | Medium | Medium | Low | — | 1 d | ★★★★★ |
| 0.5 | **Per-chunk retry (3× w/ backoff)** | Transient errors stop killing jobs | High | Medium | Low | 0.4 | 1 d | ★★★★★ |
| 0.6 | **Wire `RevenueProtectionService` (F-3)** | Real cost ceiling | Low | Medium | Low | — | 1.5 d | ★★★★★ |
| 0.7 | **Cost truth: `document_id` on `CostEvent`; dashboard reads it (F-4, F-11)** | See real spend | Low | Medium | Low | — | 1.5 d | ★★★★★ |
| 0.8 | **Per-voice cost rates (F-12) + fix tier model (F-10)** | Correct economics | Low | Low | Low | — | 0.5 d | ★★★★ |
| 0.9 | **Rate-limit upload/retry (F-29)** | Abuse ceiling | Low | Low | Low | — | 0.5 d | ★★★★ |
| 0.10 | **Delete `frontend/` + dead modules (F-28)** | Stop wasted work | — | Medium | Low | — | 0.5 d | ★★★★ |

### Phase 1 — Make it good (Week 3–6, ~26 d)

| # | Item | Purpose | Complexity | Depends | Effort | ROI |
|---|---|---|---|---|---|---|
| 1.1 | **Priority C — Chapter Engine V2** | Correct chapters across genres | High | 0.1–0.3 | 12 d | ★★★★★ |
| 1.2 | **Staged pipeline refactor + checkpointing** | Resumable, parallel, testable | High | 0.4 | 8 d | ★★★★★ |
| 1.3 | **Parallel chunk synthesis (F-8)** | 3–5× faster conversions | Medium | 1.2 | 2 d | ★★★★★ |
| 1.4 | **Synthesis cache (content-addressed)** | Retries/dupes free | Medium | 1.2 | 3 d | ★★★★ |
| 1.5 | **Production metrics + cost alerting (R4)** | Never be surprised again | Low | 0.7 | 1 d | ★★★★★ |

### Phase 2 — Make it cheap and durable (Week 7–10, ~24 d)

| # | Item | Complexity | Depends | Effort | ROI |
|---|---|---|---|---|---|
| 2.1 | **Priority F — provider registry, routing, circuit breaker** | Medium | 1.2 | 6 d | ★★★★★ |
| 2.2 | **Kokoro self-hosted pilot** (previews + FREE tier) | High | 2.1 | 10 d | ★★★★ |
| 2.3 | **Priority E — full cost intelligence + dashboards** | Medium | 0.7 | 5 d | ★★★★ |
| 2.4 | **Audio mastering: loudnorm, gaps, ID3 CHAP/CTOC (F-9)** | Medium | 1.2 | 3 d | ★★★★★ |

### Phase 3 — Make it delightful (Week 11–16, ~34 d)

| # | Item | Complexity | Depends | Effort | ROI |
|---|---|---|---|---|---|
| 3.1 | **Priority D — resumable processing sessions + SSE** | High | 1.2 | 8 d | ★★★★ |
| 3.2 | **Priority A — Metadata V3** | Medium | — | 7 d | ★★★★ |
| 3.3 | **Priority B — Cover V3** | Medium | 3.2 | 5 d | ★★★ |
| 3.4 | **Priority G — Voice Marketplace** | Medium | 2.1 | 6 d | ★★★★ |
| 3.5 | **PWA + offline playback** | Medium | — | 5 d | ★★★★ |
| 3.6 | **Presigned URL refresh (F-26) + library search** | Low | — | 3 d | ★★★ |

### Phase 4 — Expand the market (Week 17+, ~21 d)

| # | Item | Complexity | Effort | ROI |
|---|---|---|---|---|
| 4.1 | **Priority H — EPUB support** | Medium | 6 d | ★★★★★ |
| 4.2 | **DOCX / TXT / Markdown / HTML** | Low | 5 d | ★★★ |
| 4.3 | **M4B export** | Medium | 4 d | ★★★★ |
| 4.4 | **Frontend CI + prod deploy gating** | Low | 3 d | ★★★★ |
| 4.5 | **CSP + security hardening (F-27, F-32)** | Medium | 3 d | ★★★ |

---

# 10. Implementation Plans

## Priority A — Intelligent Metadata Engine V3 (7 d)

**Verdict: incremental improvement, not a rewrite.** `extractor.py`'s blocklists are irreplaceable domain knowledge. The gap is a missing signal and a broken scorer, not a bad design.

**A1 — ISBN extraction from the document (2 d) — highest value.**
New `metadata/isbn_extractor.py`: scan pages 1–8 and the last 3 for `ISBN(?:-1[03])?:?\s*([\d\-X ]{10,17})`, validate ISBN-10/13 checksums, rank by position (copyright page wins). Feed as `query_isbn`. An exact ISBN lookup converts a fuzzy-match problem into a database lookup, and it is the one signal that makes edition matching (Priority B) possible.

**A2 — Consolidate scorers (1.5 d).** One `metadata/scoring.py` with a `WeightProfile` dataclass; `matcher.py` and `cover_service.py` both consume it. Port `cover_service`'s hard title floor (0.35) and author cap into the metadata path (fixes F-15). Make ISBN a *match* signal, not a presence bonus (fixes F-14).

**A3 — Confidence-gated persistence (0.5 d).** Gate author/subtitle/ISBN writes at ≥0.60, matching the cover rule (fixes F-16). Below that, store as *suggestions* the UI can offer, never as facts.

**A4 — Language before enrichment (0.5 d).** Run `detect_language` on the first ~3k chars during upload rather than in the worker (fixes F-17); the worker can reuse it.

**A5 — Fallback ladder + Redis cache (1.5 d).** Try candidates in rank order until one scores ≥0.75. Cache provider responses keyed by normalized query, TTL 30 d (fixes F-18, F-20).

**A6 — Field expansion (1 d).** Publisher, publication year, series, edition from existing provider payloads (Google `publishedDate`/`publisher`, OL `first_publish_year`) — no new calls. Front matter (foreword/bibliography/index) belongs to Priority C, not here.

**LLM verdict: no.** For title/author/ISBN, deterministic extraction + authoritative lookup beats an LLM on accuracy, cost, latency, and determinism. An LLM adds value only for *disambiguation* — "these 3 candidates, which matches this first page?" — which is a Phase 3.2 stretch goal, not the core. **Exception:** a cheap LLM is well-suited to classifying front/back matter (is this section a foreword, index, or chapter?), and that work belongs in Priority C.

## Priority B — Cover Intelligence V3 (5 d)

**Verdict: incremental.** v2's structure is sound; it needs verification, caching, and consolidation.

- **B1 (1 d)** — **Verify the image, don't guess from the URL.** `HEAD` (or ranged `GET`) each candidate; read real dimensions via Pillow; reject <400 px wide, reject aspect ratios outside 0.55–0.80, reject known 1×1 placeholders. Replaces F-19's string heuristics with truth.
- **B2 (1 d)** — **Redis cache** keyed by `sha1(title|author|isbn|lang)`, TTL 30 d, plus a negative cache for misses (F-20).
- **B3 (1 d)** — **ISBN-first ladder**: exact ISBN → title+author → title-only, and stop as soon as a ≥0.85 candidate appears. Saves calls and improves precision (depends on A1).
- **B4 (1 d)** — **Edition consolidation**: cluster candidates by normalized title+author, keep the highest-resolution image per cluster (fixes F-21). Parse OL language properly (fixes F-22).
- **B5 (1 d)** — **Provider expansion**: add Open Library *Covers* direct ISBN endpoint and evaluate Wikidata/Wikimedia. Note that most commercial book-cover APIs prohibit redistribution — verify terms before adding any.

Target: recall ≥85% with a wrong-cover rate <3% (today: unmeasured — B0 should be a 30-book labeled fixture set, 0.5 d, to make "better" provable).

## Priority C — Chapter Engine V2 (12 d)

**Verdict: architectural rewrite of the fusion + boundary model; keep the detectors.**

- **C1 (0.5 d)** — Ship the F-1 fix (Phase 0.1) immediately; do not wait for V2.
- **C2 (2 d)** — **Character-offset boundaries.** Replace page-range chapters with `(start_char, end_char)` over a single normalized document text, retaining page numbers for display. Fixes F-6, enables mid-page chapter starts, story collections, and poetry.
- **C3 (2 d)** — **Multi-heading-per-page detection.** Scan *all* lines of every page, not the first 15, and not stopping at the first hit (`heuristic_detector.py:249`). Score each candidate by position, font ratio, whitespace above, all-caps, and line length.
- **C4 (2 d)** — **Document-type classifier** (deterministic): novel / collection / academic paper / manual / thesis / poetry, from TOC shape, heading cadence, average section length, and citation density. Each type selects a different detector weighting and plausibility envelope (a novel with 300 "chapters" is wrong; a poetry collection with 300 sections is right).
- **C5 (1.5 d)** — **Plausibility validation** replacing the current blunt coverage check: chapters per page in [0.002, 0.15], chapter length CV < 2.0, no chapter >30% of the book unless count==1. Reject and re-run with the next strategy rather than collapsing to one chapter.
- **C6 (1 d)** — **Front/back matter classification**: copyright, dedication, foreword, TOC, index, bibliography, appendix — flagged, not deleted, so the user can choose to skip them. Big perceived-quality win: audiobooks that don't start by reading the copyright page.
- **C7 (2 d)** — **Optional LLM adjudication.** *This is where an LLM genuinely earns its cost.* When C5 plausibility fails or confidence <0.6, send **only the candidate headings** (title + page + surrounding 100 chars, ~2–4k tokens for a whole book) to a small model and ask which are real chapter starts. At Haiku-class pricing this is well under $0.01 per book — negligible against $8.64 of TTS — and it runs on maybe 20% of documents. Never send the full book; never let it invent boundaries (it may only *select* from detected candidates).
- **C8 (1 d)** — **Golden corpus**: 25–30 real books (novels, Spanish, academic, collections, scanned) with hand-labeled chapter counts, wired as a CI test asserting ≥90% exact-count accuracy.

**ML/LLM verdict:** a trained ML segmenter is not worth it — insufficient labeled data and deterministic rules cover the mass of cases. Constrained LLM *adjudication* on the ambiguous tail is high-value and cheap. Build C1–C6 first; measure; then add C7 only if the corpus shows a residual failure rate above ~10%.

## Priority D — Processing Experience (8 d)

**Verdict: architectural — the state must move server-side.**

- **D1 (2 d)** — **`ProcessingSession` server state**: stage, weighted percent, chunk counts, ETA, per-stage timings. Frontend becomes a renderer of server truth. Fixes F-24.
- **D2 (2 d)** — **SSE endpoint** `GET /documents/{id}/progress/stream` replacing 2.5 s polling (F-25). Fall back to polling if EventSource fails.
- **D3 (1 d)** — **Multi-tab sync** via `BroadcastChannel` from a single leader connection.
- **D4 (1 d)** — **Global processing indicator** in `DashboardLayout` — active jobs visible from anywhere, Linear-style. Navigating away no longer feels like abandoning the job.
- **D5 (1 d)** — **Predictive ETA v2**: server already computes rate-based ETA (`documents.py:1276`); extend it with a per-stage historical model (median seconds/char per stage over the last 100 jobs) so the *analyzing* phase stops sitting silently at 14%.
- **D6 (1 d)** — **Job history** page: every attempt, duration, cost, outcome, with re-run.

**On believable progress without lying:** keep the current three-part discipline — (1) percentages derive from real counted work (`completed_chunks/total_chunks`), (2) interpolation only *animates between* confirmed values and never runs ahead of the last known target, (3) monotonic clamping. Add: when a stage has no sub-progress signal, show elapsed time and a determinate stage list rather than a moving bar. Never show a percentage the backend has not earned.

## Priority E — Cost Intelligence (5 d)

- **E1 (1 d)** — Schema: add `document_id`, `job_id`, `attempt_number`, `provider`, `voice_id`, `stage` as indexed columns on `cost_events`; backfill from JSON where possible. Unblocks cost-per-document, per-voice, per-retry.
- **E2 (0.5 d)** — Per-voice rate table replacing the single `COST_PER_CHARACTER` constant (F-12); rates in config, not code.
- **E3 (1 d)** — `CostLedger` service: single write path, called by every provider; storage and bandwidth metered too.
- **E4 (1.5 d)** — **Admin cost dashboard** built on `CostEvent` (not `ProcessingJob`): spend by day/user/provider/voice/tier, **failed-attempt spend as a first-class line item**, top-10 costliest users and documents, margin by tier using real rates.
- **E5 (0.5 d)** — **Pre-conversion estimate** surfaced in preflight ("about 6.2 hours of audio · uses 38% of your monthly allowance") and post-conversion actuals on the job.
- **E6 (0.5 d)** — **Alerting**: daily spend > 2× trailing-7-day median; any user > $5/day; global month-to-date > 70% of cap. Delivered through Sentry or a webhook — do not wait for a Prometheus stack that isn't deployed.

## Priority F — Speech Engine Strategy (6 d + 10 d pilot)

- **F1 (2 d)** — `ProviderRegistry` + `RoutingPolicy`. Voice IDs become namespaced (`google:en-US-Neural2-A`, `kokoro:af_heart`). `TTSService` resolves per call.
- **F2 (1 d)** — Per-provider circuit breaker with automatic fallback down the chain; a Google outage degrades quality instead of failing jobs.
- **F3 (1.5 d)** — `SynthesisCache`: `sha256(text|voice|rate|pitch)` → S3 key, checked before every call.
- **F4 (1.5 d)** — Tier-aware routing + honest cost attribution per provider.
- **F5 (10 d, separate)** — **Kokoro pilot**: containerized inference service with request batching, deployed on a single GPU host; route voice previews and FREE-tier jobs to it; A/B the quality with real users before widening. Success criteria: ≤$0.10/audio-hour at production utilization and no measurable drop in FREE→paid conversion.

**Explicitly not recommended now:** migrating paid tiers off Google, or self-hosting a cloning model. Revisit ElevenLabs as a **priced add-on** (a "Studio narration" upgrade at $3.30/audio-hour cost) once the registry exists — sell it, don't absorb it.

## Priority G — Voice Marketplace (6 d)

Depends on F1 (namespaced voices). Today's ceiling is one voice per language (`preflight_service.py:151`), so this is mostly greenfield.

- **G1 (1.5 d)** — `voices` table/catalog: `id, provider, language, accent, gender, age_range, styles[], quality_tier, cost_per_1m, latency_ms, preview_key, availability, min_plan_tier`. Seed from `narration_profiles.py`, which already holds trait tuples for 30+ voices.
- **G2 (1 d)** — Pre-generate previews at deploy time to S3 (replacing the per-process in-memory cache); previews become free, instant, and unauthenticated.
- **G3 (2.5 d)** — Marketplace UI: filter by language/gender/accent/style, sample-on-hover, "recommended for this book" (driven by the C4 document-type classifier), badges for premium/open-source, honest cost-per-hour display for premium voices.
- **G4 (1 d)** — Remove the dead ElevenLabs-keyword style matcher (`UploadZone.tsx:33-39`) and drive narration styles from real catalog metadata.

## Priority H — New Input Formats (11 d)

Introduce `ingest/` with a `DocumentAdapter` protocol (`extract_text`, `extract_structure`, `extract_metadata`, `extract_cover`) — the format-specific work then never touches the pipeline.

| Format | Complexity | Metadata | Chapters | Cover | Effort | Priority |
|---|---|---|---|---|---|---|
| **EPUB** | Medium | **Excellent** (OPF: title, author, ISBN, publisher, language) | **Excellent** (spine + NCX/nav = ground truth) | **Excellent** (embedded) | 6 d | **Do first** |
| TXT / Markdown | Low | Poor (filename) | Good (MD headings) | None | 2 d | Second |
| DOCX | Low–Med | Good (core.xml) | Good (Heading 1 styles) | Sometimes | 3 d | Third |
| HTML | Low | Fair (meta/OG) | Good (h1/h2) | Fair | 1 d | With TXT |
| RTF / ODT | Medium | Fair | Fair | Rare | 3 d | Later |
| MOBI / AZW3 | High | Good | Good | Good | 5 d | **Skip** — DRM, legacy, EPUB covers the need |

**EPUB is strategically the most valuable item on this entire roadmap after Phase 0.** It sidesteps every hard problem: chapter detection becomes reading the spine (no heuristics, no LLM), metadata becomes reading the OPF (no fuzzy matching, no providers), cover becomes reading a file (no Cover Intelligence). An EPUB path would produce *better* audiobooks than the PDF path at a fraction of the engineering cost — and most pirate/library ebooks that users actually own are already EPUB.

---

## Appendix — Finding index

| ID | Severity | Subsystem | Location |
|---|---|---|---|
| F-1 | **Critical** | Chapters | `fusion/confidence_scorer.py:124` |
| F-2 | **Critical** | Cost/Worker | `tasks/processing.py:190,841` |
| F-3 | **Critical** | Cost | `pricing/protection.py:87` (no callers) |
| F-4 | High | Cost | `analytics/dashboard_service.py:106` |
| F-5 | High | Chapters | `extractors/toc_extractor.py:112` |
| F-6 | Medium | Chapters | `document_structure/models.py`, `engine.py:348` |
| F-7 | Low | Debt | `document_structure/segmenter.py` (dead) |
| F-8 | High | Scalability | `tasks/processing.py:632` |
| F-9 | Medium | Audio | `services/audio/{assembler,normalizer}.py` (dead) |
| F-10 | High | Cost model | `pricing/unit_economics.py:196` |
| F-11 | Medium | Cost data | `financial/cost/cost_models.py` |
| F-12 | Medium | Cost | `services/tts/google_provider.py:51` |
| F-13–18 | Medium | Metadata | `metadata/{extractor,matcher,service}.py` |
| F-19–22 | Medium | Covers | `metadata/cover_service.py` |
| F-23–28 | Medium | Frontend | `sonoro/src/**`, `frontend/` |
| F-29–33 | Medium | Security | `routers/auth.py`, `client.ts`, `utils/file_validation.py` |

**Sources for §7 pricing and model data:**
[Google Cloud TTS pricing 2026 — TextToLab](https://texttolab.com/blog/google-cloud-tts-pricing) ·
[Google Cloud TTS pricing — diyai.io](https://diyai.io/ai-tools/audio-generation/google-cloud-text-to-speech-pricing/) ·
[TTS API pricing compared 2026 — Awesome Agents](https://awesomeagents.ai/pricing/voice-tts-pricing/) ·
[TTS API cost calculator](https://ttscost.com/) ·
[Best open-source TTS 2026 — Speakeasy](https://www.tryspeakeasy.io/blog/open-source-text-to-speech-2026) ·
[Best self-hosted TTS — Inworld](https://inworld.ai/resources/best-self-hosted-tts) ·
[Deploy open-source TTS on GPU cloud — Spheron](https://www.spheron.network/blog/deploy-open-source-tts-gpu-cloud-2026/) ·
[Kokoro vs XTTS vs Chatterbox — Local AI Master](https://localaimaster.com/blog/kokoro-vs-xtts-vs-chatterbox) ·
[Best open-source TTS: Chatterbox — FindSkill](https://findskill.ai/blog/best-open-source-tts-2026/) ·
[Best TTS for audiobooks — CodeSOTA](https://www.codesota.com/speech/best-for-audiobooks) ·
[ElevenLabs vs Google Cloud TTS — Aloa](https://aloa.co/ai/comparisons/ai-voice-comparison/elevenlabs-vs-google-cloud-tts)
