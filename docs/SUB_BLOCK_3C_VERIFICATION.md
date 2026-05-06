# SUB-BLOCK 3C: Verification Checklist

## Pre-Verification Setup

### 1. Start Docker Services
```bash
docker-compose up -d postgres redis
```

### 2. Verify Services Are Running
```bash
docker-compose ps

# Expected output:
# - postgres: Up
# - redis: Up
```

### 3. Run Database Migration
```bash
cd services/api
alembic upgrade head
```

**Expected Output**:
```
INFO  [alembic.runtime.migration] Running upgrade 002_add_auth_fields -> 003_cost_governance
```

---

## Component Verification

### ✅ Database Tables

```bash
# Check tables were created
docker-compose exec postgres psql -U sonoro -d sonoro -c "
SELECT table_name 
FROM information_schema.tables 
WHERE table_schema = 'public' 
AND table_name IN ('cost_events', 'usage_quotas')
ORDER BY table_name;
"
```

**Expected Output**:
```
 table_name    
---------------
 cost_events
 usage_quotas
```

### ✅ User Model Update

```bash
# Check plan_tier column was added
docker-compose exec postgres psql -U sonoro -d sonoro -c "
SELECT column_name, data_type, column_default 
FROM information_schema.columns 
WHERE table_name = 'users' AND column_name = 'plan_tier';
"
```

**Expected Output**:
```
 column_name |     data_type      | column_default 
-------------+--------------------+----------------
 plan_tier   | character varying  | 'FREE'::...
```

### ✅ Cost Events Table Structure

```bash
docker-compose exec postgres psql -U sonoro -d sonoro -c "\d cost_events"
```

**Expected Columns**:
- id (uuid)
- user_id (uuid)
- event_type (enum)
- provider (enum)
- quantity (float)
- unit_cost (float)
- total_cost (float)
- metadata (json)
- created_at (timestamp)

**Expected Indexes**:
- idx_user_created
- idx_event_type_created
- idx_provider_created

### ✅ Usage Quotas Table Structure

```bash
docker-compose exec postgres psql -U sonoro -d sonoro -c "\d usage_quotas"
```

**Expected Columns**:
- id (uuid)
- user_id (uuid, unique)
- period_start (timestamp)
- period_end (timestamp)
- characters_used (integer)
- jobs_created (integer)
- storage_used_mb (float)
- api_calls (integer)
- created_at (timestamp)
- updated_at (timestamp)

---

## Module Import Verification

### ✅ Financial Module Imports

```bash
cd services/api

# Test imports (requires Python environment)
python3 -c "
from app.financial import (
    CostEventType, CostProvider, ActionType,
    PlanTier, QuotaService, QuotaExceeded,
    RateLimitService, RateLimitTier,
    AbuseDetector, AbusePattern
)
print('✅ All imports successful')
"
```

---

## API Endpoint Verification

### ✅ Start API Server

```bash
docker-compose up -d api
```

### ✅ Test Health Endpoint

```bash
curl http://localhost:8000/api/v1/health
```

**Expected Output**:
```json
{
  "status": "healthy",
  "timestamp": "...",
  "services": {
    "database": "healthy",
    "redis": "healthy"
  }
}
```

### ✅ Test Metrics Endpoint

```bash
curl http://localhost:8000/metrics | grep sonoro_cost
```

**Expected Metrics**:
```
sonoro_cost_total
sonoro_cost_per_user
sonoro_estimated_cost_total
sonoro_cost_events_total
sonoro_monthly_cost_usd
sonoro_quota_remaining
sonoro_quota_usage_percentage
```

### ✅ Test Admin Financial Endpoints (Requires Admin Token)

```bash
# Get admin token first
ADMIN_TOKEN=$(curl -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@sonoro.com","password":"admin123"}' \
  | jq -r '.access_token')

# Test cost overview
curl -X GET "http://localhost:8000/api/v1/admin/financial/cost/overview?days=30" \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

**Expected Output**:
```json
{
  "period": "current_month",
  "days_analyzed": 30,
  "monthly_summary": {
    "total_cost_usd": 0.0,
    "by_event_type": {},
    "by_provider": {}
  },
  "daily_trend": [],
  "accessed_by": "admin@sonoro.com",
  "accessed_at": "..."
}
```

---

## Functional Testing

### ✅ Test Cost Tracking

Create file: `tests/test_cost_tracking.py`

```python
import pytest
from uuid import uuid4
from app.financial import CostTracker, CostEventType, CostProvider

