# BLOCK 7: Billing & Monetization - Deployment Summary

**Version:** 0.9.0  
**Status:** ✅ Ready for Production  
**Deployment Time:** ~15 minutes

---

## 🚀 Quick Deployment

### Step 1: Run Database Migration

```bash
cd services/api
alembic upgrade head
```

**What it does:**
- Adds 4 billing columns to `users` table
- Creates indexes for Stripe customer/subscription IDs
- No downtime required

### Step 2: Configure Stripe

#### A. Create Products in Stripe Dashboard

1. Go to https://dashboard.stripe.com/products
2. Create 3 products:
   - **BASIC** - $9/month
   - **PRO** - $29/month  
   - **ENTERPRISE** - $99/month

3. For each product, add pricing:
   - Click "Add price"
   - Set recurring: Monthly
   - Copy the Price ID (starts with `price_`)

4. (Optional) Add yearly pricing with discount

#### B. Set Up Webhook

1. Go to https://dashboard.stripe.com/webhooks
2. Click "Add endpoint"
3. Enter URL: `https://api.sonoro.com/api/v1/billing/webhook`
4. Select events:
   - `checkout.session.completed`
   - `customer.subscription.created`
   - `customer.subscription.updated`
   - `customer.subscription.deleted`
   - `invoice.payment_succeeded`
   - `invoice.payment_failed`
5. Copy the "Signing secret" (starts with `whsec_`)

#### C. Enable Customer Portal

1. Go to https://dashboard.stripe.com/settings/billing/portal
2. Enable the portal
3. Configure:
   - ✅ Update payment method
   - ✅ View invoices  
   - ✅ Cancel subscription

### Step 3: Update Environment Variables

Add to `.env`:

```bash
# Stripe Keys (from Dashboard → API keys)
STRIPE_SECRET_KEY=sk_test_51...
STRIPE_PUBLISHABLE_KEY=pk_test_51...
STRIPE_WEBHOOK_SECRET=whsec_...

# Price IDs (from products you created)
STRIPE_PRICE_BASIC_MONTHLY=price_1...
STRIPE_PRICE_PRO_MONTHLY=price_1...
STRIPE_PRICE_ENTERPRISE_MONTHLY=price_1...

# Optional yearly prices
STRIPE_PRICE_BASIC_YEARLY=price_1...
STRIPE_PRICE_PRO_YEARLY=price_1...
STRIPE_PRICE_ENTERPRISE_YEARLY=price_1...

# Billing URLs
BILLING_RETURN_URL=https://app.sonoro.com/billing
```

### Step 4: Install Dependencies

```bash
pip install stripe==8.2.0
```

### Step 5: Restart API Server

```bash
# Development
uvicorn app.main:app --reload

# Production with Docker
docker-compose restart api
```

### Step 6: Verify Deployment

```bash
# 1. Check health endpoint
curl http://localhost:8000/api/v1/health

# 2. Check metrics for billing
curl http://localhost:8000/metrics | grep sonoro_revenue

# 3. Test webhook with Stripe CLI
stripe listen --forward-to localhost:8000/api/v1/billing/webhook
stripe trigger checkout.session.completed
```

---

## 📊 What's Included

### API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/v1/billing/checkout` | Create checkout session |
| GET | `/api/v1/billing/subscription` | Get subscription details |
| POST | `/api/v1/billing/portal` | Generate portal URL |
| DELETE | `/api/v1/billing/subscription` | Cancel subscription |
| POST | `/api/v1/billing/webhook` | Handle Stripe webhooks |

### Database Changes

```sql
-- 4 new columns in users table
stripe_customer_id       VARCHAR(255)  -- Indexed
stripe_subscription_id   VARCHAR(255)  -- Indexed  
subscription_status      VARCHAR(50)   -- Indexed
current_period_end       TIMESTAMPTZ
```

### Prometheus Metrics

```prometheus
sonoro_revenue_total                           # Total revenue
sonoro_active_subscriptions_total              # Active subs by tier
sonoro_mrr                                     # Monthly Recurring Revenue
sonoro_subscription_events_total               # Sub lifecycle events
sonoro_payment_failures_total                  # Payment failures
sonoro_checkout_sessions_created_total         # Checkouts started
sonoro_checkout_sessions_completed_total       # Checkouts completed
sonoro_trial_conversions_total                 # Trial → paid conversions
```

---

## 🔒 Security Checklist

- [x] Webhook signature verification enabled
- [x] All endpoints require authentication (except webhook)
- [x] API keys stored in environment variables
- [x] HTTPS required for production webhooks
- [x] No sensitive data in logs

---

## 🧪 Testing

### Test Mode (Development)

