/**
 * useFeatureFlag
 * ==============
 * Checks whether the current user's plan tier includes a given feature.
 *
 * Usage:
 *   const canUseApiAccess = useFeatureFlag('api_access');
 *   const canUsePriority   = useFeatureFlag('priority_processing');
 *
 * Returns false during loading (conservative — never show locked features prematurely).
 * Fires a 'feature_gate_hit' analytics event when a feature is blocked.
 */

'use client';

import { useCallback, useEffect, useRef } from 'react';
import { useAuthStore } from '@/store/auth-store';
import { usePricingStore } from '@/store/pricing-store';
import { track } from '@/lib/analytics';

/** Feature key strings matching backend TierFeature enum values */
export type FeatureKey =
  | 'document_upload'
  | 'tts_processing'
  | 'priority_processing'
  | 'custom_voices'
  | 'api_access'
  | 'team_members'
  | 'advanced_analytics'
  | 'sla_support'
  | 'custom_integration'
  | 'webhook_callbacks';

/**
 * Returns true if the current user's tier includes the feature.
 * Optionally fires a gate-hit analytics event when blocked.
 */
export function useFeatureFlag(
  feature: FeatureKey,
  { trackOnBlock = false }: { trackOnBlock?: boolean } = {},
): boolean {
  const { user } = useAuthStore();
  const { catalog, effectiveLimits } = usePricingStore();
  const firedRef = useRef(false);

  // Find the current user's tier config in the catalog
  const tier = effectiveLimits?.tier ?? (user?.plan_tier?.toUpperCase() as string | undefined);
  const tierConfig = catalog?.find((c) => c.tier === tier);
  const isEnabled = tierConfig ? tierConfig.features.includes(feature) : false;

  // Track gate hit once per mount when blocked
  useEffect(() => {
    if (!isEnabled && trackOnBlock && user && !firedRef.current) {
      firedRef.current = true;
      track('feature_gate_hit', {
        feature,
        current_tier: tier,
      });
    }
  }, [isEnabled, trackOnBlock, feature, tier, user]);

  return isEnabled;
}

/**
 * Returns a callback that wraps an action, gate-checking it before execution.
 * If the feature is blocked, calls `onBlocked` instead of the action.
 *
 * Usage:
 *   const handleExport = useGatedAction('api_access', {
 *     action: () => exportData(),
 *     onBlocked: () => openUpgradeModal(),
 *   });
 */
export function useGatedAction<T extends unknown[]>(
  feature: FeatureKey,
  {
    action,
    onBlocked,
  }: {
    action: (...args: T) => void;
    onBlocked: () => void;
  },
): (...args: T) => void {
  const isEnabled = useFeatureFlag(feature);

  return useCallback(
    (...args: T) => {
      if (!isEnabled) {
        track('feature_gate_hit', { feature });
        onBlocked();
      } else {
        action(...args);
      }
    },
    [isEnabled, action, onBlocked, feature],
  );
}
