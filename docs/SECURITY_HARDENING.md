# 🔒 SECURITY HARDENING GUIDE

**Sonoro SaaS Platform - Production Security Posture**

---

## 🎯 SECURITY PHILOSOPHY

Sonoro implements **defense in depth** with multiple security layers:

1. **Network Security** - Firewall, internal networking, no exposed services
2. **Application Security** - JWT, bcrypt, input validation, CORS
3. **Infrastructure Security** - Container isolation, resource limits, non-root
4. **Data Security** - Encryption, backups, secure storage
5. **Operational Security** - Monitoring, logging, incident response

---

## 🛡️ LAYER 1: NETWORK SECURITY

### Firewall Configuration (UFW)

**Current Implementation**:
```bash
# Only allow essential ports
ufw allow 22/tcp   # SSH
ufw allow 80/tcp   # HTTP (redirects to HTTPS)
ufw allow 443/tcp  # HTTPS
ufw enable
```

**Security Posture**:
- ✅ PostgreSQL (5432) NOT exposed to internet
- ✅ Redis (6379) NOT exposed to internet
- ✅ API (8000) only accessible via Nginx reverse proxy
- ✅ All services communicate via internal Docker network

**Verification**:
```bash
# Check open ports
sudo netstat -tulpn | grep LISTEN

# Expected output:
# - 22 (SSH)
# - 80 (Nginx HTTP)
# - 443 (Nginx HTTPS)
# - NO 5432, 6379, or 8000
```

### Internal Network Isolation

**Docker Network Configuration**:
- Custom bridge network: `172.25.0.0/16`
- Services communicate via service names (DNS)
- No port mapping for internal services (postgres, redis)
- Only Nginx exposes ports 80/443

**Security Benefits**:
- Services cannot be accessed directly from internet
- Network segmentation between containers
- Built-in DNS resolution for service discovery

---

## 🔐 LAYER 2: APPLICATION SECURITY

### Authentication & Authorization

#### JWT Token Security

**Current Implementation**:
- Access tokens: 15 minutes (short-lived)
- Refresh tokens: 7 days (long-lived, revocable)
- HS256 signing algorithm
- Unique JTI (JWT ID) for refresh tokens
- Token rotation on refresh (single-use tokens)

**Security Features**:
```python
# Token structure
{
  "sub": "user-uuid",
  "exp": timestamp,
  "iat": timestamp,
  "type": "access",  # or "refresh"
  "jti": "unique-id"  # refresh only
}
```

**Best Practices Applied**:
- ✅ Short-lived access tokens (stateless)
- ✅ Refresh token rotation (prevents replay attacks)
- ✅ Redis-backed token blacklist (instant revocation)
- ✅ Token type validation (prevents confusion attacks)
- ✅ Secure secret key (256-bit minimum)

#### Password Security

**Hashing**:
- Algorithm: bcrypt via passlib
- Automatic salt generation
- Configurable work factor (cost)
- One-way hashing (cannot reverse)

**Password Policy**:
```python
# Enforced at registration and password change
- Minimum 8 characters
- At least one uppercase letter
- At least one lowercase letter
- At least one digit
```

**Recommendations**:
- Consider adding special character requirement
- Implement password history (prevent reuse)
- Add compromised password check (HaveIBeenPwned API)

#### Session Management

**Current State**:
- Stateless JWT for access tokens
- Redis storage for refresh tokens (revocable)
- Logout invalidates refresh tokens immediately

**Future Enhancements**:
- Session tracking (active devices)
- Geolocation-based anomaly detection
- Concurrent session limits

---

## 🚦 LAYER 3: RATE LIMITING & BRUTE FORCE MITIGATION

### Nginx Rate Limiting

**Configured Zones**:

1. **Auth Endpoints** (login, register, refresh):
   - **Limit**: 10 requests per minute per IP
   - **Burst**: 5 additional requests
   - **Use case**: Prevent brute force attacks

