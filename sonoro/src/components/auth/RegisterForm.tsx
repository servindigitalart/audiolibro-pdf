import { useState } from 'react';
import { register, getErrorMessage } from '@/lib/api/client';
import { cn } from '@/lib/utils';

interface Props {
  initialPlan?: string;
}

export default function RegisterForm({ initialPlan }: Props) {
  const [email, setEmail]       = useState('');
  const [password, setPassword] = useState('');
  const [confirm, setConfirm]   = useState('');
  const [error, setError]       = useState<string | null>(null);
  const [loading, setLoading]   = useState(false);

  const mismatch = confirm.length > 0 && confirm !== password;

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (password !== confirm) { setError('Passwords do not match.'); return; }
    if (password.length < 8)  { setError('Password must be at least 8 characters.'); return; }

    setError(null);
    setLoading(true);
    try {
      await register(email, password);
      window.location.href = initialPlan
        ? `/dashboard/billing?upgrade=${initialPlan}`
        : '/onboarding';
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setLoading(false);
    }
  }

  // For plan-selected registrations encode the destination so the OAuth
  // callback lands on the billing upgrade page instead of generic onboarding.
  const googleHref = initialPlan
    ? `/api/auth/google?next=${encodeURIComponent(`/onboarding?plan=${initialPlan}`)}`
    : '/api/auth/google?next=/onboarding';

  return (
    <div className="space-y-5">
      {/* Google OAuth — primary CTA */}
      <a
        href={googleHref}
        className={cn(
          'flex w-full items-center justify-center gap-3 rounded-full border border-sonoro-border bg-sonoro-white px-5 py-3 text-sm font-medium text-sonoro-800',
          'hover:bg-sonoro-surface hover:border-sonoro-300 active:scale-[0.98]',
          'transition-all duration-150 shadow-soft'
        )}
      >
        <svg className="w-4 h-4 shrink-0" viewBox="0 0 24 24" aria-hidden="true">
          <path d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z" fill="#4285F4"/>
          <path d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" fill="#34A853"/>
          <path d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l3.66-2.84z" fill="#FBBC05"/>
          <path d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z" fill="#EA4335"/>
        </svg>
        Continue with Google
      </a>

      {/* Divider */}
      <div className="divider-text">
        <span>or create account with email</span>
      </div>

      {/* Email form */}
      <form onSubmit={handleSubmit} className="space-y-4" noValidate>
        {error && (
          <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700" role="alert">
            <span className="font-medium">Error: </span>{error}
          </div>
        )}

        <div>
          <label htmlFor="email" className="block text-sm font-medium text-sonoro-700 mb-1.5">
            Email address
          </label>
          <input
            id="email"
            type="email"
            autoComplete="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="you@example.com"
            className="input-base"
            disabled={loading}
          />
        </div>

        <div>
          <label htmlFor="password" className="block text-sm font-medium text-sonoro-700 mb-1.5">
            Password
          </label>
          <input
            id="password"
            type="password"
            autoComplete="new-password"
            required
            minLength={8}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder="At least 8 characters"
            className="input-base"
            disabled={loading}
          />
        </div>

        <div>
          <label htmlFor="confirm" className="block text-sm font-medium text-sonoro-700 mb-1.5">
            Confirm password
          </label>
          <input
            id="confirm"
            type="password"
            autoComplete="new-password"
            required
            value={confirm}
            onChange={(e) => setConfirm(e.target.value)}
            placeholder="Repeat your password"
            className={cn('input-base', mismatch && 'border-red-300 focus:border-red-400 focus:ring-red-200/40')}
            disabled={loading}
          />
          {mismatch && <p className="mt-1.5 text-xs text-red-600">Passwords don't match</p>}
        </div>

        <button
          type="submit"
          disabled={loading || !email || !password || mismatch}
          className="btn-accent w-full py-3 rounded-full disabled:opacity-40 text-sm"
        >
          {loading ? (
            <span className="flex items-center justify-center gap-2">
              <svg className="w-4 h-4 animate-spin" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                <circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" strokeOpacity=".2"/>
                <path d="M12 2a10 10 0 0 1 10 10" stroke="currentColor" strokeWidth="4" strokeLinecap="round"/>
              </svg>
              Creating account…
            </span>
          ) : (
            'Create free account'
          )}
        </button>

        <p className="text-center text-xs text-sonoro-muted">
          By creating an account you agree to our{' '}
          <a href="/terms" className="underline hover:text-sonoro-900 transition-colors">Terms</a>
          {' '}and{' '}
          <a href="/privacy" className="underline hover:text-sonoro-900 transition-colors">Privacy Policy</a>.
        </p>
      </form>
    </div>
  );
}
