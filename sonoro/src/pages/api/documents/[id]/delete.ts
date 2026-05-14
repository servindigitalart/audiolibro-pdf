import type { APIRoute } from 'astro';

export const POST: APIRoute = async ({ params, cookies, redirect }) => {
  const token = cookies.get('access_token')?.value;
  if (!token) return redirect('/login');

  const BASE = import.meta.env.PUBLIC_API_URL ?? 'http://localhost:8000/api/v1';
  await fetch(`${BASE}/documents/${params.id}`, {
    method:  'DELETE',
    headers: { Authorization: `Bearer ${token}` },
  });

  return redirect('/dashboard/documents');
};
