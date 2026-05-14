/**
 * Usage Dashboard
 * ===============
 * Full usage analytics view: quota bars, cost breakdown, period history.
 * Replaces the "coming soon" placeholder.
 */

'use client';

import { useEffect } from 'react';
import { useQuery } from '@tanstack/react-query';
import { BarChart3, TrendingUp, Calendar, Zap, AlertTriangle } from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Skeleton } from '@/components/ui/skeleton';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { UsageOverview } from '@/components/usage/usage-overview';
import { UsageWarningBanner } from '@/components/paywall/usage-warning-banner';
import { UpgradeNudge } from '@/components/growth/upgrade-nudge';
import { useUsageLimits } from '@/hooks/use-usage-limits';
import { usePricingStore, selectCurrentTier } from '@/store/pricing-store';
import { TIER_META, fmtChars, fmtStorage } from '@/lib/pricing-service';
import { apiClient } from '@/lib/api-client';
import { track } from '@/lib/analytics';

// Detailed usage response from /api/v1/account/usage
interface DetailedUsage {
  period: string;
  monthly_usage: {
    characters_used: number;
    jobs_created: number;
    storage_used_mb: number;
    api_calls: number;
    period_start: string;
    period_end: string;
  };
  cost_breakdown: Array<{
    event_type: string;
    count: number;
    total_cost_usd: number;
    percentage: number;
  }>;
  daily_data: Array<{
    date: string;
    characters: number;
    jobs: number;
    api_calls: number;
    cost_usd: number;
  }>;
  quota_remaining: {
    characters: { remaining: number; limit: number; used_percentage: number };
    jobs: { remaining: number; limit: number; used_percentage: number };
    storage_mb: { remaining: number; limit: number; used_percentage: number };
    api_calls: { remaining: number; limit: number; used_percentage: number };
  };
}

async function fetchDetailedUsage(): Promise<DetailedUsage> {
  const res = await apiClient.get<DetailedUsage>('/account/usage');
  return res.data;
}

function CostBreakdownCard({ breakdown }: { breakdown: DetailedUsage['cost_breakdown'] }) {
  if (!breakdown || breakdown.length === 0) return null;
  const total = breakdown.reduce((s, b) => s + b.total_cost_usd, 0);

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-sm flex items-center gap-2">
          <TrendingUp className="h-4 w-4" />
          Cost Breakdown
        </CardTitle>
        <CardDescription>This billing period</CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        {breakdown.slice(0, 5).map((item) => (
          <div key={item.event_type} className="space-y-1">
            <div className="flex justify-between text-sm">
              <span className="capitalize text-muted-foreground">
                {item.event_type.replace(/_/g, ' ')}
              </span>
              <span className="font-medium">
                ${item.total_cost_usd.toFixed(item.total_cost_usd < 0.01 ? 6 : 4)}
              </span>
            </div>
            <div className="h-1.5 rounded-full bg-muted overflow-hidden">
              <div
                className="h-full bg-violet-500 rounded-full"
                style={{ width: `${item.percentage}%` }}
              />
            </div>
          </div>
        ))}
        <div className="pt-2 border-t flex justify-between text-sm font-semibold">
          <span>Total</span>
          <span>${total.toFixed(total < 0.01 ? 6 : 4)}</span>
        </div>
      </CardContent>
    </Card>
  );
}

function DailyActivity({ dailyData }: { dailyData: DetailedUsage['daily_data'] }) {
  if (!dailyData || dailyData.length === 0) return null;

  const maxChars = Math.max(...dailyData.map((d) => d.characters), 1);
  const recent = dailyData.slice(-14);

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-sm flex items-center gap-2">
          <BarChart3 className="h-4 w-4" />
          Daily Activity
        </CardTitle>
        <CardDescription>Characters processed per day (last 14 days)</CardDescription>
      </CardHeader>
      <CardContent>
        <div className="flex items-end gap-1 h-24">
          {recent.map((day) => {
            const pct = (day.characters / maxChars) * 100;
            const date = new Date(day.date).toLocaleDateString('en-US', { weekday: 'short' });
            return (
              <div
                key={day.date}
                className="flex-1 flex flex-col items-center gap-1"
                title={`${date}: ${fmtChars(day.characters)} chars, ${day.jobs} jobs`}
              >
                <div className="w-full flex flex-col justify-end" style={{ height: '80px' }}>
                  <div
                    className="w-full bg-violet-500/80 hover:bg-violet-600 rounded-t transition-all cursor-default"
                    style={{ height: `${Math.max(pct, 2)}%` }}
                  />
                </div>
                <span className="text-[9px] text-muted-foreground">{date.slice(0, 1)}</span>
              </div>
            );
          })}
        </div>
      </CardContent>
    </Card>
  );
}