@pytest.mark.asyncio
async def test_track_cost_event(db_session):
    tracker = CostTracker(db_session)
    user_id = uuid4()
    
    # Track an event
    await tracker.track_event(
        user_id=user_id,
        event_type=CostEventType.TTS_GENERATION,
        provider=CostProvider.ELEVEN_LABS,
        quantity=1000,
        unit_cost=0.00003,
    )
    
    await db_session.commit()
    
    # Verify monthly cost
    monthly = await tracker.get_user_monthly_cost(user_id)
    assert monthly['total_cost_usd'] == 0.03
```

Run test:
```bash
cd services/api
pytest tests/test_cost_tracking.py -v
```

### ✅ Test Quota Enforcement

Create file: `tests/test_quota_enforcement.py`

```python
import pytest
from uuid import uuid4
from app.financial import QuotaService, ActionType, PlanTier, QuotaExceeded

@pytest.mark.asyncio
async def test_quota_check(db_session):
    service = QuotaService(db_session)
    user_id = uuid4()
    
    # Should allow within limit
    await service.check_quota(
        user_id=user_id,
        plan_tier=PlanTier.FREE,
        action=ActionType.TTS_GENERATION,
        quantity=100,
    )
    
    # Should raise on exceeding
    with pytest.raises(QuotaExceeded):
        await service.check_quota(
            user_id=user_id,
            plan_tier=PlanTier.FREE,
            action=ActionType.TTS_GENERATION,
            quantity=999999,
        )
```

Run test:
```bash
cd services/api
pytest tests/test_quota_enforcement.py -v
```

### ✅ Test Rate Limiting

Create file: `tests/test_rate_limiting.py`

```python
import pytest
from app.financial import RateLimitService, RateLimitTier, RateLimitExceeded

@pytest.mark.asyncio
async def test_rate_limit(redis_client):
    service = RateLimitService(redis_client)
    user_id = "test_user"
    
    # First request should succeed
    await service.check_rate_limit(
        user_id=user_id,
        tier=RateLimitTier.API,
    )
    
    # Get limits
    limits = await service.get_limits(user_id, RateLimitTier.API)
    assert limits['minute']['limit'] == 60
    assert limits['minute']['used'] == 1
```

Run test:
```bash
cd services/api
pytest tests/test_rate_limiting.py -v
```

---

## Configuration Verification

### ✅ Environment Variables

Check `.env` file contains:

```bash
# Cost Governance
HARD_COST_LIMIT_ENABLED=false
GLOBAL_MONTHLY_COST_CAP=10000.0
USER_MONTHLY_COST_CAP=1000.0
EMERGENCY_SHUTDOWN_MODE=false
COST_ALERT_THRESHOLD_PERCENTAGE=80.0

# Abuse Detection
ABUSE_DETECTION_ENABLED=true
ABUSE_CHECK_INTERVAL_MINUTES=15
```

### ✅ Config Loading

```python
from app.core.config import settings

