import { defineMiddleware } from 'astro:middleware';

// Routes that require an authenticated session
const PROTECTED = ['/dashboard', '/onboarding'];

// Routes that redirect to /dashboard when already authenticated
const AUTH_ONLY = ['/login', '/register'];

export const onRequest = defineMiddleware(async ({ cookies, url, redirect, locals }, next) => {
  const token = cookies.get('access_token')?.value ?? null;
  const path  = url.pathname;

  // Make the token available to every SSR page without re-reading cookies
  (locals as any).token = token;

  // /api/* routes handle their own auth — never intercept them here
  if (path.startsWith('/api/')) return next();

  const needsAuth  = PROTECTED.some((p) => path.startsWith(p));
  const isAuthPage = AUTH_ONLY.some((p) => path.startsWith(p));

  if (needsAuth && !token) {
    // Preserve the intended destination so login can redirect back
    return redirect(`/login?next=${encodeURIComponent(path)}`);
  }

  if (isAuthPage && token) {
    return redirect('/dashboard');
  }

  return next();
});