Use Stripe test mode with test cards:

```bash
# Success
4242 4242 4242 4242

# Declined
4000 0000 0000 0002

# Requires authentication
4000 0025 0000 3155
```

### Stripe CLI Testing

```bash
# Install Stripe CLI
brew install stripe/stripe-cli/stripe

# Login
stripe login

# Forward webhooks to local server
stripe listen --forward-to localhost:8000/api/v1/billing/webhook

# Trigger test events
stripe trigger checkout.session.completed
stripe trigger invoice.payment_succeeded
stripe trigger customer.subscription.deleted
```

---

## 📈 Monitoring

### Key Metrics to Watch

1. **Revenue**
   ```promql
   sum(rate(sonoro_revenue_total[30d]))
   ```

2. **Churn Rate**
   ```promql
   rate(sonoro_subscription_churn_total[30d]) / 
   avg_over_time(sonoro_active_subscriptions_total[30d])
   ```

3. **Checkout Conversion**
   ```promql
   sonoro_checkout_sessions_completed_total / 
   sonoro_checkout_sessions_created_total * 100
   ```

4. **MRR Growth**
   ```promql
   increase(sonoro_mrr[30d])
   ```

### Alerts to Set Up

```yaml
# Prometheus alerts.yml
- alert: HighPaymentFailureRate
  expr: rate(sonoro_payment_failures_total[5m]) > 0.1
  annotations:
    summary: "High payment failure rate detected"

- alert: ChurnSpike
  expr: increase(sonoro_subscription_churn_total[1h]) > 10
  annotations:
    summary: "Unusual spike in subscription cancellations"
```

---

## 🐛 Troubleshooting

### Webhook Not Working

1. **Check webhook secret**
   ```bash
   echo $STRIPE_WEBHOOK_SECRET
   # Should start with whsec_
   ```

2. **Verify endpoint URL**
   - Must be publicly accessible
   - Must be HTTPS in production
   - Check Stripe Dashboard → Webhooks → Endpoint details

3. **Check logs**
   ```bash
   # API logs
   docker logs sonoro-api -f | grep webhook
   
   # Stripe Dashboard
   # Webhooks → Click endpoint → View events
   ```

### Checkout Session Creation Fails

1. **Verify price ID**
   ```bash
   echo $STRIPE_PRICE_BASIC_MONTHLY
   # Should start with price_
   ```

2. **Check Stripe mode**
   - Test keys with test price IDs
   - Live keys with live price IDs
   - Don't mix modes!

3. **Review error message**
   ```python
   # API returns detailed error from Stripe
   {
     "detail": "No such price: 'price_123...'",
     "type": "invalid_request_error"
   }
   ```

### Subscription Not Updating After Payment

1. **Check webhook delivery**
   - Stripe Dashboard → Webhooks → Recent events
   - Should see 200 response

2. **Verify event handling**
   ```bash
   # Check API logs for webhook processing
   grep "Webhook event.*processed successfully" api.log
   ```

3. **Manual sync** (if needed)
   ```python
   # In Python shell
   from app.services.stripe_service import StripeService
   service = StripeService()
   
   # Fetch subscription from Stripe
   sub = await service.retrieve_subscription("sub_...")
   
   # Update user manually
   user.subscription_status = sub.status
   user.stripe_subscription_id = sub.id
   await db.commit()
   ```

---

## 📞 Support

### Stripe Resources

- **Dashboard:** https://dashboard.stripe.com
- **Documentation:** https://stripe.com/docs
- **Support:** https://support.stripe.com
- **Status:** https://status.stripe.com

### Internal Resources

- **Full Documentation:** `docs/BLOCK_7_COMPLETE.md`
- **API Docs:** http://localhost:8000/docs
- **Metrics:** http://localhost:8000/metrics

---

## ✅ Deployment Checklist

- [ ] Database migration completed
- [ ] Stripe products created
- [ ] Stripe webhook configured
- [ ] Customer portal enabled
- [ ] Environment variables set
- [ ] Dependencies installed
- [ ] API server restarted
- [ ] Health check passed
- [ ] Test checkout completed
- [ ] Webhook test successful
- [ ] Metrics visible in Prometheus
- [ ] Alerts configured

---

## 🎉 Success Criteria

Your deployment is successful when:

1. ✅ Health endpoint returns 200
2. ✅ Checkout session creates successfully
3. ✅ Test payment completes
4. ✅ Webhook processes and updates database
5. ✅ Customer portal accessible
6. ✅ Metrics appear in Prometheus

---

**Estimated Deployment Time:** 10-15 minutes  
**Difficulty:** Easy (if Stripe account is ready)

**Ready to deploy!** 🚀
