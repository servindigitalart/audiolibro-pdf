/**
 * Upgrade Service (Client-side)
 * ==============================
 * Evaluates usage against tier limits and generates upgrade CTAs.
 * Mirrors the backend app/pricing/upgrade.py UpgradeEvaluator logic.
 *
 * This runs entirely client-side from the usage data returned by the
 * account overview API — no extra round-trip required.
 */

import type { PlanTier } from './pricing-service';
import { TIER_RANK } from './pricing-service';

// ── Types ─────────────────────────────────────────────────────────────────────

export type UpgradeTrigger =
  | 'QUOTA_CHARS_WARNING'
  | 'QUOTA_CHARS_EXHAUSTED'
  | 'QUOTA_JOBS_WARNING'
  | 'QUOTA_JOBS_EXHAUSTED'
  | 'QUOTA_STORAGE_WARNING'
  | 'QUOTA_STORAGE_EXHAUSTED'
  | 'DAILY_API_WARNING'
  | 'DAILY_API_EXHAUSTED'
  | 'FEATURE_GATE_HIT'
  | 'RATE_LIMIT_HIT';

export interface UsageSnapshot {
  tier: PlanTier;
  chars_used: number;
  chars_limit: number;
  jobs_created: number;
  jobs_limit: number;
  storage_mb: number;
  storage_limit_mb: number;
  daily_api_calls: number;
  daily_api_limit: number;   // -1 = unlimited
  /** Optional: feature key that was gate-blocked */
  blocked_feature?: string;
}

export interface UpgradeCTA {
  trigger: UpgradeTrigger;
  /** 0–100, higher = more urgent */
  priority: number;
  /** True = hard block; user CANNOT proceed without upgrading */
  is_blocking: boolean;
  heading: string;
  body: string;
  cta_label: string;
  target_tier: PlanTier;
}

// ── Thresholds (must match backend TierConfig defaults) ───────────────────────

const WARN_PCT  = 0.80;   // soft paywall threshold
const BLOCK_PCT = 1.00;   // hard paywall threshold

// ── Helpers ───────────────────────────────────────────────────────────────────

function pct(used: number, limit: number): number {
  if (limit <= 0 || limit === -1) return 0;
  return used / limit;
}

function nextTier(current: PlanTier): PlanTier | null {
  const map: Partial<Record<PlanTier, PlanTier>> = {
    FREE: 'BASIC',
    BASIC: 'PRO',
    PRO: 'ENTERPRISE',
  };
  return map[current] ?? null;
}

function tierName(tier: PlanTier): string {
  const names: Record<PlanTier, string> = {
    FREE: 'Free',
    BASIC: 'Basic',
    PRO: 'Pro',
    ENTERPRISE: 'Enterprise',
  };
  return names[tier];
}

// ── Evaluator ─────────────────────────────────────────────────────────────────

/**
 * Evaluate a usage snapshot and return all triggered upgrade CTAs,
 * sorted by priority descending.
 */