2. **Upload Endpoints** (future):
   - **Limit**: 5 requests per minute per IP
   - **Burst**: 2 additional requests
   - **Use case**: Prevent resource exhaustion

3. **API Endpoints** (general):
   - **Limit**: 100 requests per minute per IP
   - **Burst**: 20 additional requests
   - **Use case**: Prevent API abuse

4. **Connection Limiting**:
   - **Limit**: 10 concurrent connections per IP
   - **Use case**: Prevent connection exhaustion

### Fail2Ban Integration

**Setup** (see PRODUCTION_DEPLOYMENT_CHECKLIST.md):
```bash
[nginx-auth]
enabled = true
filter = nginx-auth
logpath = /var/log/nginx/access.log
bantime = 3600    # 1 hour ban
findtime = 600    # 10 minute window
maxretry = 5      # 5 failures = ban
```

**What it does**:
- Monitors Nginx access logs
- Detects failed authentication attempts (401/403)
- Automatically bans offending IPs via iptables
- Releases ban after timeout

### Application-Level Rate Limiting (Future)

**Planned Enhancement**:
```python
# Redis-based rate limiting
# Per-user limits (not just IP-based)
# Sliding window algorithm
# Tiered limits based on subscription

@rate_limit(limit="100/minute", scope="user")
async def api_endpoint():
    ...
```

**Why not implemented yet**:
- Nginx rate limiting sufficient for Block 3A
- Application-level limits for future subscription tiers
- Requires user-based tracking (more complex)

---

## 🔒 LAYER 4: SECRETS MANAGEMENT

### Current Strategy: Environment Variables

**Security Measures**:
```bash
# File permissions
chmod 600 .env
chown sonoro:sonoro .env

# Never commit to git
.env is in .gitignore

# Separate dev and prod configs
.env.example (safe to commit)
.env (never commit)
```

**Secret Rotation**:
```bash
# Generate new SECRET_KEY
openssl rand -hex 32

# Update .env
# Restart application
docker compose -f infra/docker-compose.prod.yml restart api
```

### Future Enhancements

#### Option A: Docker Secrets (Swarm Mode)
```bash
# For Docker Swarm deployments
echo "my_secret" | docker secret create db_password -
```

#### Option B: HashiCorp Vault
- Centralized secret management
- Dynamic secrets
- Audit logging
- Automatic rotation

#### Option C: Cloud Provider Secrets
- AWS Secrets Manager
- DigitalOcean App Platform Secrets
- Azure Key Vault

**Recommendation**: Current strategy is sufficient for single-VPS deployment. Consider cloud secrets when scaling to multi-server or multi-region.

---

## 🗄️ LAYER 5: DATABASE SECURITY

### PostgreSQL Hardening

**Current Security**:
- ✅ NOT exposed to internet (no port mapping)
- ✅ Strong password authentication
- ✅ Limited to 100 max connections
- ✅ Encrypted at rest (filesystem-level)
- ✅ Regular backups (automated)

**Connection Security**:
```python
# Application connects via:
postgresql+asyncpg://user:pass@postgres:5432/db

# postgres hostname resolves to internal Docker IP
# NOT accessible from outside Docker network
```

**Additional Hardening**:
```sql
-- Revoke public schema permissions
REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT ALL ON SCHEMA public TO sonoro;

-- Disable unused extensions
-- Audit user privileges regularly
```

**Backup Security**:
```bash
# Encrypted backups
pg_dump -U sonoro sonoro | \
  openssl enc -aes-256-cbc -salt -pbkdf2 \
  -out backup_encrypted.sql.enc

# Store backups in DigitalOcean Spaces (encrypted)
```

### Redis Hardening

**Current Security**:
- ✅ NOT exposed to internet
- ✅ Password protection (optional, recommended)
- ✅ Memory limits (256MB)
- ✅ AOF persistence (durability)

**Redis Configuration**:
```bash
# In docker-compose.prod.yml
redis-server \
  --requirepass ${REDIS_PASSWORD} \
  --maxmemory 256mb \
  --maxmemory-policy allkeys-lru \
  --appendonly yes
```

