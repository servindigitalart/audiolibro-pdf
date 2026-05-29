/**
 * Admin Intelligence Dashboard
 * =============================
 * Founder/operator command center. Dark-themed, single-page scrollable.
 * All data fetched in parallel via Promise.allSettled — partial failures
 * degrade gracefully (section shows "No data" instead of crashing).
 */

import { useState, useEffect, useRef, useCallback } from 'react';
import type {
  DashboardKPIs,
  GrowthData,
  ActivityFeed,
  AnalyticsOverview,
  CostOverview,
  PlanEconomics,
  ExpensiveJob,
  VoiceEngagement,
  RuntimeInfo,
  ActivityEvent,
  AffiliateSummary,
} from '@/lib/api/admin';
import { adminApi } from '@/lib/api/admin';

// ── Utility ───────────────────────────────────────────────────────────────────

function fmt(n: number | undefined | null, decimals = 0): string {
  if (n == null) return '—';
  return n.toLocaleString('en-US', { maximumFractionDigits: decimals });
}

function fmtUsd(n: number | undefined | null, decimals = 0): string {
  if (n == null) return '—';
  return '$' + n.toLocaleString('en-US', { minimumFractionDigits: decimals, maximumFractionDigits: decimals });
}

function fmtPct(n: number | undefined | null): string {
  if (n == null) return '—';
  return n.toFixed(1) + '%';
}

function relTime(iso: string | null): string {
  if (!iso) return '—';
  const diff = (Date.now() - new Date(iso).getTime()) / 1000;
  if (diff < 60) return 'just now';
  if (diff < 3600) return `${Math.round(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.round(diff / 3600)}h ago`;
  return `${Math.round(diff / 86400)}d ago`;
}

// ── Primitives ────────────────────────────────────────────────────────────────

interface KPICardProps {
  title: string;
  value: string;
  sub?: string;
  color?: string;
  loading?: boolean;
}

function KPICard({ title, value, sub, color = 'text-white', loading }: KPICardProps) {
  return (
    <div className="bg-gray-800/60 border border-gray-700/40 rounded-xl p-4 flex flex-col gap-1">
      <p className="text-xs text-gray-400 font-medium tracking-wide uppercase">{title}</p>
      {loading ? (
        <div className="h-7 w-24 bg-gray-700/60 rounded animate-pulse mt-1" />
      ) : (
        <p className={`text-2xl font-bold tabular-nums leading-none ${color}`}>{value}</p>
      )}
      {sub && !loading && <p className="text-xs text-gray-500 mt-0.5">{sub}</p>}
    </div>
  );
}

interface MiniBarProps {
  label: string;
  value: number | string;
  pct: number;
  color?: string;
}

function MiniBar({ label, value, pct, color = 'bg-amber-500' }: MiniBarProps) {
  return (
    <div className="flex items-center gap-3">
      <span className="w-28 shrink-0 text-xs text-gray-400 truncate">{label}</span>
      <div className="flex-1 h-2 bg-gray-700/60 rounded-full overflow-hidden">
        <div className={`h-full rounded-full ${color}`} style={{ width: `${Math.min(pct, 100)}%` }} />
      </div>
      <span className="w-14 text-right text-xs text-gray-300 tabular-nums">{value}</span>
    </div>
  );
}

interface FunnelStep {
  label: string;
  value: number;
  color: string;
}

function FunnelBars({ steps }: { steps: FunnelStep[] }) {
  const max = steps[0]?.value || 1;
  return (
    <div className="space-y-3">
      {steps.map((step, i) => (
        <div key={i}>
          <div className="flex justify-between mb-1">
            <span className="text-xs text-gray-400">{step.label}</span>
            <span className="text-xs font-semibold text-gray-200 tabular-nums">{fmt(step.value)}</span>
          </div>
          <div className="h-6 bg-gray-700/40 rounded overflow-hidden">
            <div
              className={`h-full rounded ${step.color} transition-all duration-700`}
              style={{ width: `${(step.value / max) * 100}%` }}
            />
          </div>
        </div>
      ))}
    </div>
  );
}