export function evaluateUpgrades(snap: UsageSnapshot): UpgradeCTA[] {
  const target = nextTier(snap.tier);
  if (!target) return [];   // already on top tier

  const ctas: UpgradeCTA[] = [];
  const targetName = tierName(target);

  // ── TTS character quota ───────────────────────────────────────────────────
  const charPct = pct(snap.chars_used, snap.chars_limit);
  if (charPct >= BLOCK_PCT) {
    ctas.push({
      trigger: 'QUOTA_CHARS_EXHAUSTED',
      priority: 100,
      is_blocking: true,
      heading: "You've used all your character quota",
      body: 'Upgrade to keep converting documents this month.',
      cta_label: `Upgrade to ${targetName}`,
      target_tier: target,
    });
  } else if (charPct >= WARN_PCT) {
    ctas.push({
      trigger: 'QUOTA_CHARS_WARNING',
      priority: 70,
      is_blocking: false,
      heading: `${Math.round(charPct * 100)}% of characters used`,
      body: `You're approaching your monthly limit. Upgrade to avoid interruptions.`,
      cta_label: 'Upgrade for more',
      target_tier: target,
    });
  }

  // ── Job quota ─────────────────────────────────────────────────────────────
  const jobPct = pct(snap.jobs_created, snap.jobs_limit);
  if (jobPct >= BLOCK_PCT) {
    ctas.push({
      trigger: 'QUOTA_JOBS_EXHAUSTED',
      priority: 90,
      is_blocking: true,
      heading: "Monthly job limit reached",
      body: 'You cannot create more conversions until your quota resets or you upgrade.',
      cta_label: `Upgrade to ${targetName}`,
      target_tier: target,
    });
  } else if (jobPct >= WARN_PCT) {
    ctas.push({
      trigger: 'QUOTA_JOBS_WARNING',
      priority: 65,
      is_blocking: false,
      heading: `${snap.jobs_created} of ${snap.jobs_limit} jobs used`,
      body: 'Running low on conversions. Upgrade for more capacity.',
      cta_label: 'Upgrade jobs quota',
      target_tier: target,
    });
  }

  // ── Storage ───────────────────────────────────────────────────────────────
  const storagePct = pct(snap.storage_mb, snap.storage_limit_mb);
  if (storagePct >= BLOCK_PCT) {
    ctas.push({
      trigger: 'QUOTA_STORAGE_EXHAUSTED',
      priority: 85,
      is_blocking: true,
      heading: 'Storage full',
      body: 'Delete old audiobooks or upgrade to continue saving files.',
      cta_label: 'Upgrade storage',
      target_tier: target,
    });
  } else if (storagePct >= WARN_PCT) {
    ctas.push({
      trigger: 'QUOTA_STORAGE_WARNING',
      priority: 55,
      is_blocking: false,
      heading: `${Math.round(storagePct * 100)}% storage used`,
      body: 'Storage is nearly full. Upgrade for more space.',
      cta_label: 'Upgrade storage',
      target_tier: target,
    });
  }

  // ── Daily API calls ───────────────────────────────────────────────────────
  const apiPct = pct(snap.daily_api_calls, snap.daily_api_limit);
  if (snap.daily_api_limit !== -1) {
    if (apiPct >= BLOCK_PCT) {
      ctas.push({
        trigger: 'DAILY_API_EXHAUSTED',
        priority: 80,
        is_blocking: true,
        heading: 'Daily API limit reached',
        body: 'Resets at midnight UTC. Upgrade for a higher daily limit.',
        cta_label: 'Upgrade API limit',
        target_tier: target,
      });
    } else if (apiPct >= WARN_PCT) {
      ctas.push({
        trigger: 'DAILY_API_WARNING',
        priority: 50,
        is_blocking: false,
        heading: `${Math.round(apiPct * 100)}% of daily API calls used`,
        body: 'You may hit your daily limit today. Upgrade for a higher ceiling.',
        cta_label: 'Upgrade API limit',
        target_tier: target,
      });
    }
  }

  // ── Feature gate ──────────────────────────────────────────────────────────
  if (snap.blocked_feature) {
    ctas.push({
      trigger: 'FEATURE_GATE_HIT',
      priority: 95,
      is_blocking: true,
      heading: `${snap.blocked_feature} requires ${targetName}`,
      body: `Unlock ${snap.blocked_feature} and more by upgrading your plan.`,
      cta_label: `Unlock with ${targetName}`,
      target_tier: target,
    });
  }

  return ctas.sort((a, b) => b.priority - a.priority);
}

/** Return the highest-priority blocking CTA, or null if none. */
export function getBlocker(snap: UsageSnapshot): UpgradeCTA | null {
  return evaluateUpgrades(snap).find((c) => c.is_blocking) ?? null;
}

/** Return the single highest-priority CTA regardless of blocking state. */
export function topCTA(snap: UsageSnapshot): UpgradeCTA | null {
  return evaluateUpgrades(snap)[0] ?? null;
}

/**
 * Compute a 0–1 urgency score for sorting nudges.
 *   0.9+ = hard block  |  0.6–0.9 = warning  |  < 0.6 = info
 */
export function urgencyScore(snap: UsageSnapshot): number {
  const cta = topCTA(snap);
  if (!cta) return 0;
  return cta.priority / 100;
}
