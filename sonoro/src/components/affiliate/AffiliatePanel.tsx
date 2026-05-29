import { useState, useEffect } from 'react';
import { getAffiliateMe, getAffiliateDashboard } from '@/lib/api/client';
import { cn } from '@/lib/utils';

interface AffiliateProfile {
  id: string;
  name: string;
  slug: string;
  status: string;
  commission_rate_pct: number;
  created_at: string;
}

interface ConversionRow {
  id: string;
  plan_tier: string;
  amount_usd: number;
  commission_amount_usd: number;
  status: string;
  created_at: string;
}

interface DashboardData {
  affiliate: AffiliateProfile;
  stats: {
    clicks: number;
    signups: number;
    conversions_total: number;
    commission_pending_usd: number;
    commission_paid_usd: number;
    commission_total_usd: number;
  };
  recent_conversions: ConversionRow[];
}

function StatCard({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="rounded-xl border border-sonoro-border bg-sonoro-white p-5 shadow-soft">
      <p className="text-xs font-medium text-sonoro-muted uppercase tracking-wide">{label}</p>
      <p className="mt-1 text-2xl font-semibold text-sonoro-900">{value}</p>
      {sub && <p className="mt-0.5 text-xs text-sonoro-muted">{sub}</p>}
    </div>
  );
}

function StatusBadge({ status }: { status: string }) {
  const colors: Record<string, string> = {
    active:   'bg-green-100 text-green-700',
    pending:  'bg-yellow-100 text-yellow-700',
    paused:   'bg-gray-100 text-gray-600',
    approved: 'bg-blue-100 text-blue-700',
    paid:     'bg-green-100 text-green-700',
    reversed: 'bg-red-100 text-red-700',
  };
  return (
    <span className={cn('inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium', colors[status] ?? 'bg-gray-100 text-gray-600')}>
      {status}
    </span>
  );
}

function fmt(n: number) {
  return new Intl.NumberFormat('en-US', { maximumFractionDigits: 2 }).format(n);
}

function fmtUsd(n: number) {
  return `$${fmt(n)}`;
}

