# 🏗️ BLOCK 2 ARCHITECTURE DIAGRAM

```
┌─────────────────────────────────────────────────────────────────┐
│                        CLIENT APPLICATION                        │
│                     (Browser, Mobile App, etc.)                  │
└────────────────────────────┬────────────────────────────────────┘
                             │
                             │ HTTPS
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                       FASTAPI APPLICATION                        │
│                                                                  │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │                 routers/auth.py                          │  │
│  │  POST /register  POST /login  POST /refresh             │  │
│  │  POST /logout    GET  /me     POST /change-password     │  │
│  └────────────┬──────────────────────────────┬──────────────┘  │
│               │                               │                 │
│               ▼                               ▼                 │
│  ┌──────────────────────────┐   ┌──────────────────────────┐  │
│  │ core/auth_dependencies.py│   │  schemas/auth.py         │  │
│  │  - get_current_user()    │   │  - RegisterRequest       │  │
│  │  - get_current_active()  │   │  - LoginRequest          │  │
│  │  - RoleChecker           │   │  - TokenResponse         │  │
│  └────────────┬─────────────┘   └──────────────────────────┘  │
│               │                                                 │
│               ▼                                                 │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │            services/auth_service.py                       │  │
│  │  - register_user()      - authenticate_user()            │  │
│  │  - create_tokens()      - refresh_tokens()               │  │
│  │  - logout_user()        - change_password()              │  │
│  └────────┬──────────────────────────────┬──────────────────┘  │
│           │                               │                    │
│           ▼                               ▼                    │
│  ┌────────────────────┐        ┌──────────────────────────┐  │
│  │  core/security.py  │        │   db/models/user.py      │  │
│  │  - hash_password() │        │   - id (UUID)            │  │
│  │  - verify_password │        │   - email                │  │
│  │  - create_access   │        │   - hashed_password      │  │
│  │  - create_refresh  │        │   - is_active            │  │
│  │  - verify_token    │        │   - is_verified          │  │
│  └────────────────────┘        │   - role                 │  │
│                                 │   - oauth_provider       │  │
│                                 │   - oauth_id             │  │
│                                 └────────┬─────────────────┘  │
└─────────────────────────────────────────┼─────────────────────┘
                                          │
                    ┌─────────────────────┼─────────────────────┐
                    │                     │                     │
                    ▼                     ▼                     ▼
        ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐
        │   PostgreSQL     │  │      Redis       │  │  core/oauth_base │
        │                  │  │                  │  │                  │
        │  users table:    │  │  refresh tokens: │  │  - OAuthProvBase │
        │  - id            │  │  refresh_token:  │  │  - Google (stub) │
        │  - email         │  │    {jti}         │  │  - GitHub (stub) │
        │  - hashed_pass   │  │    -> user_id    │  │  (future)        │
        │  - is_active     │  │  (TTL: 7 days)   │  │                  │
        │  - is_verified   │  │                  │  │                  │
        │  - role          │  │                  │  │                  │
        │  - oauth_*       │  │                  │  │                  │
        └──────────────────┘  └──────────────────┘  └──────────────────┘
```

---

## 🔄 AUTHENTICATION FLOW

### Registration Flow
```
1. POST /api/v1/auth/register
   ├─ Validate email & password (schemas/auth.py)
   ├─ Check email not exists (services/auth_service.py)
   ├─ Hash password (core/security.py)
   ├─ Create user in DB (db/models/user.py)
   ├─ Generate access + refresh tokens (core/security.py)
   ├─ Store refresh JTI in Redis
   └─ Return tokens to client

2. Client stores tokens
   ├─ Access token: Used for API calls (expires 15 min)
   └─ Refresh token: Used to get new access token (expires 7 days)
```

### Login Flow
```
1. POST /api/v1/auth/login
   ├─ Validate email & password
   ├─ Fetch user from DB
   ├─ Verify password hash (core/security.py)
   ├─ Check user is active
   ├─ Generate access + refresh tokens
   ├─ Store refresh JTI in Redis
   └─ Return tokens to client
```

### Protected Endpoint Flow
```
1. GET /api/v1/auth/me (or any protected endpoint)
   ├─ Extract Bearer token from header
   ├─ Verify JWT signature (core/security.py)
   ├─ Check token type is "access"
   ├─ Extract user_id from token
   ├─ Fetch user from DB (core/auth_dependencies.py)
   ├─ Check user is active
   └─ Allow request & return user data
```

### Token Refresh Flow
```
1. POST /api/v1/auth/refresh
   ├─ Validate refresh token
   ├─ Extract JTI from token
   ├─ Check JTI exists in Redis (not used/revoked)
   ├─ Verify user still exists and active
   ├─ DELETE old JTI from Redis (token rotation)
   ├─ Generate NEW access + refresh tokens
   ├─ Store NEW refresh JTI in Redis
   └─ Return new tokens to client

Note: Old refresh token is now invalid (single use)
```

