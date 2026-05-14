import { defineMiddleware } from 'astro:middleware';

const PROTECTED = ['/dashboard', '/onboarding'];
const AUTH_ONLY = ['/login', '/register'];   // redirect to dashboard if already logged in

export const onRequest = defineMiddleware(async ({ cookies, url, redirect, locals }, next) => {
  const token = cookies.get('access_token')?.value;
  const path  = url.pathname;

  // Attach token to locals so Astro pages can use it without re-reading cookies
  (locals as any).token = token ?? null;

  const needsAuth = PROTECTED.some((p) => path.startsWith(p));
  const isAuthPage = AUTH_ONLY.some((p) => path.startsWith(p));

  if (needsAuth && !token) {
    return redirect(`/login?next=${encodeURIComponent(path)}`);
  }

  if (isAuthPage && token) {
    return redirect('/dashboard');
  }

  return next();
});
