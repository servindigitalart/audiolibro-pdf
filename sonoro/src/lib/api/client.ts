/**
 * Client-side API client — used in React islands.
 * Axios instance with JWT cookie injection, silent token refresh, and 401 redirect.
 *
 * Cookie contract (must match the server-side callback and logout endpoints):
 *   access_token  — short-lived (15 min), readable by JS, SameSite=Lax
 *   refresh_token — long-lived  (7 days), readable by JS, SameSite=Lax
 *
 * The cookies are intentionally NOT httpOnly so this interceptor can
 * read and rotate them without a server round-trip for every request.
 */

import axios, { type AxiosError, type InternalAxiosRequestConfig } from 'axios';
import Cookies from 'js-cookie';
import type { UploadResponse } from './types';

if (typeof window !== 'undefined' && !import.meta.env.PUBLIC_API_URL) {
  console.error('[Sonoro] PUBLIC_API_URL is not set. Uploads and API calls will fail in production. Set this variable in your Vercel environment settings.');
}

const BASE = import.meta.env.PUBLIC_API_URL ?? 'http://localhost:8000/api/v1';

export const api = axios.create({
  baseURL: BASE,
  timeout: 30_000,
  headers: { 'Content-Type': 'application/json' },
});

// Inject the access token as a Bearer header on every outbound request
api.interceptors.request.use((config: InternalAxiosRequestConfig) => {
  const token = Cookies.get('access_token');
  if (token && config.headers) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// Serialises token refreshes — prevents two simultaneous 401s from both calling /auth/refresh
let _refreshPromise: Promise<void> | null = null;

// On 401: attempt silent token rotation, then retry once; otherwise redirect to login
api.interceptors.response.use(
  (r) => r,
  async (error: AxiosError) => {
    const original = error.config as InternalAxiosRequestConfig & { _retry?: boolean };

    if (error.response?.status === 401 && !original._retry) {
      original._retry = true;

      const refresh = Cookies.get('refresh_token');
      if (refresh) {
        try {
          // Coalesce concurrent refresh calls into a single request
          if (!_refreshPromise) {
            _refreshPromise = axios
              .post(`${BASE}/auth/refresh`, { refresh_token: refresh })
              .then(({ data }) => {
                setTokens(data.access_token, data.refresh_token);
              })
              .finally(() => {
                _refreshPromise = null;
              });
          }
          await _refreshPromise;

          const newToken = Cookies.get('access_token');
          if (original.headers && newToken) {
            original.headers.Authorization = `Bearer ${newToken}`;
          }
          return api(original);
        } catch {
          // Refresh failed — fall through to hard logout
        }
      }

      clearTokens();
      window.location.href = '/login';
    }

    return Promise.reject(error);
  }
);

// ── Auth ─────────────────────────────────────────────────────────────────────

export async function login(email: string, password: string) {
  // JSON body — FastAPI LoginRequest expects { email, password }
  const { data } = await api.post('/auth/login', { email, password });
  setTokens(data.access_token, data.refresh_token);
  return data;
}

export async function register(
  email: string,
  password: string,
  referralCode?: string,
  visitorId?: string,
) {
  const { data } = await api.post('/auth/register', {
    email,
    password,
    ...(referralCode ? { referral_code: referralCode } : {}),
    ...(visitorId    ? { visitor_id:   visitorId    } : {}),
  });
  setTokens(data.access_token, data.refresh_token);
  return data;
}

// ── Affiliate API ─────────────────────────────────────────────────────────────

export async function getAffiliateMe() {
  const { data } = await api.get('/affiliate/me');
  return data;
}

export async function getAffiliateDashboard() {
  const { data } = await api.get('/affiliate/dashboard');
  return data;
}

export async function trackReferralClick(
  slug: string,
  visitorId?: string,
  landingPath?: string,
) {
  try {
    await api.post('/referral/track', {
      slug,
      visitor_id: visitorId,
      landing_path: landingPath,
    });
  } catch {
    // Fire-and-forget — never surface errors
  }
}

export async function logout() {
  // Send the refresh token so the backend can delete the Redis JTI entry
  const refresh = Cookies.get('refresh_token');
  try {
    await api.post('/auth/logout', { refresh_token: refresh ?? '' });
  } catch {}
  clearTokens();
}

export async function getMe() {
  const { data } = await api.get('/auth/me');
  return data;
}

/**
 * Probe the session before making billing API calls.
 * Calling /auth/me routes through the 401 interceptor which will silently
 * rotate an expired access token using the refresh token, so subsequent
 * requests (e.g. checkout) will have a fresh token available.
 */
export async function probeSession(): Promise<boolean> {
  try {
    await api.get('/auth/me');
    console.log('[client] billing_session_refreshed');
    return true;
  } catch {
    console.warn('[client] checkout_auth_missing – session could not be rehydrated');
    return false;
  }
}

// ── Documents ────────────────────────────────────────────────────────────────

export async function uploadDocument(
  file: File,
  onProgress?: (pct: number) => void,
  forceReprocess = false,
  preflightOnly = true,
): Promise<UploadResponse> {
  const fd = new FormData();
  fd.append('file', file);
  if (forceReprocess) fd.append('force_reprocess', 'true');
  if (preflightOnly) fd.append('preflight_only', 'true');
  const { data } = await api.post<UploadResponse>('/documents/upload', fd, {
    headers: { 'Content-Type': 'multipart/form-data' },
    onUploadProgress: (e) => {
      if (onProgress && e.total) onProgress(Math.round((e.loaded / e.total) * 100));
    },
  });
  return data;
}

export async function startProcessing(
  documentId: string,
  voiceId?: string,
  narrationStyle?: string,
): Promise<{ job_id: string; status: string }> {
  const body: Record<string, string> = {};
  if (voiceId)        body.voice_id        = voiceId;
  if (narrationStyle) body.narration_style = narrationStyle;
  const { data } = await api.post(
    `/documents/${documentId}/process`,
    Object.keys(body).length ? body : undefined,
  );
  return data;
}

export async function getDocuments() {
  const { data } = await api.get('/documents');
  return data;
}

export async function getDocument(id: string) {
  const { data } = await api.get(`/documents/${id}`);
  return data;
}

export async function deleteDocument(id: string) {
  await api.delete(`/documents/${id}`);
}

export async function getProcessingJob(documentId: string) {
  try {
    const { data } = await api.get(`/documents/${documentId}/job`);
    return data;
  } catch {
    return null;
  }
}

export async function retryProcessing(documentId: string) {
  const { data } = await api.post(`/documents/${documentId}/retry`);
  return data;
}

export async function renameDocumentTitle(documentId: string, displayTitle: string) {
  const { data } = await api.patch(`/documents/${documentId}/title`, { display_title: displayTitle });
  return data as { id: string; display_title: string };
}

export async function cancelDocument(documentId: string) {
  const { data } = await api.post(`/documents/${documentId}/cancel`);
  return data as { status: string; document_id: string };
}

export async function uploadCover(documentId: string, file: File): Promise<{ cover_url: string }> {
  const fd = new FormData();
  fd.append('file', file);
  const { data } = await api.post(`/documents/${documentId}/cover`, fd, {
    headers: { 'Content-Type': 'multipart/form-data' },
  });
  return data as { cover_url: string };
}

export async function resetCover(documentId: string): Promise<void> {
  await api.delete(`/documents/${documentId}/cover`);
}

export async function patchBookMetadata(
  documentId: string,
  fields: { display_title?: string; author?: string; subtitle?: string; isbn?: string },
) {
  const { data } = await api.patch(`/documents/${documentId}/metadata`, fields);
  return data as { id: string; display_title?: string; author?: string; subtitle?: string; isbn?: string };
}

export function audioDownloadUrl(documentId: string): string {
  const BASE = import.meta.env.PUBLIC_API_URL ?? 'http://localhost:8000/api/v1';
  return `${BASE}/documents/${documentId}/audio`;
}

export async function getChapters(documentId: string) {
  const { data } = await api.get(`/documents/${documentId}/chapters`);
  return data;
}

export async function renameChapter(documentId: string, chapterId: string, title: string) {
  const { data } = await api.patch(`/documents/${documentId}/chapters/${chapterId}`, { title });
  return data as { id: string; title: string };
}

export async function deleteChapter(documentId: string, chapterId: string) {
  const { data } = await api.delete(`/documents/${documentId}/chapters/${chapterId}`);
  return data as { deleted: boolean; id: string };
}

// ── Billing ──────────────────────────────────────────────────────────────────

export async function getAccountOverview() {
  const { data } = await api.get('/account/overview');
  return data;
}

export async function createCheckoutSession(
  tier: string,
  interval: 'monthly' | 'annual' = 'monthly'
) {
  if (!Cookies.get('access_token')) {
    console.warn('[client] checkout_auth_missing tier=', tier, '– no access_token cookie');
  }
  try {
    const { data } = await api.post('/billing/checkout', { tier, interval });
    console.log('[client] checkout_response_url=', data?.url, 'tier=', tier, 'interval=', interval);
    return data as { url: string };
  } catch (err) {
    if (axios.isAxiosError(err) && err.response?.status === 401) {
      console.warn('[client] checkout_auth_missing tier=', tier, '– 401 from checkout endpoint');
    }
    throw err;
  }
}

export async function createPortalSession() {
  const return_url = `${window.location.origin}/dashboard/billing`;
  const { data } = await api.post('/billing/portal', { return_url });
  return data as { url: string };
}

// ── Helpers ──────────────────────────────────────────────────────────────────

function setTokens(accessToken: string, refreshToken: string) {
  const isProd = location.hostname !== 'localhost';
  // SameSite=Lax: consistent with the server-side OAuth callback cookies
  Cookies.set('access_token',  accessToken,  { secure: isProd, sameSite: 'Lax', expires: 1 / 48 });
  Cookies.set('refresh_token', refreshToken, { secure: isProd, sameSite: 'Lax', expires: 7 });
}

function clearTokens() {
  Cookies.remove('access_token');
  Cookies.remove('refresh_token');
}

// Module-level blob URL cache — persists for the browser session
const _previewBlobCache = new Map<string, string>();

/**
 * Generate and cache a short TTS audio preview for a voice.
 * Returns a blob URL suitable for use with `new Audio(url)`.
 * Throws if the API is unavailable; caller should show an error state.
 */
export async function previewVoice(
  voiceId: string,
  languageCode: string,
  narrationStyle?: string,
): Promise<string> {
  const key = `${voiceId}:${languageCode}:${narrationStyle ?? ''}`;
  const cached = _previewBlobCache.get(key);
  if (cached) return cached;

  const response = await api.get('/voices/preview', {
    params: {
      voice_id:      voiceId,
      language_code: languageCode,
      ...(narrationStyle ? { narration_style: narrationStyle } : {}),
    },
    responseType: 'blob',
  });
  const blobUrl = URL.createObjectURL(response.data as Blob);
  _previewBlobCache.set(key, blobUrl);
  return blobUrl;
}

export function getErrorMessage(err: unknown): string {
  if (axios.isAxiosError(err)) {
    const d = err.response?.data;
    if (typeof d?.detail === 'string')  return d.detail;
    if (Array.isArray(d?.detail))       return d.detail[0]?.msg ?? 'Validation error';
    return err.message;
  }
  return err instanceof Error ? err.message : 'An unknown error occurred';
}

export default api;
