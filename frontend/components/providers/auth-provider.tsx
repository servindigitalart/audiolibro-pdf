/**
 * Auth Provider
 * ============
 * Initializes authentication state on app load
 */

'use client';

import { useEffect } from 'react';
import { useAuthStore } from '@/store/auth-store';

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const fetchUser = useAuthStore((state) => state.fetchUser);

  useEffect(() => {
    // Fetch user on mount if token exists
    fetchUser();
  }, [fetchUser]);

  return <>{children}</>;
}
