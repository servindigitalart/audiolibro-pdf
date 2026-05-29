/**
 * SEO infrastructure tests — sitemap content, robots rules, UTM capture, referral coexistence.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import {
  captureUtmParams,
  getUtmParams,
  clearUtmParams,
  captureReferralCode,
  getReferralCode,
  clearReferralCode,
} from '@/lib/referral';
import { PUBLIC_PAGES, buildSitemapXml } from '@/pages/sitemap.xml';

// ── Sitemap ───────────────────────────────────────────────────────────────────

describe('sitemap', () => {
  const xml = buildSitemapXml('https://sonoro.app');

  it('includes the homepage', () => {
    expect(xml).toContain('https://sonoro.app/</loc>');
  });

  it('includes /pricing', () => {
    expect(xml).toContain('<loc>https://sonoro.app/pricing</loc>');
  });

  it('includes all 5 landing pages', () => {
    expect(xml).toContain('/pdf-to-audiobook');
    expect(xml).toContain('/ai-audiobook-generator');
    expect(xml).toContain('/listen-to-pdfs');
    expect(xml).toContain('/spanish-pdf-to-audio');
    expect(xml).toContain('/student-pdf-reader');
  });

  it('does NOT include private dashboard routes', () => {
    expect(xml).not.toContain('/dashboard');
    expect(xml).not.toContain('/admin');
    expect(xml).not.toContain('/onboarding');
  });

  it('does NOT include auth pages', () => {
    expect(xml).not.toContain('/login');
    expect(xml).not.toContain('/register');
  });

  it('does NOT include API routes', () => {
    expect(xml).not.toContain('/api/');
  });

  it('is valid XML with urlset root', () => {
    expect(xml).toMatch(/^<\?xml version="1\.0"/);
    expect(xml).toContain('<urlset xmlns=');
    expect(xml).toContain('</urlset>');
  });

  it('every entry has loc, lastmod, changefreq, priority', () => {
    PUBLIC_PAGES.forEach((p) => {
      const bloc = xml.slice(xml.indexOf(`<loc>https://sonoro.app${p.loc}`));
      expect(bloc).toContain('<lastmod>');
      expect(bloc).toContain('<changefreq>');
      expect(bloc).toContain('<priority>');
    });
  });

  it('homepage has highest priority 1.0', () => {
    const home = PUBLIC_PAGES.find((p) => p.loc === '/');
    expect(home?.priority).toBe('1.0');
  });

  it('uses provided siteUrl as base', () => {
    const custom = buildSitemapXml('https://staging.sonoro.app');
    expect(custom).toContain('https://staging.sonoro.app/</loc>');
    expect(custom).not.toContain('https://sonoro.app/</loc>');
  });
});

// ── robots.txt rules (content verification) ──────────────────────────────────

describe('robots disallow list', () => {
  const PRIVATE_PATHS = [
    '/dashboard/',
    '/admin/',
    '/onboarding',
    '/api/',
    '/login',
    '/register',
  ];

  it('robots content disallows all private paths', async () => {
    // Import the handler and call GET to get the body text
    const { GET } = await import('@/pages/robots.txt');
    const response = GET({} as any);
    const text = await (response as Response).text();

    PRIVATE_PATHS.forEach((path) => {
      expect(text).toContain(`Disallow: ${path}`);
    });
  });

  it('robots allows public root', async () => {
    const { GET } = await import('@/pages/robots.txt');
    const response = GET({} as any);
    const text = await (response as Response).text();
    expect(text).toContain('Allow: /');
  });

  it('robots references sitemap', async () => {
    const { GET } = await import('@/pages/robots.txt');
    const response = GET({} as any);
    const text = await (response as Response).text();
    expect(text).toContain('Sitemap:');
    expect(text).toContain('/sitemap.xml');
  });
});

// ── UTM capture ───────────────────────────────────────────────────────────────

describe('captureUtmParams', () => {
  beforeEach(() => {
    clearUtmParams();
    // Reset location search
    Object.defineProperty(window, 'location', {
      writable: true,
      value: { search: '', pathname: '/test' },
    });
  });

  afterEach(() => clearUtmParams());

  it('does nothing when no UTM params in URL', () => {
    window.location.search = '';
    captureUtmParams();
    expect(getUtmParams()).toBeNull();
  });

  it('captures utm_source', () => {
    window.location.search = '?utm_source=google';
    captureUtmParams();
    expect(getUtmParams()?.utm_source).toBe('google');
  });

  it('captures all UTM params', () => {
    window.location.search = '?utm_source=twitter&utm_medium=social&utm_campaign=launch&utm_content=hero&utm_term=pdf+audiobook';
    captureUtmParams();
    const p = getUtmParams();
    expect(p?.utm_source).toBe('twitter');
    expect(p?.utm_medium).toBe('social');
    expect(p?.utm_campaign).toBe('launch');
    expect(p?.utm_content).toBe('hero');
    expect(p?.utm_term).toBe('pdf audiobook');
  });

  it('stores the landing path alongside UTM params', () => {
    window.location.search = '?utm_source=email';
    window.location.pathname = '/pdf-to-audiobook';
    captureUtmParams();
    expect(getUtmParams()?.landing_path).toBe('/pdf-to-audiobook');
  });

  it('clearUtmParams removes stored data', () => {
    window.location.search = '?utm_source=test';
    captureUtmParams();
    expect(getUtmParams()).not.toBeNull();
    clearUtmParams();
    expect(getUtmParams()).toBeNull();
  });
});

// ── Referral + UTM coexistence ────────────────────────────────────────────────

describe('referral and UTM coexistence', () => {
  beforeEach(() => {
    clearReferralCode();
    clearUtmParams();
    Object.defineProperty(window, 'location', {
      writable: true,
      value: { search: '?ref=creator123&utm_source=youtube&utm_medium=video', pathname: '/' },
    });
  });

  afterEach(() => {
    clearReferralCode();
    clearUtmParams();
  });

  it('capturing referral code does not clear UTM params', () => {
    captureReferralCode();
    captureUtmParams();
    expect(getReferralCode()).toBe('creator123');
    expect(getUtmParams()?.utm_source).toBe('youtube');
  });

  it('clearing referral does not clear UTM params', () => {
    captureReferralCode();
    captureUtmParams();
    clearReferralCode();
    expect(getReferralCode()).toBeNull();
    expect(getUtmParams()?.utm_source).toBe('youtube');
  });

  it('clearing UTM does not clear referral code', () => {
    captureReferralCode();
    captureUtmParams();
    clearUtmParams();
    expect(getReferralCode()).toBe('creator123');
    expect(getUtmParams()).toBeNull();
  });
});

// ── Canonical URL tracking-param stripping (pure logic) ───────────────────────

describe('canonical URL tracking param stripping', () => {
  function stripTrackingParams(urlStr: string): string {
    const url = new URL(urlStr);
    ['ref', 'utm_source', 'utm_medium', 'utm_campaign', 'utm_content', 'utm_term'].forEach(
      (p) => url.searchParams.delete(p),
    );
    return url.toString();
  }

  it('strips ?ref= from canonical', () => {
    const out = stripTrackingParams('https://sonoro.app/pdf-to-audiobook?ref=creator');
    expect(out).toBe('https://sonoro.app/pdf-to-audiobook');
  });

  it('strips all utm_* params', () => {
    const out = stripTrackingParams(
      'https://sonoro.app/?utm_source=google&utm_medium=cpc&utm_campaign=brand',
    );
    expect(out).toBe('https://sonoro.app/');
  });

  it('preserves non-tracking query params', () => {
    const out = stripTrackingParams('https://sonoro.app/pricing?plan=pro&ref=creator&utm_source=email');
    expect(out).toBe('https://sonoro.app/pricing?plan=pro');
  });

  it('leaves clean URLs unchanged', () => {
    const url = 'https://sonoro.app/pdf-to-audiobook';
    expect(stripTrackingParams(url)).toBe(url);
  });
});
