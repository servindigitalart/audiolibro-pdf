/**
 * Dashboard
 * =========
 * Main authenticated dashboard. Shows live usage, real document stats,
 * onboarding checklist for new users, and upgrade prompts when appropriate.
 */

'use client';

import { useEffect } from 'react';
import { useQuery } from '@tanstack/react-query';
import { FileText, Clock, CheckCircle, Upload, Zap, ArrowRight } from 'lucide-react';
import { useRouter } from 'next/navigation';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Skeleton } from '@/components/ui/skeleton';
import { UsageOverview } from '@/components/usage/usage-overview';
import { UsageWarningBanner } from '@/components/paywall/usage-warning-banner';
import { UpgradeNudge } from '@/components/growth/upgrade-nudge';
import { OnboardingChecklist } from '@/components/growth/onboarding-checklist';
import { useAuthStore } from '@/store/auth-store';
import { usePricingStore, selectCurrentTier } from '@/store/pricing-store';
import { useUsageLimits } from '@/hooks/use-usage-limits';
import { TIER_META } from '@/lib/pricing-service';
import { track } from '@/lib/analytics';
import { apiClient } from '@/lib/api-client';

// ── Document summary from backend ─────────────────────────────────────────────

interface DocumentStats {
  total: number;
  processing: number;
  completed: number;
  failed: number;
}

async function fetchDocumentStats(): Promise<DocumentStats> {
  const res = await apiClient.get<{ documents: any[] }>('/documents?limit=200');
  const docs = res.data?.documents ?? (Array.isArray(res.data) ? res.data : []);
  return {
    total: docs.length,
    processing: docs.filter((d: any) => d.status === 'processing' || d.status === 'queued').length,
    completed: docs.filter((d: any) => d.status === 'completed').length,
    failed: docs.filter((d: any) => d.status === 'failed').length,
  };
}

// ── Stat card ─────────────────────────────────────────────────────────────────

function StatCard({
  icon: Icon,
  label,
  value,
  sub,
  loading,
}: {
  icon: typeof FileText;
  label: string;
  value: number | string;
  sub?: string;
  loading?: boolean;
}) {
  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between pb-2">
        <CardTitle className="text-sm font-medium">{label}</CardTitle>
        <Icon className="h-4 w-4 text-muted-foreground" />
      </CardHeader>
      <CardContent>
        {loading ? (
          <Skeleton className="h-8 w-16" />
        ) : (
          <>
            <div className="text-2xl font-bold">{value}</div>
            {sub && <p className="text-xs text-muted-foreground mt-0.5">{sub}</p>}
          </>
        )}
      </CardContent>
    </Card>
  );
}

// ── Recent documents preview ──────────────────────────────────────────────────

function RecentDocumentRow({ doc }: { doc: any }) {
  const statusColors: Record<string, string> = {
    completed: 'bg-green-500',
    processing: 'bg-blue-500 animate-pulse',
    queued: 'bg-yellow-500',
    failed: 'bg-red-500',
  };
  return (
    <div className="flex items-center gap-3 py-2.5 border-b last:border-0">
      <div className={`h-2 w-2 rounded-full shrink-0 ${statusColors[doc.status] ?? 'bg-muted'}`} />
      <div className="flex-1 min-w-0">
        <p className="text-sm font-medium truncate">{doc.original_filename ?? doc.title ?? 'Document'}</p>
        <p className="text-xs text-muted-foreground capitalize">{doc.status}</p>
      </div>
      <span className="text-xs text-muted-foreground">
        {doc.created_at ? new Date(doc.created_at).toLocaleDateString('en-US', { month: 'short', day: 'numeric' }) : ''}
      </span>
    </div>
  );
}

// ── Empty state ───────────────────────────────────────────────────────────────

