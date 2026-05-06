# BLOCK 5B: Processing Orchestration Layer - COMPLETE ✅

**Implementation Date**: February 11, 2026  
**Version**: 0.5.1  
**Status**: Production-Ready

---

## 📋 EXECUTIVE SUMMARY

Block 5B implements a **production-grade processing orchestration system** using Celery for the Sonoro SaaS platform. This is pure infrastructure - NO TTS business logic.

### Scope Discipline ✅

**IMPLEMENTED:**
- ✅ Processing job database model
- ✅ Real Celery configuration (Redis broker)
- ✅ 3-tier priority queue system
- ✅ Processing service layer
- ✅ Job creation and lifecycle management
- ✅ Celery task orchestration (simulation)
- ✅ Job cancellation and retry logic
- ✅ Concurrency limits (per-user & global)
- ✅ Prometheus metrics (6 new)
- ✅ API endpoints (5 total)
- ✅ Docker integration with real worker

**NOT IMPLEMENTED (By Design):**
- ❌ TTS processing logic
- ❌ Chapter detection
- ❌ Audio generation
- ❌ Billing integration
- ❌ Product UI
- ❌ Email notifications

---

## 🏗️ ARCHITECTURE OVERVIEW

```
┌─────────────────────────────────────────────────────────────────┐
│                  BLOCK 5B ARCHITECTURE                           │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌──────────┐      ┌──────────────┐      ┌──────────────┐     │
│  │  Client  │──────▶│   API        │──────▶│  Processing  │     │
│  │          │      │  /processing │      │   Service    │     │
│  └──────────┘      └──────────────┘      └──────────────┘     │
│                            │                      │             │
│                            │                      │             │
│                            ▼                      ▼             │
│                    ┌──────────────┐      ┌──────────────┐     │
│                    │ Validate     │      │  Create Job  │     │
│                    │ • Document   │      │  Record      │     │
│                    │ • Ownership  │      │  in DB       │     │
│                    │ • Limits     │      └──────────────┘     │
│                    └──────────────┘              │             │
│                                                  │             │
│                                                  ▼             │
│                                          ┌──────────────┐     │
│                                          │  Enqueue to  │     │
│                                          │    Celery    │     │
│                                          └──────────────┘     │
│                                                  │             │
│                                                  │             │
│                      ┌───────────────────────────┼─────┐      │
│                      │        Redis Broker       │     │      │
│                      │  ┌──────────┬──────────┬──────────┐   │
│                      │  │   High   │  Normal  │   Low    │   │
│                      │  │ Priority │   Queue  │ Priority │   │
│                      │  └──────────┴──────────┴──────────┘   │
│                      └───────────────────────────────────┘    │
│                                     │                          │
│                                     │                          │
│                                     ▼                          │
│                      ┌───────────────────────────┐            │
│                      │   Celery Worker Pool      │            │
│                      │  ┌─────────┐ ┌─────────┐ │            │
│                      │  │Worker 1 │ │Worker 2 │ │            │
│                      │  └─────────┘ └─────────┘ │            │
│                      └───────────────────────────┘            │
│                                     │                          │
│                                     │                          │
│                                     ▼                          │
│                      ┌───────────────────────────┐            │
│                      │  process_document_job()   │            │
│                      │  • Update status          │            │
│                      │  • Track progress         │            │
│                      │  • Simulate processing    │            │
│                      │  • Handle errors/retry    │            │
│                      └───────────────────────────┘            │
│                                     │                          │
│                                     │                          │
│                                     ▼                          │
│                             ┌───────────────┐                 │
│                             │   PostgreSQL  │                 │
│                             │ processing_   │                 │
│                             │    jobs       │                 │
│                             └───────────────┘                 │
│                                                                │
└────────────────────────────────────────────────────────────────┘

Integration Points:
├── Block 2: Authentication (user verification)
├── Block 3B: Observability (Prometheus metrics)
├── Block 3C: Cost Governance (job limits)
├── Block 4: Activity Logging (job events)
└── Block 5A: Document Storage (document validation)
```

---

## 📊 DATABASE SCHEMA

### `processing_jobs` Table

