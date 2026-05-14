import { useState } from 'react';
import { createCheckoutSession, createPortalSession, getErrorMessage } from '@/lib/api/client';
import { fmtChars } from '@/lib/utils';
import { cn } from '@/lib/utils';
import type { TierConfig, AccountOverview } from '@/lib/api/types';

interface Props {
  overview: AccountOverview;
  tiers: TierConfig[];
}

type Interval = 'monthly' | 'annual';

export default function BillingPanel({ overview, tiers }: Props) {
  const [interval, setInterval] = useState<Interval>('monthly');
  const [loading, setLoading]   = useState<string | null>(null);
  const [error, setError]       = useState<string | null>(null);

  const currentTier = overview.user.plan_tier;
  const TIER_RANK: Record<string, number> = { FREE: 0, BASIC: 1, PRO: 2, ENTERPRISE: 3 };

  async function handleUpgrade(tier: string) {
    setLoading(tier);
    setError(null);
    try {
      const { url } = await createCheckoutSession(tier, interval);
      window.location.href = url;
    } catch (err) {
      setError(getErrorMessage(err));
      setLoading(null);
    }
  }

  async function handlePortal() {
    setLoading('portal');
    setError(null);
    try {
      const { url } = await createPortalSession();
      window.location.href = url;
    } catch (err) {
      setError(getErrorMessage(err));
      setLoading(null);
    }
  }

  const { chars_used, chars_limit, jobs_created, jobs_limit, storage_mb, storage_limit_mb } = overview.usage;
  const charPct    = chars_limit > 0 ? Math.min(100, (chars_used / chars_limit) * 100) : 0;
  const jobPct     = jobs_limit  > 0 ? Math.min(100, (jobs_created / jobs_limit) * 100) : 0;
  const storagePct = storage_limit_mb > 0 ? Math.min(100, (storage_mb / storage_limit_mb) * 100) : 0;

  function barColor(pct: number) {
    return pct >= 100 ? 'bg-red-500' : pct >= 80 ? 'bg-amber-500' : 'bg-green-500';
  }

  return (
    <div className="space-y-6">
      {error && (
        <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700" role="alert">
          {error}
        </div>
      )}

      {/* Current plan summary */}
      <div className="card-base p-6">
        <div className="flex items-start justify-between gap-4 mb-5">
          <div>
            <p className="label-sm mb-1">Current plan</p>
            <p className="text-2xl font-bold text-sonoro-900">{currentTier}</p>
            {overview.billing.current_period_end && (
              <p className="text-xs text-sonoro-muted mt-1">
                Renews {new Date(overview.billing.current_period_end).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })}
              </p>
            )}
          </div>
          {currentTier !== 'FREE' && (
            <button
              onClick={handlePortal}
              disabled={loading === 'portal'}
              className="btn-outline btn-sm shrink-0 disabled:opacity-50"
            >
              {loading === 'portal' ? 'Loading…' : 'Manage billing'}
            </button>
          )}
        </div>

        {/* Usage bars */}
        <div className="space-y-4">
          {[
            { label: 'Characters', used: chars_used, limit: chars_limit, pct: charPct, fmt: (n: number) => fmtChars(n) },
            { label: 'Conversions', used: jobs_created, limit: jobs_limit, pct: jobPct, fmt: (n: number) => String(n) },
            { label: 'Storage', used: storage_mb, limit: storage_limit_mb, pct: storagePct, fmt: (n: number) => `${n} MB` },
          ].map(({ label, used, limit, pct, fmt }) => (
            <div key={label}>
              <div className="flex justify-between mb-1.5">
                <span className="text-xs text-sonoro-700 font-medium">{label}</span>
                <span className="text-xs text-sonoro-muted">{fmt(used)} / {limit < 0 ? '∞' : fmt(limit)}</span>
              </div>
              <div className="h-1.5 w-full rounded-full bg-sonoro-border overflow-hidden">
                <div
                  className={cn('h-full rounded-full transition-all duration-500', barColor(pct))}
                  style={{ width: `${Math.min(pct, 100)}%` }}
                />
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Upgrade plans */}
      {currentTier !== 'ENTERPRISE' && (
        <div>
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-base font-semibold text-sonoro-900">Available plans</h2>
            {/* Billing interval toggle */}
            <div className="flex items-center gap-1 rounded-full border border-sonoro-border bg-sonoro-surface p-1">
              {(['monthly', 'annual'] as Interval[]).map((i) => (
                <button
                  key={i}
                  onClick={() => setInterval(i)}
                  className={cn(
                    'rounded-full px-3 py-1 text-xs font-medium transition-all',
                    interval === i
                      ? 'bg-sonoro-black text-sonoro-white'
                      : 'text-sonoro-600 hover:text-sonoro-900'
                  )}
                >
                  {i === 'monthly' ? 'Monthly' : 'Annual (save 20%)'}
                </button>
              ))}
            </div>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
            {tiers.map((tier) => {
              const isCurrent   = tier.tier === currentTier;
              const isHigher    = TIER_RANK[tier.tier] > TIER_RANK[currentTier];
              const isHighlight = tier.tier === 'PRO';
              const price       = interval === 'annual'
                ? tier.annual_price_usd / 12
                : tier.monthly_price_usd;

              return (
                <div
                  key={tier.tier}
                  className={cn(
                    'relative rounded-2xl p-5 border flex flex-col',
                    isHighlight && !isCurrent
                      ? 'border-sonoro-amber bg-sonoro-amber-light'
                      : isCurrent
                      ? 'border-green-300 bg-green-50'
                      : 'border-sonoro-border bg-sonoro-white'
                  )}
                >
                  {isHighlight && !isCurrent && (
                    <span className="absolute -top-2.5 left-1/2 -translate-x-1/2 badge-pro text-[10px] px-2.5 py-0.5">
                      Most popular
                    </span>
                  )}
                  {isCurrent && (
                    <span className="absolute -top-2.5 left-1/2 -translate-x-1/2 badge badge-success text-[10px] px-2.5 py-0.5">
                      Current plan
                    </span>
                  )}

                  <p className="text-xs font-bold text-sonoro-900 mb-1">{tier.tier}</p>
                  <p className="text-2xl font-bold text-sonoro-900 tracking-tight">
                    {price === 0 ? 'Free' : `$${price % 1 === 0 ? price.toFixed(0) : price.toFixed(2)}`}
                    {price > 0 && <span className="text-xs font-normal text-sonoro-muted">/mo</span>}
                  </p>

                  <ul className="mt-3 mb-5 flex-1 space-y-1.5">
                    {[
                      fmtChars(tier.limits.monthly_chars) + ' chars',
                      (tier.limits.monthly_jobs < 0 ? 'Unlimited' : tier.limits.monthly_jobs) + ' jobs',
                      ...tier.features.slice(0, 2),
                    ].map((f) => (
                      <li key={f} className="flex items-center gap-1.5 text-xs text-sonoro-600">
                        <svg className="w-3 h-3 text-green-500 shrink-0" viewBox="0 0 12 12" fill="currentColor" aria-hidden="true">
                          <path d="M10 3L5 8.5 2 5.5" stroke="white" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" fill="none"/>
                          <circle cx="6" cy="6" r="6" fill="currentColor" opacity=".15"/>
                          <path d="M9 3.5L5 8 3 6" stroke="#16a34a" strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round" fill="none"/>
                        </svg>
                        {f}
                      </li>
                    ))}
                  </ul>

                  {isCurrent ? (
                    <div className="rounded-full bg-green-100 border border-green-200 py-2 text-center text-xs font-semibold text-green-700">
                      Active
                    </div>
                  ) : isHigher ? (
                    <button
                      onClick={() => handleUpgrade(tier.tier)}
                      disabled={!!loading}
                      className={cn(
                        'w-full rounded-full py-2 text-xs font-semibold transition-all active:scale-[0.98]',
                        isHighlight
                          ? 'bg-sonoro-amber text-sonoro-black hover:bg-sonoro-amber-dark'
                          : 'bg-sonoro-black text-sonoro-white hover:bg-sonoro-800',
                        loading === tier.tier && 'opacity-50 cursor-not-allowed'
                      )}
                    >
                      {loading === tier.tier ? 'Loading…' : `Upgrade to ${tier.tier}`}
                    </button>
                  ) : (
                    <div className="rounded-full bg-sonoro-surface border border-sonoro-border py-2 text-center text-xs text-sonoro-muted">
                      Downgrade
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