function DonutChart({ segments }: { segments: Array<{ color: string; value: number; label: string }> }) {
  const total = segments.reduce((s, x) => s + x.value, 0) || 1;
  const r = 38;
  const circ = 2 * Math.PI * r;
  let offset = 0;
  const arcs = segments.map((seg) => {
    const dash = (seg.value / total) * circ;
    const arc = { ...seg, dash, offset };
    offset += dash;
    return arc;
  });

  return (
    <div className="flex items-center gap-6">
      <svg width="96" height="96" viewBox="0 0 96 96" className="shrink-0">
        <circle cx="48" cy="48" r={r} fill="none" stroke="#374151" strokeWidth="14" />
        {arcs.map((a, i) => (
          <circle
            key={i}
            cx="48" cy="48" r={r}
            fill="none"
            stroke={a.color}
            strokeWidth="14"
            strokeDasharray={`${a.dash} ${circ}`}
            strokeDashoffset={-a.offset}
            transform="rotate(-90 48 48)"
          />
        ))}
      </svg>
      <div className="space-y-1.5 min-w-0">
        {segments.map((seg, i) => (
          <div key={i} className="flex items-center gap-2">
            <span className="w-2.5 h-2.5 rounded-full shrink-0" style={{ background: seg.color }} />
            <span className="text-xs text-gray-400 truncate">{seg.label}</span>
            <span className="ml-auto text-xs font-medium text-gray-200 tabular-nums">
              {total > 1 ? fmtPct((seg.value / total) * 100) : '—'}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

function SectionBlock({ id, title, children }: { id: string; title: string; children: React.ReactNode }) {
  return (
    <section id={id} className="mb-12 scroll-mt-4">
      <h2 className="text-xs font-bold uppercase tracking-widest text-amber-400 mb-4">{title}</h2>
      {children}
    </section>
  );
}

function StatGrid({ children }: { children: React.ReactNode }) {
  return <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-3 mb-6">{children}</div>;
}

function Card({ children, className = '' }: { children: React.ReactNode; className?: string }) {
  return (
    <div className={`bg-gray-800/60 border border-gray-700/40 rounded-xl p-5 ${className}`}>
      {children}
    </div>
  );
}

function CardTitle({ children }: { children: React.ReactNode }) {
  return <p className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-4">{children}</p>;
}

function Skeleton({ h = 'h-4', w = 'w-full' }: { h?: string; w?: string }) {
  return <div className={`${h} ${w} bg-gray-700/60 rounded animate-pulse`} />;
}

// ── Data hook ─────────────────────────────────────────────────────────────────

interface AdminData {
  kpis: DashboardKPIs | null;
  growth: GrowthData | null;
  activity: ActivityFeed | null;
  analytics: AnalyticsOverview | null;
  costs: CostOverview | null;
  economics: PlanEconomics | null;
  expensive: ExpensiveJob[] | null;
  voice: VoiceEngagement | null;
  runtime: RuntimeInfo | null;
  affiliate: AffiliateSummary | null;
  loading: boolean;
  error: string | null;
  refreshedAt: Date | null;
}

function useAdminData(): AdminData & { refresh: () => void } {
  const [state, setState] = useState<AdminData>({
    kpis: null, growth: null, activity: null, analytics: null,
    costs: null, economics: null, expensive: null, voice: null,
    runtime: null, affiliate: null, loading: true, error: null, refreshedAt: null,
  });

  const load = useCallback(async () => {
    setState((s) => ({ ...s, loading: true, error: null }));
    try {
      const [k, g, act, an, c, ec, ex, v, rt, aff] = await Promise.allSettled([
        adminApi.getKpis(),
        adminApi.getGrowth(30),
        adminApi.getActivity(50),
        adminApi.getAnalyticsOverview(30),
        adminApi.getCostOverview(30),
        adminApi.getPlanEconomics(),
        adminApi.getExpensiveJobs(20, 30),
        adminApi.getVoiceEngagement(30),
        adminApi.getRuntime(),
        adminApi.getAffiliateSummary(),
      ]);

      setState({
        kpis:      k.status   === 'fulfilled' ? k.value   : null,
        growth:    g.status   === 'fulfilled' ? g.value   : null,
        activity:  act.status === 'fulfilled' ? act.value : null,
        analytics: an.status  === 'fulfilled' ? an.value  : null,
        costs:     c.status   === 'fulfilled' ? c.value   : null,
        economics: ec.status  === 'fulfilled' ? ec.value  : null,
        expensive: ex.status  === 'fulfilled' ? (ex.value as any)?.jobs ?? [] : null,
        voice:     v.status   === 'fulfilled' ? v.value   : null,
        runtime:   rt.status  === 'fulfilled' ? rt.value  : null,
        affiliate: aff.status === 'fulfilled' ? aff.value : null,
        loading: false,
        error: null,
        refreshedAt: new Date(),
      });
    } catch (e) {
      setState((s) => ({ ...s, loading: false, error: 'Failed to load dashboard data' }));
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  return { ...state, refresh: load };
}

// ── Section: Executive Overview ───────────────────────────────────────────────

function ExecutiveSection({ kpis, loading }: { kpis: DashboardKPIs | null; loading: boolean }) {
  return (
    <SectionBlock id="overview" title="Executive Overview">
      <StatGrid>
        <KPICard title="Total Users"     value={fmt(kpis?.users.total)}       loading={loading} />
        <KPICard title="Active (7d)"     value={fmt(kpis?.users.active_7d)}   loading={loading} color="text-emerald-400" />
        <KPICard title="Active (30d)"    value={fmt(kpis?.users.active_30d)}  loading={loading} color="text-emerald-400" />
        <KPICard title="Paid Users"      value={fmt(kpis?.users.paid)}        loading={loading} color="text-amber-400" />
        <KPICard title="MRR"             value={fmtUsd(kpis?.revenue.mrr_usd)} loading={loading} color="text-amber-400" />
        <KPICard title="ARR Projection"  value={fmtUsd(kpis?.revenue.arr_projected_usd)} loading={loading} color="text-amber-400" />
        <KPICard title="Est. Monthly Cost" value={fmtUsd(kpis?.costs.monthly_estimated_usd, 2)} loading={loading} color="text-red-400" />
        <KPICard title="Gross Margin"    value={fmtPct(kpis?.costs.estimated_gross_margin_pct)} loading={loading}
          color={(kpis?.costs.estimated_gross_margin_pct ?? 0) >= 60 ? 'text-emerald-400' : 'text-amber-400'} />
        <KPICard title="Audiobooks"      value={fmt(kpis?.content.audiobooks_generated)} loading={loading} />
        <KPICard title="Listening Hours" value={fmt(kpis?.content.listening_hours_total, 1)} loading={loading} />
        <KPICard title="Avg Completion"  value={fmtPct(kpis?.content.avg_completion_pct)} loading={loading} />
        <KPICard title="Upgrade Conv. Rate" value={fmtPct(kpis?.conversion.upgrade_conversion_rate_pct)} loading={loading}
          color="text-blue-400" />
      </StatGrid>
    </SectionBlock>
  );
}

// ── Section: Revenue & Billing ────────────────────────────────────────────────

const PLAN_COLORS: Record<string, string> = {
  FREE: '#6b7280',
  BASIC: '#3b82f6',
  PRO: '#f59e0b',
  ENTERPRISE: '#10b981',
};
const PLAN_PRICES: Record<string, number> = { FREE: 0, BASIC: 9, PRO: 29, ENTERPRISE: 99 };

function RevenueSection({ kpis, loading }: { kpis: DashboardKPIs | null; loading: boolean }) {
  const planSegments = Object.entries(kpis?.users.by_plan ?? {}).map(([tier, count]) => ({
    label: `${tier} (${count})`,
    value: count,
    color: PLAN_COLORS[tier] ?? '#6b7280',
  }));

  const planBars = Object.entries(kpis?.users.by_plan ?? {}).map(([tier, count]) => {
    const total = kpis?.users.total || 1;
    return { label: tier, value: `${count} · ${fmtUsd(count * (PLAN_PRICES[tier] ?? 0))}/mo`, pct: (count / total) * 100, color: 'bg-amber-500/70' };
  });

  return (
    <SectionBlock id="revenue" title="Revenue & Billing">
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-6">
        <KPICard title="MRR"   value={fmtUsd(kpis?.revenue.mrr_usd)} loading={loading} color="text-amber-400" />
        <KPICard title="ARR"   value={fmtUsd(kpis?.revenue.arr_projected_usd)} loading={loading} color="text-amber-400" />
        <KPICard title="ARPU"  value={fmtUsd(kpis?.revenue.arpu_usd, 2)}  loading={loading} />
        <KPICard title="ARPPU" value={fmtUsd(kpis?.revenue.arppu_usd, 2)} loading={loading} color="text-emerald-400" />
      </div>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <Card>
          <CardTitle>Plan Distribution</CardTitle>
          {loading ? <Skeleton h="h-24" /> : <DonutChart segments={planSegments} />}
        </Card>
        <Card>
          <CardTitle>Users by Plan</CardTitle>
          {loading ? (
            <div className="space-y-3"><Skeleton /><Skeleton /><Skeleton /></div>
          ) : (
            <div className="space-y-3">
              {planBars.map((b, i) => <MiniBar key={i} {...b} />)}
            </div>
          )}
        </Card>
      </div>
    </SectionBlock>
  );
}

// ── Section: Unit Economics ───────────────────────────────────────────────────

function CostsSection({
  kpis, economics, expensive, loading
}: { kpis: DashboardKPIs | null; economics: PlanEconomics | null; expensive: ExpensiveJob[] | null; loading: boolean }) {
  const observed = economics?.observed ?? [];
  const maxCost = Math.max(...observed.map((r) => r.total_cost_usd), 0.01);

  return (
    <SectionBlock id="economics" title="Unit Economics">
      <div className="grid grid-cols-2 sm:grid-cols-3 gap-3 mb-6">
        <KPICard title="Est. Monthly Cost" value={fmtUsd(kpis?.costs.monthly_estimated_usd, 2)} loading={loading} color="text-red-400" />
        <KPICard title="Gross Margin" value={fmtPct(kpis?.costs.estimated_gross_margin_pct)} loading={loading}
          color={(kpis?.costs.estimated_gross_margin_pct ?? 0) >= 60 ? 'text-emerald-400' : 'text-amber-400'} />
        <KPICard title="MRR" value={fmtUsd(kpis?.revenue.mrr_usd)} loading={loading} color="text-amber-400" />
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-6">
        <Card>
          <CardTitle>Observed Cost by Plan (30d)</CardTitle>
          {loading ? (
            <div className="space-y-3"><Skeleton /><Skeleton /><Skeleton /></div>
          ) : observed.length === 0 ? (
            <p className="text-xs text-gray-500">No cost telemetry yet</p>
          ) : (
            <div className="space-y-3">
              {observed.map((r, i) => (
                <MiniBar
                  key={i}
                  label={r.plan_tier}
                  value={`${fmtUsd(r.total_cost_usd, 3)} (${r.job_count} jobs)`}
                  pct={(r.total_cost_usd / maxCost) * 100}
                  color="bg-red-500/60"
                />
              ))}
            </div>
          )}
        </Card>

        <Card>
          <CardTitle>Margin by Plan (theoretical)</CardTitle>
          {loading ? (
            <div className="space-y-3"><Skeleton /><Skeleton /><Skeleton /></div>
          ) : !economics?.theoretical?.length ? (
            <p className="text-xs text-gray-500">No economics data</p>
          ) : (
            <div className="space-y-3">
              {economics.theoretical.map((r, i) => (
                <MiniBar
                  key={i}
                  label={r.plan_tier}
                  value={fmtPct(r.theoretical_margin_pct)}
                  pct={Math.max(0, r.theoretical_margin_pct)}
                  color="bg-emerald-500/60"
                />
              ))}
            </div>
          )}
        </Card>
      </div>

      {/* Top 20 costliest jobs */}
      <Card>
        <CardTitle>Top Costliest Audiobooks (30d)</CardTitle>
        {loading ? (
          <div className="space-y-2">{[...Array(5)].map((_, i) => <Skeleton key={i} />)}</div>
        ) : !expensive?.length ? (
          <p className="text-xs text-gray-500">No cost data yet</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="text-gray-500 border-b border-gray-700/40">
                  <th className="text-left py-2 pr-4 font-medium">Job ID</th>
                  <th className="text-left py-2 pr-4 font-medium">Plan</th>
                  <th className="text-left py-2 pr-4 font-medium">Chars</th>
                  <th className="text-right py-2 font-medium">Cost</th>
                </tr>
              </thead>
              <tbody>
                {expensive.slice(0, 10).map((job, i) => (
                  <tr key={i} className="border-b border-gray-700/20 hover:bg-gray-700/20 transition-colors">
                    <td className="py-2 pr-4 font-mono text-gray-400">{job.job_id?.slice(0, 8)}…</td>
                    <td className="py-2 pr-4">
                      <span className="px-1.5 py-0.5 rounded text-[10px] font-semibold"
                        style={{ background: PLAN_COLORS[job.plan_tier] + '22', color: PLAN_COLORS[job.plan_tier] }}>
                        {job.plan_tier}
                      </span>
                    </td>
                    <td className="py-2 pr-4 text-gray-400 tabular-nums">{fmt(job.characters_processed)}</td>
                    <td className="py-2 text-right text-red-400 tabular-nums font-semibold">{fmtUsd(job.estimated_cost_usd, 4)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </SectionBlock>
  );
}

// ── Section: User Behavior ────────────────────────────────────────────────────

function BehaviorSection({ analytics, loading }: { analytics: AnalyticsOverview | null; loading: boolean }) {
  const c = analytics?.completion;
  const s = analytics?.sessions;

  const funnelSteps: FunnelStep[] = [
    { label: 'Sessions started', value: c?.total_sessions ?? 0, color: 'bg-blue-500/60' },
    { label: 'Engaged (>10%)',   value: Math.round((c?.engaged_rate_pct ?? 0) / 100 * (c?.total_sessions ?? 0)), color: 'bg-amber-500/60' },
    { label: 'Halfway (>50%)',   value: Math.round((c?.halfway_rate_pct ?? 0) / 100 * (c?.total_sessions ?? 0)), color: 'bg-orange-500/60' },
    { label: 'Completed (>90%)', value: Math.round((c?.completed_rate_pct ?? 0) / 100 * (c?.total_sessions ?? 0)), color: 'bg-emerald-500/60' },
  ];

  const topEvents = analytics?.top_events ?? [];
  const maxEvt = topEvents[0]?.count || 1;

  return (
    <SectionBlock id="behavior" title="User Behavior">
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-6">
        <KPICard title="Total Sessions"  value={fmt(c?.total_sessions)}       loading={loading} />
        <KPICard title="Avg Completion"  value={fmtPct(c?.avg_completion_pct)} loading={loading} color="text-amber-400" />
        <KPICard title="Avg Session"     value={`${fmt(s?.avg_duration_minutes, 1)}m`} loading={loading} />
        <KPICard title="Avg Speed"       value={`${(s?.avg_speed ?? 1).toFixed(2)}×`}  loading={loading} />
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <Card>
          <CardTitle>Completion Funnel</CardTitle>
          {loading ? (
            <div className="space-y-3"><Skeleton /><Skeleton /><Skeleton /><Skeleton /></div>
          ) : !c?.total_sessions ? (
            <p className="text-xs text-gray-500">No sessions yet</p>
          ) : (
            <FunnelBars steps={funnelSteps} />
          )}
        </Card>

        <Card>
          <CardTitle>Top Event Types (30d)</CardTitle>
          {loading ? (
            <div className="space-y-3"><Skeleton /><Skeleton /><Skeleton /></div>
          ) : !topEvents.length ? (
            <p className="text-xs text-gray-500">No events yet</p>
          ) : (
            <div className="space-y-3">
              {topEvents.slice(0, 8).map((e, i) => (
                <MiniBar key={i} label={e.event_type.replace(/_/g, ' ')} value={fmt(e.count)}
                  pct={(e.count / maxEvt) * 100} color="bg-blue-500/60" />
              ))}
            </div>
          )}
        </Card>
      </div>
    </SectionBlock>
  );
}

// ── Section: Retention ────────────────────────────────────────────────────────

function RetentionSection({ analytics, loading }: { analytics: AnalyticsOverview | null; loading: boolean }) {
  const r = analytics?.retention;

  return (
    <SectionBlock id="retention" title="Retention">
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-6">
        <KPICard title="Users with Sessions" value={fmt(r?.total_users_with_sessions)} loading={loading} />
        <KPICard title="Returning Users"     value={fmt(r?.returning_users)}           loading={loading} color="text-emerald-400" />
        <KPICard title="Retention Rate"      value={fmtPct(r?.retention_rate_pct)}    loading={loading} color="text-emerald-400" />
        <KPICard title="Avg Sessions/User"   value={fmt(r?.avg_sessions_per_user, 1)} loading={loading} />
      </div>
      <Card>
        <CardTitle>Continue Listening Resume Rate</CardTitle>
        {loading ? <Skeleton h="h-12" /> : (
          <div className="flex items-end gap-8">
            <div>
              <p className="text-3xl font-bold text-amber-400">
                {fmtPct(analytics?.sessions?.continue_listening_resume_rate_pct)}
              </p>
              <p className="text-xs text-gray-500 mt-1">of sessions resumed via Continue Listening</p>
            </div>
            <div className="flex-1 h-2 bg-gray-700/60 rounded-full overflow-hidden">
              <div
                className="h-full bg-amber-500 rounded-full"
                style={{ width: `${Math.min(analytics?.sessions?.continue_listening_resume_rate_pct ?? 0, 100)}%` }}
              />
            </div>
          </div>
        )}
      </Card>
    </SectionBlock>
  );
}

// ── Section: Conversion Intelligence ─────────────────────────────────────────

function ConversionSection({ kpis, analytics, loading }: {
  kpis: DashboardKPIs | null;
  analytics: AnalyticsOverview | null;
  loading: boolean;
}) {
  const uf = analytics?.upgrade_funnel;
  const conv = kpis?.conversion;

  const funnelSteps: FunnelStep[] = [
    { label: 'Paywall Views',    value: uf?.paywall_views ?? conv?.paywall_views_30d ?? 0,  color: 'bg-blue-500/60' },
    { label: 'Upgrade Clicks',   value: uf?.upgrade_clicks ?? conv?.upgrade_clicks_30d ?? 0, color: 'bg-amber-500/60' },
    { label: 'Conversions',      value: uf?.conversions ?? 0,                                color: 'bg-emerald-500/60' },
  ];

  return (
    <SectionBlock id="conversion" title="Conversion Intelligence">
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-6">
        <KPICard title="Paywall Views (30d)"   value={fmt(conv?.paywall_views_30d)}           loading={loading} />
        <KPICard title="Upgrade Clicks (30d)"  value={fmt(conv?.upgrade_clicks_30d)}          loading={loading} color="text-amber-400" />
        <KPICard title="Click Rate"            value={fmtPct(uf?.paywall_click_rate)}          loading={loading} color="text-amber-400" />
        <KPICard title="Click → Convert Rate"  value={fmtPct(uf?.click_convert_rate)}         loading={loading} color="text-emerald-400" />
      </div>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <Card>
          <CardTitle>Upgrade Funnel (30d)</CardTitle>
          {loading ? (
            <div className="space-y-3"><Skeleton /><Skeleton /><Skeleton /></div>
          ) : !funnelSteps[0]?.value ? (
            <p className="text-xs text-gray-500">No paywall events yet</p>
          ) : (
            <FunnelBars steps={funnelSteps} />
          )}
        </Card>
        <Card>
          <CardTitle>Quota Exceeded Events (30d)</CardTitle>
          {loading ? <Skeleton h="h-16" /> : (
            <div>
              <p className="text-3xl font-bold text-orange-400">{fmt(conv?.quota_exceeded_events_30d)}</p>
              <p className="text-xs text-gray-500 mt-1">
                Users hitting quota limits — primary upgrade trigger
              </p>
            </div>
          )}
        </Card>
      </div>
    </SectionBlock>
  );
}

// ── Section: Voice Intelligence ───────────────────────────────────────────────

function VoiceSection({ voice, loading }: { voice: VoiceEngagement | null; loading: boolean }) {
  const voices = voice?.voices ?? [];
  const maxCount = voices[0]?.preview_count || 1;

  return (
    <SectionBlock id="voice" title="Voice Intelligence">
      <Card>
        <CardTitle>Most Previewed Voices (30d)</CardTitle>
        {loading ? (
          <div className="space-y-3">{[...Array(5)].map((_, i) => <Skeleton key={i} />)}</div>
        ) : !voices.length ? (
          <p className="text-xs text-gray-500">No voice preview events yet</p>
        ) : (
          <div className="space-y-3">
            {voices.slice(0, 10).map((v, i) => (
              <MiniBar
                key={i}
                label={v.voice_id || `Voice ${i + 1}`}
                value={`${v.preview_count} previews`}
                pct={(v.preview_count / maxCount) * 100}
                color="bg-purple-500/60"
              />
            ))}
          </div>
        )}
      </Card>
    </SectionBlock>
  );
}

// ── Section: Abuse & Risk ─────────────────────────────────────────────────────

function AbuseSection({ expensive, kpis, loading }: {
  expensive: ExpensiveJob[] | null;
  kpis: DashboardKPIs | null;
  loading: boolean;
}) {
  const topCostUsers = (expensive ?? [])
    .reduce<Record<string, { total: number; jobs: number; plan: string }>>((acc, job) => {
      if (!job.user_id) return acc;
      const key = job.user_id.slice(0, 8);
      acc[key] = acc[key] ?? { total: 0, jobs: 0, plan: job.plan_tier };
      acc[key].total += job.estimated_cost_usd;
      acc[key].jobs++;
      return acc;
    }, {});

  const riskUsers = Object.entries(topCostUsers)
    .sort(([, a], [, b]) => b.total - a.total)
    .slice(0, 10);

  return (
    <SectionBlock id="abuse" title="Abuse & Risk">
      <div className="grid grid-cols-2 gap-3 mb-6">
        <KPICard title="Quota Exceeded (30d)"     value={fmt(kpis?.conversion.quota_exceeded_events_30d)} loading={loading} color="text-orange-400" />
        <KPICard title="High-Cost Jobs (30d)"     value={fmt(expensive?.length)} loading={loading} color="text-red-400" />
      </div>
      <Card>
        <CardTitle>High-Cost Users (by job spend, 30d)</CardTitle>
        {loading ? (
          <div className="space-y-2">{[...Array(5)].map((_, i) => <Skeleton key={i} />)}</div>
        ) : !riskUsers.length ? (
          <p className="text-xs text-gray-500">No cost data yet</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="text-gray-500 border-b border-gray-700/40">
                  <th className="text-left py-2 pr-4 font-medium">User (prefix)</th>
                  <th className="text-left py-2 pr-4 font-medium">Plan</th>
                  <th className="text-left py-2 pr-4 font-medium">Jobs</th>
                  <th className="text-right py-2 font-medium">Total Cost</th>
                </tr>
              </thead>
              <tbody>
                {riskUsers.map(([prefix, data], i) => (
                  <tr key={i} className="border-b border-gray-700/20 hover:bg-gray-700/20 transition-colors">
                    <td className="py-2 pr-4 font-mono text-gray-400">{prefix}…</td>
                    <td className="py-2 pr-4">
                      <span className="px-1.5 py-0.5 rounded text-[10px] font-semibold"
                        style={{ background: PLAN_COLORS[data.plan] + '22', color: PLAN_COLORS[data.plan] }}>
                        {data.plan}
                      </span>
                    </td>
                    <td className="py-2 pr-4 text-gray-400 tabular-nums">{data.jobs}</td>
                    <td className="py-2 text-right text-red-400 tabular-nums font-semibold">{fmtUsd(data.total, 4)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </SectionBlock>
  );
}

// ── Section: Activity Feed ────────────────────────────────────────────────────

const SEVERITY_STYLES: Record<string, string> = {
  success: 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20',
  warning: 'bg-orange-500/10 text-orange-400 border-orange-500/20',
  info:    'bg-blue-500/10  text-blue-400  border-blue-500/20',
  neutral: 'bg-gray-700/40  text-gray-400  border-gray-600/20',
};

const SEVERITY_DOT: Record<string, string> = {
  success: 'bg-emerald-400',
  warning: 'bg-orange-400',
  info:    'bg-blue-400',
  neutral: 'bg-gray-500',
};

function ActivityFeedSection({ activity, loading }: { activity: ActivityFeed | null; loading: boolean }) {
  const events = activity?.events ?? [];

  return (
    <SectionBlock id="activity" title="Real-Time Activity Feed">
      <Card>
        <div className="flex items-center justify-between mb-4">
          <CardTitle>Recent Events</CardTitle>
          {activity && (
            <span className="text-xs text-gray-500">{activity.total} events</span>
          )}
        </div>
        {loading ? (
          <div className="space-y-3">{[...Array(8)].map((_, i) => <Skeleton key={i} h="h-10" />)}</div>
        ) : !events.length ? (
          <p className="text-xs text-gray-500">No events yet</p>
        ) : (
          <div className="space-y-2 max-h-[520px] overflow-y-auto pr-1">
            {events.map((ev, i) => (
              <div key={i} className={`flex items-start gap-3 px-3 py-2.5 rounded-lg border text-xs ${SEVERITY_STYLES[ev.severity]}`}>
                <span className={`mt-1 w-2 h-2 shrink-0 rounded-full ${SEVERITY_DOT[ev.severity]}`} />
                <span className="flex-1 font-medium">{ev.label}</span>
                <span className="shrink-0 font-mono text-[10px] opacity-60">{ev.user_id_prefix}</span>
                <span className="shrink-0 opacity-50">{relTime(ev.created_at)}</span>
              </div>
            ))}
          </div>
        )}
      </Card>
    </SectionBlock>
  );
}

// ── Section: System Health ────────────────────────────────────────────────────

function SystemSection({ runtime, loading }: { runtime: RuntimeInfo | null; loading: boolean }) {
  const uptimeDays = runtime ? Math.floor(runtime.uptime_seconds / 86400) : 0;
  const uptimeHrs  = runtime ? Math.floor((runtime.uptime_seconds % 86400) / 3600) : 0;

  return (
    <SectionBlock id="system" title="System Health">
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <KPICard title="Uptime"          value={runtime ? `${uptimeDays}d ${uptimeHrs}h` : '—'} loading={loading} color="text-emerald-400" />
        <KPICard title="Memory"          value={runtime ? `${Math.round(runtime.memory_mb)}MB` : '—'} loading={loading} />
        <KPICard title="Active Requests" value={fmt(runtime?.active_requests)} loading={loading} />
        <KPICard title="Environment"     value={runtime?.environment ?? '—'} loading={loading}
          color={runtime?.environment === 'production' ? 'text-amber-400' : 'text-gray-300'} />
      </div>
    </SectionBlock>
  );
}

// ── Section: Affiliate Program ────────────────────────────────────────────────

function AffiliateSection({ affiliate, loading }: { affiliate: AffiliateSummary | null; loading: boolean }) {
  const totals = affiliate?.totals;
  const top    = affiliate?.top_affiliates ?? [];

  return (
    <SectionBlock id="affiliate" title="Affiliate Program">
      <div className="grid grid-cols-2 sm:grid-cols-5 gap-3 mb-6">
        <KPICard title="Total Clicks"    value={fmt(totals?.clicks)}       loading={loading} />
        <KPICard title="Signups"         value={fmt(totals?.signups)}       loading={loading} color="text-emerald-400" />
        <KPICard title="Conversions"     value={fmt(totals?.conversions)}   loading={loading} color="text-amber-400" />
        <KPICard title="Commission Owed" value={`$${fmt(totals?.pending_commission, 2)}`} loading={loading} color="text-orange-400" />
        <KPICard title="Commission Paid" value={`$${fmt(totals?.paid_commission, 2)}`}    loading={loading} color="text-emerald-400" />
      </div>
      <Card>
        <div className="flex items-center justify-between mb-4">
          <CardTitle>Top Affiliates</CardTitle>
          <a href="/dashboard/admin/affiliates" className="text-xs text-amber-400 hover:underline">Manage →</a>
        </div>
        {loading ? (
          <div className="space-y-2">{[...Array(4)].map((_, i) => <Skeleton key={i} />)}</div>
        ) : !top.length ? (
          <p className="text-xs text-gray-500">No affiliates yet</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="text-gray-500 border-b border-gray-700/40">
                  <th className="text-left py-2 pr-4 font-medium">Name</th>
                  <th className="text-left py-2 pr-4 font-medium">Slug</th>
                  <th className="text-right py-2 pr-4 font-medium">Clicks</th>
                  <th className="text-right py-2 pr-4 font-medium">Conv.</th>
                  <th className="text-right py-2 font-medium">Commission</th>
                </tr>
              </thead>
              <tbody>
                {top.map((aff, i) => (
                  <tr key={i} className="border-b border-gray-700/20 hover:bg-gray-700/20 transition-colors">
                    <td className="py-2 pr-4 font-medium text-gray-200">{aff.name}</td>
                    <td className="py-2 pr-4 font-mono text-gray-400">/{aff.slug}</td>
                    <td className="py-2 pr-4 text-right tabular-nums text-gray-300">{fmt(aff.clicks)}</td>
                    <td className="py-2 pr-4 text-right tabular-nums text-amber-400">{fmt(aff.conversions_total)}</td>
                    <td className="py-2 text-right tabular-nums text-emerald-400">${fmt(aff.commission_total_usd, 2)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </SectionBlock>
  );
}

// ── Nav items ─────────────────────────────────────────────────────────────────

const NAV_SECTIONS = [
  { id: 'overview',   label: 'Overview'   },
  { id: 'revenue',    label: 'Revenue'    },
  { id: 'economics',  label: 'Economics'  },
  { id: 'behavior',   label: 'Behavior'   },
  { id: 'retention',  label: 'Retention'  },
  { id: 'conversion', label: 'Conversion' },
  { id: 'voice',      label: 'Voice'      },
  { id: 'abuse',      label: 'Abuse & Risk'},
  { id: 'affiliate',  label: 'Affiliates' },
  { id: 'activity',   label: 'Activity'   },
  { id: 'system',     label: 'System'     },
];

// ── Root component ────────────────────────────────────────────────────────────

export default function AdminDashboard() {
  const data = useAdminData();
  const [activeSection, setActiveSection] = useState('overview');

  function scrollTo(id: string) {
    setActiveSection(id);
    document.getElementById(id)?.scrollIntoView({ behavior: 'smooth' });
  }

  if (data.error && !data.kpis) {
    return (
      <div className="min-h-screen bg-gray-950 flex items-center justify-center">
        <div className="text-center">
          <p className="text-red-400 font-semibold mb-2">Access denied or load error</p>
          <p className="text-xs text-gray-500">{data.error}</p>
          <a href="/dashboard" className="mt-4 inline-block text-xs text-amber-400 underline">← Back to dashboard</a>
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-screen bg-gray-950 text-gray-100 font-sans">
      {/* ── Sidebar ─────────────────────────────────────────────────────────── */}
      <nav className="w-48 shrink-0 border-r border-gray-800 bg-gray-900/80 flex flex-col">
        <div className="px-4 pt-5 pb-4 border-b border-gray-800">
          <a href="/dashboard" className="flex items-center gap-2 group mb-3">
            <svg viewBox="0 0 16 16" fill="none" className="w-3.5 h-3.5 text-gray-500 group-hover:text-gray-300 transition-colors" stroke="currentColor" strokeWidth="1.5">
              <path d="M10 13L5 8l5-5" strokeLinecap="round" strokeLinejoin="round"/>
            </svg>
            <span className="text-xs text-gray-500 group-hover:text-gray-300 transition-colors">Dashboard</span>
          </a>
          <p className="text-[10px] font-bold tracking-widest uppercase text-amber-400">Sonoro Admin</p>
          {data.refreshedAt && (
            <p className="text-[10px] text-gray-600 mt-1">Updated {relTime(data.refreshedAt.toISOString())}</p>
          )}
        </div>

        <ul className="flex-1 overflow-y-auto py-3 px-2 space-y-0.5">
          {NAV_SECTIONS.map((s) => (
            <li key={s.id}>
              <button
                onClick={() => scrollTo(s.id)}
                className={`w-full text-left px-3 py-2 rounded-lg text-xs font-medium transition-colors ${
                  activeSection === s.id
                    ? 'bg-amber-500/10 text-amber-400'
                    : 'text-gray-500 hover:text-gray-200 hover:bg-gray-800/60'
                }`}
              >
                {s.label}
              </button>
            </li>
          ))}
        </ul>

        <div className="p-3 border-t border-gray-800">
          <button
            onClick={data.refresh}
            disabled={data.loading}
            className="w-full px-3 py-2 rounded-lg text-xs font-medium bg-gray-800 text-gray-400 hover:bg-gray-700 hover:text-gray-200 transition-colors disabled:opacity-50 disabled:cursor-wait"
          >
            {data.loading ? 'Loading…' : '↻ Refresh'}
          </button>
        </div>
      </nav>

      {/* ── Main content ─────────────────────────────────────────────────────── */}
      <main className="flex-1 overflow-y-auto p-8">
        <div className="max-w-5xl mx-auto">
          <header className="mb-10">
            <div className="flex items-center justify-between">
              <div>
                <h1 className="text-xl font-bold text-white">Intelligence Dashboard</h1>
                <p className="text-xs text-gray-500 mt-0.5">
                  Sonoro founder command center · {new Date().toLocaleDateString('en-US', { weekday: 'long', month: 'long', day: 'numeric' })}
                </p>
              </div>
              {data.runtime && (
                <span className="flex items-center gap-2 text-xs text-emerald-400 bg-emerald-500/10 border border-emerald-500/20 px-3 py-1.5 rounded-full">
                  <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
                  {data.runtime.environment}
                </span>
              )}
            </div>
          </header>

          <ExecutiveSection  kpis={data.kpis}        loading={data.loading} />
          <RevenueSection    kpis={data.kpis}        loading={data.loading} />
          <CostsSection      kpis={data.kpis}        economics={data.economics} expensive={data.expensive} loading={data.loading} />
          <BehaviorSection   analytics={data.analytics} loading={data.loading} />
          <RetentionSection  analytics={data.analytics} loading={data.loading} />
          <ConversionSection kpis={data.kpis}        analytics={data.analytics} loading={data.loading} />
          <VoiceSection      voice={data.voice}       loading={data.loading} />
          <AbuseSection      expensive={data.expensive} kpis={data.kpis} loading={data.loading} />
          <AffiliateSection  affiliate={data.affiliate} loading={data.loading} />
          <ActivityFeedSection activity={data.activity} loading={data.loading} />
          <SystemSection     runtime={data.runtime}   loading={data.loading} />
        </div>
      </main>
    </div>
  );
}