```sql
CREATE TABLE processing_jobs (
    -- Identity
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    
    -- Job Configuration
    job_type jobtype NOT NULL DEFAULT 'full_process',
    priority INTEGER NOT NULL DEFAULT 5 CHECK (priority >= 1 AND priority <= 10),
    
    -- Status Tracking
    status jobstatus NOT NULL DEFAULT 'queued',
    progress_percentage INTEGER NOT NULL DEFAULT 0 CHECK (progress_percentage >= 0 AND progress_percentage <= 100),
    
    -- Error Handling
    error_message TEXT,
    retry_count INTEGER NOT NULL DEFAULT 0,
    
    -- Celery Integration
    celery_task_id VARCHAR(255),
    
    -- Timestamps
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    cancelled_at TIMESTAMP
);

-- Enums
CREATE TYPE jobtype AS ENUM ('full_process', 'preview', 'reprocess');
CREATE TYPE jobstatus AS ENUM ('queued', 'processing', 'completed', 'failed', 'cancelled');

-- Indexes (11 total)
CREATE INDEX ix_processing_jobs_id ON processing_jobs(id);
CREATE INDEX ix_processing_jobs_document_id ON processing_jobs(document_id);
CREATE INDEX ix_processing_jobs_user_id ON processing_jobs(user_id);
CREATE INDEX ix_processing_jobs_job_type ON processing_jobs(job_type);
CREATE INDEX ix_processing_jobs_status ON processing_jobs(status);
CREATE INDEX ix_processing_jobs_created_at ON processing_jobs(created_at);
CREATE INDEX ix_processing_jobs_celery_task_id ON processing_jobs(celery_task_id);

-- Composite indexes for common queries
CREATE INDEX idx_processing_jobs_user_created ON processing_jobs(user_id, created_at);
CREATE INDEX idx_processing_jobs_user_status ON processing_jobs(user_id, status);
CREATE INDEX idx_processing_jobs_status_created ON processing_jobs(status, created_at);
CREATE INDEX idx_processing_jobs_document_status ON processing_jobs(document_id, status);
```

---

## 🔌 API ENDPOINTS

### Base Path: `/api/v1/processing`

All endpoints require authentication.

### 1. Create Processing Job

```http
POST /api/v1/processing/documents/{document_id}/process
Content-Type: application/json

{
  "job_type": "full_process",
  "priority": 5
}
```

**Job Types:**
- `full_process`: Complete processing pipeline (default)
- `preview`: Quick preview (future use)
- `reprocess`: Reprocess existing job

**Priority:**
- 1-3: High priority → `high_priority` queue
- 4-7: Normal priority → `normal` queue (default)
- 8-10: Low priority → `low_priority` queue

**Response** (201 Created):
```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "document_id": "660e8400-e29b-41d4-a716-446655440001",
  "user_id": "770e8400-e29b-41d4-a716-446655440002",
  "job_type": "full_process",
  "status": "queued",
  "priority": 5,
  "progress_percentage": 0,
  "error_message": null,
  "retry_count": 0,
  "celery_task_id": "550e8400-e29b-41d4-a716-446655440000",
  "created_at": "2026-02-11T18:30:00Z",
  "started_at": null,
  "completed_at": null,
  "is_active": true,
  "is_terminal": false,
  "is_cancellable": true
}
```

**Validation:**
- Document must exist and belong to user
- Document must be uploaded successfully
- Document not already processing
- User concurrent job limit: 3
- Global active job limit: 100

---

### 2. Get Job Status

```http
GET /api/v1/processing/jobs/{job_id}
```

**Response** (200 OK):
```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "document_id": "660e8400-e29b-41d4-a716-446655440001",
  "user_id": "770e8400-e29b-41d4-a716-446655440002",
  "job_type": "full_process",
  "status": "processing",
  "priority": 5,
  "progress_percentage": 45,
  "error_message": null,
  "retry_count": 0,
  "celery_task_id": "550e8400-e29b-41d4-a716-446655440000",
  "created_at": "2026-02-11T18:30:00Z",
  "started_at": "2026-02-11T18:30:05Z",
  "completed_at": null,
  "cancelled_at": null,
  "is_active": true,
  "is_terminal": false,
  "is_cancellable": true,
  "duration_seconds": null,
  "document_filename": "my_document.pdf"
}
```

---

### 3. List Jobs

```http
GET /api/v1/processing/jobs?page=1&page_size=20&status=processing
```

**Query Parameters:**
- `page` (default: 1): Page number
- `page_size` (default: 20, max: 100): Items per page
- `status` (optional): Filter by job status

