import type { APIRoute } from 'astro';

const SITE_URL =
  import.meta.env.SITE_URL ??
  import.meta.env.PUBLIC_SITE_URL ??
  'https://sonoro.app';

export const PUBLIC_PAGES = [
  { loc: '/',                       priority: '1.0', changefreq: 'weekly'  },
  { loc: '/pricing',                priority: '0.9', changefreq: 'weekly'  },
  { loc: '/pdf-to-audiobook',       priority: '0.8', changefreq: 'monthly' },
  { loc: '/ai-audiobook-generator', priority: '0.8', changefreq: 'monthly' },
  { loc: '/listen-to-pdfs',         priority: '0.7', changefreq: 'monthly' },
  { loc: '/spanish-pdf-to-audio',   priority: '0.7', changefreq: 'monthly' },
  { loc: '/student-pdf-reader',     priority: '0.7', changefreq: 'monthly' },
] as const;

export function buildSitemapXml(siteUrl = SITE_URL): string {
  const today = new Date().toISOString().split('T')[0];
  return [
    '<?xml version="1.0" encoding="UTF-8"?>',
    '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    ...PUBLIC_PAGES.map((p) =>
      [
        '  <url>',
        `    <loc>${siteUrl}${p.loc}</loc>`,
        `    <lastmod>${today}</lastmod>`,
        `    <changefreq>${p.changefreq}</changefreq>`,
        `    <priority>${p.priority}</priority>`,
        '  </url>',
      ].join('\n')
    ),
    '</urlset>',
  ].join('\n');
}

export const GET: APIRoute = () =>
  new Response(buildSitemapXml(), {
    headers: {
      'Content-Type': 'application/xml; charset=utf-8',
      'Cache-Control': 'public, max-age=3600',
    },
  });