function StatCard({ icon: Icon, label, value, sub }: {
  icon: typeof BarChart3;
  label: string;
  value: string;
  sub?: string;
}) {
  return (
    <Card>
      <CardContent className="pt-5">
        <div className="flex items-center gap-3">
          <div className="h-9 w-9 rounded-lg bg-violet-100 dark:bg-violet-900/30 flex items-center justify-center shrink-0">
            <Icon className="h-4 w-4 text-violet-600 dark:text-violet-400" />
          </div>
          <div>
            <p className="text-xs text-muted-foreground">{label}</p>
            <p className="text-lg font-bold">{value}</p>
            {sub && <p className="text-xs text-muted-foreground">{sub}</p>}
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

export default function UsagePage() {
  const { tier, refetch, isLoading } = useUsageLimits();
  const usage = usePricingStore((s) => s.usage);
  const tier_ = usePricingStore(selectCurrentTier);
  const meta = TIER_META[tier_] ?? TIER_META.FREE;

  const { data: detailed, isLoading: detailedLoading } = useQuery({
    queryKey: ['detailed-usage'],
    queryFn: fetchDetailedUsage,
    staleTime: 30_000,
  });

  useEffect(() => {
    track('page_view', { path: '/usage' });
  }, []);

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Usage</h1>
          <p className="text-muted-foreground mt-1">
            Monitor your quota, costs, and activity for the current period.
          </p>
        </div>
        <Badge variant="outline" className="text-sm">
          {meta.name} Plan
        </Badge>
      </div>

      {/* Upgrade nudge (warning-level prompts) */}
      <UpgradeNudge />

      {/* Hard block banner */}
      <UsageWarningBanner />

      {/* Summary stats */}
      {(isLoading || detailedLoading) && !usage ? (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-24" />
          ))}
        </div>
      ) : usage ? (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <StatCard
            icon={Zap}
            label="Characters used"
            value={fmtChars(usage.chars_used)}
            sub={`of ${fmtChars(usage.chars_limit)}`}
          />
          <StatCard
            icon={BarChart3}
            label="Jobs created"
            value={`${usage.jobs_created}`}
            sub={`of ${usage.jobs_limit}`}
          />
          <StatCard
            icon={TrendingUp}
            label="Storage used"
            value={fmtStorage(usage.storage_mb)}
            sub={`of ${fmtStorage(usage.storage_limit_mb)}`}
          />
          <StatCard
            icon={Calendar}
            label="Period ends"
            value={
              usage.period_end
                ? new Date(usage.period_end).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
                : '—'
            }
            sub="Quota resets then"
          />
        </div>
      ) : null}

      {/* Main grid */}
      <div className="grid gap-6 md:grid-cols-2 xl:grid-cols-3">
        {/* Quota bars — spans 2 columns on xl */}
        <div className="xl:col-span-2">
          <UsageOverview onRefetch={refetch} />
        </div>

        {/* Cost breakdown */}
        {detailed?.cost_breakdown && (
          <CostBreakdownCard breakdown={detailed.cost_breakdown} />
        )}
      </div>

      {/* Daily activity chart */}
      {detailed?.daily_data && detailed.daily_data.length > 0 && (
        <DailyActivity dailyData={detailed.daily_data} />
      )}

      {/* No usage yet */}
      {!isLoading && !detailedLoading && !usage && (
        <Alert>
          <AlertTriangle className="h-4 w-4" />
          <AlertDescription>
            No usage data yet. Upload your first document to start tracking.
          </AlertDescription>
        </Alert>
      )}
    </div>
  );
}
