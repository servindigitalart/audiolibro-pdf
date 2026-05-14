/**
 * Client-side API client — used in React islands.
 * Axios instance with JWT cookie injection + auto-refresh + redirect on 401.
 */

import axios, { type AxiosError, type InternalAxiosRequestConfig } from 'axios';
import Cookies from 'js-cookie';

const BASE = (import.meta as any).env?.PUBLIC_API_URL ?? 'http://localhost:8000/api/v1';

export const api = axios.create({
  baseURL: BASE,
  timeout: 30_000,
  headers: { 'Content-Type': 'application/json' },
});

api.interceptors.request.use((config: InternalAxiosRequestConfig) => {
  const token = Cookies.get('access_token');
  if (token && config.headers) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

api.interceptors.response.use(
  (r) => r,
  async (error: AxiosError) => {
    const original = error.config as InternalAxiosRequestConfig & { _retry?: boolean };

    if (error.response?.status === 401 && !original._retry) {
      original._retry = true;

      const refresh = Cookies.get('refresh_token');
      if (refresh) {
        try {
          const { data } = await axios.post(`${BASE}/auth/refresh`, { refresh_token: refresh });
          Cookies.set('access_token', data.access_token, { secure: true, sameSite: 'strict', expires: 1 / 48 });
          if (data.refresh_token) {
            Cookies.set('refresh_token', data.refresh_token, { secure: true, sameSite: 'strict', expires: 7 });
          }
          if (original.headers) original.headers.Authorization = `Bearer ${data.access_token}`;
          return api(original);
        } catch {
          // fall through to redirect
        }
      }

      Cookies.remove('access_token');
      Cookies.remove('refresh_token');
      window.location.href = '/login';
    }

    return Promise.reject(error);
  }
);

// ── Auth ─────────────────────────────────────────────────────────────────────

export async function login(email: string, password: string) {
  const body = new URLSearchParams({ username: email, password });
  const { data } = await api.post('/auth/login', body, {
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
  });
  setTokens(data.access_token, data.refresh_token);
  return data;
}

export async function register(email: string, password: string) {
  const { data } = await api.post('/auth/register', { email, password });
  setTokens(data.access_token, data.refresh_token);
  return data;
}

export async function logout() {
  try { await api.post('/auth/logout'); } catch {}
  Cookies.remove('access_token');
  Cookies.remove('refresh_token');
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

export async function createCheckoutSession(tier: string, interval: 'monthly' | 'annual' = 'monthly') {
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
  Cookies.set('access_token', accessToken,  { secure: isProd, sameSite: 'strict', expires: 1 / 48 });
  Cookies.set('refresh_token', refreshToken, { secure: isProd, sameSite: 'strict', expires: 7 });
}

export function getErrorMessage(err: unknown): string {
  if (axios.isAxiosError(err)) {
    const d = err.response?.data;
    if (typeof d?.detail === 'string') return d.detail;
    if (Array.isArray(d?.detail)) return d.detail[0]?.msg ?? 'Validation error';
    return err.message;
  }
  return err instanceof Error ? err.message : 'An unknown error occurred';
}

export default api;
