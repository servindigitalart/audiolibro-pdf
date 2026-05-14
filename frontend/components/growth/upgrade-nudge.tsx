/**
 * UpgradeNudge
 * ============
 * Contextual non-intrusive upgrade prompt that appears based on usage signals.
 *
 * Positioning: rendered as a persistent footer strip inside the dashboard,
 * or as a toast-positioned card. Disappears when dismissed.
 *
 * Only shown when:
 *   1. User is on FREE or BASIC tier
 *   2. A non-blocking upgrade CTA is active (80–99% quota, feature gate)
 *   3. Not already dismissed in this session
 */

'use client';

import { useState, useEffect } from 'react';
import { Sparkles, X, ArrowRight } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { UpgradeModal } from '@/components/paywall/upgrade-modal';
import { usePricingStore, selectCurrentTier, selectWarnings } from '@/store/pricing-store';
import { track } from '@/lib/analytics';
import { cn } from '@/lib/utils';
import type { PlanTier } from '@/lib/pricing-service';

const SESSION_KEY = '_nudge_dismissed';

interface UpgradeNudgeProps {
  className?: string;
}

export function UpgradeNudge({ className }: UpgradeNudgeProps) {
  const [dismissed, setDismissed] = useState(false);
  const [shown, setShown] = useState(false);
  const [modalOpen, setModalOpen] = useState(false);

  const tier = usePricingStore(selectCurrentTier);
  const warnings = usePricingStore(selectWarnings);
  const isBlocked = usePricingStore((s) => s.upgradeCTAs.some((c) => c.is_blocking));

  // Only nudge on FREE / BASIC
  const shouldNudge = tier === 'FREE' || tier === 'BASIC';

  const topWarning = warnings[0] ?? null;

  useEffect(() => {
    if (typeof window !== 'undefined') {
      setDismissed(sessionStorage.getItem(SESSION_KEY) === '1');
    }
  }, []);

  // Fire analytics when nudge becomes visible
  useEffect(() => {
    if (shouldNudge && topWarning && !dismissed && !shown && !isBlocked) {
      setShown(true);
      track('upgrade_nudge_shown', {
        trigger: topWarning.trigger,
        tier,
      });
    }
  }, [shouldNudge, topWarning, dismissed, shown, isBlocked, tier]);

  const handleDismiss = () => {
    sessionStorage.setItem(SESSION_KEY, '1');
    setDismissed(true);
  };

  const handleClick = () => {
    track('upgrade_nudge_clicked', {
      trigger: topWarning?.trigger,
      tier,
    });
    setModalOpen(true);
  };

  // Don't show if: hard blocked (banner handles that), dismissed, wrong tier, no warning
  if (!shouldNudge || !topWarning || dismissed || isBlocked) return null;

  return (
    <>
      <div
        className={cn(
          'flex items-center gap-3 px-4 py-2.5 rounded-lg border',
          'bg-violet-50 border-violet-200 dark:bg-violet-950/30 dark:border-violet-800',
          className,
        )}
      >
        <Sparkles className="h-4 w-4 text-violet-600 dark:text-violet-400 shrink-0" />

        <p className="text-sm flex-1 text-violet-900 dark:text-violet-200">
          <span className="font-medium">{topWarning.heading}</span>
          {topWarning.body && (
            <span className="ml-1.5 opacity-80">{topWarning.body}</span>
          )}
        </p>

        <Button
          size="sm"
          variant="ghost"
          className="h-7 text-xs text-violet-700 hover:text-violet-900 hover:bg-violet-100 dark:text-violet-300 dark:hover:bg-violet-900/50 shrink-0"
          onClick={handleClick}
        >
          {topWarning.cta_label}
          <ArrowRight className="ml-1 h-3 w-3" />
        </Button>

        <button
          onClick={handleDismiss}
          aria-label="Dismiss"
          className="text-violet-400 hover:text-violet-600 transition-colors shrink-0"
        >
          <X className="h-4 w-4" />
        </button>
      </div>

      <UpgradeModal
        open={modalOpen}
        onClose={() => setModalOpen(false)}
        cta={topWarning}
      />
    </>
  );
}

/**
 * UpgradeNudgeBar
 * ===============
 * Full-width version rendered at the top of the sidebar or main content area.
 */
export function UpgradeNudgeBar() {
  return <UpgradeNudge className="mx-4 my-3" />;
}
