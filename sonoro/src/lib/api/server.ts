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

// ── Normalization helpers ────────────────────────────────────────────────────
// The backend uses a richer schema than the lean frontend Document/AccountOverview
// types. These functions map backend field names to frontend expectations so that
// all SSR pages see a consistent, well-typed shape regardless of backend evolution.

type RawDocument = Record<string, unknown>;

function deriveStatus(
  processingStatus: string,
  uploadStatus: string,
): Document['status'] {
  if (processingStatus === 'completed') return 'completed';
  if (processingStatus === 'failed' || uploadStatus === 'failed') return 'failed';
  if (
    processingStatus === 'processing' ||
    processingStatus === 'assembling' ||
    processingStatus === 'finalizing'
  ) return 'processing';
  return 'pending';
}

function normalizeDocument(raw: RawDocument): Document {
  const processingStatus = String(raw.processing_status ?? '');
  const uploadStatus     = String(raw.upload_status ?? '');
  const pageCount        = raw.page_count != null ? Number(raw.page_count) : undefined;
  const durationSeconds  = raw.audio_duration_seconds != null ? Number(raw.audio_duration_seconds) : undefined;

  const metadataFields = {
    ...(pageCount != null       ? { pages: pageCount }                : {}),
    ...(durationSeconds != null ? { duration_seconds: durationSeconds } : {}),
  };
  const metadata = Object.keys(metadataFields).length > 0 ? metadataFields : undefined;

  return {
    id:           String(raw.id ?? ''),
    title:        String(raw.display_title ?? raw.original_filename ?? raw.filename ?? 'Untitled'),
    display_title: raw.display_title ? String(raw.display_title) : undefined,
    author:       raw.author ? String(raw.author) : undefined,
    subtitle:     raw.subtitle ? String(raw.subtitle) : undefined,
    isbn:         raw.isbn ? String(raw.isbn) : undefined,
    metadata_source:     raw.metadata_source ? String(raw.metadata_source) : undefined,
    metadata_confidence: raw.metadata_confidence != null ? Number(raw.metadata_confidence) : undefined,
    filename:     String(raw.filename ?? ''),
    file_size:    Number(raw.file_size_bytes ?? raw.file_size ?? 0),
    status:       deriveStatus(processingStatus, uploadStatus),
    upload_date:  String(raw.created_at ?? new Date().toISOString()),
    updated_at:   raw.updated_at ? String(raw.updated_at) : undefined,
    completed_date: raw.processing_completed_at
      ? String(raw.processing_completed_at)
      : undefined,
    error_message: raw.error_message ? String(raw.error_message) : undefined,
    audiobook_url: raw.audio_url ? String(raw.audio_url) : undefined,
    cover_url:    raw.cover_url ? String(raw.cover_url) : undefined,
    metadata,
  };
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function normalizeAccountOverview(raw: any): AccountOverview {
  const user      = raw?.user      ?? {};
  const usage     = raw?.usage     ?? {};
  const remaining = raw?.remaining_quota ?? {};
  const charQuota = remaining?.characters ?? {};
  const jobQuota  = remaining?.jobs       ?? {};
  const storeQuota = remaining?.storage_mb ?? {};

  return {
    user: {
      id:          String(user.id          ?? ''),
      email:       String(user.email       ?? ''),
      role:        String(user.role        ?? 'user'),
      plan_tier:   (user.plan_tier as 'FREE' | 'BASIC' | 'PRO' | 'ENTERPRISE') ?? 'FREE',
      is_active:   Boolean(user.is_active   ?? true),
      is_verified: Boolean(user.is_verified ?? false),
      created_at:  String(user.created_at  ?? ''),
    },
    usage: {
      // Backend: characters_used / quota limit comes from remaining_quota
      chars_used:       Number(usage.characters_used  ?? 0),
      chars_limit:      Number(charQuota.limit         ?? 0),
      jobs_created:     Number(usage.jobs_created      ?? 0),
      jobs_limit:       Number(jobQuota.limit           ?? 0),
      storage_mb:       Number(usage.storage_used_mb   ?? 0),
      storage_limit_mb: Number(storeQuota.limit         ?? 0),
    },
    billing: {
      plan_tier:           String(user.plan_tier ?? 'FREE'),
      status:              String(raw?.plan      ?? 'active'),
      current_period_end:  raw?.current_period_end  ? String(raw.current_period_end) : undefined,
      cancel_at_period_end: Boolean(raw?.cancel_at_period_end ?? false),
    },
  };
}

// ── Public endpoints (no auth needed) ──────────────────────────────────────

export async function fetchTierCatalog(): Promise<TierConfig[]> {
  // Backend returns { tiers: [...] } — unwrap the envelope
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const raw = await get<any>('/pricing/tiers');
  const tiers: TierConfig[] = Array.isArray(raw) ? raw : (raw?.tiers ?? []);
  console.log(`[SSR] fetchTierCatalog count=${tiers.length}`);
  return tiers;
}

// ── Authenticated endpoints ─────────────────────────────────────────────────

export async function fetchAccountOverview(token: string): Promise<AccountOverview> {
  console.log('[SSR] billing_fetch_start');
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  let raw: any;
  try {
    raw = await get<any>('/account/overview', token);
  } catch (err) {
    console.error('[SSR] billing_fetch_failed error=', err instanceof Error ? err.message : err);
    throw err;
  }
  try {
    const result = normalizeAccountOverview(raw);
    console.log(`[SSR] billing_fetch_ok plan=${result.billing.plan_tier}`);
    return result;
  } catch (err) {
    console.error('[SSR] billing_normalize_failed error=', err instanceof Error ? err.message : err);
    throw err;
  }
}

export async function fetchDocuments(token: string): Promise<Document[]> {
  // Backend returns a paginated envelope: { documents: [...], total, page, ... }
  // Trailing slash avoids a FastAPI 307 redirect — Node.js fetch may strip the
  // Authorization header when following redirects, causing a silent 401.
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  let raw: any;
  try {
    raw = await get<any>('/documents/', token);
  } catch (err) {
    console.error('[SSR] fetchDocuments API call failed:', err instanceof Error ? err.message : err);
    return [];
  }

  // Tolerate both a plain array (in case the API ever changes) and the paginated envelope
  const items: RawDocument[] = Array.isArray(raw)
    ? raw
    : Array.isArray(raw?.documents)
    ? raw.documents
    : [];

  console.log(`[SSR] fetchDocuments raw_count=${items.length}`);

  try {
    const docs = items.map(normalizeDocument);
    console.log(`[SSR] fetchDocuments normalized_count=${docs.length} statuses=${docs.map(d => d.status).join(',')}`);
    return docs;
  } catch (err) {
    console.error('[SSR] Failed to normalize documents list:', err);
    return [];
  }
}

export async function fetchDocument(token: string, id: string): Promise<Document> {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const raw = await get<any>(`/documents/${id}`, token);
  return normalizeDocument(raw as RawDocument);
}
