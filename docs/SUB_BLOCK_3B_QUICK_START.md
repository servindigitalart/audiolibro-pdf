# 🚀 SUB-BLOCK 3B QUICK START

**Quick reference for getting observability running**

---

## 📦 INSTALLATION

### Step 1: Install Dependencies

```bash
cd /Users/servinemilio/audiolibro-pdf

# Install Python dependencies
cd services/api
pip install -r requirements.txt

# This will install:
# - prometheus-client==0.20.0
# - sentry-sdk[fastapi]==1.40.6
# - psutil==5.9.8
```

### Step 2: Configure Environment

```bash
cd /Users/servinemilio/audiolibro-pdf

# Copy example if needed
cp .env.example .env

# Add Sentry configuration (optional but recommended)
# Get your DSN from https://sentry.io
echo "SENTRY_DSN=your-sentry-dsn-here" >> .env
echo "SENTRY_TRACES_SAMPLE_RATE=0.1" >> .env
echo "SENTRY_PROFILES_SAMPLE_RATE=0.1" >> .env
echo "METRICS_COLLECTION_INTERVAL=15" >> .env
```

### Step 3: Start Services

```bash
# Start all services including monitoring
docker-compose up -d

# Check status
docker-compose ps

# View logs
docker-compose logs -f api prometheus grafana
```

---

## 🔗 ACCESS POINTS

| Service | URL | Credentials |
|---------|-----|-------------|
| **API** | http://localhost:8000 | N/A |
| **API Docs** | http://localhost:8000/docs | N/A |
| **Metrics** | http://localhost:8000/metrics | N/A |
| **Prometheus** | http://localhost:9090 | None |
| **Grafana** | http://localhost:3001 | admin/admin |

---

## ✅ VERIFICATION

### 1. Check Metrics Endpoint

```bash
curl http://localhost:8000/metrics | head -20

# Should return Prometheus metrics:
# sonoro_http_requests_total{...} 123
# sonoro_active_requests 5
# ...
```

### 2. Check Prometheus Targets

```bash
# Open browser
open http://localhost:9090/targets

# Verify "sonoro-api" target is UP
```

### 3. Check Grafana Dashboards

```bash
# Open browser
open http://localhost:3001

# Login: admin/admin
# Navigate to: Dashboards → Browse → Sonoro folder
# Open any dashboard (should show data)
```

### 4. Test Admin Endpoints (Requires Admin User)

```bash
# First, create admin user or login
TOKEN=$(curl -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"your-admin@email.com","password":"your-password"}' \
  | jq -r '.access_token')

# Get runtime info
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/admin/runtime | jq

# Should return:
# {
#   "uptime_seconds": 123.45,
#   "environment": "development",
#   "version": "0.2.0",
#   ...
# }
```

---

## 📊 KEY METRICS TO MONITOR

### HTTP Performance
```promql
# Request rate
rate(sonoro_http_requests_total[5m])

# P95 latency
histogram_quantile(0.95, 
  sum(rate(sonoro_http_request_duration_seconds_bucket[5m])) by (le)
)

# Error rate
rate(sonoro_http_requests_total{status=~"5.."}[5m])
```

### Infrastructure Health
```promql
# Active requests
sonoro_active_requests

# DB pool utilization
sonoro_db_connection_pool_checked_out / sonoro_db_connection_pool_size

# Redis status
sonoro_redis_connection_status
```

### Authentication
```promql
# Login attempts
rate(sonoro_auth_login_attempts_total[5m])

# Failed logins
rate(sonoro_auth_login_failures_total[5m])

# User registrations
rate(sonoro_auth_registrations_total[5m])
```

---

## 🚨 COMMON ISSUES & FIXES

### Issue: Metrics endpoint returns 404

```bash
# Check if API is running
docker-compose ps api

# Check logs for errors
docker-compose logs api | grep -i error

# Restart API
docker-compose restart api
```

### Issue: Prometheus shows target as DOWN

```bash
# Check if API is accessible from Prometheus
docker-compose exec prometheus wget -O- http://api:8000/metrics

# If fails, check network
docker-compose exec prometheus ping api

# Restart Prometheus
docker-compose restart prometheus
```

### Issue: Grafana shows "No Data"

```bash
# 1. Check Prometheus datasource in Grafana
# Go to Configuration → Data Sources → Prometheus
# Click "Test" - should be green

# 2. Verify data in Prometheus
# Open http://localhost:9090/graph
# Query: sonoro_http_requests_total
# Should show results

# 3. Check time range in Grafana (top right)
# Set to "Last 15 minutes"

# 4. Generate some traffic
for i in {1..10}; do
  curl http://localhost:8000/api/v1/health
done
```

### Issue: Sentry not capturing errors

```bash
# 1. Check SENTRY_DSN is set
docker-compose exec api env | grep SENTRY_DSN

# 2. Check logs for Sentry initialization
docker-compose logs api | grep -i sentry

# 3. Trigger test error
curl http://localhost:8000/nonexistent-endpoint

# 4. Check Sentry dashboard
# https://sentry.io (should see error)
```

---

## 🎯 NEXT STEPS

### For Development
1. ✅ Install dependencies
2. ✅ Start services
3. ✅ Access Grafana dashboards
4. ✅ Generate test traffic
5. ✅ Explore metrics in Prometheus

### For Production
1. ✅ Set `SENTRY_DSN` in `.env`
2. ✅ Change Grafana admin password
3. ✅ Configure alert destinations (future)
4. ✅ Set up SSH tunnel for Grafana access
5. ✅ Review alert thresholds

---

## 📚 DOCUMENTATION

- **Complete Guide**: `docs/SUB_BLOCK_3B_COMPLETE.md`
- **Operations Manual**: `docs/OBSERVABILITY_GUIDE.md`
- **Deployment**: `docs/PRODUCTION_DEPLOYMENT_CHECKLIST.md`
- **Security**: `docs/SECURITY_HARDENING.md`

---

## 🎉 SUCCESS CRITERIA

- [x] Metrics endpoint working (`/metrics`)
- [x] Prometheus scraping successfully
- [x] Grafana dashboards loading
- [x] Admin endpoints functional
- [x] Business metrics tracking auth events
- [x] Sentry ready (when DSN configured)
- [x] Alert rules defined
- [x] Zero business logic modified

**Status**: ✅ **SUB-BLOCK 3B COMPLETE**

---

**Version**: 0.2.0  
**Last Updated**: February 2026
