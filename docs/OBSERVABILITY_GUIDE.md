# 📊 SONORO OBSERVABILITY GUIDE

**Complete guide to monitoring, metrics, and observability for Sonoro SaaS Platform**

---

## 🎯 TABLE OF CONTENTS

1. [Quick Start](#quick-start)
2. [Accessing Monitoring Tools](#accessing-monitoring-tools)
3. [Understanding Metrics](#understanding-metrics)
4. [Using Grafana Dashboards](#using-grafana-dashboards)
5. [Querying Prometheus](#querying-prometheus)
6. [Sentry Error Tracking](#sentry-error-tracking)
7. [Alert Management](#alert-management)
8. [Runtime Introspection](#runtime-introspection)
9. [Troubleshooting](#troubleshooting)
10. [Best Practices](#best-practices)

---

## 🚀 QUICK START

### Development Environment

```bash
# Start all services including monitoring
docker-compose up -d

# Verify services are running
docker-compose ps

# Check logs
docker-compose logs -f api prometheus grafana
```

### Access Points
- **API**: http://localhost:8000
- **API Docs**: http://localhost:8000/docs
- **Metrics**: http://localhost:8000/metrics
- **Prometheus**: http://localhost:9090
- **Grafana**: http://localhost:3001 (admin/admin)

### Production Environment

```bash
# Deploy with monitoring
docker-compose -f infra/docker-compose.prod.yml up -d

# Access Prometheus/Grafana via SSH tunnel
ssh -L 9090:localhost:9090 -L 3001:localhost:3000 user@your-vps

# Then access locally:
# - Prometheus: http://localhost:9090
# - Grafana: http://localhost:3001
```

---

## 🔐 ACCESSING MONITORING TOOLS

### Grafana

**Development**:
```
URL: http://localhost:3001
Username: admin
Password: admin
```

**Production**:
```bash
# Set strong password in .env
GRAFANA_ADMIN_PASSWORD=your-strong-password-here

# Access via SSH tunnel
ssh -L 3001:localhost:3000 user@your-vps
# Then: http://localhost:3001
```

**First Login**:
1. Navigate to http://localhost:3001
2. Login with admin credentials
3. Go to Dashboards → Browse
4. Open "Sonoro" folder
5. Select any dashboard

### Prometheus

**Development**:
```
URL: http://localhost:9090
No authentication required
```

**Production**:
```bash
# Access via SSH tunnel
ssh -L 9090:localhost:9090 user@your-vps
# Then: http://localhost:9090
```

**Useful Pages**:
- `/targets` - Check scrape target status
- `/graph` - Query metrics
- `/alerts` - View active alerts
- `/config` - View configuration

### Sentry

**Setup**:
1. Create account at https://sentry.io
2. Create new project (Python/FastAPI)
3. Copy DSN
4. Add to `.env`:
   ```env
   SENTRY_DSN=https://xxx@sentry.io/xxx
   ```
5. Restart API: `docker-compose restart api`

**Access**:
- Dashboard: https://sentry.io/organizations/your-org/issues/
- Performance: https://sentry.io/organizations/your-org/performance/

---

## 📊 UNDERSTANDING METRICS

### Metric Types

#### Counter
Monotonically increasing value. Use for counting events.
```
sonoro_http_requests_total
sonoro_auth_login_attempts_total
```

#### Gauge
Can go up or down. Use for current values.
```
sonoro_active_requests
sonoro_db_connection_pool_size
```

#### Histogram
Observations in configurable buckets. Use for measuring distributions.
```
sonoro_http_request_duration_seconds
```

### Metric Naming Convention

```
<namespace>_<subsystem>_<name>_<unit>

Examples:
sonoro_http_requests_total
sonoro_db_connection_pool_size
sonoro_redis_latency_seconds
```

### Available Metrics

#### HTTP Metrics
```promql
# Total requests by method, endpoint, status
sonoro_http_requests_total{method="GET", endpoint="/api/v1/health", status="200"}

# Request duration histogram (seconds)
sonoro_http_request_duration_seconds_bucket{method="POST", endpoint="/api/v1/auth/login", le="0.5"}

# Total exceptions
sonoro_http_exceptions_total{exception_type="ValueError"}

# Current active requests
sonoro_active_requests
```

#### Database Metrics
```promql
# Connection pool size
sonoro_db_connection_pool_size

# Pool overflow
sonoro_db_connection_pool_overflow

# Checked out connections
sonoro_db_connection_pool_checked_out
```

#### Redis Metrics
```promql
# Connection status (1=connected, 0=disconnected)
sonoro_redis_connection_status

# Latency in seconds
sonoro_redis_latency_seconds

# Commands executed
sonoro_redis_commands_total{command="get"}
```

#### Authentication Metrics
```promql
# Login attempts
sonoro_auth_login_attempts_total{status="success"}
sonoro_auth_login_attempts_total{status="failure"}

# Login failures by reason
sonoro_auth_login_failures_total{reason="invalid_credentials"}

# Registrations
sonoro_auth_registrations_total{status="success"}

# Token refreshes
sonoro_auth_token_refreshes_total{status="success"}
```

#### User Metrics
```promql
# Total registered users
sonoro_registered_users_total

# Active users (30 days)
sonoro_active_users_total
```

---

## 📈 USING GRAFANA DASHBOARDS

### System Health Dashboard

**Purpose**: Monitor infrastructure health and performance

**Key Panels**:
1. **Request Rate**: Requests per second over time
2. **Active Requests**: Current concurrent requests
3. **Request Latency**: P50, P95, P99 percentiles
4. **Redis Status**: Connection health
5. **Redis Latency**: Performance metric
6. **DB Connection Pool**: Pool utilization

**When to Use**:
- Daily health checks
- Performance degradation investigation
- Capacity planning
- Incident response

### API Performance Dashboard

**Purpose**: Analyze API endpoint performance and errors

**Key Panels**:
1. **Requests by Status Code**: 2xx, 4xx, 5xx distribution
2. **Error Rate**: Percentage of 5xx responses
3. **Latency by Endpoint**: Performance per endpoint
4. **Exception Rate**: Exceptions by type
5. **Top Endpoints**: Highest traffic endpoints

**When to Use**:
- Performance optimization
- Error rate investigation
- Endpoint usage analysis
- SLA monitoring

### Authentication Dashboard

**Purpose**: Monitor user authentication and security

**Key Panels**:
1. **Total Registered Users**: User growth
2. **Active Users**: 30-day active users
3. **Login Failures/Minute**: Security monitoring
4. **Login Attempts**: Success vs failure
5. **Login Failures by Reason**: Security insights
6. **User Registrations**: Growth rate
7. **Token Refreshes**: Session activity

**When to Use**:
- Security monitoring
- Brute force attack detection
- User growth tracking
- Authentication issues

### Creating Custom Dashboards

1. **Go to Grafana** → Dashboards → New Dashboard
2. **Add Panel**
3. **Select Prometheus** datasource
4. **Enter PromQL query**:
   ```promql
   rate(sonoro_http_requests_total[5m])
   ```
5. **Configure visualization** (Line, Gauge, Stat, etc.)
6. **Set thresholds** for color coding
7. **Save dashboard**

---

## 🔍 QUERYING PROMETHEUS

### Basic Queries

#### Current Value
```promql
# Current active requests
sonoro_active_requests

# Redis connection status
sonoro_redis_connection_status
```

#### Rate of Change
```promql
# Requests per second (5-minute average)
rate(sonoro_http_requests_total[5m])

# Login failures per minute
rate(sonoro_auth_login_failures_total[1m]) * 60
```

#### Aggregation
```promql
# Total requests by status
sum by(status) (rate(sonoro_http_requests_total[5m]))

# Max latency by endpoint
max by(endpoint) (sonoro_http_request_duration_seconds)
```

#### Percentiles
```promql
# P95 latency (overall)
histogram_quantile(0.95, 
  sum(rate(sonoro_http_request_duration_seconds_bucket[5m])) by (le)
)

# P50 latency by endpoint
histogram_quantile(0.50,
  sum(rate(sonoro_http_request_duration_seconds_bucket[5m])) by (le, endpoint)
)
```

### Advanced Queries

#### Error Rate
```promql
# 5xx error rate as percentage
(
  sum(rate(sonoro_http_requests_total{status=~"5.."}[5m]))
  /
  sum(rate(sonoro_http_requests_total[5m]))
) * 100
```

#### Database Pool Utilization
```promql
# Percentage of pool in use
(
  sonoro_db_connection_pool_checked_out
  /
  (sonoro_db_connection_pool_size + sonoro_db_connection_pool_overflow)
) * 100
```

#### Login Success Rate
```promql
# Percentage of successful logins
(
  sum(rate(sonoro_auth_login_attempts_total{status="success"}[5m]))
  /
  sum(rate(sonoro_auth_login_attempts_total[5m]))
) * 100
```

### Query Tips

1. **Always use rate() for counters**:
   ```promql
   # ❌ Wrong
   sonoro_http_requests_total
   
   # ✅ Correct
   rate(sonoro_http_requests_total[5m])
   ```

2. **Use appropriate time ranges**:
   - `[1m]` - High frequency, real-time
   - `[5m]` - Standard operational view
   - `[1h]` - Trend analysis
   - `[24h]` - Daily patterns

3. **Label filtering**:
   ```promql
   # Filter by endpoint
   rate(sonoro_http_requests_total{endpoint="/api/v1/auth/login"}[5m])
   
   # Filter by status
   rate(sonoro_http_requests_total{status=~"5.."}[5m])
   ```

---

## 🐛 SENTRY ERROR TRACKING

### Automatic Capture

All unhandled exceptions are automatically sent to Sentry if configured.

**Example**:
```python
# This exception will be captured automatically
raise ValueError("Something went wrong")
```

### Manual Capture

```python
from app.monitoring.sentry import capture_exception, capture_message

# Capture exception
try:
    risky_operation()
except Exception as e:
    capture_exception(e, level="error", extra={"user_id": user.id})
    
# Capture message
capture_message("Important event occurred", level="info", extra={"details": "..."})
```

### User Context

```python
from app.monitoring.sentry import set_user_context

# Add user context to errors
set_user_context(user_id=str(user.id), email=user.email)
```

### Breadcrumbs

```python
from app.monitoring.sentry import add_breadcrumb

# Add debugging context
add_breadcrumb(
    message="User uploaded document",
    category="upload",
    level="info",
    data={"filename": "document.pdf", "size": 1024}
)
```

### Viewing Errors

1. **Go to Sentry Dashboard**
2. **Navigate to Issues**
3. **Click on an issue** to see:
   - Stack trace
   - Request data
   - User information
   - Breadcrumbs
   - Similar issues

### Performance Monitoring

**Transaction Tracking**:
- Automatically tracks API endpoint performance
- 10% sample rate (configurable)
- View in Sentry Performance tab

**Spans**:
- Database queries
- Redis operations
- HTTP requests

---

## 🚨 ALERT MANAGEMENT

### Viewing Alerts

**Prometheus Alerts**:
```
http://localhost:9090/alerts
```

**Alert States**:
- **Inactive**: Condition not met
- **Pending**: Condition met, waiting for `for` duration
- **Firing**: Alert is active

### Alert Rules Reference

#### Critical Alerts (Immediate Action Required)

**HighErrorRate**:
```yaml
Condition: Error rate > 5% for 5 minutes
Action: Investigate failing endpoints, check logs
```

**APIDown**:
```yaml
Condition: API unreachable for 1 minute
Action: Check API container, restart if needed
```

**DatabaseDown**:
```yaml
Condition: DB connection lost for 1 minute
Action: Check PostgreSQL container, verify connection
```

**RedisDown**:
```yaml
Condition: Redis connection lost for 1 minute
Action: Check Redis container, verify connection
```

#### Warning Alerts (Monitor Closely)

**HighLatency**:
```yaml
Condition: P95 latency > 1 second for 5 minutes
Action: Review slow endpoints, optimize queries
```

**DatabasePoolExhausted**:
```yaml
Condition: Pool > 90% capacity for 2 minutes
Action: Increase pool size or optimize connection usage
```

**HighLoginFailureRate**:
```yaml
Condition: > 50 failures/minute for 2 minutes
Action: Possible brute force attack, review IPs, consider rate limiting
```

### Testing Alerts

#### Trigger High Error Rate
```bash
# Generate 500 errors
for i in {1..100}; do
  curl -X POST http://localhost:8000/api/v1/auth/login \
    -H "Content-Type: application/json" \
    -d '{"email":"invalid","password":"invalid"}'
done
```

#### Trigger High Latency
```python
# Add artificial delay in endpoint (testing only)
import time
time.sleep(2)
```

#### Simulate DB Connection Issues
```bash
# Stop PostgreSQL temporarily
docker-compose stop postgres

# Wait for alert to fire (1 minute)
# Restart
docker-compose start postgres
```

### Setting Up AlertManager (Future)

```yaml
# alertmanager.yml (example)
route:
  receiver: 'slack'
  group_by: ['alertname', 'severity']
  group_wait: 30s
  repeat_interval: 4h

receivers:
  - name: 'slack'
    slack_configs:
      - api_url: 'https://hooks.slack.com/services/YOUR/SLACK/WEBHOOK'
        channel: '#alerts'
        text: '{{ range .Alerts }}{{ .Annotations.summary }}{{ end }}'
```

---

## 🔧 RUNTIME INTROSPECTION

### Admin Runtime Endpoint

**Endpoint**: `GET /api/v1/admin/runtime`

**Authentication**: Requires admin role

**Example Request**:
```bash
# 1. Login as admin
TOKEN=$(curl -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@sonoro.com","password":"admin123"}' \
  | jq -r '.access_token')

# 2. Get runtime info
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/admin/runtime | jq
```

**Response**:
```json
{
  "uptime_seconds": 3600.5,
  "environment": "production",
  "version": "0.2.0",
  "total_requests": 12345,
  "active_requests": 5,
  "memory_usage_mb": 256.7,
  "active_connections": {
    "database": 5,
    "redis": 1
  },
  "feature_flags": {
    "email_verification": false,
    "rate_limiting": true
  }
}
```

### Detailed Health Check

**Endpoint**: `GET /api/v1/admin/health/detailed`

**Example Request**:
```bash
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/admin/health/detailed | jq
```

**Response**:
```json
{
  "status": "healthy",
  "services": {
    "database": "healthy",
    "redis": "healthy",
    "sentry": "enabled"
  },
  "uptime_seconds": 3600.5,
  "version": "0.2.0"
}
```

### Use Cases

1. **Debugging Production Issues**:
   - Check memory usage
   - Verify active connections
   - Confirm environment settings

2. **Health Monitoring**:
   - Automated health checks
   - Service dependency status
   - Uptime tracking

3. **Capacity Planning**:
   - Monitor memory trends
   - Track request volumes
   - Identify connection bottlenecks

---

## 🔍 TROUBLESHOOTING

### Common Issues

#### 1. Metrics Not Appearing

**Symptoms**: `/metrics` endpoint returns empty or partial data

**Solutions**:
```bash
# Check if MetricsMiddleware is registered
docker-compose logs api | grep "MetricsMiddleware"

# Verify metrics collector is running
docker-compose logs api | grep "Metrics collector started"

# Restart API
docker-compose restart api
```

#### 2. Prometheus Not Scraping

**Symptoms**: Targets show as "DOWN" in Prometheus

**Check**:
```bash
# Verify API is accessible from Prometheus container
docker-compose exec prometheus wget -O- http://api:8000/metrics

# Check Prometheus logs
docker-compose logs prometheus | grep "error"

# Verify network connectivity
docker-compose exec prometheus ping api
```

**Fix**:
```bash
# Restart Prometheus
docker-compose restart prometheus
```

#### 3. Grafana Dashboards Not Loading

**Symptoms**: Dashboards show "No Data"

**Solutions**:
```bash
# Check Prometheus datasource
# Grafana → Configuration → Data Sources → Prometheus
# Test connection

# Verify data in Prometheus
# Open http://localhost:9090/graph
# Query: sonoro_http_requests_total
# Should return data

# Check time range in Grafana (top right)
```

#### 4. Sentry Not Capturing Errors

**Symptoms**: Errors not appearing in Sentry dashboard

**Check**:
```bash
# Verify SENTRY_DSN is set
docker-compose exec api env | grep SENTRY_DSN

# Check Sentry initialization logs
docker-compose logs api | grep "Sentry"

# Trigger test error
curl http://localhost:8000/this-does-not-exist
```

**Fix**:
```bash
# Set SENTRY_DSN in .env
SENTRY_DSN=https://xxx@sentry.io/xxx

# Restart API
docker-compose restart api
```

#### 5. High Memory Usage

**Symptoms**: API container using excessive memory

**Diagnosis**:
```bash
# Check runtime info
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/admin/runtime | jq '.memory_usage_mb'

# Check container stats
docker stats sonoro-api
```

**Solutions**:
- Reduce `db_pool_size` in config
- Lower `metrics_collection_interval`
- Increase container memory limit

---

## ✅ BEST PRACTICES

### Metric Collection

1. **Use appropriate metric types**:
   - Counters for events (requests, errors)
   - Gauges for current values (active connections)
   - Histograms for distributions (latency)

2. **Keep label cardinality low**:
   ```python
   # ❌ Bad: High cardinality
   metric.labels(user_id=user.id).inc()
   
   # ✅ Good: Low cardinality
   metric.labels(user_role=user.role).inc()
   ```

3. **Use consistent naming**:
   - Follow `<namespace>_<subsystem>_<name>_<unit>` convention
   - Use base units (seconds, not milliseconds)

### Dashboard Design

1. **Focus on actionable metrics**:
   - What can you do with this information?
   - Does it help diagnose issues?

2. **Use appropriate time ranges**:
   - Real-time: Last 15 minutes
   - Operational: Last 1-4 hours
   - Trend analysis: Last 24 hours - 7 days

3. **Set meaningful thresholds**:
   - Green: Normal operation
   - Yellow: Warning (investigate)
   - Red: Critical (immediate action)

### Alert Configuration

1. **Avoid alert fatigue**:
   - Only alert on actionable conditions
   - Use appropriate `for` durations
   - Group related alerts

2. **Document alert responses**:
   - What does this alert mean?
   - What action should be taken?
   - Who is responsible?

3. **Test alerts regularly**:
   - Simulate failure conditions
   - Verify notifications work
   - Update thresholds based on actual usage

### Error Tracking

1. **Add context to errors**:
   ```python
   capture_exception(e, extra={
       "user_id": user.id,
       "action": "upload_document",
       "file_size": file.size,
   })
   ```

2. **Use breadcrumbs for debugging**:
   ```python
   add_breadcrumb(message="Starting upload", data={"filename": name})
   # ... operation ...
   add_breadcrumb(message="Upload complete", data={"duration": elapsed})
   ```

3. **Filter noise**:
   - Exclude expected errors (404, validation)
   - Sample high-frequency errors
   - Group similar issues

### Performance Monitoring

1. **Track key endpoints**:
   - Authentication
   - Critical business operations
   - High-traffic endpoints

2. **Monitor percentiles, not averages**:
   - P50: Typical user experience
   - P95: Slow but not uncommon
   - P99: Worst case scenarios

3. **Investigate spikes**:
   - Sudden latency increases
   - Error rate changes
   - Unusual traffic patterns

---

## 📚 ADDITIONAL RESOURCES

### Official Documentation
- **Prometheus**: https://prometheus.io/docs/
- **Grafana**: https://grafana.com/docs/
- **Sentry**: https://docs.sentry.io/
- **FastAPI**: https://fastapi.tiangolo.com/

### PromQL Learning
- **PromQL Basics**: https://prometheus.io/docs/prometheus/latest/querying/basics/
- **Query Examples**: https://prometheus.io/docs/prometheus/latest/querying/examples/
- **Functions**: https://prometheus.io/docs/prometheus/latest/querying/functions/

### Grafana Resources
- **Dashboard Best Practices**: https://grafana.com/docs/grafana/latest/dashboards/build-dashboards/best-practices/
- **Community Dashboards**: https://grafana.com/grafana/dashboards/

### Monitoring Philosophy
- **Google SRE Book**: https://sre.google/sre-book/monitoring-distributed-systems/
- **The Four Golden Signals**: Latency, Traffic, Errors, Saturation

---

## 🆘 SUPPORT

### Need Help?

1. **Check logs**:
   ```bash
   docker-compose logs -f api prometheus grafana
   ```

2. **Verify configuration**:
   ```bash
   docker-compose config
   ```

3. **Review documentation**:
   - SUB_BLOCK_3B_COMPLETE.md
   - PRODUCTION_DEPLOYMENT_CHECKLIST.md
   - SECURITY_HARDENING.md

4. **Test individual components**:
   - Metrics: `curl http://localhost:8000/metrics`
   - Health: `curl http://localhost:8000/api/v1/health`
   - Prometheus: http://localhost:9090/targets

---

**Last Updated**: February 2026  
**Version**: 0.2.0 (SUB-BLOCK 3B)  
**Status**: Production Ready ✅
