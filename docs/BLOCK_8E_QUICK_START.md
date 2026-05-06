# BLOCK 8E - Quick Start Guide

**Status:** ✅ PRODUCTION-READY  
**Time to Deploy:** ~5 minutes

---

## 🚀 QUICK DEPLOYMENT

### 1. Run Database Migration

```bash
# Start services
docker-compose up -d

# Run migration
docker-compose exec api alembic upgrade head

# Verify migration
docker-compose exec postgres psql -U sonoro -d sonoro \
  -c "\d api_keys" \
  -c "SELECT column_name FROM information_schema.columns WHERE table_name='users' AND column_name='full_name';"
```

**Expected output:**
```
                       Table "public.api_keys"
    Column    |           Type           | Collation | Nullable | Default
--------------+--------------------------+-----------+----------+---------
 id           | uuid                     |           | not null | 
 user_id      | uuid                     |           | not null | 
 key_hash     | character varying(255)   |           | not null | 
 key_preview  | character varying(10)    |           | not null | 
 is_active    | boolean                  |           | not null | true
 created_at   | timestamp with time zone |           | not null | now()
 last_used_at | timestamp with time zone |           |          | 

 column_name 
-------------
 full_name
```

---

## 🧪 QUICK TEST

### 1. Test Backend Endpoints

```bash
# Login first
TOKEN=$(curl -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"test@example.com","password":"TestPassword123!"}' \
  | jq -r '.access_token')

# Test profile endpoint
curl http://localhost:8000/api/v1/account/profile \
  -H "Authorization: Bearer $TOKEN"

# Update profile
curl -X PATCH http://localhost:8000/api/v1/account/profile \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"full_name":"John Doe"}'

# Generate API key
curl -X POST http://localhost:8000/api/v1/account/api-key \
  -H "Authorization: Bearer $TOKEN"

# List API keys
curl http://localhost:8000/api/v1/account/api-keys \
  -H "Authorization: Bearer $TOKEN"
```

### 2. Test Frontend

```bash
# Navigate to settings page
open http://localhost:3000/settings
```

**Test Checklist:**
- [ ] Can update full name
- [ ] Can change preferences (language, voice, timezone, currency)
- [ ] Can toggle notification settings
- [ ] Can generate API key (see full key once)
- [ ] Can revoke API key
- [ ] Toast notifications appear for all actions
- [ ] Can open account deletion dialog

---

## 📱 USER FLOW

### Profile Update
1. Navigate to `/settings`
2. Update full name in Profile section
3. Click "Save Profile"
4. See success toast

### Change Password
1. Go to Security section
2. Enter current password
3. Enter new password (min 8 chars)
4. Confirm new password
5. Click "Change Password"
6. See success toast

### Generate API Key
1. Go to API Keys section
2. Click "Generate Key"
3. **Copy key from dialog** (shown once!)
4. Click "Close"
5. See masked key in list

### Revoke API Key
1. Find key in list (shows last 4 chars)
2. Click "Revoke" button
3. Confirm action
4. See success toast

### Delete Account
1. Scroll to Danger Zone
2. Click "Delete Account"
3. Enter password
4. Type "DELETE" exactly
5. Click "Delete Account"
6. Account deactivated, redirected to homepage

---

## 🔧 CONFIGURATION

### Available Languages
```typescript
en, es, fr, de, it, pt, nl, pl, ru, ja, zh
```

### Available Voices
```typescript
alloy, echo, fable, onyx, nova, shimmer
```

### Timezones
```typescript
UTC, America/New_York, America/Chicago, America/Denver,
America/Los_Angeles, Europe/London, Europe/Paris, Europe/Berlin,
Asia/Tokyo, Asia/Shanghai, Australia/Sydney
```

### Currencies
```typescript
USD, EUR, GBP, JPY, CAD, AUD
```

---

## 📊 MONITORING

### Check Metrics
```bash
# View settings metrics
curl http://localhost:8000/metrics | grep sonoro_profile
curl http://localhost:8000/metrics | grep sonoro_api_key
curl http://localhost:8000/metrics | grep sonoro_password
curl http://localhost:8000/metrics | grep sonoro_account_deletion
```

### Example Queries
```promql
# Profile updates in last hour
increase(sonoro_profile_updates_total[1h])

# API keys generated today
increase(sonoro_api_keys_generated_total[24h])

# Password change rate
rate(sonoro_password_changes_total[5m])
```

---

## 🐛 TROUBLESHOOTING

### Migration Issues
```bash
# Check current migration version
docker-compose exec api alembic current

# Downgrade if needed
docker-compose exec api alembic downgrade -1

# Re-upgrade
docker-compose exec api alembic upgrade head
```

### Frontend TypeScript Errors
```bash
# Rebuild frontend
cd frontend
npm run build

# Restart dev server
npm run dev
```

### API Key Not Generated
```bash
# Check database
docker-compose exec postgres psql -U sonoro -d sonoro \
  -c "SELECT COUNT(*) FROM api_keys WHERE is_active=true;"

# Check logs
docker-compose logs api | grep "api-key"
```

### Toast Not Showing
- Verify Toaster component is in layout
- Check browser console
- Hard refresh browser (Cmd+Shift+R)

---

## 📁 KEY FILES

### Backend
- `services/api/app/routers/account.py` - Account endpoints
- `services/api/app/schemas/account.py` - Request/response schemas
- `services/api/app/db/models/api_key.py` - APIKey model
- `services/api/alembic/versions/010_user_settings_personalization.py` - Migration

### Frontend
- `frontend/app/(dashboard)/settings/page.tsx` - Settings UI
- `frontend/lib/settings-service.ts` - API client
- `frontend/hooks/use-toast.ts` - Toast hook
- `frontend/components/toaster.tsx` - Toast display

---

## ✅ VERIFICATION

### Backend Health Check
```bash
# All should return 200
curl -I http://localhost:8000/api/v1/account/profile \
  -H "Authorization: Bearer $TOKEN"

curl -I http://localhost:8000/api/v1/account/settings \
  -H "Authorization: Bearer $TOKEN"

curl -I http://localhost:8000/api/v1/account/api-keys \
  -H "Authorization: Bearer $TOKEN"
```

### Frontend Health Check
```bash
# Should load without errors
curl -I http://localhost:3000/settings

# Check in browser
open http://localhost:3000/settings
# No console errors
# All sections visible
# All buttons functional
```

---

## 🎉 SUCCESS CRITERIA

You've successfully deployed BLOCK 8E if:

- ✅ Migration ran without errors
- ✅ Settings page loads
- ✅ Can update profile
- ✅ Can change preferences
- ✅ Can generate API key (see full key once)
- ✅ Can revoke API key
- ✅ Toast notifications work
- ✅ All Prometheus metrics incrementing
- ✅ No console errors

---

**Deployment time: ~5 minutes**  
**Zero downtime: Yes (with rolling deployment)**  
**Rollback time: ~1 minute**

For detailed documentation, see [BLOCK_8E_COMPLETE.md](./BLOCK_8E_COMPLETE.md)
