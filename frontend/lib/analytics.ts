/**
 * Analytics Service
 * =================
 * Lightweight event tracking for the product analytics + growth funnel.
 *
 * Architecture:
 *   - Events queued in memory and flushed every 2 seconds as a batch POST
 *   - UTM parameters persisted in sessionStorage and attached to all events
 *   - GTM dataLayer integration for external analytics (optional)
 *   - navigator.sendBeacon used on page unload to avoid dropped events
 *   - Backend-unavailable gracefully falls back to console.debug in dev
 *
 * Privacy:
 *   - No PII tracked beyond user_id (never email/name/IP)
 *   - Backend strips additional sensitive keys before logging
 */

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000/api/v1';

// ── Event types (allowlisted in backend events router) ────────────────────────

export type AnalyticsEventName =
  | 'sign_up'
  | 'login'
  | 'logout'
  | 'onboarding_step'
  | 'onboarding_complete'
  | 'document_upload'
  | 'document_processed'
  | 'feature_gate_hit'
  | 'paywall_shown'
  | 'paywall_dismissed'
  | 'upgrade_intent'
  | 'upgrade_complete'
  | 'upgrade_abandoned'
  | 'quota_warning'
  | 'quota_exceeded'
  | 'upgrade_nudge_shown'
  | 'upgrade_nudge_clicked'
  | 'pricing_page_view'
  | 'page_view'
  | 'checkout_started'
  | 'checkout_completed'
  | 'checkout_abandoned'
  | 'referral_shared'
  | 'referral_converted';

interface EventRecord {
  event: AnalyticsEventName;
  properties?: Record<string, unknown>;
  user_id?: string;
  session_id: string;
  timestamp: string;
  utm_source?: string;
  utm_medium?: string;
  utm_campaign?: string;
  utm_term?: string;
  utm_content?: string;
}

// ── Internal state ────────────────────────────────────────────────────────────

const _queue: EventRecord[] = [];
let _flushTimer: ReturnType<typeof setTimeout> | null = null;
let _sessionId: string | null = null;
let _userId: string | undefined;

// ── Session management ────────────────────────────────────────────────────────

function getSessionId(): string {
  if (typeof window === 'undefined') return 'ssr';
  if (_sessionId) return _sessionId;
  _sessionId =
    sessionStorage.getItem('_analytics_sid') ??
    `s_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`;
  sessionStorage.setItem('_analytics_sid', _sessionId);
  return _sessionId;
}

// ── UTM capture & persistence ─────────────────────────────────────────────────

const UTM_KEYS = ['utm_source', 'utm_medium', 'utm_campaign', 'utm_term', 'utm_content'] as const;
type UtmKey = typeof UTM_KEYS[number];

function captureUtm(): Partial<Record<UtmKey, string>> {
  if (typeof window === 'undefined') return {};
  const params = new URLSearchParams(window.location.search);
  const utm: Partial<Record<UtmKey, string>> = {};

  UTM_KEYS.forEach((key) => {
    const val = params.get(key);
    if (val) {
      sessionStorage.setItem(key, val);
      utm[key] = val;
    } else {
      const stored = sessionStorage.getItem(key);
      if (stored) utm[key] = stored;
    }
  });

  return utm;
}

// ── Flush logic ───────────────────────────────────────────────────────────────

async function flushQueue(): Promise<void> {
  if (_queue.length === 0) return;
  const batch = _queue.splice(0, 50); // max 50 per flush

  try {
    await fetch(`${API_BASE}/events/batch`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({ events: batch }),
    });
  } catch {
    if (process.env.NODE_ENV === 'development') {
      console.debug('[analytics] flush failed — events dropped:', batch);
    }
  }
}

function scheduleFlush(): void {
  if (_flushTimer !== null) return;
  _flushTimer = setTimeout(async () => {
    _flushTimer = null;
    await flushQueue();
  }, 2_000);
}

// ── Public API ────────────────────────────────────────────────────────────────

/**
 * Identify the current user.
 * Call this after login / registration so all subsequent events carry user_id.
 */
export function identify(userId: string, traits?: Record<string, unknown>): void {
  _userId = userId;

  if (typeof window !== 'undefined' && (window as any).dataLayer) {
    (window as any).dataLayer.push({ event: 'identify', userId, ...traits });
  }
}

/**
 * Track an analytics event.
 *
 * @param event  One of AnalyticsEventName
 * @param props  Arbitrary properties (no PII beyond user_id)
 */
export function track(
  event: AnalyticsEventName,
  props?: Record<string, unknown>,
): void {
  const utmData = captureUtm();

  const record: EventRecord = {
    event,
    properties: props,
    user_id: _userId,
    session_id: getSessionId(),
    timestamp: new Date().toISOString(),
    ...utmData,
  };

  _queue.push(record);

  if (process.env.NODE_ENV === 'development') {
    console.debug(`[analytics] ${event}`, props);
  }

  // GTM dataLayer
  if (typeof window !== 'undefined' && (window as any).dataLayer) {
    (window as any).dataLayer.push({ event, ...props });
  }

  scheduleFlush();
}

/** Convenience: track a page view (call from layout or route components). */
export function page(path?: string): void {
  track('page_view', { path: path ?? (typeof window !== 'undefined' ? window.location.pathname : '') });
}

// ── Beacon on unload ──────────────────────────────────────────────────────────

if (typeof window !== 'undefined') {
  window.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'hidden' && _queue.length > 0) {
      const blob = new Blob(
        [JSON.stringify({ events: _queue.splice(0) })],
        { type: 'application/json' },
      );
      navigator.sendBeacon?.(`${API_BASE}/events/batch`, blob);
    }
  });
}

export default { track, page, identify };
