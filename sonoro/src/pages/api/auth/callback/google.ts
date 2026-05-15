/**
 * GET /api/auth/callback/google
 *
 * Google OAuth callback handler (server-side, never visible to client JS).
 *
 * 1. Validates CSRF state cookie against the state Google echoed.
 * 2. POSTs the authorization code to FastAPI (server-to-server).
 * 3. FastAPI exchanges with Google, provisions the user, issues Sonoro JWTs.
 * 4. Sets access_token + refresh_token cookies.
 * 5. Redirects to the intended destination (onboarding for new users).
 *
 * Cookie note: access_token and refresh_token are NOT httpOnly so that
 * the client-side Axios interceptor in lib/api/client.ts can read them
 * for Bearer-token injection and silent refresh rotation.
 * The oauth_state / oauth_next cookies ARE httpOnly (JS never needs them).
 */

import type { APIRoute } from 'astro';

const API_URL  = import.meta.env.API_URL  ?? 'http://localhost:8000';
const SITE_URL = import.meta.env.SITE_URL ?? 'http://localhost:3000';

export const GET: APIRoute = async ({ cookies, url, redirect }) => {
  const code  = url.searchParams.get('code');
  const state = url.searchParams.get('state');
  const error = url.searchParams.get('error');

  // User declined or provider error
  if (error) {
    const msg = error === 'access_denied' ? 'cancelled' : error;
    return redirect(`/login?error=${encodeURIComponent(msg)}`);
  }

  if (!code || !state) {
    return redirect('/login?error=missing_params');
  }

  // --- CSRF verification ---
  const storedState = cookies.get('oauth_state')?.value;
  if (!storedState || storedState !== state) {
    // State mismatch: possible CSRF or expired flow
    return redirect('/login?error=invalid_state');
  }

  const next = cookies.get('oauth_next')?.value ?? '/dashboard';

  // Consume the one-time state cookies immediately
  cookies.delete('oauth_state', { path: '/' });
  cookies.delete('oauth_next',  { path: '/' });

  // --- Exchange with FastAPI (server-to-server) ---
  let tokens: {
    access_token:  string;
    refresh_token: string;
    is_new_user:   boolean;
  };

  try {
    const res = await fetch(`${API_URL}/api/v1/auth/oauth/google/exchange`, {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({
        code,
        redirect_uri: `${SITE_URL}/api/auth/callback/google`,
      }),
    });

    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      console.error('[oauth/callback] exchange failed', res.status, body);
      return redirect('/login?error=oauth_failed');
    }

    tokens = await res.json();
  } catch (err) {
    console.error('[oauth/callback] network error', err);
    return redirect('/login?error=server_error');
  }

  // --- Set auth cookies ---
  // sameSite: lax  — strict would break future cross-site navigations
  // NOT httpOnly   — client.ts must read these for Bearer injection + refresh
  const BASE = {
    secure:   import.meta.env.PROD,
    sameSite: 'lax' as const,
    path:     '/',
  };

  cookies.set('access_token',  tokens.access_token,  { ...BASE, maxAge: 15 * 60 });
  cookies.set('refresh_token', tokens.refresh_token, { ...BASE, maxAge: 7 * 24 * 60 * 60 });

  // New users with no explicit destination go to onboarding
  const destination =
    tokens.is_new_user && next === '/dashboard' ? '/onboarding' : next;

  return redirect(destination.startsWith('/') ? destination : '/dashboard');
};
