/**
 * Settings Service
 * ================
 * API client for user settings and personalization endpoints (BLOCK 8E)
 */

import { apiClient } from './api-client';

// ============================================
// TYPE DEFINITIONS
// ============================================

export interface Profile {
  email: string;
  full_name: string | null;
  is_active: boolean;
  is_verified: boolean;
  role: string;
  created_at: string;
  updated_at: string;
}

export interface AccountPreferences {
  preferred_language: string;
  preferred_voice: string | null;
  timezone: string;
  currency: string;
  email_notifications: boolean;
  marketing_emails: boolean;
  usage_alerts: boolean;
}

export interface AccountPreferencesResponse {
  preferences: AccountPreferences;
  created_at: string;
  updated_at: string;
}

export interface APIKey {
  key_id: string;
  key_preview: string;
  created_at: string;
  last_used_at: string | null;
}

export interface APIKeysListResponse {
  keys: APIKey[];
  total: number;
}

export interface APIKeyResponse {
  key: string;
  key_id: string;
  created_at: string;
}

// ============================================
// PROFILE ENDPOINTS
// ============================================

/**
 * Get user profile
 */
export async function getProfile(): Promise<Profile> {
  const response = await apiClient.get('/account/profile');
  return response.data;
}

/**
 * Update user profile
 */
export async function updateProfile(data: { full_name?: string }): Promise<Profile> {
  const response = await apiClient.patch('/account/profile', data);
  return response.data;
}

// ============================================
// PREFERENCES ENDPOINTS
// ============================================

/**
 * Get account preferences
 */
export async function getPreferences(): Promise<AccountPreferencesResponse> {
  const response = await apiClient.get('/account/settings');
  return response.data;
}

/**
 * Update account preferences (partial update)
 */
export async function updatePreferences(
  data: Partial<AccountPreferences>
): Promise<AccountPreferencesResponse> {
  const response = await apiClient.patch('/account/settings', data);
  return response.data;
}

// ============================================
// PASSWORD ENDPOINTS
// ============================================

/**
 * Change password
 */
export async function changePassword(data: {
  current_password: string;
  new_password: string;
}): Promise<{ message: string }> {
  const response = await apiClient.post('/auth/change-password', data);
  return response.data;
}

// ============================================
// API KEY ENDPOINTS
// ============================================

/**
 * Generate new API key
 */
export async function generateAPIKey(): Promise<APIKeyResponse> {
  const response = await apiClient.post('/account/api-key');
  return response.data;
}

/**
 * List all API keys
 */
export async function listAPIKeys(): Promise<APIKeysListResponse> {
  const response = await apiClient.get('/account/api-keys');
  return response.data;
}

/**
 * Revoke API key
 */
export async function revokeAPIKey(keyId: string): Promise<{ message: string }> {
  const response = await apiClient.delete(`/account/api-key/${keyId}`);
  return response.data;
}

// ============================================
// ACCOUNT DELETION
// ============================================

/**
 * Delete account (soft delete)
 */
export async function deleteAccount(data: {
  password: string;
  confirmation: string;
}): Promise<{ message: string }> {
  const response = await apiClient.delete('/account/delete-account', {
    data,
  });
  return response.data;
}

// ============================================
// HELPER CONSTANTS
// ============================================

export const LANGUAGES = [
  { value: 'en', label: 'English' },
  { value: 'es', label: 'Spanish' },
  { value: 'fr', label: 'French' },
  { value: 'de', label: 'German' },
  { value: 'it', label: 'Italian' },
  { value: 'pt', label: 'Portuguese' },
  { value: 'nl', label: 'Dutch' },
  { value: 'pl', label: 'Polish' },
  { value: 'ru', label: 'Russian' },
  { value: 'ja', label: 'Japanese' },
  { value: 'zh', label: 'Chinese' },
];

export const VOICES = [
  { value: 'alloy', label: 'Alloy' },
  { value: 'echo', label: 'Echo' },
  { value: 'fable', label: 'Fable' },
  { value: 'onyx', label: 'Onyx' },
  { value: 'nova', label: 'Nova' },
  { value: 'shimmer', label: 'Shimmer' },
];

export const TIMEZONES = [
  { value: 'UTC', label: 'UTC' },
  { value: 'America/New_York', label: 'Eastern Time (US)' },
  { value: 'America/Chicago', label: 'Central Time (US)' },
  { value: 'America/Denver', label: 'Mountain Time (US)' },
  { value: 'America/Los_Angeles', label: 'Pacific Time (US)' },
  { value: 'Europe/London', label: 'London' },
  { value: 'Europe/Paris', label: 'Paris' },
  { value: 'Europe/Berlin', label: 'Berlin' },
  { value: 'Asia/Tokyo', label: 'Tokyo' },
  { value: 'Asia/Shanghai', label: 'Shanghai' },
  { value: 'Australia/Sydney', label: 'Sydney' },
];

export const CURRENCIES = [
  { value: 'USD', label: 'USD ($)' },
  { value: 'EUR', label: 'EUR (€)' },
  { value: 'GBP', label: 'GBP (£)' },
  { value: 'JPY', label: 'JPY (¥)' },
  { value: 'CAD', label: 'CAD ($)' },
  { value: 'AUD', label: 'AUD ($)' },
];
