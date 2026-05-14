/**
 * Server-side API client — used in Astro page frontmatter.
 * Uses native fetch with the access_token cookie from Astro.cookies.
 */

import type { TierConfig, Document, AccountOverview } from './types';

const BASE = import.meta.env.PUBLIC_API_URL ?? 'http://localhost:8000/api/v1';

function authHeaders(token?: string): HeadersInit {
  return {
    'Content-Type': 'application/json',
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  };
}

async function get<T>(path: string, token?: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: authHeaders(token),
    cache: 'no-store',
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail ?? `API error ${res.status}`);
  }
  return res.json() as Promise<T>;
}

// ── Public endpoints (no auth needed) ──────────────────────────────────────

export async function fetchTierCatalog(): Promise<TierConfig[]> {
  return get<TierConfig[]>('/pricing/tiers');
}

// ── Authenticated endpoints ─────────────────────────────────────────────────

export async function fetchAccountOverview(token: string): Promise<AccountOverview> {
  return get<AccountOverview>('/account/overview', token);
}

export async function fetchDocuments(token: string): Promise<Document[]> {
  return get<Document[]>('/documents', token);
}

export async function fetchDocument(token: string, id: string): Promise<Document> {
  return get<Document>(`/documents/${id}`, token);
}
