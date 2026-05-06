/**
 * Billing Page
 * ===========
 * Subscription and billing management with pricing plans
 */

'use client';

import { useState, useEffect } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useSearchParams } from 'next/navigation';
import {
  PLANS,
  getSubscription,
  createCheckoutSession,
  type BillingInterval,
  type PlanTier,
} from '@/lib/billing-service';
import { SubscriptionOverview } from '@/components/billing/subscription-overview';
import { UsageMeter } from '@/components/billing/usage-meter';
import { PlanCard } from '@/components/billing/plan-card';
import { Button } from '@/components/ui/button';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Skeleton } from '@/components/ui/skeleton';
import { CheckCircle2, XCircle } from 'lucide-react';
import { cn } from '@/lib/utils';

export default function BillingPage() {
  const [billingInterval, setBillingInterval] = useState<BillingInterval>('monthly');
  const [checkoutError, setCheckoutError] = useState<string | null>(null);
  const searchParams = useSearchParams();
  const queryClient = useQueryClient();

  // Handle Stripe redirect
  useEffect(() => {
    const success = searchParams?.get('success');
    const canceled = searchParams?.get('canceled');

    if (success === 'true') {
      // Refetch subscription after successful checkout
      queryClient.invalidateQueries({ queryKey: ['subscription'] });
      queryClient.invalidateQueries({ queryKey: ['usage'] });
    }

    if (canceled === 'true') {
      setCheckoutError('Checkout was canceled');
    }
  }, [searchParams, queryClient]);

  // Fetch current subscription
  const { data: subscription, isLoading: isLoadingSubscription } = useQuery({
    queryKey: ['subscription'],
    queryFn: getSubscription,
  });

  const handleSelectPlan = async (tier: PlanTier, interval: BillingInterval) => {
    setCheckoutError(null);

    try {
      // For free tier, just show a message (no checkout needed)
      if (tier === 'FREE') {
        setCheckoutError('Please contact support to downgrade to the free plan');
        return;
      }

      // Create checkout session
      const { checkout_url } = await createCheckoutSession(tier, interval);
      
      // Redirect to Stripe checkout
      window.location.href = checkout_url;
    } catch (error: any) {
      setCheckoutError(
        error.response?.data?.detail || 
        'Failed to start checkout. Please try again.'
      );
    }
  };

  const currentPlan = subscription?.plan_tier || 'FREE';

  return (
    <div className="space-y-8">
      {/* Header */}
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Billing & Subscription</h1>
        <p className="text-muted-foreground mt-2">
          Manage your subscription, view usage, and upgrade your plan
        </p>
      </div>

      {/* Success/Error Alerts */}
      {searchParams?.get('success') === 'true' && (
        <Alert className="border-green-500 bg-green-50 dark:bg-green-950">
          <CheckCircle2 className="h-4 w-4 text-green-600 dark:text-green-400" />
          <AlertDescription className="text-green-600 dark:text-green-400">
            Subscription activated successfully! Your new features are now available.
          </AlertDescription>
        </Alert>
      )}

      {checkoutError && (
        <Alert variant="destructive">
          <XCircle className="h-4 w-4" />
          <AlertDescription>{checkoutError}</AlertDescription>
        </Alert>
      )}

      {/* Overview Section */}
      {isLoadingSubscription ? (
        <div className="grid gap-6 md:grid-cols-2">
          <Skeleton className="h-64" />
          <Skeleton className="h-64" />
        </div>
      ) : (
        <div className="grid gap-6 md:grid-cols-2">
          <SubscriptionOverview />
          <UsageMeter planTier={currentPlan} />
        </div>
      )}

      {/* Pricing Plans */}
      <div className="space-y-6">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-2xl font-bold">Choose Your Plan</h2>
            <p className="text-muted-foreground mt-1">
              Select the plan that best fits your needs
            </p>
          </div>

          {/* Billing Toggle */}
          <div className="flex items-center gap-2 p-1 bg-muted rounded-lg">
            <Button
              variant={billingInterval === 'monthly' ? 'default' : 'ghost'}
              size="sm"
              onClick={() => setBillingInterval('monthly')}
              className={cn(
                'transition-all',
                billingInterval === 'monthly' && 'shadow-sm'
              )}
            >
              Monthly
            </Button>
            <Button
              variant={billingInterval === 'yearly' ? 'default' : 'ghost'}
              size="sm"
              onClick={() => setBillingInterval('yearly')}
              className={cn(
                'transition-all',
                billingInterval === 'yearly' && 'shadow-sm'
              )}
            >
              Yearly
              <span className="ml-1 text-xs">(Save 17%)</span>
            </Button>
          </div>
        </div>

        {/* Plans Grid */}
        <div className="grid gap-8 md:grid-cols-2 lg:grid-cols-4">
          <PlanCard
            plan={PLANS.FREE}
            currentPlan={currentPlan}
            billingInterval={billingInterval}
            onSelectPlan={handleSelectPlan}
          />
          <PlanCard
            plan={PLANS.BASIC}
            currentPlan={currentPlan}
            billingInterval={billingInterval}
            onSelectPlan={handleSelectPlan}
          />
          <PlanCard
            plan={PLANS.PRO}
            currentPlan={currentPlan}
            billingInterval={billingInterval}
            onSelectPlan={handleSelectPlan}
            isPopular
          />
          <PlanCard
            plan={PLANS.ENTERPRISE}
            currentPlan={currentPlan}
            billingInterval={billingInterval}
            onSelectPlan={handleSelectPlan}
          />
        </div>
      </div>

      {/* FAQ or Additional Info */}
      <div className="pt-8 border-t">
        <div className="max-w-3xl">
          <h3 className="text-lg font-semibold mb-4">Frequently Asked Questions</h3>
          <div className="space-y-4 text-sm text-muted-foreground">
            <div>
              <p className="font-medium text-foreground mb-1">Can I change my plan anytime?</p>
              <p>Yes, you can upgrade or downgrade your plan at any time. Changes take effect immediately.</p>
            </div>
            <div>
              <p className="font-medium text-foreground mb-1">What happens if I exceed my character limit?</p>
              <p>Processing will be paused until your next billing cycle or you upgrade your plan.</p>
            </div>
            <div>
              <p className="font-medium text-foreground mb-1">Can I cancel anytime?</p>
              <p>Yes, you can cancel your subscription at any time. You&apos;ll retain access until the end of your billing period.</p>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
