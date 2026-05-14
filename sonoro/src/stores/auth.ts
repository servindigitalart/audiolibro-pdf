import { atom, computed } from 'nanostores';
import type { User } from '@/lib/api/types';

export const $user = atom<User | null>(null);
export const $authLoading = atom<boolean>(true);

export const $isAuthenticated = computed($user, (u) => u !== null);
export const $planTier = computed($user, (u) => u?.plan_tier ?? 'FREE');
export const $isPro = computed($user, (u) =>
  ['PRO', 'ENTERPRISE'].includes(u?.plan_tier ?? '')
);