**Response** (200 OK):
```json
{
  "jobs": [
    {
      "id": "550e8400-e29b-41d4-a716-446655440000",
      "document_id": "660e8400-e29b-41d4-a716-446655440001",
      "job_type": "full_process",
      "status": "processing",
      "priority": 5,
      "progress_percentage": 45,
      "retry_count": 0,
      "created_at": "2026-02-11T18:30:00Z",
      "started_at": "2026-02-11T18:30:05Z",
      "completed_at": null,
      "is_active": true
    }
  ],
  "total": 5,
  "page": 1,
  "page_size": 20,
  "has_more": false
}
```

---

### 4. Cancel Job

```http
DELETE /api/v1/processing/jobs/{job_id}
```

**Response** (200 OK):
```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "cancelled",
  "message": "Job cancelled successfully",
  "cancelled_at": "2026-02-11T18:35:00Z"
}
```

**Actions:**
- Revokes Celery task (terminates if running)
- Updates job status to CANCELLED
- Resets document processing status

**Requirements:**
- Job must be in QUEUED or PROCESSING status

---

### 5. Get Queue Depth

```http
GET /api/v1/processing/queue/depth
```

**Response** (200 OK):
```json
{
  "queued_jobs": 12,
  "processing_jobs": 3,
  "total_active": 15
}
```

---

## ⚙️ CELERY CONFIGURATION

### Broker & Backend
- **Broker**: Redis (dedicated database 1)
- **Result Backend**: Redis
- **Serializer**: JSON

### Queue System

```python
# 3-Tier Priority System
high_priority  # Priority 1-3 jobs
normal         # Priority 4-7 jobs (default)
low_priority   # Priority 8-10 jobs
```

### Worker Configuration

```bash
celery -A app.celery_app worker \
  --loglevel=info \
  --concurrency=2 \
  --max-tasks-per-child=100 \
  --queues=high_priority,normal,low_priority
```

**Settings:**
- Concurrency: 2 workers per container
- Task limit: 1000 tasks per worker (then recycle)
- Prefetch: 1 task at a time
- Acks: Late acknowledgment
- Time limits: 1 hour hard, 55 minutes soft
- Retry: Max 3 attempts with exponential backoff

### Task Retry Strategy

```python
autoretry_for = (Exception,)
max_retries = 3
retry_backoff = True
retry_backoff_max = 600  # 10 minutes
retry_jitter = True
```

---

## 📈 PROMETHEUS METRICS

### New Metrics (6 total)

```python
# Job Tracking
sonoro_processing_jobs_total{status}
sonoro_processing_failures_total{failure_reason}

# Performance
sonoro_processing_job_duration_seconds{job_type}

# Queue Management
sonoro_processing_queue_depth
sonoro_processing_active_jobs

# Retry Tracking
sonoro_processing_retry_count{job_type}
```

**Example Queries**:

```promql
# Job success rate
rate(sonoro_processing_jobs_total{status="completed"}[5m]) / 
  rate(sonoro_processing_jobs_total[5m])

# Average job duration
histogram_quantile(0.95, 
  rate(sonoro_processing_job_duration_seconds_bucket[5m]))

# Queue backlog
sonoro_processing_queue_depth

# Active processing
sonoro_processing_active_jobs

# Failure rate
rate(sonoro_processing_failures_total[5m])
```

---

## 🔧 IMPLEMENTATION DETAILS

### Files Created (9 files)

1. **Database Model**
   - `app/db/models/processing_job.py` (214 lines)
   - ProcessingJob, JobType, JobStatus enums
   - Complete lifecycle tracking
   - Computed properties

2. **Pydantic Schemas**
   - `app/schemas/processing.py` (302 lines)
   - Request/response schemas
   - Validation logic
   - Documentation examples

3. **Celery Configuration**
   - `app/celery_app.py` (209 lines)
   - Enterprise Celery setup
   - Queue routing logic
   - Signal handlers
   - Utility functions

4. **Celery Tasks**
   - `app/tasks/__init__.py` (16 lines)
   - `app/tasks/processing.py` (282 lines)
   - Orchestration task (simulation for Block 5B)
   - Async database operations
   - Progress tracking
   - Error handling

5. **Processing Service**
   - `app/services/processing_service.py` (489 lines)
   - Job creation and validation
   - Concurrency enforcement
   - Lifecycle management
   - CRUD operations

6. **API Router**
   - `app/routers/processing.py` (290 lines)
   - 5 production endpoints
   - Activity logging
   - Metrics integration

7. **Worker Entrypoint**
   - `services/worker/worker.py` (35 lines)
   - Real Celery worker starter

