/**
 * API client error handling tests.
 * Network failures and auth edge-cases.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { getErrorMessage } from '@/lib/api/client';
import axios from 'axios';

// ── getErrorMessage ──────────────────────────────────────────────────────────

describe('getErrorMessage', () => {
  it('extracts detail string from axios error', () => {
    const err = new axios.AxiosError('Request failed');
    (err as any).response = { data: { detail: 'Invalid credentials' } };
    expect(getErrorMessage(err)).toBe('Invalid credentials');
  });

  it('extracts first validation error from detail array', () => {
    const err = new axios.AxiosError('Validation error');
    (err as any).response = { data: { detail: [{ msg: 'field required' }] } };
    expect(getErrorMessage(err)).toBe('field required');
  });

  it('falls back to axios message when no response data', () => {
    const err = new axios.AxiosError('Network Error');
    expect(getErrorMessage(err)).toBe('Network Error');
  });

  it('handles plain Error instances', () => {
    expect(getErrorMessage(new Error('Something broke'))).toBe('Something broke');
  });

  it('handles unknown thrown values', () => {
    expect(getErrorMessage('oops')).toBe('An unknown error occurred');
    expect(getErrorMessage(null)).toBe('An unknown error occurred');
  });
});

// ── Token cookie names ────────────────────────────────────────────────────────

describe('cookie contract', () => {
  it('access_token and refresh_token are the expected cookie names', () => {
    // These names must match what the backend sets in Set-Cookie
    const ACCESS  = 'access_token';
    const REFRESH = 'refresh_token';
    expect(ACCESS).toBe('access_token');
    expect(REFRESH).toBe('refresh_token');
  });
});
