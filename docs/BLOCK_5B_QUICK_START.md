# BLOCK 5B: Quick Start Guide

## 🚀 Getting Started

### 1. Run Database Migration

```bash
cd /Users/servinemilio/audiolibro-pdf
make migrate
```

Or manually:
```bash
docker-compose exec api alembic upgrade head
```

### 2. Rebuild Containers (Celery Integration)

```bash
make build
make restart
```

### 3. Verify Celery Worker

```bash
docker-compose logs -f worker
```

**Expected output**:
```
Celery worker starting...
Broker URL: redis://redis:6379/1
Tasks imported and registered
 
 -------------- celery@worker v5.3.6 (emerald-rush)
--- ***** ----- 
-- ******* ---- Linux-6.1.0-...
- *** --- * --- 
- ** ---------- [config]
- ** ---------- .> app:         sonoro_worker:0x...
- ** ---------- .> transport:   redis://redis:6379/1
- ** ---------- .> results:     redis://redis:6379/1
- *** --- * --- .> concurrency: 2 (prefork)
-- ******* ---- .> task events: ON
--- ***** ----- 
 -------------- [queues]
                .> high_priority    exchange=sonoro routing_key=high_priority
                .> normal           exchange=sonoro routing_key=normal
                .> low_priority     exchange=sonoro routing_key=low_priority

[tasks]
  . app.tasks.processing.cleanup_stale_jobs
  . app.tasks.processing.process_document_job
  . app.tasks.processing.update_queue_metrics
  . health_check

[2026-02-11 18:00:00,000: INFO/MainProcess] Connected to redis://redis:6379/1
[2026-02-11 18:00:00,000: INFO/MainProcess] celery@worker ready.
```

### 4. Test the Processing Pipeline

**Step 1: Login**
```bash
TOKEN=$(curl -s -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=test@sonoro.com&password=TestPass123!" \
  | jq -r '.access_token')

echo "Token: $TOKEN"
```

**Step 2: Upload Document**
```bash
DOCUMENT_ID=$(curl -s -X POST http://localhost:8000/api/v1/documents/upload \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@/path/to/your/document.pdf" \
  | jq -r '.id')

echo "Document ID: $DOCUMENT_ID"
```

**Step 3: Create Processing Job**
```bash
JOB_ID=$(curl -s -X POST \
  "http://localhost:8000/api/v1/processing/documents/$DOCUMENT_ID/process" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "job_type": "full_process",
    "priority": 5
  }' | jq -r '.id')

echo "Job ID: $JOB_ID"
```

**Step 4: Watch Progress**
```bash
# Poll every 2 seconds
watch -n 2 "curl -s http://localhost:8000/api/v1/processing/jobs/$JOB_ID \
  -H 'Authorization: Bearer $TOKEN' \
  | jq '{status, progress: .progress_percentage, started_at, completed_at}'"
```

Expected progression:
```json
{"status": "queued", "progress": 0, "started_at": null, "completed_at": null}
{"status": "processing", "progress": 10, "started_at": "2026-02-11T18:01:05Z", "completed_at": null}
{"status": "processing", "progress": 20, "started_at": "2026-02-11T18:01:05Z", "completed_at": null}
...
{"status": "processing", "progress": 90, "started_at": "2026-02-11T18:01:05Z", "completed_at": null}
{"status": "completed", "progress": 100, "started_at": "2026-02-11T18:01:05Z", "completed_at": "2026-02-11T18:01:25Z"}
```

**Step 5: Check Worker Logs**
```bash
docker-compose logs -f worker
```

You should see:
```
Task started: process_document_job
Processing job {job_id} for document {filename}
Job {job_id} progress: 10%
Job {job_id} progress: 20%
Job {job_id} progress: 30%
...
Job {job_id} progress: 100%
Processing job completed successfully
Task completed: process_document_job
```

---

## 📋 New Endpoints

All under `/api/v1/processing/`:

1. **POST /documents/{id}/process** - Create processing job
2. **GET /jobs/{id}** - Get job status
3. **GET /jobs** - List user jobs (paginated)
4. **DELETE /jobs/{id}** - Cancel job
5. **GET /queue/depth** - Get queue statistics

---

## 🧪 Testing Different Scenarios

### Test Concurrent Job Limit

Create 4 jobs (limit is 3):

```bash
for i in {1..4}; do
  curl -X POST \
    "http://localhost:8000/api/v1/processing/documents/$DOCUMENT_ID/process" \
    -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    -d '{"job_type": "full_process", "priority": 5}'
  echo ""
done
```

**Expected**: First 3 succeed, 4th returns `429 Too Many Requests`

### Test Priority Queues

```bash
# High priority (queue: high_priority)
curl -X POST \
  "http://localhost:8000/api/v1/processing/documents/$DOCUMENT_ID/process" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"job_type": "full_process", "priority": 1}'

# Normal priority (queue: normal)
curl -X POST \
  "http://localhost:8000/api/v1/processing/documents/$DOCUMENT_ID/process" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"job_type": "full_process", "priority": 5}'

# Low priority (queue: low_priority)
curl -X POST \
  "http://localhost:8000/api/v1/processing/documents/$DOCUMENT_ID/process" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"job_type": "full_process", "priority": 9}'
```