8. **Database Migration**
   - `alembic/versions/006_processing_jobs.py` (144 lines)
   - Creates processing_jobs table
   - Creates enums
   - Adds 11 indexes

9. **Documentation**
   - This file (you're reading it!)

### Files Modified (7 files)

1. `app/db/models/__init__.py` - Export ProcessingJob
2. `app/db/models/document.py` - Add processing_jobs relationship
3. `app/db/models/user.py` - Add processing_jobs relationship
4. `app/financial/financial_metrics.py` - 6 new metrics
5. `app/main.py` - Register processing router (v0.5.1)
6. `services/api/requirements.txt` - Add Celery
7. `services/worker/requirements.txt` - Add Celery
8. `docker-compose.yml` - Real worker command
9. `infra/docker/worker.Dockerfile` - Production worker config

**Total Lines**: ~2,000 lines of production code

---

## 🧪 TESTING

### Manual Testing

**1. Start Services**:
```bash
cd /Users/servinemilio/audiolibro-pdf
make build
make dev
```

**2. Run Migration**:
```bash
make migrate
```

**3. Check Worker is Running**:
```bash
docker-compose logs -f worker
```

You should see:
```
Celery worker starting...
Tasks imported and registered
celery@worker ready.
```

**4. Upload a Document**:
```bash
TOKEN=$(curl -s -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=test@sonoro.com&password=TestPass123!" \
  | jq -r '.access_token')

DOCUMENT_ID=$(curl -s -X POST http://localhost:8000/api/v1/documents/upload \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@/path/to/document.pdf" \
  | jq -r '.id')

echo "Document ID: $DOCUMENT_ID"
```

**5. Create Processing Job**:
```bash
JOB_ID=$(curl -s -X POST \
  "http://localhost:8000/api/v1/processing/documents/$DOCUMENT_ID/process" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"job_type": "full_process", "priority": 5}' \
  | jq -r '.id')

echo "Job ID: $JOB_ID"
```

**6. Watch Progress**:
```bash
# Watch job progress
watch -n 2 "curl -s http://localhost:8000/api/v1/processing/jobs/$JOB_ID \
  -H 'Authorization: Bearer $TOKEN' | jq '.progress_percentage, .status'"
```

**7. Check Celery Worker Logs**:
```bash
docker-compose logs -f worker
```

You should see:
```
Task started: process_document_job
Processing job {job_id} for document {filename}
Job {job_id} progress: 10%
Job {job_id} progress: 20%
...
Job {job_id} progress: 100%
Processing job completed successfully
```

**8. List Jobs**:
```bash
curl http://localhost:8000/api/v1/processing/jobs \
  -H "Authorization: Bearer $TOKEN" | jq
```

**9. Check Queue Depth**:
```bash
curl http://localhost:8000/api/v1/processing/queue/depth \
  -H "Authorization: Bearer $TOKEN" | jq
```

**10. Check Metrics**:
```bash
curl -s http://localhost:8000/metrics | grep sonoro_processing
```

---

## 🎯 SUCCESS CRITERIA CHECKLIST

### Core Functionality ✅
- [x] Processing job database model created
- [x] Real Celery configuration implemented
- [x] 3-tier priority queue system
- [x] Job creation with validation
- [x] Job status tracking and updates
- [x] Progress percentage updates
- [x] Job cancellation
- [x] Celery task orchestration
- [x] Retry logic with exponential backoff

### Validation & Limits ✅
- [x] Document ownership verification
- [x] Document upload status check
- [x] Prevent duplicate processing
- [x] User concurrent job limit (3)
- [x] Global active job limit (100)

### Integration ✅
- [x] Activity logging
- [x] Prometheus metrics (6 new)
- [x] Structured logging
- [x] Error tracking
- [x] Document status updates

### Infrastructure ✅
- [x] Real Celery worker container
- [x] Docker healthcheck
- [x] Redis broker
- [x] Queue routing
- [x] Worker concurrency control

### Scope Discipline ✅
- [x] NO TTS implementation
- [x] NO chapter detection
- [x] NO audio generation
- [x] NO billing logic
- [x] NO product UI
- [x] Pure orchestration only

---

## 🔒 CONCURRENCY CONTROLS

### Per-User Limits

```python
MAX_CONCURRENT_JOBS_PER_USER = 3
```

**Reason**: Prevent single user from monopolizing resources

**Enforcement**: Checked before job creation

**Error**: `429 Too Many Requests`

### Global Limits

```python
MAX_GLOBAL_ACTIVE_JOBS = 100
```

**Reason**: System capacity protection

**Enforcement**: Checked before job creation

**Error**: `503 Service Unavailable`

### Idempotency

**Document-level**: One active job per document at a time

**Check**: Before job creation

**Error**: `409 Conflict`

---

## 🔄 JOB LIFECYCLE

```
┌─────────────┐
│   QUEUED    │ ← Job created, enqueued to Celery
└──────┬──────┘
       │
       ▼
┌─────────────┐
│ PROCESSING  │ ← Worker picked up, started execution
└──────┬──────┘
       │
       ├─────────────────┐
       │                 │
       ▼                 ▼
┌─────────────┐   ┌─────────────┐
│  COMPLETED  │   │   FAILED    │ ← Max retries exceeded
└─────────────┘   └─────────────┘

       OR (user action)
       │
       ▼
┌─────────────┐
│  CANCELLED  │ ← User cancelled via DELETE endpoint
└─────────────┘
```

### Status Transitions

1. **Created**: `QUEUED`
2. **Worker picks up**: `QUEUED` → `PROCESSING`
3. **Success**: `PROCESSING` → `COMPLETED`
4. **Failure (retry)**: `PROCESSING` → `QUEUED` (retry_count++)
5. **Failure (final)**: `PROCESSING` → `FAILED`
6. **User cancels**: `QUEUED|PROCESSING` → `CANCELLED`

---

## 📝 TASK SIMULATION (Block 5B Only)

The current `process_document_job` task is a **simulation** for Block 5B:

```python
# Simulated processing (20 seconds total)
total_steps = 10
for step in range(1, total_steps + 1):
    await asyncio.sleep(2)  # Simulate work
    progress = int((step / total_steps) * 100)
    job.progress_percentage = progress
    await session.commit()
```

**In Block 6 (TTS Engine)**, this will be replaced with:
- PDF parsing
- Chapter detection
- TTS generation
- Audio assembly
- File storage

**The orchestration infrastructure is ready** - just plug in the business logic.

---

## 🔧 CONFIGURATION

### Environment Variables

```bash
# Celery Configuration
CELERY_BROKER_URL=redis://redis:6379/1
CELERY_RESULT_BACKEND=redis://redis:6379/1

# Processing Limits
MAX_CONCURRENT_JOBS_PER_USER=3
MAX_GLOBAL_ACTIVE_JOBS=100
```

### Redis Setup

**Database Allocation**:
- DB 0: API cache & rate limiting
- DB 1: Celery broker & results ← **Block 5B**

### Worker Scaling

**Development**:
```bash
--concurrency=2  # 2 worker processes
```

**Production**:
```bash
--concurrency=4  # Scale based on CPU cores
--autoscale=10,3  # Min 3, max 10 workers
```

---

## 🚀 NEXT STEPS

### Immediate Actions

1. **Run Migration**:
   ```bash
   make migrate
   ```

2. **Rebuild Containers**:
   ```bash
   make build
   make restart
   ```

3. **Verify Worker**:
   ```bash
   docker-compose logs -f worker
   # Should see: "celery@worker ready."
   ```

4. **Test Processing**:
   - Upload document
   - Create processing job
   - Watch progress
   - Check metrics

### Future Enhancements (Block 6+)

1. **TTS Integration**:
   - Replace simulation with real TTS
   - Add provider selection
   - Voice configuration
   - Cost tracking

2. **Advanced Features**:
   - Chapter detection
   - Audio assembly
   - Format conversion
   - Download URLs

3. **Monitoring**:
   - Celery Flower (web UI)
   - Dead letter queue
   - Task monitoring dashboard
   - Alert rules

4. **Performance**:
   - Task result compression
   - Worker auto-scaling
   - Queue prioritization tuning
   - Resource optimization

---

## 🎉 BLOCK 5B SUMMARY

**Status**: ✅ **COMPLETE**

**Delivered**:
- 9 new files created
- 9 files modified
- 1 database migration
- 5 API endpoints
- 6 Prometheus metrics
- Real Celery integration
- Complete documentation

**Lines of Code**: ~2,000 lines

**Key Achievement**: Production-ready processing orchestration system with enterprise-grade queue management, retry logic, and monitoring.

**Integration**: Seamlessly integrated with Blocks 1-5A, ready for Block 6 (TTS Engine).

**Scope Discipline**: Zero feature creep - pure infrastructure as specified.

---

*End of BLOCK 5B Documentation*
