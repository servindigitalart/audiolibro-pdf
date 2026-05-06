# 🚀 PRODUCTION DEPLOYMENT CHECKLIST

**Sonoro SaaS Platform - DigitalOcean VPS Deployment**

---

## ✅ PRE-DEPLOYMENT CHECKLIST

### 1. VPS Setup (DigitalOcean Droplet)

#### Recommended Specifications
- **Minimum**: 2 vCPUs, 4 GB RAM, 80 GB SSD
- **Recommended**: 4 vCPUs, 8 GB RAM, 160 GB SSD
- **OS**: Ubuntu 22.04 LTS (recommended)
- **Location**: Choose based on target user geography

#### Initial Server Setup
```bash
# SSH into your VPS
ssh root@your_server_ip

# Update system packages
apt update && apt upgrade -y

# Create non-root user with sudo privileges
adduser sonoro
usermod -aG sudo sonoro

# Set up SSH key authentication (recommended)
mkdir -p /home/sonoro/.ssh
cp ~/.ssh/authorized_keys /home/sonoro/.ssh/
chown -R sonoro:sonoro /home/sonoro/.ssh
chmod 700 /home/sonoro/.ssh
chmod 600 /home/sonoro/.ssh/authorized_keys

# Disable root SSH login (security)
sed -i 's/PermitRootLogin yes/PermitRootLogin no/' /etc/ssh/sshd_config
systemctl restart sshd

# Switch to sonoro user
su - sonoro
```

---

### 2. Firewall Configuration (UFW)

```bash
# Enable UFW
sudo ufw enable

# Allow SSH (IMPORTANT: Do this first!)
sudo ufw allow 22/tcp

# Allow HTTP and HTTPS
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp

# Deny all other incoming by default
sudo ufw default deny incoming
sudo ufw default allow outgoing

# Verify firewall status
sudo ufw status verbose

# Expected output:
# Status: active
# To                         Action      From
# --                         ------      ----
# 22/tcp                     ALLOW       Anywhere
# 80/tcp                     ALLOW       Anywhere
# 443/tcp                    ALLOW       Anywhere
```

**🔒 CRITICAL**: PostgreSQL (5432) and Redis (6379) should NOT be accessible from outside.

---

### 3. Docker Installation

```bash
# Install Docker
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh

# Add user to docker group
sudo usermod -aG docker sonoro

# Log out and back in for group to take effect
exit
ssh sonoro@your_server_ip

# Verify Docker installation
docker --version
docker run hello-world

# Install Docker Compose
sudo apt install docker-compose-plugin -y

# Verify Docker Compose
docker compose version
```

---

### 4. DNS Configuration

#### Point Domain to VPS
1. Go to your domain registrar (Namecheap, GoDaddy, etc.)
2. Add/Update DNS records:

```
Type    Name    Value               TTL
A       @       your_server_ip      300
A       www     your_server_ip      300
```

3. Wait for DNS propagation (5-30 minutes)
4. Verify DNS:
```bash
nslookup yourdomain.com
dig yourdomain.com
```

---

### 5. SSL Certificate (Let's Encrypt)

```bash
# Install Certbot
sudo apt install certbot python3-certbot-nginx -y

# Create directory for ACME challenge
sudo mkdir -p /var/www/certbot

# Start Nginx temporarily (HTTP only for ACME challenge)
cd /path/to/sonoro
docker compose -f infra/docker-compose.prod.yml up -d nginx

# Obtain SSL certificate
sudo certbot certonly --webroot \
  -w /var/www/certbot \
  -d yourdomain.com \
  -d www.yourdomain.com \
  --email your-email@example.com \
  --agree-tos \
  --no-eff-email

# Certificates will be stored in:
# /etc/letsencrypt/live/yourdomain.com/fullchain.pem
# /etc/letsencrypt/live/yourdomain.com/privkey.pem

# Set up automatic renewal
sudo systemctl enable certbot.timer
sudo systemctl start certbot.timer

# Test renewal (dry run)
sudo certbot renew --dry-run
```

---

