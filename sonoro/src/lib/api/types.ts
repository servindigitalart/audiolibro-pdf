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
  stage?: 'analyzing' | 'detecting_chapters' | 'generating_audio' | 'finalizing';
  progress: number;
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
