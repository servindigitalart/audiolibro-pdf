/**
 * UpgradeModal
 * ============
 * Conversion-optimized modal shown when a user hits a paywall.
 * Fetches live tier data from the pricing engine — never hardcoded.
 *
 * Features:
 *   - Hero message derived from the triggering CTA
 *   - Annual/monthly toggle with savings callout
 *   - Feature comparison vs. current plan
 *   - Social proof elements
 *   - Direct Stripe checkout on click (no extra confirmation step)
 */

'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import { useQuery } from '@tanstack/react-query';
import { CheckCircle2, Zap, ArrowRight, X } from 'lucide-react';
import { Dialog, DialogContent, DialogTitle } from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Separator } from '@/components/ui/separator';
import { cn } from '@/lib/utils';
import { fetchTierCatalog, TIER_META, fmtChars, fmtStorage, fmtApiCalls, annualMonthlyRate, annualDiscountPct, type PlanTier, type TierConfig } from '@/lib/pricing-service';
import { createCheckoutSession, type BillingInterval } from '@/lib/billing-service';
import { track } from '@/lib/analytics';
import type { UpgradeCTA } from '@/lib/upgrade-service';
import { useAuthStore } from '@/store/auth-store';

interface UpgradeModalProps {
  open: boolean;
  onClose: () => void;
  /** CTA that triggered this modal (provides heading/body copy) */
  cta?: UpgradeCTA | null;
  /** Force a specific target tier (overrides cta.target_tier) */
  targetTier?: PlanTier;
}

function PlanHighlight({ config, interval, isTarget, onSelect, loading }: {
  config: TierConfig;
  interval: BillingInterval;
  isTarget: boolean;
  onSelect: () => void;
  loading: boolean;
}) {
  const meta = TIER_META[config.tier];
  const price = interval === 'yearly' ? annualMonthlyRate(config) : config.monthly_price_usd;
  const discount = annualDiscountPct(config);

  return (
    <div
      className={cn(
        'relative rounded-xl border p-5 flex flex-col gap-4 transition-all',
        isTarget
          ? 'border-violet-500 bg-violet-50 dark:bg-violet-950/30 shadow-md shadow-violet-100 dark:shadow-none'
          : 'border-border bg-card',
      )}
    >
      {meta.badge && (
        <Badge className="absolute -top-3 left-1/2 -translate-x-1/2 bg-violet-600 text-white text-xs px-3">
          {meta.badge}
        </Badge>
      )}

      <div>
        <p className="font-semibold text-sm">{meta.name}</p>
        <div className="flex items-baseline gap-1 mt-1">
          <span className="text-2xl font-bold">
            {price === 0 ? 'Free' : `$${price.toFixed(price % 1 === 0 ? 0 : 2)}`}
          </span>
          {price > 0 && (
            <span className="text-xs text-muted-foreground">/mo</span>
          )}
          {interval === 'yearly' && discount > 0 && (
            <Badge variant="secondary" className="ml-1 text-xs">
              Save {discount}%
            </Badge>
          )}
        </div>
      </div>

      <ul className="space-y-1.5 text-sm flex-1">
        {[
          `${fmtChars(config.limits.monthly_chars)} chars/mo`,
          `${config.limits.monthly_jobs} jobs/mo`,
          fmtStorage(config.limits.storage_mb),
          fmtApiCalls(config.limits.daily_api_calls),
        ].map((f) => (
          <li key={f} className="flex items-center gap-2 text-muted-foreground">
            <CheckCircle2 className="h-3.5 w-3.5 text-green-500 shrink-0" />
            {f}
          </li>
        ))}
      </ul>

      {isTarget && (
        <Button
          className="w-full bg-violet-600 hover:bg-violet-700 text-white"
          onClick={onSelect}
          disabled={loading}
        >
          {loading ? 'Loading…' : 'Upgrade now'}
          {!loading && <ArrowRight className="ml-2 h-4 w-4" />}
        </Button>
      )}
    </div>
  );
}