### 6. Application Deployment

#### Clone Repository
```bash
# Install Git
sudo apt install git -y

# Clone repository (use deploy key or personal access token)
git clone https://github.com/your-org/sonoro.git
cd sonoro

# Or use deploy key:
ssh-keygen -t ed25519 -C "deploy@sonoro"
# Add public key to GitHub deploy keys
```

#### Configure Environment
```bash
# Copy environment template
cp .env.example .env

# Edit environment file
nano .env

# CRITICAL SETTINGS TO CHANGE:
# - APP_ENV=production
# - DEBUG=false
# - SECRET_KEY=<generate with: openssl rand -hex 32>
# - DOMAIN_NAME=yourdomain.com
# - POSTGRES_PASSWORD=<strong password>
# - REDIS_PASSWORD=<strong password>
# - API_CORS_ORIGINS=https://yourdomain.com
# - DATABASE_URL=<update with production password>
# - REDIS_URL=<update with production password if set>
```

#### Generate Strong Secrets
```bash
# Generate SECRET_KEY
openssl rand -hex 32

# Generate database password
openssl rand -base64 32

# Generate Redis password
openssl rand -base64 32
```

#### Build and Start Services
```bash
# Build images
docker compose -f infra/docker-compose.prod.yml build

# Start services
docker compose -f infra/docker-compose.prod.yml up -d

# View logs
docker compose -f infra/docker-compose.prod.yml logs -f

# Check service status
docker compose -f infra/docker-compose.prod.yml ps
```

#### Run Database Migrations
```bash
# Run migrations
docker compose -f infra/docker-compose.prod.yml exec api alembic upgrade head

# Verify migration
docker compose -f infra/docker-compose.prod.yml exec api alembic current
```

---

### 7. Post-Deployment Verification

#### Health Check
```bash
# Check API health
curl https://yourdomain.com/api/v1/health

# Expected response:
# {"status":"healthy","services":{"database":"healthy","redis":"healthy"}}
```

#### API Documentation
```bash
# Open in browser
https://yourdomain.com/docs
https://yourdomain.com/redoc
```

#### Test Authentication Flow
```bash
# Register a test user
curl -X POST https://yourdomain.com/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email":"test@yourdomain.com","password":"TestPass123"}'

# Login
curl -X POST https://yourdomain.com/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"test@yourdomain.com","password":"TestPass123"}'

# Get current user (use token from login)
curl https://yourdomain.com/api/v1/auth/me \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN"
```

#### SSL Verification
```bash
# Check SSL certificate
curl -vI https://yourdomain.com

# Verify SSL grade (external tool)
# https://www.ssllabs.com/ssltest/analyze.html?d=yourdomain.com
```

---

## 🔒 SECURITY HARDENING

### 1. Secrets Management

#### Option A: Environment Variables (Current)
- ✅ Simple for single-server deployment
- ✅ Suitable for VPS hosting
- ⚠️ Ensure `.env` has proper permissions:
```bash
chmod 600 .env
chown sonoro:sonoro .env
```

#### Option B: Docker Secrets (Advanced)
```bash
# For Docker Swarm mode
echo "super_secret_password" | docker secret create postgres_password -
```

#### Option C: DigitalOcean App Platform Secrets
- If using DO App Platform, use built-in secret management

### 2. Database Security

```bash
# Verify PostgreSQL is NOT exposed
sudo netstat -tulpn | grep 5432
# Should show: 127.0.0.1:5432 or no output (Docker internal only)

# Access PostgreSQL only via Docker network
docker compose -f infra/docker-compose.prod.yml exec postgres psql -U sonoro
```

### 3. Redis Security

```bash
# Verify Redis is NOT exposed
sudo netstat -tulpn | grep 6379
# Should show: 127.0.0.1:6379 or no output (Docker internal only)

# Enable Redis password (in .env)
REDIS_PASSWORD=your_strong_redis_password
REDIS_URL=redis://:your_strong_redis_password@redis:6379/0
```

### 4. Fail2Ban (Brute Force Protection)

