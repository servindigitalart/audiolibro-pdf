/**
 * Referral Code Capture
 * =====================
 * Lightweight, privacy-safe referral tracking.
 *
 * Flow:
 *   1. Visitor lands on /?ref=CODE
 *   2. captureReferralCode() reads the param and stores it in
 *      localStorage (primary) + cookie (fallback for SSR).
 *   3. On registration, getReferralCode() retrieves it and it's
 *      sent with the register payload.
 *   4. clearReferralCode() is called after successful attribution.
 *
 * No PII stored — only the slug itself (max 50 chars).
 */

const STORAGE_KEY = 'sonoro_ref';
const COOKIE_NAME = 'sonoro_ref';
const COOKIE_MAX_AGE = 30 * 86_400; // 30 days in seconds

export function captureReferralCode(): void {
  if (typeof window === 'undefined') return;
  const params = new URLSearchParams(window.location.search);
  const ref = params.get('ref');
  if (!ref || ref.length > 50) return;

  // Validate: only safe slug characters
  if (!/^[a-z0-9][a-z0-9-]{1,48}[a-z0-9]$/i.test(ref)) return;

  try {
    localStorage.setItem(STORAGE_KEY, ref);
  } catch {
    // Private browsing / storage quota
  }

  // Cookie fallback (SameSite=Lax, no Secure flag — works on http dev too)
  document.cookie = [
    `${COOKIE_NAME}=${encodeURIComponent(ref)}`,
    `max-age=${COOKIE_MAX_AGE}`,
    'path=/',
    'SameSite=Lax',
  ].join('; ');
}

export function getReferralCode(): string | null {
  if (typeof window === 'undefined') return null;

  // localStorage first
  try {
    const local = localStorage.getItem(STORAGE_KEY);
    if (local) return local;
  } catch {
    // ignore
  }

  // Cookie fallback
  const match = document.cookie
    .split(';')
    .map((c) => c.trim())
    .find((c) => c.startsWith(`${COOKIE_NAME}=`));

  return match ? decodeURIComponent(match.split('=')[1]) : null;
}

export function clearReferralCode(): void {
  if (typeof window === 'undefined') return;
  try {
    localStorage.removeItem(STORAGE_KEY);
  } catch {
    // ignore
  }
  document.cookie = `${COOKIE_NAME}=; max-age=0; path=/; SameSite=Lax`;
}

// ── UTM Parameter Capture ─────────────────────────────────────────────────────

const UTM_KEY = 'sonoro_utm';

export interface UtmParams {
  utm_source?:   string;
  utm_medium?:   string;
  utm_campaign?: string;
  utm_content?:  string;
  utm_term?:     string;
  landing_path?: string;
}

/**
 * Capture UTM parameters from the current URL and persist them in localStorage.
 * Only writes when at least one UTM param is present.
 * Stored for the session so signup attribution survives multi-page journeys.
 */
export function captureUtmParams(): void {
  if (typeof window === 'undefined') return;
  const p = new URLSearchParams(window.location.search);

  const utm: UtmParams = {};
  const src      = p.get('utm_source');
  const medium   = p.get('utm_medium');
  const campaign = p.get('utm_campaign');
  const content  = p.get('utm_content');
  const term     = p.get('utm_term');

  if (src)      utm.utm_source   = src;
  if (medium)   utm.utm_medium   = medium;
  if (campaign) utm.utm_campaign = campaign;
  if (content)  utm.utm_content  = content;
  if (term)     utm.utm_term     = term;

  if (Object.keys(utm).length === 0) return;

  utm.landing_path = window.location.pathname;

  try {
    localStorage.setItem(UTM_KEY, JSON.stringify(utm));
  } catch {
    // Private browsing / storage quota
  }
}

export function getUtmParams(): UtmParams | null {
  if (typeof window === 'undefined') return null;
  try {
    const raw = localStorage.getItem(UTM_KEY);
    return raw ? (JSON.parse(raw) as UtmParams) : null;
  } catch {
    return null;
  }
}

export function clearUtmParams(): void {
  if (typeof window === 'undefined') return;
  try {
    localStorage.removeItem(UTM_KEY);
  } catch {}
}

// ── Visitor ID ────────────────────────────────────────────────────────────────

/**
 * Generate a random visitor ID to link clicks to eventual signups.
 * Stored alongside the referral code so the backend can mark the
 * click row as converted_to_signup=true on registration.
 */
const VISITOR_KEY = 'sonoro_vid';

export function getOrCreateVisitorId(): string {
  if (typeof window === 'undefined') return '';
  try {
    let vid = localStorage.getItem(VISITOR_KEY);
    if (!vid) {
      vid = crypto.randomUUID();
      localStorage.setItem(VISITOR_KEY, vid);
    }
    return vid;
  } catch {
    return '';
  }
}
