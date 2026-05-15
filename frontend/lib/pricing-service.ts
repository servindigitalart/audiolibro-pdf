/**
 * Pricing Service
 * ===============
 * Fetches tier configuration from the backend pricing engine.
 * This is the single source of truth for plan limits, prices, and features.
 *
 * Replaces hardcoded plan data in billing-service.ts.
 * All limit values come from /api/v1/pricing/tiers — aligned with backend TIER_CATALOG.
 */

import { apiClient } from './api-client';

export type PlanTier = 'FREE' | 'BASIC' | 'PRO' | 'ENTERPRISE';

export interface TierLimits {
  monthly_chars: number;       // TTS characters per month
  monthly_jobs: number;        // Conversion jobs per month
  concurrent_jobs: number;     // Jobs running simultaneously
  storage_mb: number;          // Persistent storage cap
  daily_api_calls: number;     // -1 = unlimited
  api_calls_per_minute: number;
}

export interface TierConfig {
  tier: PlanTier;
  monthly_price_usd: number;
  annual_price_usd: number;
  annual_savings_usd: number;
  limits: TierLimits;
  features: string[];          // Feature key strings from backend TierFeature enum
  max_team_members: number;
  trial_days: number;
  upgrades_to: PlanTier | null;
  stripe_price_ids?: {
    monthly: string;
    annual: string;
  };
}

export interface EffectiveLimits {
  user_id: string;
  tier: PlanTier;
  limits: Pick<TierLimits, 'monthly_chars' | 'monthly_jobs' | 'storage_mb' | 'daily_api_calls'>;
  experiment_active: boolean;
  experiment_changes: Record<string, { base: number; effective: number }>;
}

// ── API calls ─────────────────────────────────────────────────────────────────

export async function fetchTierCatalog(): Promise<TierConfig[]> {
  const res = await apiClient.get<{ tiers: TierConfig[] }>('/pricing/tiers');
  return res.data.tiers;
}

export async function fetchTierDetail(tier: PlanTier): Promise<TierConfig> {
  const res = await apiClient.get<TierConfig>(`/pricing/tiers/${tier.toLowerCase()}`);
  return res.data;
}

export async function fetchEffectiveLimits(userId: string): Promise<EffectiveLimits> {
  const res = await apiClient.get<EffectiveLimits>(`/pricing/limits/${userId}`);
  return res.data;
}

// ── Display helpers ───────────────────────────────────────────────────────────

/** Human-readable names for backend feature key strings */
export const FEATURE_DISPLAY: Record<string, string> = {
  document_upload:      'Document Upload',
  tts_processing:       'Text-to-Speech Processing',
  priority_processing:  'Priority Processing',
  custom_voices:        'Custom Voices',
  api_access:           'API Access',
  team_members:         'Team Members',
  advanced_analytics:   'Advanced Analytics',
  sla_support:          'SLA Support',
  custom_integration:   'Custom Integrations',
  webhook_callbacks:    'Webhooks',
};

/** Visual metadata per tier — not returned by the API */
export const TIER_META: Record<PlanTier, {
  name: string;
  tagline: string;
  badge?: string;
  highlight: boolean;
  gradient: string;
}> = {
  FREE: {
    name: 'Free',
    tagline: 'Perfect for exploring',
    highlight: false,
    gradient: 'from-slate-500 to-slate-600',
  },
  BASIC: {
    name: 'Basic',
    tagline: 'For regular creators',
    highlight: false,
    gradient: 'from-blue-500 to-blue-600',
  },
  PRO: {
    name: 'Pro',
    tagline: 'For power users',
    badge: 'Most Popular',
    highlight: true,
    gradient: 'from-violet-500 to-purple-600',
  },
  ENTERPRISE: {
    name: 'Enterprise',
    tagline: 'For teams and businesses',
    highlight: false,
    gradient: 'from-amber-500 to-orange-600',
  },
};

/** Tier rank — higher is more expensive */
export const TIER_RANK: Record<PlanTier, number> = {
  FREE: 0,
  BASIC: 1,
  PRO: 2,
  ENTERPRISE: 3,
};

/** Returns true if `next` is an upgrade from `current` */
export function isUpgrade(current: PlanTier, next: PlanTier): boolean {
  return TIER_RANK[next] > TIER_RANK[current];
}

/** Format character count for display: 10000 → "10K", 500000 → "500K", 5000000 → "5M" */
export function fmtChars(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(n % 1_000_000 === 0 ? 0 : 1)}M`;
  if (n >= 1_000) return `${Math.round(n / 1_000)}K`;
  return n.toLocaleString();
}

/** Format storage in MB/GB */
export function fmtStorage(mb: number): string {
  if (mb >= 1_000) return `${Math.round(mb / 1_000)} GB`;
  return `${mb} MB`;
}

/** Format API calls per day */
export function fmtApiCalls(n: number): string {
  if (n === -1) return 'Unlimited';
  if (n >= 1_000) return `${Math.round(n / 1_000)}K/day`;
  return `${n}/day`;
}

/** Format price: 0 → 'Free', 9 → '$9/mo' */
export function fmtPrice(usd: number, period: 'mo' | 'yr' = 'mo'): string {
  if (usd === 0) return 'Free';
  return `$${usd.toFixed(usd % 1 === 0 ? 0 : 2)}/${period}`;
}

/** Annual price divided by 12 (effective monthly rate on annual plan) */
export function annualMonthlyRate(cfg: TierConfig): number {
  if (cfg.annual_price_usd === 0) return 0;
  return cfg.annual_price_usd / 12;
}

/** Annual discount percentage */
export function annualDiscountPct(cfg: TierConfig): number {
  if (cfg.monthly_price_usd === 0) return 0;
  const monthlyTotal = cfg.monthly_price_usd * 12;
  return Math.round((1 - cfg.annual_price_usd / monthlyTotal) * 100);
}