```bash
# Install Fail2Ban
sudo apt install fail2ban -y

# Create Nginx jail for auth endpoints
sudo nano /etc/fail2ban/jail.local

# Add:
[nginx-auth]
enabled = true
filter = nginx-auth
action = iptables-multiport[name=NoAuthFailures, port="http,https"]
logpath = /var/log/nginx/access.log
bantime = 3600
findtime = 600
maxretry = 5

# Create filter
sudo nano /etc/fail2ban/filter.d/nginx-auth.conf

# Add:
[Definition]
failregex = ^<HOST> .* "(POST|GET) /api/v1/auth/(login|register)" .* (401|403) .*$

# Restart Fail2Ban
sudo systemctl restart fail2ban
sudo fail2ban-client status
```

---

## 📊 MONITORING & OBSERVABILITY

### 1. Enable Sentry (Error Tracking)

```bash
# Sign up at sentry.io
# Create a project
# Get DSN from project settings

# Update .env
SENTRY_DSN=https://your-sentry-dsn@sentry.io/project-id
SENTRY_ENVIRONMENT=production
SENTRY_TRACES_SAMPLE_RATE=0.1
```

### 2. Log Management

```bash
# View application logs
docker compose -f infra/docker-compose.prod.yml logs -f api

# View Nginx logs
docker compose -f infra/docker-compose.prod.yml logs -f nginx

# View all logs
docker compose -f infra/docker-compose.prod.yml logs -f

# Log rotation is configured in docker-compose.prod.yml
# API: 50MB x 5 files
# Nginx: 20MB x 5 files
# Others: 10-20MB x 3-5 files
```

### 3. Resource Monitoring

```bash
# Install monitoring tools
sudo apt install htop iotop -y

# Monitor resource usage
htop

# Monitor Docker containers
docker stats

# Monitor disk usage
df -h
du -sh /var/lib/docker/*
```

### 4. Uptime Monitoring (External)

Recommended services:
- **UptimeRobot** (free): https://uptimerobot.com
- **Pingdom**: https://www.pingdom.com
- **Better Uptime**: https://betteruptime.com

Set up monitoring for:
- `https://yourdomain.com/api/v1/health` (every 5 minutes)
- Alert channels: Email, Slack, SMS

---

## 💾 BACKUP STRATEGY

### 1. Database Backups

```bash
# Create backup script
sudo nano /usr/local/bin/backup-sonoro-db.sh
```

```bash
#!/bin/bash
# Sonoro PostgreSQL Backup Script

BACKUP_DIR="/home/sonoro/backups/postgres"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="$BACKUP_DIR/sonoro_backup_$TIMESTAMP.sql.gz"

# Create backup directory
mkdir -p $BACKUP_DIR

# Backup database
docker compose -f /home/sonoro/sonoro/infra/docker-compose.prod.yml exec -T postgres \
  pg_dump -U sonoro sonoro | gzip > $BACKUP_FILE

# Keep only last 7 days of backups
find $BACKUP_DIR -name "sonoro_backup_*.sql.gz" -mtime +7 -delete

echo "Backup completed: $BACKUP_FILE"
```

```bash
# Make executable
sudo chmod +x /usr/local/bin/backup-sonoro-db.sh

# Add to crontab (daily at 2 AM)
crontab -e

# Add line:
0 2 * * * /usr/local/bin/backup-sonoro-db.sh
```

### 2. DigitalOcean Snapshots

```bash
# Enable weekly snapshots in DigitalOcean dashboard
# Droplet > Settings > Snapshots
# Schedule: Weekly on Sunday at 2 AM
```

### 3. Restore from Backup

```bash
# Stop application
docker compose -f infra/docker-compose.prod.yml down

# Restore database
gunzip -c /home/sonoro/backups/postgres/sonoro_backup_TIMESTAMP.sql.gz | \
  docker compose -f infra/docker-compose.prod.yml exec -T postgres \
  psql -U sonoro sonoro

# Start application
docker compose -f infra/docker-compose.prod.yml up -d
```

---