**Additional Hardening**:
```bash
# Disable dangerous commands
redis-cli CONFIG SET rename-command FLUSHDB ""
redis-cli CONFIG SET rename-command FLUSHALL ""
redis-cli CONFIG SET rename-command CONFIG ""
```

---

## 🌐 LAYER 6: WEB SECURITY HEADERS

### Security Headers (Nginx)

**Implemented Headers**:

1. **Strict-Transport-Security (HSTS)**
   ```nginx
   add_header Strict-Transport-Security "max-age=31536000; includeSubDomains; preload" always;
   ```
   - Forces HTTPS for 1 year
   - Includes all subdomains
   - Preload list eligible

2. **X-Frame-Options**
   ```nginx
   add_header X-Frame-Options "SAMEORIGIN" always;
   ```
   - Prevents clickjacking
   - Only allows framing from same origin

3. **X-Content-Type-Options**
   ```nginx
   add_header X-Content-Type-Options "nosniff" always;
   ```
   - Prevents MIME sniffing
   - Forces declared content type

4. **X-XSS-Protection**
   ```nginx
   add_header X-XSS-Protection "1; mode=block" always;
   ```
   - Enables browser XSS filter
   - Blocks page if XSS detected

5. **Referrer-Policy**
   ```nginx
   add_header Referrer-Policy "strict-origin-when-cross-origin" always;
   ```
   - Limits referrer information leakage
   - Full URL only on same origin

6. **Content-Security-Policy (CSP)**
   ```nginx
   add_header Content-Security-Policy "default-src 'self'; ..." always;
   ```
   - Restricts resource loading
   - Prevents XSS and injection attacks

7. **Permissions-Policy**
   ```nginx
   add_header Permissions-Policy "geolocation=(), microphone=(), camera=()" always;
   ```
   - Disables unnecessary browser features

### Verification

**Check Headers**:
```bash
curl -I https://yourdomain.com | grep -E '(Strict-Transport|X-Frame|X-Content|CSP)'
```

**Security Scanners**:
- **Mozilla Observatory**: https://observatory.mozilla.org
- **Security Headers**: https://securityheaders.com
- **SSL Labs**: https://www.ssllabs.com/ssltest

**Target Grade**: A or A+

---

## 🔍 LAYER 7: LOGGING & MONITORING

### Logging Strategy

**What We Log**:
- Application errors (Sentry)
- HTTP requests (Nginx access log)
- Failed authentication attempts (Nginx + Fail2Ban)
- Database queries (error level only)
- Container health (Docker logs)

**What We DON'T Log**:
- ❌ Passwords (never)
- ❌ JWT tokens (security risk)
- ❌ Sensitive user data (PII)
- ❌ API keys or secrets

**Log Rotation**:
```yaml
# Configured in docker-compose.prod.yml
logging:
  driver: "json-file"
  options:
    max-size: "50m"   # API logs
    max-file: "5"     # Keep 5 rotated files
```

### Security Monitoring

**Health Checks**:
```bash
# Automated health monitoring
GET /api/v1/health

# Returns:
{
  "status": "healthy",
  "services": {
    "database": "healthy",
    "redis": "healthy"
  }
}
```

**Error Tracking (Sentry)**:
```python
# Automatic error reporting
# Configured in .env:
SENTRY_DSN=https://your-dsn@sentry.io/project
SENTRY_ENVIRONMENT=production
SENTRY_TRACES_SAMPLE_RATE=0.1  # 10% tracing
```

**Uptime Monitoring**:
- External service (UptimeRobot, Pingdom)
- Checks every 5 minutes
- Alerts via email/Slack/SMS
- Tracks uptime percentage

### Log Analysis

**Detect Anomalies**:
```bash
# Failed authentication attempts
grep "POST /api/v1/auth/login.*401" /var/log/nginx/access.log

# High rate of 429 errors (rate limiting triggered)
grep " 429 " /var/log/nginx/access.log | wc -l

# Suspicious user agents
grep -i "bot\|crawler\|scanner" /var/log/nginx/access.log
```

