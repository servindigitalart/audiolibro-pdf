# BLOCK 7: Billing Quick Reference

**⏱️ 2-Minute Setup Guide**

---

## 🚀 Deploy in 3 Commands

```bash
# 1. Install Stripe
pip install stripe==8.2.0

# 2. Run migration
cd services/api && alembic upgrade head

# 3. Configure (add to .env)
STRIPE_SECRET_KEY=sk_test_...
STRIPE_WEBHOOK_SECRET=whsec_...
STRIPE_PRICE_BASIC_MONTHLY=price_...
STRIPE_PRICE_PRO_MONTHLY=price_...
```

---

## 📡 API Endpoints

```bash
# Create checkout
POST /api/v1/billing/checkout
{
  "price_id": "price_...",
  "success_url": "https://app.sonoro.com/success",
  "cancel_url": "https://app.sonoro.com/cancel"
}

# Get subscription
GET /api/v1/billing/subscription

# Customer portal
POST /api/v1/billing/portal
{"return_url": "https://app.sonoro.com/billing"}

# Cancel subscription
DELETE /api/v1/billing/subscription
{"immediately": false}

# Webhook (Stripe calls this)
POST /api/v1/billing/webhook
```

---

## 📊 Key Metrics

```promql
# Monthly Recurring Revenue
sum(sonoro_mrr) by (plan_tier)

# Active subscribers
sonoro_active_subscriptions_total

# Churn rate
rate(sonoro_subscription_churn_total[30d])

# Checkout conversion
sonoro_checkout_sessions_completed_total / 
sonoro_checkout_sessions_created_total * 100
```

---

## 🧪 Test with Stripe CLI

```bash
# Install
brew install stripe/stripe-cli/stripe

# Forward webhooks
stripe listen --forward-to localhost:8000/api/v1/billing/webhook

# Trigger events
stripe trigger checkout.session.completed
stripe trigger invoice.payment_succeeded
```

---

## 🔧 Stripe Dashboard Setup

**Products** → Create 3 products:
- BASIC: $9/month
- PRO: $29/month  
- ENTERPRISE: $99/month

**Webhooks** → Add endpoint:
- URL: `https://api.sonoro.com/api/v1/billing/webhook`
- Events: `checkout.session.completed`, `customer.subscription.*`, `invoice.payment_*`

**Customer Portal** → Enable:
- Update payment method ✓
- View invoices ✓
- Cancel subscription ✓

---

## 🗄️ Database Schema

```sql
-- New user fields
stripe_customer_id       VARCHAR(255)
stripe_subscription_id   VARCHAR(255)
subscription_status      VARCHAR(50)
current_period_end       TIMESTAMPTZ
```

---

## ✅ Subscription Statuses

- `active` - Subscription paid and active
- `trialing` - In trial period
- `past_due` - Payment failed
- `canceled` - Subscription cancelled
- `incomplete` - Payment pending

---

## 🔐 Security

✓ Webhook signature verification  
✓ All endpoints require JWT (except webhook)  
✓ No API keys in code  
✓ HTTPS required for production

---

## 🐛 Quick Troubleshoots

**Webhook fails?**
```bash
# Check secret
echo $STRIPE_WEBHOOK_SECRET

# View events in Stripe Dashboard
Webhooks → Recent events
```

**Checkout fails?**
```bash
# Verify price ID
echo $STRIPE_PRICE_PRO_MONTHLY

# Check Stripe mode (test vs live)
echo $STRIPE_SECRET_KEY | cut -c1-7
# Should match: sk_test_ or sk_live_
```

---

## 📚 Full Documentation

- **Architecture**: `docs/BLOCK_7_COMPLETE.md`
- **Deployment**: `BLOCK_7_SUMMARY.md`
- **Stripe Docs**: https://stripe.com/docs

---

**Need help?** Run: `python3 verify_block_7.py`
