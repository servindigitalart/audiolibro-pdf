# SUB-BLOCK 3C: Quick Reference

## 🎯 One-Line Summary
**Cost tracking, quota enforcement, rate limiting, and abuse detection for Sonoro SaaS.**

---

## 📥 Installation

```bash
cd services/api
alembic upgrade head
```

---

## 🔥 Usage Examples

### Track Cost
```python
from app.financial import CostTracker, CostEventType, CostProvider

tracker = CostTracker(db)
await tracker.track_event(
    user_id=user.id,
    event_type=CostEventType.TTS_GENERATION,
    provider=CostProvider.ELEVEN_LABS,
    quantity=5000,
    unit_cost=0.00003,
)
```

### Check Quota
```python
from app.financial import QuotaService, ActionType, PlanTier, QuotaExceeded

try:
    await QuotaService(db).check_quota(
        user_id=user.id,
        plan_tier=PlanTier.FREE,
        action=ActionType.TTS_GENERATION,
        quantity=5000,
    )
except QuotaExceeded as e:
    raise HTTPException(status_code=429, detail=str(e))
```

### Apply Rate Limit
```python
from app.financial import RateLimitService, RateLimitTier, RateLimitExceeded

try:
    await RateLimitService(redis).check_rate_limit(
        user_id=str(user.id),
        tier=RateLimitTier.API,
    )
except RateLimitExceeded as e:
    raise HTTPException(status_code=429, detail=str(e))
```

### Detect Abuse
```python
from app.financial import AbuseDetector

detections = await AbuseDetector(db, redis).check_all_patterns(
    user_id=user.id,
    user_email=user.email,
)
```

---

## 📊 Plan Tiers

| Tier | Chars/Month | Jobs | Storage | API/Min |
|------|-------------|------|---------|---------|
| FREE | 10K | 5 | 100MB | 60 |
| BASIC | 100K | 50 | 1GB | 60 |
| PRO | 500K | 200 | 10GB | 120 |
| ENTERPRISE | 5M | 2000 | 100GB | 240 |

---

## 🚦 Rate Limits

| Tier | Per Minute | Per Hour | Per Day |
|------|------------|----------|---------|
| AUTH | 5 | 20 | 100 |
| UPLOAD | 10 | 50 | 200 |
| API | 60 | 1000 | 10000 |
| ADMIN | 120 | 5000 | 50000 |

---

## 🔌 Admin Endpoints

```bash
# Cost overview
GET /api/v1/admin/financial/cost/overview?days=30

# User cost
GET /api/v1/admin/financial/cost/user/{user_id}

# User quota
GET /api/v1/admin/financial/quota/{user_id}

# Reset quota
POST /api/v1/admin/financial/quota/{user_id}/reset

# Alert status
GET /api/v1/admin/financial/cost/alert-status
```

---

## 📈 Prometheus Metrics

```promql
sonoro_cost_total
sonoro_cost_per_user
sonoro_monthly_cost_usd
sonoro_quota_remaining
sonoro_quota_usage_percentage
sonoro_rate_limit_exceeded_total
sonoro_abuse_patterns_detected_total
```

---

## 🗄️ Database Tables

- `cost_events` - All cost-generating events
- `usage_quotas` - Monthly usage tracking
- `users.plan_tier` - User plan (FREE, BASIC, PRO, ENTERPRISE)

---

## 📚 Documentation

- **Complete Guide**: `docs/SUB_BLOCK_3C_COMPLETE.md`
- **Integration**: `docs/COST_GOVERNANCE_GUIDE.md`
- **Verification**: `docs/SUB_BLOCK_3C_VERIFICATION.md`

---

## 🎓 Cost Event Types (15+)

- TTS_GENERATION, TTS_STREAMING
- STORAGE_UPLOAD, STORAGE_HOSTING, STORAGE_TRANSFER
- API_CALL_EXTERNAL, API_CALL_INTERNAL
- COMPUTE_PROCESSING
- EMAIL_SENT
- CDN_BANDWIDTH
- DATABASE_QUERY
- CREDIT_PURCHASE, CREDIT_USAGE
- INFRASTRUCTURE_HOSTING, INFRASTRUCTURE_DATABASE

---

## 🏢 Cost Providers (7)

- OPENAI
- ANTHROPIC
- ELEVEN_LABS
- DIGITALOCEAN
- AWS_S3
- SENDGRID
- INTERNAL

---

## ⚡ Quick Commands

```bash
# Run migration
alembic upgrade head

# Check tables
docker-compose exec postgres psql -U sonoro -d sonoro -c "\dt"

# View metrics
curl http://localhost:8000/metrics | grep sonoro_cost

# API docs
open http://localhost:8000/docs
```

---

## ✅ Status

**Version**: 0.3.0  
**Status**: ✅ COMPLETE  
**Next**: Integrate with TTS endpoints

---

**Need Help?** Read `docs/COST_GOVERNANCE_GUIDE.md`
