/**
 * useUsageLimits
 * ==============
 * Core hook that fetches the current user's account overview, hydrates the
 * pricing store, and evaluates upgrade triggers.
 *
 * Returns:
 *   - usage          : raw UsageState
 *   - tier           : PlanTier
 *   - upgradeCTAs    : sorted upgrade prompts
 *   - isBlocked      : true when any quota is exhausted (hard paywall)
 *   - hasWarning     : true when any quota ≥ 80% (soft paywall)
 *   - topCTA         : highest-priority CTA (null if none)
 *   - blocker        : highest-priority blocking CTA
 *   - charPct        : 0–1 character usage fraction
 *   - refetch        : function to refresh usage data
 *
 * Data source: GET /api/v1/account/overview
 * Evaluated: client-side via upgrade-service.ts evaluateUpgrades()
 */

'use client';

import { useEffect, useCallback } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useAuthStore } from '@/store/auth-store';
import { usePricingStore, type UsageState } from '@/store/pricing-store';
import { fetchEffectiveLimits } from '@/lib/pricing-service';
import { evaluateUpgrades, topCTA, getBlocker, type UsageSnapshot } from '@/lib/upgrade-service';
import { apiClient } from '@/lib/api-client';
import type { PlanTier } from '@/lib/pricing-service';

// Backend shape from GET /api/v1/account/overview
interface AccountOverview {
  user: { id: string; plan_tier: string };
  plan: string;
  usage: {
    characters_used: number;
    jobs_created: number;
    storage_used_mb: number;
    api_calls: number;
    period_start: string;
    period_end: string;
  };
  costs: { total_cost_usd: number };
  remaining_quota: {
    characters: { remaining: number; limit: number; used_percentage: number };
    jobs: { remaining: number; limit: number; used_percentage: number };
    storage_mb: { remaining: number; limit: number; used_percentage: number };
    api_calls: { remaining: number; limit: number; used_percentage: number };
  };
  health: { quota_warnings: string[]; cost_warnings: string[] };
}

async function fetchAccountOverview(): Promise<AccountOverview> {
  const res = await apiClient.get<AccountOverview>('/account/overview');
  return res.data;
}

function overviewToUsageState(
  data: AccountOverview,
  tier: PlanTier,
  dailyApiLimit: number,
): UsageState {
  const rq = data.remaining_quota;
  return {
    chars_used: data.usage.characters_used,
    chars_limit: rq.characters.limit,
    jobs_created: data.usage.jobs_created,
    jobs_limit: rq.jobs.limit,
    storage_mb: data.usage.storage_used_mb,
    storage_limit_mb: rq.storage_mb.limit,
    daily_api_calls: data.usage.api_calls,
    daily_api_limit: dailyApiLimit,
    monthly_cost_usd: data.costs.total_cost_usd,
    max_monthly_cost_usd: 0, // filled from effective limits
    period_start: data.usage.period_start,
    period_end: data.usage.period_end,
  };
}

export function useUsageLimits() {
  const { user, isAuthenticated } = useAuthStore();
  const {
    usage, upgradeCTAs, effectiveLimits,
    setUsage, setUsageLoading, setUsageError,
    setEffectiveLimits, setUpgradeCTAs,
  } = usePricingStore();

  // Fetch account overview every 60 seconds while authenticated
  const {
    data: overview,
    isLoading: overviewLoading,
    error: overviewError,
    refetch,
  } = useQuery({
    queryKey: ['account-overview'],
    queryFn: fetchAccountOverview,
    enabled: isAuthenticated,
    staleTime: 30_000,
    refetchInterval: 60_000,
  });

  // Fetch effective limits (with experiment overrides) when user changes
  const {
    data: limits,
  } = useQuery({
    queryKey: ['effective-limits', user?.id],
    queryFn: () => fetchEffectiveLimits(user!.id),
    enabled: isAuthenticated && !!user?.id,
    staleTime: 120_000,
  });

  // Hydrate store when data arrives
  useEffect(() => {
    if (limits) setEffectiveLimits(limits);
  }, [limits, setEffectiveLimits]);

  useEffect(() => {
    if (!overview || !limits) return;

    const tier = (limits.tier ?? user?.plan_tier ?? 'FREE') as PlanTier;
    const usageState = overviewToUsageState(
      overview,
      tier,
      limits.limits.daily_api_calls,
    );
    setUsage(usageState);

    const snapshot: UsageSnapshot = {
      tier,
      chars_used: usageState.chars_used,
      chars_limit: usageState.chars_limit,
      jobs_created: usageState.jobs_created,
      jobs_limit: usageState.jobs_limit,
      storage_mb: usageState.storage_mb,
      storage_limit_mb: usageState.storage_limit_mb,
      daily_api_calls: usageState.daily_api_calls,
      daily_api_limit: usageState.daily_api_limit,
    };

    setUpgradeCTAs(evaluateUpgrades(snapshot));
  }, [overview, limits, user, setUsage, setUpgradeCTAs]);

  useEffect(() => {
    setUsageLoading(overviewLoading);
  }, [overviewLoading, setUsageLoading]);

  useEffect(() => {
    if (overviewError) {
      setUsageError((overviewError as Error).message ?? 'Failed to load usage');
    }
  }, [overviewError, setUsageError]);

  // Derived values
  const tier = (effectiveLimits?.tier ?? user?.plan_tier ?? 'FREE') as PlanTier;
  const isBlocked = upgradeCTAs.some((c) => c.is_blocking);
  const hasWarning = upgradeCTAs.length > 0;
  const top = topCTA({
    tier,
    chars_used: usage?.chars_used ?? 0,
    chars_limit: usage?.chars_limit ?? 0,
    jobs_created: usage?.jobs_created ?? 0,
    jobs_limit: usage?.jobs_limit ?? 0,
    storage_mb: usage?.storage_mb ?? 0,
    storage_limit_mb: usage?.storage_limit_mb ?? 0,
    daily_api_calls: usage?.daily_api_calls ?? 0,
    daily_api_limit: usage?.daily_api_limit ?? -1,
  });
  const blocker = upgradeCTAs.find((c) => c.is_blocking) ?? null;
  const charPct = usage && usage.chars_limit > 0
    ? Math.min(1, usage.chars_used / usage.chars_limit)
    : 0;

  return {
    usage,
    tier,
    upgradeCTAs,
    isBlocked,
    hasWarning,
    topCTA: top,
    blocker,
    charPct,
    isLoading: overviewLoading,
    error: overviewError,
    refetch,
  };
}