### Logout Flow
```
1. POST /api/v1/auth/logout
   ├─ Validate refresh token
   ├─ Extract JTI from token
   ├─ DELETE JTI from Redis
   └─ Refresh token is now invalid

Note: Access token will expire naturally in 15 minutes
```

---

## 🔐 SECURITY LAYERS

```
┌─────────────────────────────────────────────────────────────┐
│                      SECURITY LAYERS                         │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  Layer 1: Password Security                                 │
│  ├─ Bcrypt hashing (passlib)                                │
│  ├─ Strong password validation (8+ chars, mixed case)       │
│  └─ Current password verification for changes               │
│                                                              │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  Layer 2: Token Security                                    │
│  ├─ JWT with HS256 signing                                  │
│  ├─ Short-lived access tokens (15 min, stateless)           │
│  ├─ Long-lived refresh tokens (7 days, revocable)           │
│  ├─ Token type validation (access vs refresh)               │
│  └─ Unique JTI per refresh token                            │
│                                                              │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  Layer 3: Token Rotation                                    │
│  ├─ Refresh tokens single-use only                          │
│  ├─ Old token invalidated on refresh                        │
│  ├─ Prevents token reuse attacks                            │
│  └─ Redis-backed blacklist                                  │
│                                                              │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  Layer 4: Authorization                                     │
│  ├─ Active user checks                                      │
│  ├─ Role-based access control                               │
│  ├─ Email verification flag (ready for Block 3)             │
│  └─ Flexible RoleChecker dependency                         │
│                                                              │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  Layer 5: API Security (Ready for Block 3)                 │
│  ├─ Rate limiting hooks                                     │
│  ├─ Input validation (Pydantic)                             │
│  ├─ Error sanitization (no info leakage)                    │
│  └─ CORS configuration                                      │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

---

## 📊 DATA FLOW

### User Registration
```
Client                API                  Service              Database/Redis
  │                    │                      │                      │
  ├─ POST /register ──>│                      │                      │
  │                    ├─ Validate schema ───>│                      │
  │                    │                      ├─ Check email ──────>│
  │                    │                      │<─ Email unique ─────┤
  │                    │                      ├─ Hash password       │
  │                    │                      ├─ Create user ──────>│
  │                    │                      │<─ User created ─────┤
  │                    │                      ├─ Create tokens       │
  │                    │                      ├─ Store JTI ────────>│ Redis
  │                    │<─ Tokens ────────────┤                      │
  │<── 201 + Tokens ───┤                      │                      │
  │                    │                      │                      │
```

### Protected Request
```
Client                API                  Dependency           Database
  │                    │                      │                      │
  ├─ GET /me ────────>│                      │                      │
  │    + Bearer token  │                      │                      │
  │                    ├─ Extract token ─────>│                      │
  │                    │                      ├─ Verify JWT          │
  │                    │                      ├─ Extract user_id     │
  │                    │                      ├─ Fetch user ───────>│
  │                    │                      │<─ User data ────────┤
  │                    │                      ├─ Check active        │
  │                    │<─ User object ───────┤                      │
  │<── 200 + User data ┤                      │                      │
  │                    │                      │                      │
```

---

## 🎯 EXTENSIBILITY POINTS

### For Block 3 (Email Verification):
- `is_verified` flag ready
- `get_current_verified_user()` dependency available
- Email service can be added to `services/`

### For Block 4 (OAuth):
- `OAuthProviderBase` abstract class ready
- `oauth_provider` and `oauth_id` fields in User model
- Unique constraint on provider+ID combination

### For Block 5 (Rate Limiting):
- Rate limit hooks in auth router
- Redis client available
- Can implement sliding window or token bucket

### For Block 6+ (Advanced Auth):
- Role-based access via `RoleChecker`
- Can add permissions table
- Can add 2FA fields to User model
- Can add session management

---

## 📈 PERFORMANCE CHARACTERISTICS

### Database Queries
- **Registration**: 2 queries (SELECT + INSERT)
- **Login**: 1 query (SELECT by email with index)
- **Token refresh**: 1 query (SELECT by UUID PK)
- **Get current user**: 1 query (SELECT by UUID PK)

### Redis Operations
- **Create tokens**: 1 SETEX (O(1))
- **Verify refresh**: 1 GET (O(1))
- **Logout**: 1 DEL (O(1))
- **Automatic expiry**: TTL 7 days

### Memory Usage
- **Per refresh token**: ~100 bytes
- **10,000 active users**: ~1 MB Redis
- **Token size**: ~200 bytes (JWT)

### Scalability
- ✅ Stateless access tokens (no server-side storage)
- ✅ Horizontal scaling ready (shared Redis)
- ✅ Database indexes on hot paths
- ✅ Connection pooling configured

---

This architecture is production-ready and follows industry best practices! 🚀
