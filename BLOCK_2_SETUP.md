# 🚀 BLOCK 2 SETUP GUIDE

## Quick Start

### 1. Start Docker Desktop
Ensure Docker Desktop is running before proceeding.

### 2. Start Services
```bash
cd /Users/servinemilio/audiolibro-pdf
make dev
```

### 3. Run Migration
```bash
make migrate
```

### 4. Verify Setup
```bash
# Check health
curl http://localhost:8000/api/v1/health

# View API docs
open http://localhost:8000/docs
```

---

## Testing the Authentication System

### Test Registration
```bash
curl -X POST http://localhost:8000/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{
    "email": "test@example.com",
    "password": "SecurePass123"
  }'
```

Expected response:
```json
{
  "access_token": "eyJhbGc...",
  "refresh_token": "eyJhbGc...",
  "token_type": "bearer",
  "expires_in": 900
}
```

### Test Login
```bash
curl -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{
    "email": "test@example.com",
    "password": "SecurePass123"
  }'
```

### Test Get Current User
```bash
# Replace YOUR_ACCESS_TOKEN with actual token from login/register
curl -X GET http://localhost:8000/api/v1/auth/me \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN"
```

Expected response:
```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "email": "test@example.com",
  "is_active": true,
  "is_verified": false,
  "role": "user",
  "oauth_provider": null,
  "created_at": "2026-02-11T10:30:00Z",
  "updated_at": "2026-02-11T10:30:00Z"
}
```

### Test Token Refresh
```bash
curl -X POST http://localhost:8000/api/v1/auth/refresh \
  -H "Content-Type: application/json" \
  -d '{
    "refresh_token": "YOUR_REFRESH_TOKEN"
  }'
```

### Test Logout
```bash
curl -X POST http://localhost:8000/api/v1/auth/logout \
  -H "Content-Type: application/json" \
  -d '{
    "refresh_token": "YOUR_REFRESH_TOKEN"
  }'
```

---

## Run Tests

```bash
# Run all tests
make test

# Run only auth tests
docker-compose exec api pytest tests/test_auth.py -v

# Run with coverage
docker-compose exec api pytest --cov=app --cov-report=term tests/test_auth.py
```

---

## Troubleshooting

### Migration Issues
If migration fails, check:
```bash
# Check database connection
docker-compose exec api alembic current

# View migration history
docker-compose exec api alembic history

# Manually run migration
docker-compose exec api alembic upgrade head
```

### Token Issues
- **401 Unauthorized**: Check token is valid and not expired
- **Token reuse error**: Refresh tokens can only be used once (token rotation)
- **Invalid token format**: Ensure `Authorization: Bearer <token>` header format

### Password Validation
Password must meet these requirements:
- Minimum 8 characters
- At least one uppercase letter
- At least one lowercase letter  
- At least one digit

Example valid passwords:
- `SecurePass123`
- `MyPassword1`
- `Admin@123`

Example invalid passwords:
- `weak` (too short)
- `nodigits` (no numbers)
- `NOLOWER1` (no lowercase)
- `noupper1` (no uppercase)

---

## Environment Variables

Ensure these are set in your `.env` file:

```bash
# Security
SECRET_KEY=your-super-secret-key-change-in-production

# JWT Settings
JWT_ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=15
REFRESH_TOKEN_EXPIRE_DAYS=7

# Database
DATABASE_URL=postgresql+asyncpg://sonoro:sonoro_dev_password@postgres:5432/sonoro

# Redis
REDIS_URL=redis://redis:6379/0
```

---

## Interactive API Documentation

Once services are running, visit:
- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc

The Swagger UI allows you to:
1. Test all endpoints interactively
2. See request/response schemas
3. Try authentication flow
4. Use "Authorize" button to set Bearer token

---

## Next Steps

After verifying Block 2 works:

1. ✅ **Block 1**: Infrastructure ✓ Complete
2. ✅ **Block 2**: Authentication ✓ Complete
3. ⏭️ **Block 3**: User Features & Email Verification
4. ⏭️ **Block 4**: Project Management
5. ⏭️ **Block 5**: File Upload & Processing
6. ⏭️ **Block 6**: TTS & Audio Generation
7. ⏭️ **Block 7**: Payments & Subscription
8. ⏭️ **Block 8**: Frontend & Deployment

---

## 🎉 Success Criteria

Block 2 is complete when:
- [x] All files created
- [ ] Migration runs successfully
- [ ] All tests pass
- [ ] Can register new users
- [ ] Can login with credentials
- [ ] Can refresh tokens
- [ ] Can access protected endpoints
- [ ] Token rotation works
- [ ] Logout invalidates tokens

Run the commands above to verify! 🚀
