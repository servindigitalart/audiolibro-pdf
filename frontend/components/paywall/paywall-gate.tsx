/**
 * PaywallGate
 * ===========
 * Wraps a feature with tier-based access control.
 *
 * Modes:
 *   'hide'    – render nothing when blocked (default for premium UI areas)
 *   'blur'    – render children blurred with an overlay CTA
 *   'replace' – render a locked state card instead of children
 *
 * Usage:
 *   <PaywallGate feature="priority_processing" mode="replace">
 *     <PriorityQueueToggle />
 *   </PaywallGate>
 *
 *   <PaywallGate feature="api_access" mode="blur">
 *     <ApiKeysPanel />
 *   </PaywallGate>
 */

'use client';

import { useState, type ReactNode } from 'react';
import { Lock, Sparkles } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { UpgradeModal } from './upgrade-modal';
import { useFeatureFlag, type FeatureKey } from '@/hooks/use-feature-flag';
import { track } from '@/lib/analytics';
import { usePricingStore } from '@/store/pricing-store';
import { TIER_META, type PlanTier } from '@/lib/pricing-service';

interface PaywallGateProps {
  feature: FeatureKey;
  mode?: 'hide' | 'blur' | 'replace';
  /** Override the upgrade target tier */
  targetTier?: PlanTier;
  /** Custom locked state label (defaults to feature display name) */
  lockedLabel?: string;
  /** Rendered when feature is unlocked */
  children: ReactNode;
}

function LockedOverlay({ feature, targetTier, onUpgrade }: {
  feature: FeatureKey;
  targetTier?: PlanTier;
  onUpgrade: () => void;
}) {
  const { effectiveLimits, catalog } = usePricingStore();
  const tier = (effectiveLimits?.tier ?? 'FREE') as PlanTier;
  const targetCfg = catalog?.find((c) => c.tier === (targetTier ?? 'PRO'));
  const targetName = targetCfg ? TIER_META[targetCfg.tier].name : 'Pro';

  return (
    <div className="flex flex-col items-center justify-center gap-3 p-6 text-center">
      <div className="h-10 w-10 rounded-full bg-muted flex items-center justify-center">
        <Lock className="h-5 w-5 text-muted-foreground" />
      </div>
      <div>
        <p className="font-medium text-sm">Requires {targetName} plan</p>
        <p className="text-xs text-muted-foreground mt-0.5">
          Unlock this feature by upgrading your plan
        </p>
      </div>
      <Button
        size="sm"
        className="bg-violet-600 hover:bg-violet-700 text-white"
        onClick={onUpgrade}
      >
        <Sparkles className="h-3.5 w-3.5 mr-1.5" />
        Upgrade to {targetName}
      </Button>
    </div>
  );
}

export function PaywallGate({
  feature,
  mode = 'replace',
  targetTier,
  lockedLabel,
  children,
}: PaywallGateProps) {
  const isEnabled = useFeatureFlag(feature, { trackOnBlock: true });
  const [modalOpen, setModalOpen] = useState(false);

  const openModal = () => {
    track('upgrade_intent', { source: 'paywall_gate', feature });
    setModalOpen(true);
  };

  // Unlocked — render normally
  if (isEnabled) return <>{children}</>;

  // Locked — render by mode
  if (mode === 'hide') return null;

  if (mode === 'blur') {
    return (
      <>
        <div className="relative">
          <div className="pointer-events-none select-none blur-sm opacity-50">
            {children}
          </div>
          <div className="absolute inset-0 flex items-center justify-center bg-background/40 rounded-lg backdrop-blur-[2px]">
            <LockedOverlay feature={feature} targetTier={targetTier} onUpgrade={openModal} />
          </div>
        </div>

        <UpgradeModal
          open={modalOpen}
          onClose={() => setModalOpen(false)}
          cta={{
            trigger: 'FEATURE_GATE_HIT',
            priority: 95,
            is_blocking: true,
            heading: `${lockedLabel ?? feature} requires an upgrade`,
            body: 'Unlock this feature and more by upgrading your plan.',
            cta_label: 'Upgrade now',
            target_tier: targetTier ?? 'PRO',
          }}
        />
      </>
    );
  }

  // mode === 'replace'
  return (
    <>
      <Card className="border-dashed">
        <CardContent className="p-0">
          <LockedOverlay feature={feature} targetTier={targetTier} onUpgrade={openModal} />
        </CardContent>
      </Card>

      <UpgradeModal
        open={modalOpen}
        onClose={() => setModalOpen(false)}
        cta={{
          trigger: 'FEATURE_GATE_HIT',
          priority: 95,
          is_blocking: true,
          heading: `${lockedLabel ?? feature} requires an upgrade`,
          body: 'Unlock this feature and more by upgrading your plan.',
          cta_label: 'Upgrade now',
          target_tier: targetTier ?? 'PRO',
        }}
      />
    </>
  );
}
