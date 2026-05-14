/**
 * Upgrade Service Tests
 * =====================
 * Verifies that upgrade CTA evaluation correctly mirrors the backend
 * UpgradeEvaluator logic for all quota dimensions and thresholds.
 */

import { describe, it, expect } from 'vitest';
import {
  evaluateUpgrades,
  getBlocker,
  topCTA,
  urgencyScore,
  type UsageSnapshot,
} from '../lib/upgrade-service';

// ── Helpers ───────────────────────────────────────────────────────────────────

function snap(overrides: Partial<UsageSnapshot> = {}): UsageSnapshot {
  return {
    tier: 'FREE',
    chars_used: 0,
    chars_limit: 10_000,
    jobs_created: 0,
    jobs_limit: 5,
    storage_mb: 0,
    storage_limit_mb: 100,
    daily_api_calls: 0,
    daily_api_limit: 100,
    ...overrides,
  };
}

// ── No triggers ───────────────────────────────────────────────────────────────

describe('evaluateUpgrades — no triggers', () => {
  it('returns empty list when all quotas are fine', () => {
    expect(evaluateUpgrades(snap())).toHaveLength(0);
  });

  it('returns empty list for ENTERPRISE (top tier)', () => {
    expect(evaluateUpgrades(snap({ tier: 'ENTERPRISE' }))).toHaveLength(0);
  });

  it('returns empty list at 79% usage', () => {
    const s = snap({ chars_used: 7_900, chars_limit: 10_000 });
    const ctas = evaluateUpgrades(s);
    expect(ctas.filter((c) => c.trigger === 'QUOTA_CHARS_WARNING')).toHaveLength(0);
  });
});

// ── Character quota ───────────────────────────────────────────────────────────

describe('character quota triggers', () => {
  it('fires WARNING at 80%', () => {
    const ctas = evaluateUpgrades(snap({ chars_used: 8_000, chars_limit: 10_000 }));
    expect(ctas.find((c) => c.trigger === 'QUOTA_CHARS_WARNING')).toBeDefined();
  });

  it('WARNING is not blocking', () => {
    const ctas = evaluateUpgrades(snap({ chars_used: 8_500, chars_limit: 10_000 }));
    const warn = ctas.find((c) => c.trigger === 'QUOTA_CHARS_WARNING');
    expect(warn?.is_blocking).toBe(false);
  });

  it('fires EXHAUSTED at 100%', () => {
    const ctas = evaluateUpgrades(snap({ chars_used: 10_000, chars_limit: 10_000 }));
    expect(ctas.find((c) => c.trigger === 'QUOTA_CHARS_EXHAUSTED')).toBeDefined();
  });

  it('EXHAUSTED is blocking', () => {
    const ctas = evaluateUpgrades(snap({ chars_used: 10_000, chars_limit: 10_000 }));
    const ex = ctas.find((c) => c.trigger === 'QUOTA_CHARS_EXHAUSTED');
    expect(ex?.is_blocking).toBe(true);
  });

  it('EXHAUSTED has higher priority than WARNING', () => {
    const warn = evaluateUpgrades(snap({ chars_used: 8_500, chars_limit: 10_000 }))[0];
    const ex = evaluateUpgrades(snap({ chars_used: 10_000, chars_limit: 10_000 }))[0];
    expect(ex!.priority).toBeGreaterThan(warn!.priority);
  });

  it('target_tier points to BASIC for FREE user', () => {
    const ctas = evaluateUpgrades(snap({ chars_used: 10_000 }));
    expect(ctas[0].target_tier).toBe('BASIC');
  });
});

// ── Job quota ─────────────────────────────────────────────────────────────────

describe('job quota triggers', () => {
  it('fires WARNING at 80% jobs used', () => {
    const ctas = evaluateUpgrades(snap({ jobs_created: 4, jobs_limit: 5 }));
    expect(ctas.find((c) => c.trigger === 'QUOTA_JOBS_WARNING')).toBeDefined();
  });

  it('fires EXHAUSTED at 100% jobs used', () => {
    const ctas = evaluateUpgrades(snap({ jobs_created: 5, jobs_limit: 5 }));
    expect(ctas.find((c) => c.trigger === 'QUOTA_JOBS_EXHAUSTED')).toBeDefined();
  });
});

// ── Storage ───────────────────────────────────────────────────────────────────