export function UpgradeModal({ open, onClose, cta, targetTier }: UpgradeModalProps) {
  const [interval, setInterval] = useState<BillingInterval>('yearly');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const { user } = useAuthStore();

  const target = targetTier ?? cta?.target_tier ?? 'PRO';

  const { data: catalog } = useQuery({
    queryKey: ['tier-catalog'],
    queryFn: fetchTierCatalog,
    staleTime: 300_000,
  });

  const targetConfig = catalog?.find((c) => c.tier === target);

  const handleUpgrade = async () => {
    if (!targetConfig) return;
    setError(null);
    setLoading(true);

    track('checkout_started', {
      target_tier: target,
      interval,
      trigger: cta?.trigger,
    });

    try {
      const priceIdAttr = interval === 'yearly'
        ? targetConfig.stripe_price_ids?.annual
        : targetConfig.stripe_price_ids?.monthly;

      if (!priceIdAttr) {
        throw new Error('Stripe price ID not configured');
      }

      const { url } = await createCheckoutSession(
        target as any,
        interval,
      ) as any;

      if (url) {
        window.location.href = url;
      }
    } catch (e: any) {
      const msg = e?.response?.data?.detail ?? e?.message ?? 'Could not start checkout';
      setError(msg);
      setLoading(false);
    }
  };

  const handleClose = () => {
    track('paywall_dismissed', { trigger: cta?.trigger, target_tier: target });
    onClose();
  };

  const relevantTiers = catalog?.filter(
    (c) => c.tier !== 'FREE' && (c.tier === target || c.tier === 'PRO'),
  ) ?? [];

  return (
    <Dialog open={open} onOpenChange={(v) => !v && handleClose()}>
      <DialogContent className="max-w-2xl p-0 overflow-hidden">
        {/* Header */}
        <div className="bg-gradient-to-br from-violet-600 to-purple-700 p-6 text-white">
          <div className="flex items-start justify-between">
            <div className="flex items-center gap-2">
              <Zap className="h-5 w-5 text-yellow-300" />
              <DialogTitle className="text-white text-lg font-bold">
                {cta?.heading ?? 'Unlock more power'}
              </DialogTitle>
            </div>
            <button
              onClick={handleClose}
              className="text-white/70 hover:text-white transition-colors"
              aria-label="Close"
            >
              <X className="h-5 w-5" />
            </button>
          </div>
          {cta?.body && (
            <p className="mt-2 text-sm text-violet-100">{cta.body}</p>
          )}

          {/* Social proof */}
          <div className="mt-4 flex items-center gap-4 text-xs text-violet-200">
            <span>⭐ 4.9/5 from 2,000+ users</span>
            <Separator orientation="vertical" className="h-4 bg-violet-400" />
            <span>Cancel anytime</span>
            <Separator orientation="vertical" className="h-4 bg-violet-400" />
            <span>Instant activation</span>
          </div>
        </div>

        {/* Billing toggle */}
        <div className="px-6 py-4 border-b flex items-center justify-between">
          <p className="text-sm font-medium">Billing period</p>
          <div className="flex items-center gap-1 p-1 bg-muted rounded-lg text-sm">
            <button
              onClick={() => setInterval('monthly')}
              className={cn(
                'px-3 py-1.5 rounded-md transition-all',
                interval === 'monthly' ? 'bg-background shadow font-medium' : 'text-muted-foreground',
              )}
            >
              Monthly
            </button>
            <button
              onClick={() => setInterval('yearly')}
              className={cn(
                'px-3 py-1.5 rounded-md transition-all flex items-center gap-1.5',
                interval === 'yearly' ? 'bg-background shadow font-medium' : 'text-muted-foreground',
              )}
            >
              Annual
              <Badge className="bg-green-500/20 text-green-700 dark:text-green-400 text-xs px-1.5">
                Save up to 20%
              </Badge>
            </button>
          </div>
        </div>

        {/* Plan cards */}
        <div className="px-6 py-5">
          <div className={cn('grid gap-4', relevantTiers.length === 2 ? 'grid-cols-2' : 'grid-cols-1 max-w-xs mx-auto')}>
            {relevantTiers.map((cfg) => (
              <PlanHighlight
                key={cfg.tier}
                config={cfg}
                interval={interval}
                isTarget={cfg.tier === target}
                onSelect={handleUpgrade}
                loading={loading}
              />
            ))}
          </div>

          {error && (
            <p className="mt-3 text-sm text-destructive text-center">{error}</p>
          )}
        </div>

        {/* Footer */}
        <div className="px-6 py-4 border-t bg-muted/30 text-xs text-muted-foreground text-center">
          Secured by Stripe · Charges in USD · Cancel anytime from Settings
        </div>
      </DialogContent>
    </Dialog>
  );
}
