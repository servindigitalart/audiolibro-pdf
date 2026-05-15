/**
 * GET /api/auth/google
 *
 * Initiates the Google OAuth flow.
 *
 * 1. Generates a cryptographically random CSRF nonce.
 * 2. Stores the nonce + post-auth destination in short-lived httpOnly cookies.
 * 3. Redirects the browser to Google's authorization endpoint.
 *
 * Query params:
 *   ?next=<path>   — where to send the user after auth (default: /dashboard)
 *   ?plan=<tier>   — pre-selected plan from the pricing/register page
 *                    (encoded into next as /onboarding?plan=<tier>)
 */

import { randomBytes } from 'node:crypto';
import type { APIRoute } from 'astro';

export const GET: APIRoute = async ({ cookies, url, redirect }) => {
  const clientId = import.meta.env.GOOGLE_CLIENT_ID;
  const siteUrl  = import.meta.env.SITE_URL ?? 'http://localhost:3000';

  if (!clientId) {
    return new Response('Google OAuth is not configured', { status: 503 });
  }

  // Resolve the post-auth destination.
  // ?plan= is a legacy param from RegisterForm; encode it into the next path.
  const plan        = url.searchParams.get('plan');
  const rawNext     = url.searchParams.get('next') ?? '/dashboard';
  const resolvedNext = plan
    ? `/onboarding?plan=${encodeURIComponent(plan)}`
    : rawNext;

  // CSRF nonce — compared against the state Google echoes back in the callback.
  const nonce = randomBytes(16).toString('hex');

  const COOKIE = {
    httpOnly: true,
    secure:   import.meta.env.PROD,
    sameSite: 'lax' as const,  // lax required: Google redirects cross-site
    maxAge:   600,              // 10-minute window to complete OAuth
    path:     '/',
  };

  cookies.set('oauth_state', nonce,        COOKIE);
  cookies.set('oauth_next',  resolvedNext, COOKIE);

  const params = new URLSearchParams({
    client_id:     clientId,
    redirect_uri:  `${siteUrl}/api/auth/callback/google`,
    response_type: 'code',
    scope:         'openid email profile',
    state:         nonce,
    access_type:   'offline',
    prompt:        'select_account',
  });

  return redirect(
    `https://accounts.google.com/o/oauth2/v2/auth?${params}`,
    302,
  );
};
