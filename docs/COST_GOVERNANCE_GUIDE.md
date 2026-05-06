# Cost Governance Guide

## Quick Start

This guide shows you how to integrate cost tracking, quota enforcement, rate limiting, and abuse detection into your Sonoro API endpoints.

---

## Table of Contents

1. [Setup](#setup)
2. [Cost Tracking](#cost-tracking)
3. [Quota Enforcement](#quota-enforcement)
4. [Rate Limiting](#rate-limiting)
5. [Abuse Detection](#abuse-detection)
6. [Admin Operations](#admin-operations)
7. [Testing](#testing)
8. [Best Practices](#best-practices)

---

## Setup

### 1. Run Database Migration

```bash
cd services/api
alembic upgrade head
```

### 2. Update Environment Variables

Add to your `.env` file:

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

### 3. Verify Services

```bash
# Check Redis
redis-cli PING

# Check PostgreSQL
docker-compose ps postgres

# Check migrations
alembic current
```

---

## Cost Tracking

### Basic Usage

```python
from uuid import UUID
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.financial import CostTracker, CostEventType, CostProvider

router = APIRouter()

@router.post("/tts/generate")
async def generate_tts(
    text: str,
    db: AsyncSession = Depends(get_db),
):
    tracker = CostTracker(db)
    
    # Calculate costs
    char_count = len(text)
    unit_cost = 0.00003  # $0.03 per 1000 characters
    
    # Track the cost event
    await tracker.track_event(
        user_id=current_user.id,
        event_type=CostEventType.TTS_GENERATION,
        provider=CostProvider.ELEVEN_LABS,
        quantity=char_count,
        unit_cost=unit_cost,
        metadata={
            "voice_id": "rachel",
            "model": "eleven_multilingual_v2",
            "text_length": char_count,
        }
    )
    
    # Continue with TTS generation...
    return {"status": "processing"}
```

### Estimate Cost Before Tracking

```python
# Get cost estimate without tracking
estimate = await tracker.track_estimate(
    event_type=CostEventType.TTS_GENERATION,
    quantity=5000,
    unit_cost=0.00003,
)

print(f"This will cost: ${estimate['estimated_cost']:.4f}")
```

### Query Monthly Costs

```python
# Get user's monthly cost
monthly_cost = await tracker.get_user_monthly_cost(user_id)

print(f"Total: ${monthly_cost['total_cost_usd']:.2f}")
print(f"By type: {monthly_cost['by_event_type']}")
print(f"By provider: {monthly_cost['by_provider']}")

# Get system-wide costs
system_cost = await tracker.get_system_monthly_cost()
```

### Get Cost Trends

```python
# Get daily trend for last 30 days
trend = await tracker.get_user_cost_trend(user_id, days=30)

for day in trend:
    print(f"{day['date']}: ${day['total_cost']:.2f}")
```

---

## Quota Enforcement

### Check Quota Before Action

```python
from app.financial import QuotaService, ActionType, PlanTier, QuotaExceeded

@router.post("/tts/generate")
async def generate_tts(
    text: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    quota_service = QuotaService(db)
    
    try:
        # Check if user has quota
        await quota_service.check_quota(
            user_id=current_user.id,
            plan_tier=PlanTier(current_user.plan_tier),
            action=ActionType.TTS_GENERATION,
            quantity=len(text),
        )
    except QuotaExceeded as e:
        raise HTTPException(
            status_code=429,
            detail=str(e),
            headers={"Retry-After": "3600"}
        )
    
    # Process request...
    
    # Increment usage after success
    await quota_service.increment_usage(
        user_id=current_user.id,
        plan_tier=PlanTier(current_user.plan_tier),
        action=ActionType.TTS_GENERATION,
        quantity=len(text),
    )
    
    return {"status": "success"}
```

### Get Remaining Quota

```python
# Get remaining quota for specific action
remaining = await quota_service.get_remaining_quota(
    user_id=current_user.id,
    plan_tier=PlanTier(current_user.plan_tier),
    action=ActionType.TTS_GENERATION,
)

print(f"Remaining: {remaining['remaining']}")
print(f"Used: {remaining['used_percentage']:.1f}%")
print(f"Limit: {remaining['limit']}")
```

### Manual Quota Reset (Admin)

```python
# Reset user's quota (admin operation)
quota = await quota_service.get_or_create_quota(
    user_id=user_id,
    plan_tier=PlanTier.FREE,
)

# Reset counters
quota.characters_used = 0
quota.jobs_created = 0
quota.storage_used_mb = 0
quota.api_calls = 0

# Reset period
from datetime import datetime, timedelta
quota.period_start = datetime.utcnow()
quota.period_end = quota.period_start + timedelta(days=30)

await db.commit()
```

---

## Rate Limiting

### Apply Rate Limiting to Endpoint

```python
from app.financial import RateLimitService, RateLimitTier, RateLimitExceeded
from app.core.redis import get_redis

@router.post("/auth/login")
async def login(
    credentials: LoginRequest,
    redis: Redis = Depends(get_redis),
):
    rate_limiter = RateLimitService(redis)
    
    try:
        # Check rate limit
        await rate_limiter.check_rate_limit(
            user_id=credentials.email,  # Use email for auth endpoints
            tier=RateLimitTier.AUTH,
            endpoint="/auth/login"
        )
    except RateLimitExceeded as e:
        raise HTTPException(
            status_code=429,
            detail=str(e),
            headers={
                "Retry-After": str(e.retry_after),
                "X-RateLimit-Limit": str(e.limit),
                "X-RateLimit-Window": str(e.window),
            }
        )
    
    # Process login...
    return {"access_token": token}
```

### Custom Rate Limit Configuration

```python
from app.financial import RateLimitConfig

# Override default rate limits
custom_config = RateLimitConfig(
    requests_per_minute=100,
    requests_per_hour=2000,
    requests_per_day=20000,
    burst_size=150,
)

rate_limiter.configure_limit(RateLimitTier.API, custom_config)
```

### Check Rate Limit Status

```python
# Get current rate limit status
limits = await rate_limiter.get_limits(
    user_id=str(current_user.id),
    tier=RateLimitTier.API,
)

for window, info in limits.items():
    print(f"{window}: {info['used']}/{info['limit']} "
          f"({info['remaining']} remaining)")
```

### Reset Rate Limits (Admin)

```python
# Reset rate limits for a user
await rate_limiter.reset(
    user_id=str(user_id),
    tier=RateLimitTier.API,
)
```

---

## Abuse Detection

### Run Abuse Checks

```python
from app.financial import AbuseDetector

@router.post("/tts/generate")
async def generate_tts(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
):
    detector = AbuseDetector(db, redis)
    
    # Check all abuse patterns
    detections = await detector.check_all_patterns(
        user_id=current_user.id,
        user_email=current_user.email,
    )
    
    if detections:
        # Log detections (no automatic blocking)
        for detection in detections:
            logger.warning("abuse_pattern_detected", **detection)
            
            # Optionally alert admins for HIGH/CRITICAL severity
            if detection['severity'] in ['HIGH', 'CRITICAL']:
                await send_admin_alert(detection)
    
    # Continue processing...
    return {"status": "success"}
```

### Track Failed Login Attempts

```python
from app.financial import AbuseDetector

@router.post("/auth/login")
async def login(
    credentials: LoginRequest,
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
):
    detector = AbuseDetector(db, redis)
    
    # Verify credentials
    user = await authenticate_user(credentials)
    
    if not user:
        # Track failed login
        await detector.track_failed_login(
            user_identifier=credentials.email,
            ttl_seconds=900,  # 15 minutes
        )
        
        # Check for abuse pattern
        abuse = await detector.check_failed_logins(
            user_identifier=credentials.email,
            threshold=5,
        )
        
        if abuse:
            logger.warning("excessive_failed_logins", **abuse)
        
        raise HTTPException(status_code=401, detail="Invalid credentials")
    
    # Success - reset counter
    await detector.reset_failed_logins(credentials.email)
    
    return {"access_token": token}
```

### Check Specific Patterns

```python
# Check for usage spike
usage_spike = await detector.check_usage_spike(
    user_id=user_id,
    lookback_hours=24,
    spike_multiplier=5.0,
)

# Check for cost spike
cost_spike = await detector.check_cost_spike(
    user_id=user_id,
    lookback_hours=24,
    spike_multiplier=5.0,
)

# Check for excessive API calls
api_abuse = await detector.check_excessive_api_calls(
    user_id=user_id,
    lookback_minutes=60,
    threshold=1000,
)
```

---

## Admin Operations

### Access Admin Financial Endpoints

All admin endpoints require authentication with admin role.

#### 1. Get System Cost Overview

```bash
curl -X GET "http://localhost:8000/api/v1/admin/financial/cost/overview?days=30" \
  -H "Authorization: Bearer {admin_token}"
```

Response:
```json
{
  "period": "current_month",
  "days_analyzed": 30,
  "monthly_summary": {
    "total_cost_usd": 1234.56,
    "by_event_type": {
      "TTS_GENERATION": 800.00,
      "STORAGE_HOSTING": 200.00,
      "API_CALL_EXTERNAL": 234.56
    },
    "by_provider": {
      "ELEVEN_LABS": 800.00,
      "AWS_S3": 200.00,
      "OPENAI": 234.56
    }
  },
  "daily_trend": [...]
}
```

#### 2. Get User Cost Details

```bash
curl -X GET "http://localhost:8000/api/v1/admin/financial/cost/user/{user_id}?days=30" \
  -H "Authorization: Bearer {admin_token}"
```

#### 3. Get User Quota Status

```bash
curl -X GET "http://localhost:8000/api/v1/admin/financial/quota/{user_id}" \
  -H "Authorization: Bearer {admin_token}"
```

Response:
```json
{
  "user_id": "...",
  "plan_tier": "FREE",
  "current_usage": {
    "characters_used": 8500,
    "jobs_created": 3,
    "storage_used_mb": 45.2,
    "api_calls": 120
  },
  "remaining_quota": {
    "TTS_GENERATION": {
      "remaining": 1500,
      "used_percentage": 85.0,
      "limit": 10000
    }
  },
  "period": {
    "start": "2026-02-01T00:00:00Z",
    "end": "2026-03-01T00:00:00Z"
  }
}
```

#### 4. Reset User Quota

```bash
curl -X POST "http://localhost:8000/api/v1/admin/financial/quota/{user_id}/reset" \
  -H "Authorization: Bearer {admin_token}"
```

#### 5. Check Cost Alert Status

```bash
curl -X GET "http://localhost:8000/api/v1/admin/financial/cost/alert-status" \
  -H "Authorization: Bearer {admin_token}"
```

Response:
```json
{
  "current_cost_usd": 8234.56,
  "cost_cap_usd": 10000.00,
  "usage_percentage": 82.35,
  "alert_threshold_percentage": 80.0,
  "is_at_alert_threshold": true,
  "is_at_cap": false,
  "emergency_shutdown_active": false,
  "hard_cost_limit_enabled": false
}
```

---

## Testing

### Test Cost Tracking

```python
import pytest
from app.financial import CostTracker, CostEventType, CostProvider

@pytest.mark.asyncio
async def test_cost_tracking(db_session, test_user):
    tracker = CostTracker(db_session)
    
    # Track event
    await tracker.track_event(
        user_id=test_user.id,
        event_type=CostEventType.TTS_GENERATION,
        provider=CostProvider.ELEVEN_LABS,
        quantity=1000,
        unit_cost=0.00003,
    )
    
    # Verify monthly cost
    monthly = await tracker.get_user_monthly_cost(test_user.id)
    assert monthly['total_cost_usd'] == 0.03
```

### Test Quota Enforcement

```python
@pytest.mark.asyncio
async def test_quota_enforcement(db_session, test_user):
    from app.financial import QuotaService, ActionType, PlanTier, QuotaExceeded
    
    service = QuotaService(db_session)
    
    # Should allow small request
    await service.check_quota(
        user_id=test_user.id,
        plan_tier=PlanTier.FREE,
        action=ActionType.TTS_GENERATION,
        quantity=100,
    )
    
    # Should raise on exceeding limit
    with pytest.raises(QuotaExceeded):
        await service.check_quota(
            user_id=test_user.id,
            plan_tier=PlanTier.FREE,
            action=ActionType.TTS_GENERATION,
            quantity=1000000,  # Exceeds FREE tier limit
        )
```

### Test Rate Limiting

```python
@pytest.mark.asyncio
async def test_rate_limiting(redis_client):
    from app.financial import RateLimitService, RateLimitTier, RateLimitExceeded
    
    service = RateLimitService(redis_client)
    
    # First request should succeed
    await service.check_rate_limit(
        user_id="test_user",
        tier=RateLimitTier.API,
    )
    
    # Exceed limit
    for _ in range(100):
        await service.check_rate_limit(
            user_id="test_user",
            tier=RateLimitTier.API,
        )
    
    # Should raise
    with pytest.raises(RateLimitExceeded):
        await service.check_rate_limit(
            user_id="test_user",
            tier=RateLimitTier.API,
        )
```

---

## Best Practices

### 1. Always Track Costs

```python
# ✅ Good: Track all cost-generating events
await tracker.track_event(...)

# ❌ Bad: Skipping cost tracking
# (Creates blind spots in financial data)
```

### 2. Check Quota BEFORE Processing

```python
# ✅ Good: Check quota first
await quota_service.check_quota(...)
result = await expensive_operation()
await quota_service.increment_usage(...)

# ❌ Bad: Check quota after
result = await expensive_operation()
await quota_service.check_quota(...)  # Too late!
```

### 3. Use Appropriate Rate Limit Tiers

```python
# ✅ Good: Auth endpoints use AUTH tier
@router.post("/auth/login")
async def login(...):
    await rate_limiter.check_rate_limit(tier=RateLimitTier.AUTH)

# ❌ Bad: Auth using API tier
# (Allows too many login attempts)
```

### 4. Handle Exceptions Gracefully

```python
# ✅ Good: Provide helpful error messages
try:
    await quota_service.check_quota(...)
except QuotaExceeded as e:
    raise HTTPException(
        status_code=429,
        detail=f"Monthly character limit exceeded. Upgrade to process more.",
        headers={"Retry-After": "86400"}
    )

# ❌ Bad: Generic error
except QuotaExceeded:
    raise HTTPException(status_code=500, detail="Error")
```

### 5. Use Metadata for Context

```python
# ✅ Good: Include useful metadata
await tracker.track_event(
    ...,
    metadata={
        "job_id": job.id,
        "voice_id": "rachel",
        "model": "eleven_multilingual_v2",
        "input_file": "document.pdf",
        "duration_seconds": 123.45,
    }
)

# ❌ Bad: No metadata
await tracker.track_event(..., metadata={})
```

### 6. Monitor Abuse Patterns

```python
# ✅ Good: Regular abuse checks
detections = await detector.check_all_patterns(...)
if detections:
    for d in detections:
        if d['severity'] in ['HIGH', 'CRITICAL']:
            await alert_admins(d)

# ❌ Bad: Never checking for abuse
# (Allows bad actors to drain resources)
```

### 7. Set Realistic Quotas

```python
# ✅ Good: Quotas match your cost structure
FREE = QuotaLimits(
    monthly_char_limit=10_000,      # ~$0.30 cost
    storage_limit_mb=100,            # ~$0.02 cost
    ...
)

# ❌ Bad: Unlimited free tier
FREE = QuotaLimits(monthly_char_limit=999_999_999, ...)
```

### 8. Use Cost Simulation

```python
# ✅ Good: Estimate before committing
estimate = await tracker.track_estimate(...)
if estimate['estimated_cost'] > user_budget:
    return {"error": "Insufficient budget"}

# ❌ Bad: No cost awareness
# (Surprise bills for users)
```

---

## Common Issues

### Issue: Quota Not Resetting

**Cause**: Period hasn't expired yet
**Solution**: Check `period_end` in database or manually reset

```python
quota = await quota_service.get_or_create_quota(user_id, plan_tier)
print(f"Period ends: {quota.period_end}")
```

### Issue: Rate Limit Always Exceeded

**Cause**: Redis keys not expiring
**Solution**: Check Redis TTL and clear if needed

```bash
redis-cli TTL "ratelimit:api:user_id:minute"
redis-cli DEL "ratelimit:api:user_id:*"
```

### Issue: Cost Events Not Appearing

**Cause**: Transaction not committed
**Solution**: Ensure `await db.commit()` is called

```python
await tracker.track_event(...)
await db.commit()  # Don't forget!
```

### Issue: Abuse Detection Not Working

**Cause**: Insufficient historical data
**Solution**: Need at least 7 days of data for spike detection

---

## Support

For questions or issues:
1. Check the logs: `docker-compose logs api`
2. Review the metrics: `http://localhost:8000/metrics`
3. Check the database: `psql -d sonoro -c "SELECT * FROM cost_events LIMIT 10;"`
4. Consult the complete guide: `docs/SUB_BLOCK_3C_COMPLETE.md`

---

**Last Updated**: February 11, 2026
**Version**: 0.3.0
