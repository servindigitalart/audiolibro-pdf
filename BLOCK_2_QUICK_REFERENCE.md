# 🎯 BLOCK 2 QUICK REFERENCE

## 🚀 Quick Start Commands

```bash
# Start services
make dev

# Run migration
make migrate

# Run tests
make test

# View logs
make logs-api

# Check health
curl http://localhost:8000/api/v1/health
```

---

## 📡 API Endpoints

| Method | Endpoint | Description | Auth Required |
|--------|----------|-------------|---------------|
| POST | `/api/v1/auth/register` | Register new user | ❌ No |
| POST | `/api/v1/auth/login` | Login with credentials | ❌ No |
| POST | `/api/v1/auth/refresh` | Refresh access token | ❌ No |
| POST | `/api/v1/auth/logout` | Logout user | ❌ No |
| GET | `/api/v1/auth/me` | Get current user | ✅ Yes |
| POST | `/api/v1/auth/change-password` | Change password | ✅ Yes |

---

## 🔑 Request Examples

### Register
```bash
curl -X POST http://localhost:8000/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email":"user@example.com","password":"SecurePass123"}'
```

### Login
```bash
curl -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"user@example.com","password":"SecurePass123"}'
```

### Get Current User
```bash
curl http://localhost:8000/api/v1/auth/me \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN"
```

---

## 📦 Password Requirements

- ✅ Minimum 8 characters
- ✅ At least one uppercase letter
- ✅ At least one lowercase letter
- ✅ At least one digit

**Valid examples**: `SecurePass123`, `MyPassword1`, `Admin@2026`

---

## 🔐 Token Information

| Token Type | Lifetime | Storage | Revocable |
|------------|----------|---------|-----------|
| Access Token | 15 minutes | Client-side | ❌ No (stateless) |
| Refresh Token | 7 days | Redis (JTI) | ✅ Yes |

---

## 🏗️ Code Structure Reference

### Protect an Endpoint
```python
from fastapi import Depends
from app.core.auth_dependencies import get_current_active_user
from app.db.models.user import User

@router.get("/protected")
async def protected_route(user: User = Depends(get_current_active_user)):
    return {"message": f"Hello, {user.email}"}
```

### Require Admin Role
```python
from app.core.auth_dependencies import RoleChecker

@router.get("/admin-only")
async def admin_route(user: User = Depends(RoleChecker(["admin"]))):
    return {"message": "Admin access"}
```

### Require Verified Email
```python
from app.core.auth_dependencies import get_current_verified_user

@router.get("/verified-only")
async def verified_route(user: User = Depends(get_current_verified_user)):
    return {"message": "Email verified"}
```

---

## 🗄️ Database Schema

### Users Table
```sql
id                UUID PRIMARY KEY
email             VARCHAR(255) UNIQUE NOT NULL
hashed_password   VARCHAR(255) NULL
is_active         BOOLEAN NOT NULL DEFAULT true
is_verified       BOOLEAN NOT NULL DEFAULT false
role              VARCHAR(50) NOT NULL DEFAULT 'user'
oauth_provider    VARCHAR(50) NULL
oauth_id          VARCHAR(255) NULL
created_at        TIMESTAMP WITH TIME ZONE NOT NULL
updated_at        TIMESTAMP WITH TIME ZONE NOT NULL
```

### Redis Keys
```
refresh_token:{jti} -> user_id    (TTL: 7 days)
```

---

## 🧪 Testing Commands

```bash
# All tests
make test

# Auth tests only
docker-compose exec api pytest tests/test_auth.py -v

# With coverage
docker-compose exec api pytest --cov=app tests/test_auth.py

# Specific test
docker-compose exec api pytest tests/test_auth.py::test_register_success -v
```

---

## 🔧 Environment Variables

```bash
# Required
SECRET_KEY=your-secret-key-here
DATABASE_URL=postgresql+asyncpg://user:pass@host/db
REDIS_URL=redis://host:6379/0

# JWT Settings (optional, have defaults)
JWT_ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=15
REFRESH_TOKEN_EXPIRE_DAYS=7
```

---

## 🐛 Troubleshooting

### "Email already registered"
- User with that email already exists
- Try different email or use login endpoint

### "Invalid refresh token"
- Token has been used (single-use with rotation)
- Token has been revoked (logout)
- Token has expired (7 days)
- Get new tokens via login

### "Could not validate credentials"
- Access token expired (15 minutes)
- Token signature invalid
- Token format incorrect
- Use refresh endpoint to get new access token

### "Inactive user account"
- User's `is_active` flag is false
- Contact admin to reactivate

### "Email not verified"
- User's `is_verified` flag is false
- Complete email verification (Block 3 feature)

---

## 📚 File Locations

### Core
- `services/api/app/core/security.py` - Password & JWT
- `services/api/app/core/auth_dependencies.py` - FastAPI deps
- `services/api/app/core/oauth_base.py` - OAuth classes

### Business Logic
- `services/api/app/services/auth_service.py` - Auth service

### API
- `services/api/app/routers/auth.py` - Endpoints
- `services/api/app/schemas/auth.py` - Schemas

### Database
- `services/api/app/db/models/user.py` - User model
- `services/api/alembic/versions/002_add_auth_fields.py` - Migration

### Tests
- `services/api/tests/test_auth.py` - Auth tests

---

## 🎓 Key Concepts

### Token Rotation
- Refresh tokens are **single-use**
- When used, old token is invalidated
- New token pair is issued
- Prevents token replay attacks

### Password Hashing
- Uses **bcrypt** via passlib
- Automatically salted
- Computationally expensive (prevents brute force)
- One-way function (cannot reverse)

### JWT Structure
```json
{
  "sub": "user-uuid",
  "exp": 1709297400,
  "iat": 1709296500,
  "type": "access",
  "jti": "unique-id"  // refresh tokens only
}
```

### Role-Based Access
- Default role: `"user"`
- Can create roles: `"admin"`, `"premium"`, etc.
- Use `RoleChecker(["admin"])` to protect endpoints
- Extensible for complex permissions

---

## 🔮 Future Features (Block 3+)

- [ ] Email verification flow
- [ ] Password reset via email
- [ ] OAuth login (Google, GitHub)
- [ ] Two-factor authentication
- [ ] Redis rate limiting
- [ ] Login history
- [ ] Session management

---

## ✅ Success Checklist

- [ ] Docker Desktop running
- [ ] Services started with `make dev`
- [ ] Migration run with `make migrate`
- [ ] Health check returns 200
- [ ] Can register new user
- [ ] Can login
- [ ] Can access `/auth/me` with token
- [ ] Can refresh token
- [ ] Can logout
- [ ] All tests pass

---

## 📖 Documentation Links

- **Complete Guide**: `BLOCK_2_COMPLETE.md`
- **Setup Instructions**: `BLOCK_2_SETUP.md`
- **Architecture**: `BLOCK_2_ARCHITECTURE.md`
- **API Docs**: http://localhost:8000/docs

---

**Need help?** Check the detailed documentation files above! 🚀
