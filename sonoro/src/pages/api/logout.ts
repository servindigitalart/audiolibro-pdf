import type { APIRoute } from 'astro';

export const POST: APIRoute = async ({ cookies, redirect }) => {
  const refreshToken = cookies.get('refresh_token')?.value;

  // Invalidate the refresh token in Redis so it can't be rotated again.
  // Non-fatal: if the backend is down the cookies are still cleared.
  if (refreshToken) {
    const BASE = import.meta.env.PUBLIC_API_URL ?? 'http://localhost:8000/api/v1';
    await fetch(`${BASE}/auth/logout`, {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({ refresh_token: refreshToken }),
    }).catch(() => {});
  }

  cookies.delete('access_token',  { path: '/' });
  cookies.delete('refresh_token', { path: '/' });

  return redirect('/login');
};
