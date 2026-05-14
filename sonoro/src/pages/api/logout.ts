import type { APIRoute } from 'astro';

export const POST: APIRoute = async ({ cookies, redirect }) => {
  const token = cookies.get('access_token')?.value;

  // Invalidate server-side session if token present
  if (token) {
    const BASE = import.meta.env.PUBLIC_API_URL ?? 'http://localhost:8000/api/v1';
    await fetch(`${BASE}/auth/logout`, {
      method:  'POST',
      headers: { Authorization: `Bearer ${token}` },
    }).catch(() => {}); // Non-fatal
  }

  cookies.delete('access_token',  { path: '/' });
  cookies.delete('refresh_token', { path: '/' });

  return redirect('/login');
};