export default function AffiliatePanel() {
  const [data, setData] = useState<DashboardData | null>(null);
  const [notAffiliate, setNotAffiliate] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function load() {
      try {
        await getAffiliateMe();
        const dash = await getAffiliateDashboard();
        setData(dash as DashboardData);
      } catch (err: any) {
        if (err?.response?.status === 404) {
          setNotAffiliate(true);
        } else {
          setError('Failed to load affiliate data.');
        }
      } finally {
        setLoading(false);
      }
    }
    load();
  }, []);

  if (loading) {
    return (
      <div className="p-8 space-y-4">
        {[1,2,3].map(i => (
          <div key={i} className="h-24 rounded-xl bg-sonoro-surface animate-pulse" />
        ))}
      </div>
    );
  }

  if (notAffiliate) {
    return (
      <div className="flex flex-col items-center justify-center p-12 text-center">
        <div className="w-16 h-16 rounded-full bg-sonoro-surface flex items-center justify-center mb-4">
          <svg className="w-8 h-8 text-sonoro-muted" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0z" />
          </svg>
        </div>
        <h2 className="text-lg font-semibold text-sonoro-900 mb-2">You're not an affiliate yet</h2>
        <p className="text-sm text-sonoro-muted max-w-sm">
          Interested in earning commissions by referring new users to Sonoro? Reach out to us to join the affiliate program.
        </p>
        <a
          href="mailto:hello@sonoro.app?subject=Affiliate Program"
          className="mt-6 btn-accent px-6 py-2.5 rounded-full text-sm"
        >
          Apply to become an affiliate
        </a>
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="p-8">
        <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          {error ?? 'Something went wrong. Please refresh the page.'}
        </div>
      </div>
    );
  }

  const { affiliate, stats, recent_conversions } = data;
  const appUrl = typeof window !== 'undefined' ? window.location.origin : 'https://sonoro.app';
  const referralLink = `${appUrl}/?ref=${affiliate.slug}`;

  return (
    <div className="p-6 md:p-8 space-y-8 max-w-4xl">
      {/* Header */}
      <div>
        <div className="flex items-center gap-3 mb-1">
          <h1 className="text-xl font-semibold text-sonoro-900">Affiliate Dashboard</h1>
          <StatusBadge status={affiliate.status} />
        </div>
        <p className="text-sm text-sonoro-muted">
          Commission rate: <span className="font-medium text-sonoro-700">{affiliate.commission_rate_pct}%</span> per conversion
        </p>
      </div>

      {/* Referral link */}
      <div className="rounded-xl border border-sonoro-border bg-sonoro-surface p-5">
        <p className="text-xs font-medium text-sonoro-muted uppercase tracking-wide mb-2">Your referral link</p>
        <div className="flex gap-2">
          <input
            type="text"
            readOnly
            value={referralLink}
            className="input-base flex-1 text-sm font-mono bg-sonoro-white"
            onFocus={e => e.target.select()}
          />
          <button
            className="btn-accent px-4 py-2 rounded-lg text-sm shrink-0"
            onClick={() => {
              navigator.clipboard.writeText(referralLink);
            }}
          >
            Copy
          </button>
        </div>
        <p className="mt-2 text-xs text-sonoro-muted">
          Share this link to earn {affiliate.commission_rate_pct}% commission on every paid conversion.
        </p>
      </div>

      {/* Stats grid */}
      <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
        <StatCard label="Clicks" value={fmt(stats.clicks)} />
        <StatCard label="Signups" value={fmt(stats.signups)} sub={stats.clicks ? `${Math.round(stats.signups / stats.clicks * 100)}% click→signup` : undefined} />
        <StatCard label="Conversions" value={fmt(stats.conversions_total)} />
        <StatCard label="Commission pending" value={fmtUsd(stats.commission_pending_usd)} sub="awaiting payout" />
        <StatCard label="Commission paid" value={fmtUsd(stats.commission_paid_usd)} sub="total earned" />
        <StatCard label="Total commission" value={fmtUsd(stats.commission_total_usd)} />
      </div>

      {/* Payout info */}
      <div className="rounded-xl border border-sonoro-border bg-sonoro-white p-5">
        <h2 className="text-sm font-semibold text-sonoro-900 mb-2">Payout information</h2>
        <p className="text-sm text-sonoro-muted">
          Payouts are processed manually at the end of each month. Once your balance reaches $50, we'll reach out to arrange payment. If you have questions, email us at{' '}
          <a href="mailto:affiliates@sonoro.app" className="underline hover:text-sonoro-900">affiliates@sonoro.app</a>.
        </p>
      </div>

      {/* Recent conversions */}
      {recent_conversions.length > 0 && (
        <div>
          <h2 className="text-sm font-semibold text-sonoro-900 mb-3">Recent conversions</h2>
          <div className="rounded-xl border border-sonoro-border overflow-hidden">
            <table className="w-full text-sm">
              <thead className="bg-sonoro-surface border-b border-sonoro-border">
                <tr>
                  <th className="text-left px-4 py-3 text-xs font-medium text-sonoro-muted uppercase tracking-wide">Date</th>
                  <th className="text-left px-4 py-3 text-xs font-medium text-sonoro-muted uppercase tracking-wide">Plan</th>
                  <th className="text-right px-4 py-3 text-xs font-medium text-sonoro-muted uppercase tracking-wide">Amount</th>
                  <th className="text-right px-4 py-3 text-xs font-medium text-sonoro-muted uppercase tracking-wide">Commission</th>
                  <th className="text-right px-4 py-3 text-xs font-medium text-sonoro-muted uppercase tracking-wide">Status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-sonoro-border bg-sonoro-white">
                {recent_conversions.map(conv => (
                  <tr key={conv.id} className="hover:bg-sonoro-surface/50 transition-colors">
                    <td className="px-4 py-3 text-sonoro-muted">
                      {new Date(conv.created_at).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })}
                    </td>
                    <td className="px-4 py-3 font-medium text-sonoro-900">{conv.plan_tier}</td>
                    <td className="px-4 py-3 text-right text-sonoro-muted">{fmtUsd(conv.amount_usd)}</td>
                    <td className="px-4 py-3 text-right font-medium text-green-700">{fmtUsd(conv.commission_amount_usd)}</td>
                    <td className="px-4 py-3 text-right">
                      <StatusBadge status={conv.status} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
