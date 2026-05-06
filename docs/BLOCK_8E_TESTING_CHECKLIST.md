# BLOCK 8E - Testing Checklist

**Feature:** User Settings & Personalization Layer  
**Version:** 1.0.0  
**Test Environment:** Development/Staging

---

## 🧪 BACKEND TESTING

### Database Migration
- [ ] Migration runs without errors
- [ ] `api_keys` table created with all columns
- [ ] `full_name` column added to `users` table
- [ ] Indexes created: `ix_api_keys_user_id_is_active`, `ix_api_keys_key_hash`
- [ ] Foreign key constraint works (CASCADE on delete)
- [ ] Default values correct (`is_active=true`)

**Command:**
```bash
docker-compose exec api alembic upgrade head
docker-compose exec postgres psql -U sonoro -d sonoro -c "\d api_keys"
docker-compose exec postgres psql -U sonoro -d sonoro -c "\d users"
```

---

### Profile Endpoints

#### GET /api/v1/account/profile
- [ ] Returns 200 with valid token
- [ ] Returns 401 without token
- [ ] Includes all fields: email, full_name, is_active, is_verified, role, timestamps
- [ ] `full_name` is null for existing users (backwards compatible)
- [ ] Response matches ProfileResponse schema

**Test:**
```bash
curl http://localhost:8000/api/v1/account/profile \
  -H "Authorization: Bearer $TOKEN"
```

#### PATCH /api/v1/account/profile
- [ ] Updates `full_name` successfully
- [ ] Returns 200 with updated data
- [ ] Handles null/empty full_name
- [ ] Validates max length (255 chars)
- [ ] Returns 400 for invalid data
- [ ] Updates `updated_at` timestamp
- [ ] Increments `sonoro_profile_updates_total` metric
- [ ] Logs activity in `account_activity` table

**Test:**
```bash
curl -X PATCH http://localhost:8000/api/v1/account/profile \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"full_name":"John Doe"}'

curl -X PATCH http://localhost:8000/api/v1/account/profile \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"full_name":""}'
```

---

### API Key Endpoints

