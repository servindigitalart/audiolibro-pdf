/**
 * Admin API Client
 * ================
 * Typed wrappers for all internal admin endpoints.
 * Uses the shared Axios instance (JWT cookie injection + refresh).
 */

import api from '@/lib/api/client';

// ── Response types ────────────────────────────────────────────────────────────

export interface DashboardKPIs {
  generated_at: string;
  users: {
    total: number;
    active_7d: number;
    active_30d: number;
    free: number;
    paid: number;
    by_plan: Record<string, number>;
  };
  revenue: {
    mrr_usd: number;
    arr_projected_usd: number;
    arpu_usd: number;
    arppu_usd: number;
  };
  costs: {
    monthly_estimated_usd: number;
    estimated_gross_margin_pct: number;
  };
  content: {
    audiobooks_generated: number;
    listening_hours_total: number;
    avg_completion_pct: number;
    avg_session_minutes: number;
  };
  conversion: {
    quota_exceeded_events_30d: number;
    paywall_views_30d: number;
    upgrade_clicks_30d: number;
    upgrade_conversion_rate_pct: number;
  };
}

export interface GrowthData {
  period_days: number;
  data: Array<{ day: string; signups: number }>;
}

export type ActivitySeverity = 'neutral' | 'success' | 'warning' | 'info';

export interface ActivityEvent {
  event_type: string;
  label: string;
  severity: ActivitySeverity;
  user_id_prefix: string;
  created_at: string | null;
  properties: Record<string, unknown>;
}

export interface ActivityFeed {
  events: ActivityEvent[];
  total: number;
}

export interface AnalyticsOverview {
  period_days: number;
  completion: {
    total_sessions: number;
    avg_completion_pct: number;
    avg_listened_minutes: number;
    engaged_rate_pct: number;
    halfway_rate_pct: number;
    completed_rate_pct: number;
  };
  sessions: {
    avg_duration_minutes: number;
    avg_speed: number;
    continue_listening_resume_rate_pct: number;
  };
  top_events: Array<{ event_type: string; count: number }>;
  upgrade_funnel: {
    paywall_views: number;
    upgrade_clicks: number;
    conversions: number;
    paywall_click_rate: number;
    click_convert_rate: number;
  };
  retention: {
    total_users_with_sessions: number;
    returning_users: number;
    retention_rate_pct: number;
    avg_sessions_per_user: number;
  };
}

export interface CostOverview {
  period_days: number;
  total_cost_usd: number;
  cost_breakdown: Record<string, number>;
  daily_trend: Array<{ date: string; cost: number }>;
  top_users: Array<{ user_id: string; total_cost: number }>;
}

export interface PlanEconomics {
  observed: Array<{
    plan_tier: string;
    job_count: number;
    total_cost_usd: number;
    avg_cost_usd: number;
  }>;
  theoretical: Array<{
    plan_tier: string;
    monthly_revenue_usd: number;
    max_tts_cost_usd: number;
    theoretical_margin_pct: number;
  }>;
}

export interface ExpensiveJob {
  job_id: string;
  user_id: string;
  document_id: string | null;
  plan_tier: string;
  characters_processed: number | null;
  estimated_cost_usd: number;
  created_at: string;
}

export interface VoiceEngagement {
  period_days: number;
  voices: Array<{ voice_id: string; preview_count: number }>;
}

export interface RuntimeInfo {
  uptime_seconds: number;
  memory_mb: number;
  active_requests: number;
  environment: string;
  version: string;
}

export interface AffiliateSummary {
  totals: {
    clicks: number;
    signups: number;
    conversions: number;
    pending_commission: number;
    paid_commission: number;
  };
  top_affiliates: Array<{
    id: string;
    name: string;
    slug: string;
    status: string;
    clicks: number;
    signups: number;
    conversions_total: number;
    commission_pending_usd: number;
    commission_paid_usd: number;
    commission_total_usd: number;
  }>;
}

// ── Client functions ──────────────────────────────────────────────────────────

function adminGet<T>(path: string): Promise<T> {
  return api.get<T>(path).then((r) => r.data);
}

export const adminApi = {
  getKpis: (): Promise<DashboardKPIs> =>
    adminGet('/admin/dashboard/kpis'),

  getGrowth: (days = 30): Promise<GrowthData> =>
    adminGet(`/admin/dashboard/growth?days=${days}`),

  getActivity: (limit = 50): Promise<ActivityFeed> =>
    adminGet(`/admin/dashboard/activity?limit=${limit}`),

  getAnalyticsOverview: (days = 30): Promise<AnalyticsOverview> =>
    adminGet(`/admin/analytics/overview?days=${days}`),

  getCostOverview: (days = 30): Promise<CostOverview> =>
    adminGet(`/admin/financial/cost/overview?days=${days}`),

  getPlanEconomics: (): Promise<PlanEconomics> =>
    adminGet('/admin/financial/plan-economics'),

  getExpensiveJobs: (limit = 20, days = 30): Promise<{ jobs: ExpensiveJob[] }> =>
    adminGet(`/admin/financial/expensive-jobs?limit=${limit}&days=${days}`),

  getVoiceEngagement: (days = 30): Promise<VoiceEngagement> =>
    adminGet(`/admin/analytics/voice-engagement?days=${days}`),

  getRuntime: (): Promise<RuntimeInfo> =>
    adminGet('/admin/runtime'),

  getAffiliateSummary: (): Promise<AffiliateSummary> =>
    adminGet('/admin/affiliates/summary'),
};