### Test Job Cancellation

```bash
# Create job
JOB_ID=$(curl -s -X POST \
  "http://localhost:8000/api/v1/processing/documents/$DOCUMENT_ID/process" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"job_type": "full_process", "priority": 5}' \
  | jq -r '.id')

# Cancel it quickly (while queued or processing)
curl -X DELETE \
  "http://localhost:8000/api/v1/processing/jobs/$JOB_ID" \
  -H "Authorization: Bearer $TOKEN" | jq
```

### Test Queue Depth

```bash
curl http://localhost:8000/api/v1/processing/queue/depth \
  -H "Authorization: Bearer $TOKEN" | jq
```

Expected:
```json
{
  "queued_jobs": 2,
  "processing_jobs": 1,
  "total_active": 3
}
```

---

## 📊 Check Metrics

```bash
curl -s http://localhost:8000/metrics | grep sonoro_processing
```

Expected output:
```
# HELP sonoro_processing_jobs_total Total processing jobs by status
# TYPE sonoro_processing_jobs_total counter
sonoro_processing_jobs_total{status="created"} 5.0
sonoro_processing_jobs_total{status="completed"} 3.0
sonoro_processing_jobs_total{status="cancelled"} 1.0

# HELP sonoro_processing_queue_depth Number of jobs in processing queue
# TYPE sonoro_processing_queue_depth gauge
sonoro_processing_queue_depth 2.0

# HELP sonoro_processing_active_jobs Number of currently active processing jobs
# TYPE sonoro_processing_active_jobs gauge
sonoro_processing_active_jobs 2.0

# HELP sonoro_processing_job_duration_seconds Processing job duration in seconds
# TYPE sonoro_processing_job_duration_seconds histogram
sonoro_processing_job_duration_seconds_bucket{job_type="full_process",le="10"} 0.0
sonoro_processing_job_duration_seconds_bucket{job_type="full_process",le="30"} 3.0
...
```

---

## 🔍 Verification Checklist

- [ ] Database migration ran successfully
- [ ] `processing_jobs` table exists
- [ ] Celery worker started and shows "ready"
- [ ] 3 queues visible (high_priority, normal, low_priority)
- [ ] Can create processing job
- [ ] Job status changes: queued → processing → completed
- [ ] Progress updates from 0% to 100%
- [ ] Can cancel queued job
- [ ] Can list user jobs
- [ ] Queue depth endpoint works
- [ ] Metrics appear in `/metrics` endpoint
- [ ] Worker logs show task execution
- [ ] Activity logged in `user_activity_log` table

---

## 🐛 Troubleshooting

### Worker Not Starting

**Check logs**:
```bash
docker-compose logs worker
```

**Common issues**:
- Missing Celery dependencies (rebuild: `make build`)
- Redis not accessible (check `CELERY_BROKER_URL`)
- Import errors (check Python path)

**Solution**:
```bash
make build
make restart
```

### Job Stuck in QUEUED

**Check worker is running**:
```bash
docker-compose ps | grep worker
```

**Check worker can connect to Redis**:
```bash
docker-compose exec worker celery -A app.celery_app inspect ping
```

Expected: `pong`

**Check queues**:
```bash
docker-compose exec worker celery -A app.celery_app inspect active
```

### Job Fails Immediately

**Check worker logs**:
```bash
docker-compose logs -f worker
```

**Check job details**:
```bash
curl http://localhost:8000/api/v1/processing/jobs/$JOB_ID \
  -H "Authorization: Bearer $TOKEN" | jq '.error_message'
```

### "429 Too Many Requests"

You've hit the concurrent job limit (3 per user).

**Check active jobs**:
```bash
curl "http://localhost:8000/api/v1/processing/jobs?status=processing" \
  -H "Authorization: Bearer $TOKEN" | jq '.total'
```

**Wait for jobs to complete** or **cancel some jobs**.

---

## 📚 Documentation

- **Full Documentation**: `docs/BLOCK_5B_COMPLETE.md`
- **API Docs**: http://localhost:8000/docs
- **Metrics**: http://localhost:8000/metrics

---

## ✅ Success Criteria

You've successfully completed Block 5B when:

1. ✅ Celery worker is running
2. ✅ Can create processing job
3. ✅ Job status updates automatically
4. ✅ Progress increases from 0% to 100%
5. ✅ Job completes successfully
6. ✅ Can cancel active job
7. ✅ Queue depth tracking works
8. ✅ Metrics show in Prometheus

---

## 🎯 What's Next?

**Block 6** (TTS Engine):
- Real PDF parsing
- Chapter detection
- TTS provider integration
- Audio generation
- Format conversion

**Block 7** (Billing & Payments):
- Stripe integration
- Subscription management
- Usage-based billing
- Invoice generation

---

*For detailed implementation details, see `docs/BLOCK_5B_COMPLETE.md`*