function EmptyState() {
  const router = useRouter();
  return (
    <Card className="border-dashed">
      <CardContent className="flex flex-col items-center justify-center py-12 gap-4 text-center">
        <div className="h-12 w-12 rounded-full bg-muted flex items-center justify-center">
          <Upload className="h-6 w-6 text-muted-foreground" />
        </div>
        <div>
          <p className="font-semibold">No documents yet</p>
          <p className="text-sm text-muted-foreground mt-1">
            Upload a PDF, EPUB or TXT to create your first audiobook
          </p>
        </div>
        <Button onClick={() => router.push('/documents')}>
          Upload document
          <ArrowRight className="ml-2 h-4 w-4" />
        </Button>
      </CardContent>
    </Card>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function DashboardPage() {
  const { user } = useAuthStore();
  const tier_ = usePricingStore(selectCurrentTier);
  const meta = TIER_META[tier_] ?? TIER_META.FREE;
  const { isLoading: usageLoading } = useUsageLimits();

  const firstName = user?.email?.split('@')[0] ?? 'there';
  const isNewUser = user
    ? (Date.now() - new Date(user.created_at).getTime()) < 7 * 24 * 60 * 60 * 1000
    : false;

  const { data: stats, isLoading: statsLoading } = useQuery({
    queryKey: ['document-stats'],
    queryFn: fetchDocumentStats,
    staleTime: 30_000,
    retry: 1,
  });

  const { data: recentDocs, isLoading: docsLoading } = useQuery({
    queryKey: ['recent-documents'],
    queryFn: async () => {
      const res = await apiClient.get('/documents?limit=5&sort=created_at:desc');
      return res.data?.documents ?? (Array.isArray(res.data) ? res.data : []);
    },
    staleTime: 30_000,
    retry: 1,
  });

  useEffect(() => {
    track('page_view', { path: '/dashboard' });
  }, []);

  const docStats = stats ?? { total: 0, processing: 0, completed: 0, failed: 0 };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">
            Welcome back, {firstName}!
          </h1>
          <p className="text-muted-foreground mt-1">
            Here's what's happening with your audiobooks.
          </p>
        </div>
        <Badge variant="outline">{meta.name} plan</Badge>
      </div>

      {/* Hard paywall banner */}
      <UsageWarningBanner />

      {/* Soft upgrade nudge */}
      <UpgradeNudge />

      {/* Onboarding checklist for new users */}
      {isNewUser && (
        <OnboardingChecklist />
      )}

      {/* Stats row */}
      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
        <StatCard
          icon={FileText}
          label="Total documents"
          value={docStats.total}
          sub="All time"
          loading={statsLoading}
        />
        <StatCard
          icon={Clock}
          label="Processing"
          value={docStats.processing}
          sub="Currently running"
          loading={statsLoading}
        />
        <StatCard
          icon={CheckCircle}
          label="Completed"
          value={docStats.completed}
          sub="Ready to listen"
          loading={statsLoading}
        />
        <StatCard
          icon={Zap}
          label="This month"
          value={usePricingStore.getState().usage?.chars_used
            ? `${Math.round(usePricingStore.getState().usage!.chars_used / 1000)}K chars`
            : '—'}
          sub="Characters converted"
          loading={usageLoading}
        />
      </div>

      {/* Two-column: recent documents + usage overview */}
      <div className="grid gap-6 md:grid-cols-2">
        {/* Recent documents */}
        <Card>
          <CardHeader className="flex flex-row items-center justify-between pb-3">
            <div>
              <CardTitle className="text-base">Recent documents</CardTitle>
              <CardDescription>Your latest audiobook conversions</CardDescription>
            </div>
            <Button variant="ghost" size="sm" onClick={() => window.location.href = '/documents'}>
              View all
              <ArrowRight className="ml-1.5 h-3.5 w-3.5" />
            </Button>
          </CardHeader>
          <CardContent>
            {docsLoading ? (
              <div className="space-y-3">
                {Array.from({ length: 3 }).map((_, i) => (
                  <Skeleton key={i} className="h-10" />
                ))}
              </div>
            ) : recentDocs && recentDocs.length > 0 ? (
              <div>
                {recentDocs.map((doc: any) => (
                  <RecentDocumentRow key={doc.id} doc={doc} />
                ))}
              </div>
            ) : (
              <EmptyState />
            )}
          </CardContent>
        </Card>

        {/* Compact usage overview */}
        <UsageOverview compact />
      </div>
    </div>
  );
}