---

## 🚨 LAYER 8: INCIDENT RESPONSE

### Incident Types

1. **Brute Force Attack**
   - **Detection**: Fail2Ban, rate limiting triggers
   - **Response**: Automatic IP ban, review logs
   - **Prevention**: Already implemented

2. **DDoS Attack**
   - **Detection**: High traffic, rate limit exhaustion
   - **Response**: Enable Cloudflare (see below)
   - **Prevention**: Consider Cloudflare integration

3. **Data Breach**
   - **Detection**: Sentry alerts, unusual activity
   - **Response**: Rotate secrets, audit logs, notify users
   - **Prevention**: Regular security audits

4. **Container Compromise**
   - **Detection**: Resource anomalies, Sentry errors
   - **Response**: Stop container, investigate, redeploy
   - **Prevention**: Non-root containers, read-only filesystems

### Quick Response Commands

```bash
# Block specific IP immediately
sudo ufw insert 1 deny from <ip_address>

# Stop all services
docker compose -f infra/docker-compose.prod.yml down

# Rotate all secrets
openssl rand -hex 32 > new_secret_key
# Update .env, restart

# Check for compromised credentials
grep "401\|403" /var/log/nginx/access.log | tail -100

# Restore from backup
# See PRODUCTION_DEPLOYMENT_CHECKLIST.md
```

---

## ☁️ LAYER 9: CLOUDFLARE INTEGRATION (OPTIONAL)

### Why Cloudflare?

**Benefits**:
- DDoS protection (free)
- Global CDN
- Additional WAF (Web Application Firewall)
- Bot mitigation
- Analytics dashboard
- Zero Trust Access (paid)

**Setup**:
1. Create Cloudflare account
2. Add domain to Cloudflare
3. Update nameservers at registrar
4. Enable "Proxy" (orange cloud) for domain
5. Configure SSL/TLS mode: "Full (strict)"

**Firewall Rules** (Examples):
```
# Block bad bots
(cf.client.bot) and not (cf.verified_bot_category in {"Search Engine Crawler"})

# Rate limit auth endpoints
(http.request.uri.path contains "/auth/login") and 
(rate > 10 per 1 minute)

# Block specific countries (if needed)
(ip.geoip.country in {"XX" "YY"})
```

**Cost**: Free tier sufficient for most SaaS applications.

---

## 🔐 LAYER 10: COMPLIANCE & BEST PRACTICES

### Data Protection

**GDPR Considerations**:
- User data stored in EU region (DigitalOcean Frankfurt)
- Right to deletion (implement user account deletion)
- Data portability (implement data export)
- Privacy policy and terms of service

**PCI DSS** (if handling payments):
- Use Stripe (PCI-compliant)
- Never store credit card data
- Use Stripe Checkout or Elements

### Security Audits

**Recommended Frequency**:
- Weekly: Review access logs
- Monthly: Update dependencies, check CVEs
- Quarterly: Penetration testing
- Annually: Full security audit

**Automated Tools**:
```bash
# Dependency vulnerability scanning
docker scan sonoro-api:latest

# OWASP ZAP (web app scanner)
# Run against staging environment

# Trivy (container scanner)
trivy image sonoro-api:latest
```

### Secure Development Practices

**Code Review Checklist**:
- [ ] No hardcoded secrets
- [ ] Input validation on all endpoints
- [ ] SQL injection prevention (using ORMs)
- [ ] XSS prevention (proper output encoding)
- [ ] CSRF protection (where needed)
- [ ] Authentication required for sensitive endpoints
- [ ] Authorization checks in place

---

## 📊 SECURITY METRICS

### Key Performance Indicators

**Metrics to Track**:
1. Failed authentication attempts per hour
2. Rate limit triggers per day
3. Uptime percentage (target: 99.9%)
4. Mean time to detect (MTTD) incidents
5. Mean time to resolve (MTTR) incidents
6. SSL certificate expiration days remaining
7. Number of active user sessions

