/**
 * Pricing Service Tests
 * =====================
 * Tests for the display helper utilities and tier metadata.
 * API calls tested via integration tests (not unit tests).
 */

import { describe, it, expect } from 'vitest';
import {
  fmtChars,
  fmtStorage,
  fmtApiCalls,
  fmtPrice,
  isUpgrade,
  TIER_RANK,
  TIER_META,
  annualDiscountPct,
  annualMonthlyRate,
  type TierConfig,
  type PlanTier,
} from '../lib/pricing-service';

// ── fmtChars ──────────────────────────────────────────────────────────────────

describe('fmtChars', () => {
  it('formats thousands', () => {
    expect(fmtChars(10_000)).toBe('10K');
    expect(fmtChars(100_000)).toBe('100K');
    expect(fmtChars(500_000)).toBe('500K');
  });

  it('formats millions', () => {
    expect(fmtChars(5_000_000)).toBe('5M');
    expect(fmtChars(1_000_000)).toBe('1M');
  });

  it('handles sub-thousand', () => {
    expect(fmtChars(999)).toBe('999');
    expect(fmtChars(0)).toBe('0');
  });
});

// ── fmtStorage ────────────────────────────────────────────────────────────────

describe('fmtStorage', () => {
  it('formats MB below 1000', () => {
    expect(fmtStorage(100)).toBe('100 MB');
    expect(fmtStorage(999)).toBe('999 MB');
  });

  it('formats GB at or above 1000 MB', () => {
    expect(fmtStorage(1_000)).toBe('1 GB');
    expect(fmtStorage(10_000)).toBe('10 GB');
    expect(fmtStorage(100_000)).toBe('100 GB');
  });
});

// ── fmtApiCalls ───────────────────────────────────────────────────────────────

describe('fmtApiCalls', () => {
  it('returns "Unlimited" for -1', () => {
    expect(fmtApiCalls(-1)).toBe('Unlimited');
  });

  it('formats thousands with /day suffix', () => {
    expect(fmtApiCalls(10_000)).toBe('10K/day');
    expect(fmtApiCalls(1_000)).toBe('1K/day');
  });

  it('formats sub-thousand with /day', () => {
    expect(fmtApiCalls(100)).toBe('100/day');
  });
});

// ── fmtPrice ─────────────────────────────────────────────────────────────────

describe('fmtPrice', () => {
  it('returns "Free" for 0', () => {
    expect(fmtPrice(0)).toBe('Free');
  });

  it('formats integer price without decimals', () => {
    expect(fmtPrice(9)).toBe('$9/mo');
    expect(fmtPrice(29)).toBe('$29/mo');
  });

  it('formats fractional price with decimals', () => {
    expect(fmtPrice(9.99)).toBe('$9.99/mo');
  });

  it('uses yr suffix for yearly', () => {
    expect(fmtPrice(99, 'yr')).toBe('$99/yr');
  });
});

// ── isUpgrade ─────────────────────────────────────────────────────────────────

describe('isUpgrade', () => {
  it('BASIC > FREE', () => expect(isUpgrade('FREE', 'BASIC')).toBe(true));
  it('PRO > BASIC', () => expect(isUpgrade('BASIC', 'PRO')).toBe(true));
  it('ENTERPRISE > PRO', () => expect(isUpgrade('PRO', 'ENTERPRISE')).toBe(true));
  it('FREE is not upgrade from FREE', () => expect(isUpgrade('FREE', 'FREE')).toBe(false));
  it('downgrade is not an upgrade', () => expect(isUpgrade('PRO', 'BASIC')).toBe(false));
});

// ── TIER_RANK ─────────────────────────────────────────────────────────────────

describe('TIER_RANK', () => {
  it('FREE < BASIC < PRO < ENTERPRISE', () => {
    expect(TIER_RANK.FREE).toBeLessThan(TIER_RANK.BASIC);
    expect(TIER_RANK.BASIC).toBeLessThan(TIER_RANK.PRO);
    expect(TIER_RANK.PRO).toBeLessThan(TIER_RANK.ENTERPRISE);
  });
});

// ── TIER_META ─────────────────────────────────────────────────────────────────

describe('TIER_META', () => {
  const tiers: PlanTier[] = ['FREE', 'BASIC', 'PRO', 'ENTERPRISE'];

  it('all tiers have name and tagline', () => {
    tiers.forEach((t) => {
      expect(TIER_META[t].name).toBeTruthy();
      expect(TIER_META[t].tagline).toBeTruthy();
    });
  });

  it('PRO is highlighted (most popular)', () => {
    expect(TIER_META.PRO.highlight).toBe(true);
  });

  it('only PRO has a badge', () => {
    tiers
      .filter((t) => t !== 'PRO')
      .forEach((t) => expect(TIER_META[t].badge).toBeUndefined());
    expect(TIER_META.PRO.badge).toBeTruthy();
  });
});

// ── Annual pricing helpers ────────────────────────────────────────────────────

function mockConfig(monthly: number, annual: number): TierConfig {
  return {
    tier: 'PRO',
    monthly_price_usd: monthly,
    annual_price_usd: annual,
    annual_savings_usd: monthly * 12 - annual,
    limits: {
      monthly_chars: 500_000,
      monthly_jobs: 200,
      concurrent_jobs: 5,
      storage_mb: 10_000,
      daily_api_calls: 10_000,
      api_calls_per_minute: 100,
    },
    features: [],
    max_team_members: 5,
    trial_days: 14,
    upgrades_to: 'ENTERPRISE',
  };
}

describe('annualMonthlyRate', () => {
  it('returns annual_price / 12', () => {
    const cfg = mockConfig(29, 278.40);
    expect(annualMonthlyRate(cfg)).toBeCloseTo(278.40 / 12, 2);
  });

  it('returns 0 for free tier', () => {
    const cfg = mockConfig(0, 0);
    expect(annualMonthlyRate(cfg)).toBe(0);
  });
});

describe('annualDiscountPct', () => {
  it('returns correct discount percentage', () => {
    const cfg = mockConfig(29, 278.40); // 29*12=348, save 69.6, ~20% off
    const disc = annualDiscountPct(cfg);
    expect(disc).toBeGreaterThan(15);
    expect(disc).toBeLessThanOrEqual(25);
  });

  it('returns 0 for free tier', () => {
    expect(annualDiscountPct(mockConfig(0, 0))).toBe(0);
  });
});
