// Shared types between server and client API layers

export interface User {
  id: string;
  email: string;
  role: string;
  plan_tier: 'FREE' | 'BASIC' | 'PRO' | 'ENTERPRISE';
  is_active: boolean;
  is_verified: boolean;
  created_at: string;
}

export interface AuthTokens {
  access_token: string;
  refresh_token: string;
  token_type: string;
  user: User;
}

export interface Document {
  id: string;
  title: string;
  filename: string;
  file_size: number;
  status: 'pending' | 'processing' | 'completed' | 'failed';
  upload_date: string;
  completed_date?: string;
  error_message?: string;
  audiobook_url?: string;
  metadata?: {
    pages?: number;
    chapters?: number;
    duration_seconds?: number;
    file_type?: string;
  };
}

export interface ProcessingJob {
  id: string;
  document_id: string;
  status: 'queued' | 'processing' | 'completed' | 'failed';
  /** Mapped 4-step label used by the timeline UI. */
  stage?: 'analyzing' | 'detecting_chapters' | 'generating_audio' | 'finalizing';
  /** Raw pipeline stage stored in DB — use for labels and chunk display. */
  current_stage?: string;
  progress: number;
  /** TTS chunks completed so far. */
  completed_chunks?: number;
  /** Total TTS chunks across all chapters (set before TTS loop starts). */
  total_chunks?: number;
  /** Estimated seconds until completion, derived from chunk throughput. */
  estimated_seconds_remaining?: number;
  started_at?: string;
  completed_at?: string;
  error_message?: string;
  metadata?: {
    total_pages?: number;
    processed_pages?: number;
    total_chapters?: number;
    processed_chapters?: number;
    current_chapter?: string;
  };
}

export interface Chapter {
  id: string;
  document_id: string;
  chapter_number: number;
  title: string;
  start_page: number;
  end_page: number;
  confidence_score: number;
  audio_url?: string;
  duration_seconds?: number;
  status: 'pending' | 'processing' | 'completed' | 'failed';
}

export interface AccountOverview {
  user: User;
  usage: {
    chars_used: number;
    chars_limit: number;
    jobs_created: number;
    jobs_limit: number;
    storage_mb: number;
    storage_limit_mb: number;
  };
  billing: {
    plan_tier: string;
    status: string;
    current_period_end?: string;
    cancel_at_period_end?: boolean;
  };
}

export interface TierConfig {
  tier: string;
  monthly_price_usd: number;
  annual_price_usd: number;
  annual_savings_usd: number;
  limits: {
    monthly_chars: number;
    monthly_jobs: number;
    concurrent_jobs: number;
    storage_mb: number;
    daily_api_calls: number;
    api_calls_per_minute: number;
  };
  features: string[];
  max_team_members: number;
  trial_days: number;
  upgrades_to?: string;
}

export interface ApiError {
  detail: string;
  status?: number;
}

export interface AvailableVoice {
  voice_id: string;
  display_name: string;
}

export interface PreflightResult {
  language: string;
  language_name: string;
  voice_id: string;
  voice_display_name: string;
  available_voices: AvailableVoice[];
  estimated_characters: number;
  estimated_chapters: number;
  estimated_duration_seconds: number;
  estimated_processing_minutes: number;
  fits_current_plan: boolean;
  quota_exceeded: boolean;
  chars_limit: number;
  chars_used: number;
  chars_remaining_before: number;
  chars_remaining_after: number;
  plan_tier: string;
  plan_display_name: string;
}

/** Mirrors the backend DocumentUploadResponse schema. */
export interface UploadResponse {
  id: string;
  user_id: string;
  filename: string;
  original_filename: string;
  file_size_bytes: number;
  file_size_mb: number;
  mime_type: string;
  upload_status: string;
  processing_status: string;
  page_count: number | null;
  character_estimate: number | null;
  language_detected: string | null;
  checksum_sha256: string;
  created_at: string;
  /** True when this PDF was already uploaded by this user. */
  is_duplicate: boolean;
  /** Human-readable explanation shown in the duplicate banner. */
  duplicate_message: string | null;
  /** True when the duplicate previously failed and can be reprocessed. */
  can_reprocess: boolean;
  /** Pre-conversion analysis — populated when preflight_only=True. */
  preflight?: PreflightResult | null;
}
