# BLOCK 8C: Quick Start Guide

**Billing & Subscription UX** - Get started in 5 minutes

---

## 🚀 Quick Setup

### 1. Start the Frontend
```bash
cd frontend
npm run dev
```

Open http://localhost:3000

### 2. Navigate to Billing
- Click "Billing" in the sidebar
- Or go to http://localhost:3000/billing

### 3. View Pricing Plans
- See all 4 tiers (Free, Basic, Pro, Enterprise)
- Toggle between monthly/yearly
- Compare features and pricing

### 4. Test Upgrade Flow
- Click "Upgrade" or "Get Started" on any paid plan
- You'll be redirected to Stripe checkout
- Complete test payment
- Return to app with success message

### 5. Manage Subscription
- View current plan details
- Check usage meter
- Access Stripe portal
- Cancel subscription

---

## 📁 Key Files

### Service Layer
```
lib/
└── billing-service.ts    # Billing API calls & utilities
```

### Components
```
components/billing/
├── subscription-overview.tsx    # Current subscription
├── usage-meter.tsx              # Usage visualization
└── plan-card.tsx                # Pricing cards
```

### Pages
```
app/(dashboard)/billing/
└── page.tsx                     # Main billing page
```

---

## 🔧 Common Tasks

### Add a New Plan
```typescript
// lib/billing-service.ts
export const PLANS: Record<PlanTier, Plan> = {
  // Add new plan here
  PREMIUM: {
    tier: 'PREMIUM',
    name: 'Premium',
    description: 'For premium users',
    monthlyPrice: 49.99,
    yearlyPrice: 499.99,
    characterQuota: 5000000,
    maxConcurrentJobs: 25,
    priorityQueue: true,
    supportLevel: 'Premium',
    features: [/* ... */]
  }
};
```

### Change Usage Thresholds
```typescript
// components/billing/usage-meter.tsx
const getProgressColor = () => {
  if (usagePercentage >= 95) return 'bg-red-500';    // Red at 95%
  if (usagePercentage >= 80) return 'bg-yellow-500'; // Yellow at 80%
  return 'bg-green-500';
};

const showWarning = usagePercentage >= 90; // Warning at 90%
```

### Customize Plan Pricing
```typescript
// lib/billing-service.ts
BASIC: {
  // ...
  monthlyPrice: 19.99,  // Change price
  yearlyPrice: 199.99,  // Change yearly price
  // Savings auto-calculated
}
```

### Add Plan Features
```typescript
PRO: {
  // ...
  features: [
    '2,000,000 characters/month',
    '10 concurrent jobs',
    'Priority queue',
    'Custom feature here',  // Add new feature
    'Another feature',
  ]
}
```

---

## 🎨 UI Customization

### Change Popular Plan
```typescript
// app/(dashboard)/billing/page.tsx
<PlanCard
  plan={PLANS.ENTERPRISE}  // Change to Enterprise
  isPopular                 // Mark as popular
/>
```

### Modify Status Colors
```typescript
// components/billing/subscription-overview.tsx
function getStatusColor(status: string): string {
  const colorMap = {
    active: 'bg-purple-100 text-purple-800',  // Change colors
    // ...
  };
}
```

### Update FAQ
```typescript
// app/(dashboard)/billing/page.tsx
<div className="space-y-4">
  <div>
    <p>Your custom question?</p>
    <p>Your answer here.</p>
  </div>
</div>
```

---

## 🧪 Testing

### Test Checkout Flow
1. Click "Upgrade" on Pro plan
2. Use Stripe test card: `4242 4242 4242 4242`
3. Any future expiry date
4. Any CVC
5. Complete payment
6. Check success message

### Test Cancel Flow
1. Have an active subscription
2. Click "Cancel Subscription"
3. Confirm in dialog
4. Check subscription shows "cancel_at_period_end"
5. Verify expiry date displayed

### Test Usage Meter
1. View billing page
2. Check usage progress bar
3. Colors should change based on %
4. Warning should show if > 85%

### Test Plan Comparison
1. Toggle monthly/yearly
2. Prices should update
3. Savings should show for yearly
4. Current plan should be highlighted
5. CTA buttons should change text

---

## 🐛 Troubleshooting

### Checkout Fails
1. Check backend is running
2. Verify Stripe API keys in backend .env
3. Check network tab for errors
4. Ensure user is authenticated

### Subscription Not Loading
1. Check API endpoint `/billing/subscription`
2. Verify JWT token in cookies
3. Check backend logs
4. May return null if no subscription (normal for free users)

### Usage Meter Not Updating
1. Check `/account/usage` endpoint
2. Verify usage data in backend
3. Check query refetch interval (60s)
4. Manually refetch in React DevTools

### Portal Button Not Working
1. Check `/billing/portal` endpoint
2. Verify Stripe customer exists
3. Check backend Stripe configuration
4. Ensure subscription is active

---

## 📊 API Debugging

### Check Subscription
```bash
curl -H "Authorization: Bearer YOUR_TOKEN" \
  http://localhost:8000/api/v1/billing/subscription
```

### Check Usage
```bash
curl -H "Authorization: Bearer YOUR_TOKEN" \
  http://localhost:8000/api/v1/account/usage
```

### Create Checkout (test in frontend)
```bash
curl -X POST \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"plan_tier":"PRO","billing_interval":"monthly"}' \
  http://localhost:8000/api/v1/billing/checkout
```

---

## 🎯 Best Practices

### 1. Always Use Service Layer
```typescript
// ✅ Good
import { createCheckoutSession } from '@/lib/billing-service';
await createCheckoutSession('PRO', 'monthly');

// ❌ Bad
await apiClient.post('/billing/checkout', { ... });
```

### 2. Handle Errors Gracefully
```typescript
try {
  await createCheckoutSession(tier, interval);
} catch (error) {
  setCheckoutError('Failed to start checkout');
}
```

### 3. Invalidate Queries After Changes
```typescript
queryClient.invalidateQueries({ queryKey: ['subscription'] });
queryClient.invalidateQueries({ queryKey: ['usage'] });
```

### 4. Show Loading States
```typescript
{isLoading && <Loader2 className="animate-spin" />}
```

---

## 🔗 Related Guides

- [BLOCK_8C_COMPLETE.md](./BLOCK_8C_COMPLETE.md) - Full documentation
- [BLOCK_7_COMPLETE.md](./BLOCK_7_COMPLETE.md) - Backend billing APIs
- [BLOCK_8A_QUICK_START.md](./BLOCK_8A_QUICK_START.md) - Frontend setup

---

## 💡 Tips

1. **Test with Stripe Test Mode** - Use test API keys
2. **Clear Cache** - Cmd+Shift+R to force reload
3. **Check Network Tab** - See all API calls
4. **Use React DevTools** - Inspect query cache
5. **Monitor Backend Logs** - Watch Stripe webhooks

---

**Ready to bill! 💳**