print(f"Cost cap: ${settings.global_monthly_cost_cap}")
print(f"Hard limits: {settings.hard_cost_limit_enabled}")
print(f"Abuse detection: {settings.abuse_detection_enabled}")
```

---

## Redis Verification

### ✅ Redis Connection

```bash
docker-compose exec redis redis-cli PING
```

**Expected**: `PONG`

### ✅ Rate Limit Keys

```bash
# After making some API requests
docker-compose exec redis redis-cli KEYS "ratelimit:*"
```

**Expected**: List of rate limit keys

### ✅ Abuse Detection Keys

```bash
docker-compose exec redis redis-cli KEYS "abuse:*"
```

---

## Documentation Verification

### ✅ Files Created

Check these files exist:

- [ ] `docs/SUB_BLOCK_3C_COMPLETE.md`
- [ ] `docs/COST_GOVERNANCE_GUIDE.md`
- [ ] `docs/SUB_BLOCK_3C_SUMMARY.md`
- [ ] `app/financial/__init__.py`
- [ ] `app/financial/financial_metrics.py`
- [ ] `app/financial/cost/cost_enums.py`
- [ ] `app/financial/cost/cost_models.py`
- [ ] `app/financial/cost/cost_tracker.py`
- [ ] `app/financial/quota/quota_limits.py`
- [ ] `app/financial/quota/quota_service.py`
- [ ] `app/financial/rate_limit/rate_limit_service.py`
- [ ] `app/financial/abuse/abuse_detector.py`
- [ ] `app/routers/admin_financial.py`
- [ ] `alembic/versions/003_cost_governance.py`

### ✅ Files Modified

Check these files were updated:

- [ ] `app/core/config.py` - Cost governance config flags added
- [ ] `app/db/models/user.py` - plan_tier field added
- [ ] `app/main.py` - admin_financial router registered

---

## Integration Checklist

### Ready for Integration

- [ ] Database migration successful
- [ ] All tables created with indexes
- [ ] User model updated with plan_tier
- [ ] Financial module imports work
- [ ] Admin endpoints accessible
- [ ] Metrics exposed in /metrics
- [ ] Redis rate limiting works
- [ ] Documentation complete

### Next Integration Steps

1. **TTS Endpoints**: Add cost tracking and quota checks
2. **File Upload**: Check storage quotas before upload
3. **Billing UI**: Create React components for cost visualization
4. **Stripe Integration**: Connect plan_tier to subscriptions
5. **Email Alerts**: Notify on quota/cost thresholds
6. **Grafana Dashboards**: Create financial monitoring dashboards

---

## Troubleshooting

### Migration Fails

```bash
# Check current migration
cd services/api
alembic current

# If stuck, reset and re-run
alembic downgrade -1
alembic upgrade head
```

### Imports Fail

```bash
# Ensure dependencies installed
cd services/api
pip install -r requirements.txt

# Or use Docker
docker-compose build api
```

### Redis Connection Issues

```bash
# Check Redis is running
docker-compose ps redis

# Test connection
docker-compose exec redis redis-cli PING

# Check Redis logs
docker-compose logs redis
```

### Database Connection Issues

```bash
# Check PostgreSQL is running
docker-compose ps postgres

# Test connection
docker-compose exec postgres psql -U sonoro -d sonoro -c "SELECT 1;"

# Check logs
docker-compose logs postgres
```

---

## Success Criteria

✅ **All criteria must pass**:

1. Migration runs without errors
2. cost_events table exists with 9 columns
3. usage_quotas table exists with 10 columns
4. plan_tier column added to users table
5. Financial module imports successfully
6. Admin endpoints return 200 (with admin token)
7. Metrics endpoint shows sonoro_cost_* metrics
8. Redis rate limiting keys created
9. Documentation files exist and complete
10. No critical errors in logs

---

## Final Verification Command

```bash
# Run all verifications at once
cd /Users/servinemilio/audiolibro-pdf

echo "1. Checking Docker services..."
docker-compose ps

echo "2. Checking database tables..."
docker-compose exec postgres psql -U sonoro -d sonoro -c "
SELECT table_name FROM information_schema.tables 
WHERE table_schema = 'public' 
AND table_name IN ('cost_events', 'usage_quotas');"

echo "3. Checking user plan_tier..."
docker-compose exec postgres psql -U sonoro -d sonoro -c "
SELECT column_name FROM information_schema.columns 
WHERE table_name = 'users' AND column_name = 'plan_tier';"

echo "4. Checking metrics..."
curl -s http://localhost:8000/metrics | grep -c "sonoro_cost"

echo "5. Checking documentation..."
ls -la docs/SUB_BLOCK_3C*.md docs/COST_GOVERNANCE_GUIDE.md

echo "✅ Verification complete!"
```

---

**Status**: Ready for verification  
**Next Step**: Run verification checklist  
**Version**: 0.3.0  
**Date**: February 11, 2026