describe('storage triggers', () => {
  it('fires WARNING at 80% storage', () => {
    const ctas = evaluateUpgrades(snap({ storage_mb: 80, storage_limit_mb: 100 }));
    expect(ctas.find((c) => c.trigger === 'QUOTA_STORAGE_WARNING')).toBeDefined();
  });

  it('fires EXHAUSTED at 100% storage', () => {
    const ctas = evaluateUpgrades(snap({ storage_mb: 100, storage_limit_mb: 100 }));
    expect(ctas.find((c) => c.trigger === 'QUOTA_STORAGE_EXHAUSTED')).toBeDefined();
  });
});

// ── API calls ─────────────────────────────────────────────────────────────────

describe('API call triggers', () => {
  it('fires WARNING at 80% daily API', () => {
    const ctas = evaluateUpgrades(snap({ daily_api_calls: 80, daily_api_limit: 100 }));
    expect(ctas.find((c) => c.trigger === 'DAILY_API_WARNING')).toBeDefined();
  });

  it('fires EXHAUSTED at 100% daily API', () => {
    const ctas = evaluateUpgrades(snap({ daily_api_calls: 100, daily_api_limit: 100 }));
    expect(ctas.find((c) => c.trigger === 'DAILY_API_EXHAUSTED')).toBeDefined();
  });

  it('does NOT fire when daily_api_limit is -1 (unlimited)', () => {
    const ctas = evaluateUpgrades(snap({ daily_api_calls: 99999, daily_api_limit: -1 }));
    const apiTriggers = ctas.filter((c) => c.trigger.startsWith('DAILY_API'));
    expect(apiTriggers).toHaveLength(0);
  });
});

// ── Feature gate ──────────────────────────────────────────────────────────────

describe('feature gate trigger', () => {
  it('fires FEATURE_GATE_HIT when blocked_feature is set', () => {
    const ctas = evaluateUpgrades(snap({ blocked_feature: 'Custom Voices' }));
    const gate = ctas.find((c) => c.trigger === 'FEATURE_GATE_HIT');
    expect(gate).toBeDefined();
    expect(gate?.is_blocking).toBe(true);
    expect(gate?.heading).toContain('Custom Voices');
  });

  it('FEATURE_GATE_HIT has priority 95', () => {
    const ctas = evaluateUpgrades(snap({ blocked_feature: 'Custom Voices' }));
    expect(ctas.find((c) => c.trigger === 'FEATURE_GATE_HIT')?.priority).toBe(95);
  });
});

// ── Sort order ────────────────────────────────────────────────────────────────

describe('sort order', () => {
  it('returns CTAs sorted by priority descending', () => {
    const ctas = evaluateUpgrades(snap({
      chars_used: 10_000,    // EXHAUSTED (100)
      jobs_created: 4,       // WARNING (65)
      storage_mb: 85,        // WARNING (55)
    }));
    for (let i = 1; i < ctas.length; i++) {
      expect(ctas[i - 1].priority).toBeGreaterThanOrEqual(ctas[i].priority);
    }
  });
});

// ── getBlocker ────────────────────────────────────────────────────────────────

describe('getBlocker', () => {
  it('returns null when nothing is blocking', () => {
    expect(getBlocker(snap({ chars_used: 5_000 }))).toBeNull();
  });

  it('returns first blocking CTA when quota exhausted', () => {
    const b = getBlocker(snap({ chars_used: 10_000 }));
    expect(b).not.toBeNull();
    expect(b!.is_blocking).toBe(true);
  });
});

// ── topCTA ────────────────────────────────────────────────────────────────────

describe('topCTA', () => {
  it('returns null when no triggers', () => {
    expect(topCTA(snap())).toBeNull();
  });

  it('returns the highest-priority CTA', () => {
    const top = topCTA(snap({ chars_used: 10_000, jobs_created: 4 }));
    expect(top?.trigger).toBe('QUOTA_CHARS_EXHAUSTED');
  });
});

// ── urgencyScore ──────────────────────────────────────────────────────────────

describe('urgencyScore', () => {
  it('returns 0 with no triggers', () => {
    expect(urgencyScore(snap())).toBe(0);
  });

  it('returns ≥ 0.9 when quota exhausted', () => {
    expect(urgencyScore(snap({ chars_used: 10_000 }))).toBeGreaterThanOrEqual(0.9);
  });

  it('returns < 0.9 for warnings', () => {
    expect(urgencyScore(snap({ chars_used: 8_500 }))).toBeLessThan(0.9);
  });
});
