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
          const { data } = await axios.post(`${BASE}/auth/refresh`, {
            refresh_token: refresh,
          });
          setTokens(data.access_token, data.refresh_token);
          if (original.headers) {
            original.headers.Authorization = `Bearer ${data.access_token}`;
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

export async function register(email: string, password: string) {
  const { data } = await api.post('/auth/register', { email, password });
  setTokens(data.access_token, data.refresh_token);
  return data;
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

// ── Documents ────────────────────────────────────────────────────────────────

export async function uploadDocument(
  file: File,
  onProgress?: (pct: number) => void
) {
  const fd = new FormData();
  fd.append('file', file);
  const { data } = await api.post('/documents/upload', fd, {
    headers: { 'Content-Type': 'multipart/form-data' },
    onUploadProgress: (e) => {
      if (onProgress && e.total) onProgress(Math.round((e.loaded / e.total) * 100));
    },
  });
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

export async function getChapters(documentId: string) {
  const { data } = await api.get(`/documents/${documentId}/chapters`);
  return data;
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
  const { data } = await api.post('/billing/checkout', { tier, interval });
  return data as { url: string };
}

export async function createPortalSession() {
  const { data } = await api.post('/billing/portal');
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
