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
    if (password.length < 8) { setError('Password must be at least 8 characters.'); return; }

    setError(null);
    setLoading(true);
    try {
      await register(email, password);
      // Route to onboarding (or plan checkout) after registration
      window.location.href = initialPlan
        ? `/dashboard/billing?upgrade=${initialPlan}`
        : '/onboarding';
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setLoading(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-4" noValidate>
      {error && (
        <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700" role="alert">
          {error}
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
          className={cn('input-base', mismatch && 'border-red-400 focus:border-red-400 focus:ring-red-300/30')}
          disabled={loading}
        />
        {mismatch && <p className="mt-1 text-xs text-red-600">Passwords don't match</p>}
      </div>

      <button
        type="submit"
        disabled={loading || !email || !password || mismatch}
        className={cn(
          'w-full rounded-full py-3 text-sm font-semibold transition-all duration-150',
          'bg-sonoro-black text-sonoro-white hover:bg-sonoro-800 active:scale-[0.98]',
          'disabled:opacity-50 disabled:cursor-not-allowed'
        )}
      >
        {loading ? (
          <span className="flex items-center justify-center gap-2">
            <svg className="w-4 h-4 animate-spin" viewBox="0 0 24 24" fill="none" aria-hidden="true">
              <circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" strokeOpacity=".25"/>
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
        <a href="/terms" className="underline hover:text-sonoro-900">Terms</a>
        {' '}and{' '}
        <a href="/privacy" className="underline hover:text-sonoro-900">Privacy Policy</a>.
      </p>
    </form>
  );
}
