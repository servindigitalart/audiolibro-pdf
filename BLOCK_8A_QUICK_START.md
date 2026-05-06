# BLOCK 8A: Frontend Foundation - Quick Start

**⏱️ 5-Minute Setup Guide**

---

## 🚀 Start in 3 Commands

```bash
# 1. Navigate to frontend
cd frontend

# 2. Install dependencies (if not already done)
npm install

# 3. Start development server
npm run dev
```

**Access:** http://localhost:3000

---

## 📋 Pre-requisites

**Backend API must be running:**
```bash
# In another terminal
cd services/api
uvicorn app.main:app --reload
```

**API should be at:** http://localhost:8000

---

## 🔑 Test Authentication

### Register New User

1. Go to http://localhost:3000/register
2. Enter email: `test@example.com`
3. Enter password: `password123`
4. Confirm password: `password123`
5. Click "Create account"
6. → Redirects to dashboard

### Login Existing User

1. Go to http://localhost:3000/login
2. Enter credentials
3. Click "Sign in"
4. → Redirects to dashboard

---

## 🎨 UI Features to Test

### Theme Toggle
- Click sun/moon icon in header
- Select Light/Dark/System
- Theme persists across page reloads

### Navigation
- Click sidebar links
- Active route highlights
- Mobile: Hamburger menu

### User Menu
- Click avatar in header
- View email and plan tier
- Access Profile, Settings
- Logout

---

## 📁 Key Files

```
frontend/
├── app/
│   ├── login/page.tsx           # Login UI
│   ├── register/page.tsx        # Register UI
│   └── (dashboard)/
│       ├── layout.tsx           # Auth wrapper
│       └── dashboard/page.tsx   # Main page
│
├── lib/
│   ├── api-client.ts            # Axios + JWT
│   └── auth-service.ts          # Auth API
│
└── store/
    └── auth-store.ts            # Zustand state
```

---

## 🔧 Environment Setup

**Create `.env.local`:**
```bash
NEXT_PUBLIC_API_URL=http://localhost:8000/api/v1
NEXT_PUBLIC_APP_NAME=Sonoro
NEXT_PUBLIC_APP_VERSION=0.9.0
```

---

## 🧪 Test Checklist

- [ ] Register works
- [ ] Login works
- [ ] Dashboard loads
- [ ] Protected routes redirect
- [ ] Logout works
- [ ] Theme toggle works
- [ ] Mobile responsive
- [ ] API calls include JWT

---

## 🐛 Common Issues

**Port 3000 already in use?**
```bash
# Use different port
PORT=3001 npm run dev
```

**API connection failed?**
```bash
# Check backend is running
curl http://localhost:8000/api/v1/health

# Check .env.local
cat .env.local
```

**Module not found?**
```bash
# Clear cache and reinstall
rm -rf .next node_modules
npm install
npm run dev
```

---

## 📊 Routes

| URL | Page | Auth |
|-----|------|------|
| `/` | Redirect | - |
| `/login` | Login | No |
| `/register` | Register | No |
| `/dashboard` | Dashboard | Yes |
| `/documents` | Documents | Yes |
| `/billing` | Billing | Yes |
| `/usage` | Usage | Yes |
| `/settings` | Settings | Yes |

---

## 🎯 Next Steps

1. ✅ Test authentication flow
2. ✅ Verify all routes work
3. ✅ Check mobile responsiveness
4. ✅ Test theme switching
5. → Ready for BLOCK 8B!

---

**Full Documentation:** `docs/BLOCK_8A_COMPLETE.md`  
**Need Help?** Check console for errors