## 🔄 UPDATES & MAINTENANCE

### 1. Application Updates

```bash
# Pull latest code
cd /home/sonoro/sonoro
git pull origin main

# Rebuild and restart
docker compose -f infra/docker-compose.prod.yml build
docker compose -f infra/docker-compose.prod.yml up -d

# Run migrations (if any)
docker compose -f infra/docker-compose.prod.yml exec api alembic upgrade head

# Verify health
curl https://yourdomain.com/api/v1/health
```

### 2. Zero-Downtime Deployment (Future)

```bash
# Scale API to 2 instances
docker compose -f infra/docker-compose.prod.yml up -d --scale api=2

# Update one instance at a time
# Requires load balancer (Nginx already configured)
```

### 3. System Updates

```bash
# Update system packages (monthly)
sudo apt update && sudo apt upgrade -y

# Update Docker images (quarterly)
docker compose -f infra/docker-compose.prod.yml pull
docker compose -f infra/docker-compose.prod.yml up -d
```

---

## 🚨 INCIDENT RESPONSE

### Quick Commands

```bash
# Restart all services
docker compose -f infra/docker-compose.prod.yml restart

# Restart specific service
docker compose -f infra/docker-compose.prod.yml restart api

# View real-time logs
docker compose -f infra/docker-compose.prod.yml logs -f api

# Check container health
docker compose -f infra/docker-compose.prod.yml ps

# Enter container shell
docker compose -f infra/docker-compose.prod.yml exec api sh

# Check resource usage
docker stats

# Check disk space
df -h

# Check memory
free -h
```

### Common Issues

#### High CPU Usage
```bash
# Identify container
docker stats

# Scale down workers if needed
docker compose -f infra/docker-compose.prod.yml up -d --scale worker=1
```

#### Out of Memory
```bash
# Check memory
free -h

# Restart services to free memory
docker compose -f infra/docker-compose.prod.yml restart

# Consider upgrading VPS RAM
```

#### Disk Space Full
```bash
# Check disk usage
df -h

# Clean Docker
docker system prune -a --volumes

# Clean old logs
docker compose -f infra/docker-compose.prod.yml down
sudo rm -rf /var/lib/docker/containers/*/
docker compose -f infra/docker-compose.prod.yml up -d
```

---

## ✅ POST-DEPLOYMENT CHECKLIST

- [ ] VPS created and SSH configured
- [ ] Firewall (UFW) configured and enabled
- [ ] Docker and Docker Compose installed
- [ ] DNS records pointing to VPS
- [ ] SSL certificate obtained and configured
- [ ] `.env` file configured with production values
- [ ] Strong secrets generated and set
- [ ] Application deployed and running
- [ ] Database migrations executed
- [ ] Health check returns 200 OK
- [ ] API documentation accessible
- [ ] Authentication flow tested
- [ ] SSL grade A or A+ (ssllabs.com)
- [ ] Sentry configured and receiving errors
- [ ] Uptime monitoring configured
- [ ] Database backups automated
- [ ] Fail2Ban configured (optional but recommended)
- [ ] Team notified of deployment

---

## 📚 ADDITIONAL RESOURCES

- **DigitalOcean Docs**: https://docs.digitalocean.com
- **Let's Encrypt Docs**: https://letsencrypt.org/docs
- **Nginx Docs**: https://nginx.org/en/docs
- **Docker Docs**: https://docs.docker.com
- **Sentry Docs**: https://docs.sentry.io

---

## 🎉 SUCCESS CRITERIA

Deployment is successful when:
1. ✅ Application accessible via HTTPS
2. ✅ Health check returns healthy status
3. ✅ Can register and login users
4. ✅ SSL certificate valid (A+ grade)
5. ✅ No exposed database or Redis ports
6. ✅ Monitoring and alerts configured
7. ✅ Backups automated
8. ✅ Team can access and verify

---

**Deployment completed by**: _________________  
**Date**: _________________  
**Domain**: _________________  
**VPS IP**: _________________

---

*For support, refer to SECURITY_HARDENING.md and project documentation.*