#### POST /api/v1/account/api-key
- [ ] Generates valid API key with format `sk_live_{64-hex}`
- [ ] Returns 201 with full key (only time it's shown)
- [ ] Stores bcrypt hash in database (not plaintext)
- [ ] Stores last 4 chars as preview
- [ ] Sets `is_active=true` and `created_at`
- [ ] Returns 400 when user has 5 active keys (limit)
- [ ] Returns 401 without token
- [ ] Increments `sonoro_api_keys_generated_total` metric
- [ ] Logs activity

**Test:**
```bash
# Generate keys until limit
for i in {1..5}; do
  curl -X POST http://localhost:8000/api/v1/account/api-key \
    -H "Authorization: Bearer $TOKEN"
done

# Should fail (limit reached)
curl -X POST http://localhost:8000/api/v1/account/api-key \
  -H "Authorization: Bearer $TOKEN"
```

#### GET /api/v1/account/api-keys
- [ ] Returns list of user's API keys
- [ ] Keys are masked (only last 4 chars shown)
- [ ] Includes `key_id`, `key_preview`, `created_at`, `last_used_at`
- [ ] Only returns active keys (`is_active=true`)
- [ ] Returns empty list if no keys
- [ ] Returns 401 without token
- [ ] Sorted by `created_at` desc

**Test:**
```bash
curl http://localhost:8000/api/v1/account/api-keys \
  -H "Authorization: Bearer $TOKEN"
```

#### DELETE /api/v1/account/api-key/{key_id}
- [ ] Revokes key successfully (sets `is_active=false`)
- [ ] Returns 200 with success message
- [ ] Returns 404 if key doesn't exist
- [ ] Returns 403 if key belongs to different user
- [ ] Returns 401 without token
- [ ] Key still in database (soft delete)
- [ ] No longer appears in list
- [ ] Can generate new key after revocation
- [ ] Increments `sonoro_api_keys_revoked_total` metric
- [ ] Logs activity

**Test:**
```bash
# Get key ID from list
KEY_ID=$(curl http://localhost:8000/api/v1/account/api-keys \
  -H "Authorization: Bearer $TOKEN" \
  | jq -r '.keys[0].key_id')

# Revoke key
curl -X DELETE http://localhost:8000/api/v1/account/api-key/$KEY_ID \
  -H "Authorization: Bearer $TOKEN"

# Verify no longer in list
curl http://localhost:8000/api/v1/account/api-keys \
  -H "Authorization: Bearer $TOKEN"
```

---

### Password Change Endpoint

#### POST /api/v1/auth/change-password
- [ ] Changes password successfully with correct current password
- [ ] Returns 200 with success message
- [ ] Can login with new password
- [ ] Cannot login with old password
- [ ] Returns 400 if current password is wrong
- [ ] Returns 400 if new password < 8 chars
- [ ] Returns 400 for OAuth users
- [ ] Returns 401 without token
- [ ] Increments `sonoro_password_changes_total` metric
- [ ] Logs activity

**Test:**
```bash
# Change password
curl -X POST http://localhost:8000/api/v1/auth/change-password \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"current_password":"OldPass123!","new_password":"NewPass456!"}'

# Test login with new password
curl -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"test@example.com","password":"NewPass456!"}'
```

---

### Account Deletion Endpoint

#### DELETE /api/v1/account/delete-account
- [ ] Deletes account with correct password + "DELETE" confirmation
- [ ] Returns 200 with success message
- [ ] Sets `is_active=false` (soft delete)
- [ ] User cannot login after deletion
- [ ] Data remains in database (audit trail)
- [ ] Returns 400 if password is wrong
- [ ] Returns 400 if confirmation is not "DELETE"
- [ ] Returns 400 for OAuth users
- [ ] Returns 401 without token
- [ ] Increments `sonoro_account_deletions_total` metric
- [ ] Logs activity with metadata

**Test:**
```bash
# Delete account
curl -X DELETE http://localhost:8000/api/v1/account/delete-account \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"password":"CurrentPass123!","confirmation":"DELETE"}'

# Try to login (should fail)
curl -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"test@example.com","password":"CurrentPass123!"}'
```

---

### Preferences Endpoints (Existing)

#### GET /api/v1/account/settings
- [ ] Returns current preferences
- [ ] Includes all fields: language, voice, timezone, currency, notifications
- [ ] Returns defaults for new users

#### PATCH /api/v1/account/settings
- [ ] Updates preferences successfully
- [ ] Supports partial updates
- [ ] Validates language codes
- [ ] Validates currency codes
- [ ] Returns 400 for invalid data

---

### Metrics Testing

#### Prometheus Metrics
- [ ] `sonoro_profile_updates_total` increments on profile update
- [ ] `sonoro_password_changes_total` increments on password change
- [ ] `sonoro_api_keys_generated_total` increments on key generation
- [ ] `sonoro_api_keys_revoked_total` increments on key revocation
- [ ] `sonoro_account_deletions_total` increments on account deletion
- [ ] All metrics include correct labels (user_id, status, etc.)

**Test:**
```bash
# Check metrics endpoint
curl http://localhost:8000/metrics | grep sonoro_profile_updates_total
curl http://localhost:8000/metrics | grep sonoro_password_changes_total
curl http://localhost:8000/metrics | grep sonoro_api_keys_generated_total
curl http://localhost:8000/metrics | grep sonoro_api_keys_revoked_total
curl http://localhost:8000/metrics | grep sonoro_account_deletions_total
```

---

## 🎨 FRONTEND TESTING

### Settings Page Load
- [ ] Page loads without errors
- [ ] All 6 sections visible
- [ ] Loading states show during data fetch
- [ ] No console errors
- [ ] Responsive on mobile (test various screen sizes)
- [ ] Dark mode works correctly

**Test:**
```bash
open http://localhost:3000/settings
# Check browser console (Cmd+Option+I)
```

---

### Profile Section
- [ ] Email displays correctly (read-only, grayed out)
- [ ] Full name input shows current value
- [ ] Can update full name
- [ ] "Save Profile" button works
- [ ] Success toast appears after save
- [ ] Loading spinner shows during save
- [ ] Profile data refreshes after save
- [ ] Empty full name is allowed

---

### Preferences Section
- [ ] Language dropdown shows current selection
- [ ] Can change language
- [ ] Voice dropdown shows current selection
- [ ] Can change voice
- [ ] Timezone dropdown shows current selection
- [ ] Can change timezone
- [ ] Currency dropdown shows current selection
- [ ] Can change currency
- [ ] Each change saves individually
- [ ] Success toast for each change
- [ ] Dropdowns styled correctly

---

### Notifications Section
- [ ] Email notifications toggle shows current state
- [ ] Can toggle email notifications
- [ ] Usage alerts toggle shows current state
- [ ] Can toggle usage alerts
- [ ] Marketing emails toggle shows current state
- [ ] Can toggle marketing emails
- [ ] Button changes color when toggled
- [ ] Success toast for each toggle
- [ ] Changes persist after refresh

---

### Security Section
- [ ] Current password input works
- [ ] New password input works
- [ ] Confirm password input works
- [ ] Show/hide password toggle works
- [ ] All password fields toggle together
- [ ] "Change Password" button disabled when fields empty
- [ ] Success toast after password change
- [ ] Error toast if passwords don't match
- [ ] Error toast if password < 8 chars
- [ ] Error toast if current password wrong
- [ ] Form clears after successful change
- [ ] Loading spinner shows during change

---

### API Keys Section
- [ ] "Generate Key" button visible
- [ ] Click generates new API key
- [ ] Dialog shows full API key
- [ ] Can copy API key with button
- [ ] "Copied" toast appears after copy
- [ ] Dialog shows warning (key only shown once)
- [ ] After closing dialog, key is masked in list
- [ ] Key list shows last 4 chars only (••••••••XXXX)
- [ ] Key list shows created_at timestamp
- [ ] Key list shows last_used_at if available
- [ ] "Revoke" button works
- [ ] Success toast after revocation
- [ ] Key removed from list after revocation
- [ ] "Generate Key" disabled at 5-key limit
- [ ] Alert shows when at limit
- [ ] Empty state shows when no keys

---

### Danger Zone
- [ ] "Delete Account" button is red/destructive
- [ ] Warning alert is visible
- [ ] Click opens delete dialog
- [ ] Dialog has destructive styling
- [ ] Password input works
- [ ] Confirmation input works
- [ ] "Delete Account" button disabled until both filled
- [ ] Must type exactly "DELETE" (case-sensitive)
- [ ] Error toast if password wrong
- [ ] Error toast if confirmation not "DELETE"
- [ ] Success toast after deletion
- [ ] Redirects to homepage after deletion (2s delay)
- [ ] Loading spinner shows during deletion
- [ ] "Cancel" button closes dialog

---

### Toast Notifications
- [ ] Toast appears in bottom-right corner
- [ ] Success toasts are green with checkmark
- [ ] Error toasts are red with alert icon
- [ ] Toast has title and description
- [ ] Toast auto-dismisses after 5 seconds
- [ ] Can manually dismiss with X button
- [ ] Multiple toasts stack vertically
- [ ] Toast animation is smooth
- [ ] Toast is readable in dark mode

---

### Error Handling
- [ ] Network errors show error toast
- [ ] 401 errors redirect to login
- [ ] 400 errors show validation message
- [ ] 403 errors show permission message
- [ ] 404 errors show not found message
- [ ] 500 errors show generic error
- [ ] Error messages are user-friendly
- [ ] No uncaught exceptions in console

---

### Loading States
- [ ] Initial page load shows skeleton/spinner
- [ ] Save buttons show spinner when loading
- [ ] Buttons disabled during loading
- [ ] No flickering or layout shift
- [ ] Loading states are accessible

---

### Accessibility
- [ ] All inputs have labels
- [ ] Tab navigation works
- [ ] Enter key submits forms
- [ ] Escape key closes dialogs
- [ ] Focus indicators visible
- [ ] ARIA labels present
- [ ] Screen reader friendly

---

## 🔄 INTEGRATION TESTING

### End-to-End Flows

#### Complete Profile Update
1. [ ] Navigate to /settings
2. [ ] Update full name
3. [ ] Change language
4. [ ] Change voice
5. [ ] Verify all changes saved
6. [ ] Refresh page
7. [ ] Verify changes persisted

#### API Key Lifecycle
1. [ ] Generate API key
2. [ ] Copy key from dialog
3. [ ] Close dialog
4. [ ] Verify key in list (masked)
5. [ ] Generate 4 more keys (total 5)
6. [ ] Verify "Generate" disabled
7. [ ] Revoke 1 key
8. [ ] Verify "Generate" enabled
9. [ ] Generate new key

#### Password Change
1. [ ] Change password
2. [ ] Logout
3. [ ] Login with new password
4. [ ] Verify cannot login with old password

#### Account Deletion
1. [ ] Navigate to settings
2. [ ] Scroll to danger zone
3. [ ] Click "Delete Account"
4. [ ] Enter wrong password
5. [ ] Verify error
6. [ ] Enter correct password
7. [ ] Type "delete" (lowercase)
8. [ ] Verify button still disabled
9. [ ] Type "DELETE"
10. [ ] Confirm deletion
11. [ ] Verify redirect to homepage
12. [ ] Verify cannot login

---

## 📊 PERFORMANCE TESTING

### Response Times
- [ ] GET /profile < 50ms
- [ ] PATCH /profile < 100ms
- [ ] POST /api-key < 150ms (bcrypt is slow)
- [ ] GET /api-keys < 50ms
- [ ] DELETE /api-key < 100ms
- [ ] PATCH /settings < 50ms
- [ ] POST /change-password < 150ms

### Frontend Performance
- [ ] Settings page TTI < 1s
- [ ] Form updates feel instant (optimistic UI)
- [ ] Toast animations smooth (60fps)
- [ ] No layout thrashing
- [ ] No memory leaks (test with Chrome DevTools)

---

## 🔒 SECURITY TESTING

### Authentication
- [ ] All endpoints require authentication
- [ ] Invalid tokens return 401
- [ ] Expired tokens return 401
- [ ] Missing tokens return 401

### Authorization
- [ ] Users can only access own data
- [ ] Cannot revoke other users' API keys
- [ ] Cannot delete other users' accounts

### Input Validation
- [ ] SQL injection attempts fail
- [ ] XSS attempts sanitized
- [ ] Long strings rejected (max lengths)
- [ ] Invalid UUIDs rejected
- [ ] Invalid JSON rejected

### Password Security
- [ ] Passwords never logged
- [ ] Passwords never in responses
- [ ] Bcrypt hash strength correct (12 rounds)
- [ ] Password change requires current password

### API Key Security
- [ ] Keys stored as bcrypt hash
- [ ] Full key never retrievable after generation
- [ ] Keys never in logs
- [ ] Revoked keys cannot be reactivated

---

## 🐛 EDGE CASES

### Database
- [ ] Migration idempotent (can run twice)
- [ ] Rollback works correctly
- [ ] Handles existing users gracefully (full_name null)

### API
- [ ] Empty request bodies handled
- [ ] Malformed JSON handled
- [ ] Missing required fields handled
- [ ] Extra fields ignored
- [ ] Unicode in full_name works
- [ ] Very long names truncated

### Frontend
- [ ] Works without JavaScript (basic functionality)
- [ ] Works on slow connections
- [ ] Works with ad blockers
- [ ] Works in private/incognito mode
- [ ] Works with browser extensions

### User Actions
- [ ] Rapid clicking doesn't cause issues
- [ ] Simultaneous updates handled
- [ ] Back button works correctly
- [ ] Refresh during update handled

---

## ✅ SIGN-OFF

### Backend Lead
- [ ] All endpoints tested
- [ ] Metrics verified
- [ ] Activity logging works
- [ ] Security reviewed
- [ ] Performance acceptable

**Signed:** _________________ Date: _________

### Frontend Lead
- [ ] All UI sections tested
- [ ] UX flows verified
- [ ] Responsive design checked
- [ ] Accessibility verified
- [ ] Error handling complete

**Signed:** _________________ Date: _________

### QA Lead
- [ ] All test cases passed
- [ ] Edge cases covered
- [ ] Security testing complete
- [ ] Performance acceptable
- [ ] Documentation reviewed

**Signed:** _________________ Date: _________

---

## 📝 TEST RESULTS

### Test Summary
- Total Tests: _____ / _____
- Passed: _____
- Failed: _____
- Blocked: _____
- Not Applicable: _____

### Critical Issues
_List any critical issues found:_

### Recommendations
_List any recommendations for improvement:_

---

**Testing Complete:** [ ] YES [ ] NO  
**Ready for Production:** [ ] YES [ ] NO  
**Date:** _______________
