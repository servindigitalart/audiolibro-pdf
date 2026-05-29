import type { APIRoute } from 'astro';

export const GET: APIRoute = () => {
  const siteUrl =
    import.meta.env.SITE_URL ??
    import.meta.env.PUBLIC_SITE_URL ??
    'https://sonoro.app';

  const body = `User-agent: *
Allow: /

# Private app routes — never index
Disallow: /dashboard/
Disallow: /admin/
Disallow: /onboarding
Disallow: /api/
Disallow: /auth/

# Auth pages — no value to index
Disallow: /login
Disallow: /register

Sitemap: ${siteUrl}/sitemap.xml
`;

  return new Response(body, {
    headers: {
      'Content-Type': 'text/plain; charset=utf-8',
      'Cache-Control': 'public, max-age=86400',
    },
  });
};
