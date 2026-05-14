/**
 * UsageOverview
 * =============
 * Card showing all quota dimensions for the current billing period.
 * Used on the usage page and dashboard.
 */

'use client';

import { useState } from 'react';
import { RefreshCw, TrendingUp, Calendar, Zap } from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Skeleton } from '@/components/ui/skeleton';
import { QuotaBar } from './quota-bar';
import { UpgradeModal } from '@/components/paywall/upgrade-modal';
import { usePricingStore, selectCurrentTier, selectBlocker } from '@/store/pricing-store';
import { TIER_META, fmtChars, fmtStorage, fmtApiCalls, type PlanTier } from '@/lib/pricing-service';
import { track } from '@/lib/analytics';
import { cn } from '@/lib/utils';

function fmt(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${Math.round(n / 1_000)}K`;
  return n.toLocaleString();
}

function fmtCost(usd: number): string {
  return `$${usd.toFixed(usd < 1 ? 4 : 2)}`;
}

interface UsageOverviewProps {
  onRefetch?: () => void;
  compact?: boolean;
}

export function UsageOverview({ onRefetch, compact }: UsageOverviewProps) {
  const [modalOpen, setModalOpen] = useState(false);
  const usage = usePricingStore((s) => s.usage);
  const usageLoading = usePricingStore((s) => s.usageLoading);
  const tier = usePricingStore(selectCurrentTier);
  const blocker = usePricingStore(selectBlocker);
  const meta = TIER_META[tier] ?? TIER_META.FREE;

  if (usageLoading && !usage) {
    return (
      <Card>
        <CardHeader>
          <Skeleton className="h-5 w-40" />
        </CardHeader>
        <CardContent className="space-y-4">
          <Skeleton className="h-8 w-full" />
          <Skeleton className="h-8 w-full" />
          <Skeleton className="h-8 w-full" />
        </CardContent>
      </Card>
    );
  }

  if (!usage) return null;

  const charPct   = usage.chars_limit > 0 ? usage.chars_used / usage.chars_limit : 0;
  const jobPct    = usage.jobs_limit > 0 ? usage.jobs_created / usage.jobs_limit : 0;
  const storPct   = usage.storage_limit_mb > 0 ? usage.storage_mb / usage.storage_limit_mb : 0;
  const apiPct    = usage.daily_api_limit > 0 ? usage.daily_api_calls / usage.daily_api_limit : 0;

  const resetDate = usage.period_end
    ? new Date(usage.period_end).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
    : null;

  return (
    <>
      <Card>
        <CardHeader className="flex flex-row items-start justify-between pb-2">
          <div>
            <CardTitle className="text-base flex items-center gap-2">
              Usage This Period
              <Badge
                variant="secondary"
                className={cn(
                  'text-xs',
                  tier !== 'FREE' && 'bg-violet-100 text-violet-700 dark:bg-violet-900/30 dark:text-violet-300',
                )}
              >
                {meta.name}
              </Badge>
            </CardTitle>
            {resetDate && (
              <CardDescription className="flex items-center gap-1 mt-1">
                <Calendar className="h-3 w-3" />
                Resets {resetDate}
              </CardDescription>
            )}
          </div>

          <div className="flex items-center gap-2">
            {onRefetch && (
              <Button variant="ghost" size="icon" className="h-7 w-7" onClick={onRefetch}>
                <RefreshCw className="h-3.5 w-3.5" />
              </Button>
            )}
            {blocker && (
              <Button
                size="sm"
                className="h-7 text-xs bg-violet-600 hover:bg-violet-700 text-white"
                onClick={() => {
                  track('upgrade_intent', { source: 'usage_overview' });
                  setModalOpen(true);
                }}
              >
                <Zap className="h-3 w-3 mr-1" />
                Upgrade
              </Button>
            )}
          </div>
        </CardHeader>

        <CardContent className="space-y-4">
          <QuotaBar
            value={charPct}
            label="Characters"
            usedLabel={fmtChars(usage.chars_used)}
            limitLabel={fmtChars(usage.chars_limit)}
          />

          <QuotaBar
            value={jobPct}
            label="Conversions"
            usedLabel={`${usage.jobs_created}`}
            limitLabel={`${usage.jobs_limit}`}
          />

          {!compact && (
            <>
              <QuotaBar
                value={storPct}
                label="Storage"
                usedLabel={fmtStorage(usage.storage_mb)}
                limitLabel={fmtStorage(usage.storage_limit_mb)}
              />

              {usage.daily_api_limit !== -1 && (
                <QuotaBar
                  value={apiPct}
                  label="API Calls (today)"
                  usedLabel={`${usage.daily_api_calls}`}
                  limitLabel={fmtApiCalls(usage.daily_api_limit)}
                />
              )}

              {usage.monthly_cost_usd > 0 && (
                <div className="pt-2 border-t flex items-center justify-between text-sm">
                  <span className="flex items-center gap-1.5 text-muted-foreground">
                    <TrendingUp className="h-3.5 w-3.5" />
                    Estimated cost this period
                  </span>
                  <span className="font-semibold">{fmtCost(usage.monthly_cost_usd)}</span>
                </div>
              )}
            </>
          )}
        </CardContent>
      </Card>

      <UpgradeModal
        open={modalOpen}
        onClose={() => setModalOpen(false)}
        cta={blocker}
      />
    </>
  );
}
