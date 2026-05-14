/**
 * Pricing Store
 * =============
 * Zustand store for pricing tier catalog, usage state, and upgrade CTAs.
 *
 * One store for all monetization-related state so components can react
 * to paywall triggers, usage thresholds, and plan changes in one place.
 */

import { create } from 'zustand';
import type { TierConfig, PlanTier, EffectiveLimits } from '@/lib/pricing-service';
import type { UpgradeCTA } from '@/lib/upgrade-service';

// ── Usage state shape ─────────────────────────────────────────────────────────

export interface UsageState {
  chars_used: number;
  chars_limit: number;
  jobs_created: number;
  jobs_limit: number;
  storage_mb: number;
  storage_limit_mb: number;
  daily_api_calls: number;
  daily_api_limit: number;      // -1 = unlimited
  monthly_cost_usd: number;
  max_monthly_cost_usd: number;
  period_start: string | null;
  period_end: string | null;
}

// ── Store shape ───────────────────────────────────────────────────────────────

interface PricingStore {
  // Tier catalog (fetched from /api/v1/pricing/tiers)
  catalog: TierConfig[] | null;
  catalogLoading: boolean;
  catalogError: string | null;

  // Effective limits for current user (with experiment overrides)
  effectiveLimits: EffectiveLimits | null;

  // Live usage for current period
  usage: UsageState | null;
  usageLoading: boolean;
  usageError: string | null;

  // Active upgrade CTAs (derived from usage vs. limits)
  upgradeCTAs: UpgradeCTA[];

  // Actions
  setCatalog: (tiers: TierConfig[]) => void;
  setCatalogLoading: (v: boolean) => void;
  setCatalogError: (e: string | null) => void;

  setEffectiveLimits: (limits: EffectiveLimits) => void;

  setUsage: (usage: UsageState) => void;
  setUsageLoading: (v: boolean) => void;
  setUsageError: (e: string | null) => void;

  setUpgradeCTAs: (ctas: UpgradeCTA[]) => void;

  /** Clear all monetization state on logout */
  reset: () => void;
}

// ── Initial values ────────────────────────────────────────────────────────────

const INITIAL: Omit<PricingStore, keyof { [K in keyof PricingStore as PricingStore[K] extends Function ? K : never]: never }> = {
  catalog: null,
  catalogLoading: false,
  catalogError: null,
  effectiveLimits: null,
  usage: null,
  usageLoading: false,
  usageError: null,
  upgradeCTAs: [],
};

// ── Store ─────────────────────────────────────────────────────────────────────

export const usePricingStore = create<PricingStore>()((set) => ({
  catalog: null,
  catalogLoading: false,
  catalogError: null,
  effectiveLimits: null,
  usage: null,
  usageLoading: false,
  usageError: null,
  upgradeCTAs: [],

  setCatalog: (tiers) =>
    set({ catalog: tiers, catalogLoading: false, catalogError: null }),

  setCatalogLoading: (v) => set({ catalogLoading: v }),

  setCatalogError: (e) => set({ catalogError: e, catalogLoading: false }),

  setEffectiveLimits: (limits) => set({ effectiveLimits: limits }),

  setUsage: (usage) =>
    set({ usage, usageLoading: false, usageError: null }),

  setUsageLoading: (v) => set({ usageLoading: v }),

  setUsageError: (e) => set({ usageError: e, usageLoading: false }),

  setUpgradeCTAs: (ctas) => set({ upgradeCTAs: ctas }),

  reset: () =>
    set({
      effectiveLimits: null,
      usage: null,
      usageLoading: false,
      usageError: null,
      upgradeCTAs: [],
    }),
}));

// ── Selectors (derived state) ─────────────────────────────────────────────────

/** Current user's plan tier, or FREE if no limits loaded yet */
export const selectCurrentTier = (s: PricingStore): PlanTier =>
  (s.effectiveLimits?.tier ?? 'FREE') as PlanTier;

/** Highest-priority blocking CTA, or null */
export const selectBlocker = (s: PricingStore): UpgradeCTA | null =>
  s.upgradeCTAs.find((c) => c.is_blocking) ?? null;

/** All non-blocking warning CTAs */
export const selectWarnings = (s: PricingStore): UpgradeCTA[] =>
  s.upgradeCTAs.filter((c) => !c.is_blocking);

/** True when any quota is ≥ 80% */
export const selectHasWarning = (s: PricingStore): boolean =>
  s.upgradeCTAs.length > 0;

/** True when any quota is exhausted */
export const selectIsBlocked = (s: PricingStore): boolean =>
  s.upgradeCTAs.some((c) => c.is_blocking);

/** Usage percentage for characters (0–1) */
export const selectCharUsagePct = (s: PricingStore): number => {
  if (!s.usage || s.usage.chars_limit <= 0) return 0;
  return Math.min(1, s.usage.chars_used / s.usage.chars_limit);
};