**Alerting Thresholds**:
- Failed auth > 100/hour → Alert
- Rate limit triggers > 1000/hour → Alert
- Uptime < 99.9% → Alert
- SSL cert < 30 days remaining → Alert
- Disk usage > 80% → Alert
- Memory usage > 90% → Alert

---

## 🎯 SECURITY ROADMAP

### Block 3A (Current)
- ✅ Nginx reverse proxy with SSL
- ✅ Rate limiting on auth endpoints
- ✅ Security headers
- ✅ Firewall configuration
- ✅ Internal network isolation
- ✅ Resource limits
- ✅ Logging and monitoring foundation

### Block 3B (Future)
- [ ] Redis-based application rate limiting
- [ ] Per-user rate limits
- [ ] Tiered limits by subscription
- [ ] Advanced anomaly detection

### Block 4+ (Future)
- [ ] Email verification (anti-bot measure)
- [ ] Two-factor authentication (2FA)
- [ ] OAuth2 integration (Google, GitHub)
- [ ] Session management dashboard
- [ ] Compromised password detection
- [ ] Geographic blocking (optional)
- [ ] Web Application Firewall (WAF)

---

## ✅ SECURITY CHECKLIST

### Infrastructure
- [x] Firewall enabled (UFW)
- [x] Only essential ports open (22, 80, 443)
- [x] Database not exposed to internet
- [x] Redis not exposed to internet
- [x] SSL certificate installed
- [x] SSL grade A or A+ (ssllabs.com)
- [x] HSTS enabled
- [ ] Fail2Ban configured (optional but recommended)
- [ ] Cloudflare enabled (optional)

### Application
- [x] Strong password hashing (bcrypt)
- [x] Password complexity requirements
- [x] JWT token security implemented
- [x] Token rotation on refresh
- [x] Rate limiting on auth endpoints
- [x] CORS properly configured
- [x] Input validation (Pydantic)
- [x] SQL injection prevention (SQLAlchemy ORM)

### Operations
- [x] Automated backups configured
- [x] Secrets not in version control
- [x] Strong SECRET_KEY generated
- [x] Database password changed from default
- [x] Redis password set (optional but recommended)
- [x] Logging configured
- [x] Error tracking enabled (Sentry)
- [x] Uptime monitoring enabled
- [x] Incident response plan documented

### Monitoring
- [x] Health check endpoint monitored
- [x] Application errors tracked (Sentry)
- [x] Access logs reviewed regularly
- [x] Resource usage monitored
- [x] SSL certificate expiration monitored

---

## 📚 ADDITIONAL RESOURCES

**Security Standards**:
- OWASP Top 10: https://owasp.org/www-project-top-ten
- CIS Benchmarks: https://www.cisecurity.org/cis-benchmarks

**Tools**:
- OWASP ZAP: https://www.zaproxy.org
- Burp Suite: https://portswigger.net/burp
- Trivy: https://github.com/aquasecurity/trivy
- Fail2Ban: https://www.fail2ban.org

**Learning**:
- OWASP Cheat Sheets: https://cheatsheetseries.owasp.org
- Mozilla Web Security: https://infosec.mozilla.org
- NIST Cybersecurity Framework: https://www.nist.gov/cyberframework

---

## 🎉 CONCLUSION

Sonoro's security posture is **production-ready** for a single-VPS SaaS deployment with:

✅ **Strong authentication** (JWT + bcrypt)  
✅ **Network isolation** (firewall + Docker)  
✅ **Rate limiting** (Nginx + Fail2Ban)  
✅ **Encrypted transport** (HTTPS + HSTS)  
✅ **Secure secrets** (environment variables)  
✅ **Monitoring** (Sentry + uptime)  
✅ **Backups** (automated PostgreSQL)  
✅ **Incident response** (documented procedures)

**Security is an ongoing process**. Regular audits, updates, and monitoring are essential to maintain a strong security posture.

---

*Last updated: Block 3A completion*  
*Next review: Block 4 implementation*
