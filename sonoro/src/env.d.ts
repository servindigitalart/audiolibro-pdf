/// <reference path="../.astro/types.d.ts" />

interface ImportMetaEnv {
  // Public — exposed to browser bundles via Vite
  readonly PUBLIC_API_URL: string;
  readonly PUBLIC_APP_URL: string;

  // Private — server-side only (Astro API routes, SSR)
  readonly API_URL: string;
  readonly SITE_URL: string;
  readonly GOOGLE_CLIENT_ID: string;
  readonly GOOGLE_CLIENT_SECRET: string;
  readonly GOOGLE_REDIRECT_URI: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
