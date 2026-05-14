/**
 * UsageWarningBanner
 * ==================
 * Inline banner rendered at the top of a page or section when the user
 * is approaching or has exceeded a quota limit.
 *
 * Soft paywall (80–99%): yellow warning with upgrade CTA
 * Hard paywall (100%):   red block with mandatory upgrade CTA
 *
 * Dismissable for soft warnings; non-dismissable for hard blocks.
 */

'use client';

import { useState } from 'react';
import { AlertTriangle, XCircle, ArrowRight, X } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { UpgradeModal } from './upgrade-modal';
import { usePricingStore, selectIsBlocked, selectWarnings, selectBlocker } from '@/store/pricing-store';
import { track } from '@/lib/analytics';
import { cn } from '@/lib/utils';

interface UsageWarningBannerProps {
  className?: string;
}

export function UsageWarningBanner({ className }: UsageWarningBannerProps) {
  const [dismissed, setDismissed] = useState(false);
  const [modalOpen, setModalOpen] = useState(false);

  const isBlocked = usePricingStore(selectIsBlocked);
  const blocker = usePricingStore(selectBlocker);
  const warnings = usePricingStore(selectWarnings);

  // Nothing to show
  if (!isBlocked && warnings.length === 0) return null;
  // Soft warning dismissed
  if (!isBlocked && dismissed) return null;

  const activeCTA = blocker ?? warnings[0] ?? null;
  if (!activeCTA) return null;

  const isHardBlock = activeCTA.is_blocking;

  const handleUpgrade = () => {
    track('upgrade_intent', { source: 'usage_warning_banner', trigger: activeCTA.trigger });
    setModalOpen(true);
  };

  const handleDismiss = () => {
    track('paywall_dismissed', { trigger: activeCTA.trigger, source: 'banner' });
    setDismissed(true);
  };

  return (
    <>
      <Alert
        className={cn(
          'flex items-center gap-3 py-3 pr-3',
          isHardBlock
            ? 'border-destructive bg-destructive/10 text-destructive'
            : 'border-yellow-500 bg-yellow-50 text-yellow-900 dark:bg-yellow-950/20 dark:text-yellow-300',
          className,
        )}
      >
        {isHardBlock ? (
          <XCircle className="h-4 w-4 shrink-0" />
        ) : (
          <AlertTriangle className="h-4 w-4 shrink-0" />
        )}

        <AlertDescription className="flex-1 text-sm font-medium">
          {activeCTA.heading}
          {activeCTA.body && (
            <span className="font-normal ml-1 opacity-80">{activeCTA.body}</span>
          )}
        </AlertDescription>

        <div className="flex items-center gap-2 ml-auto shrink-0">
          <Button
            size="sm"
            variant={isHardBlock ? 'destructive' : 'default'}
            className={cn(
              'h-7 text-xs',
              !isHardBlock && 'bg-yellow-600 hover:bg-yellow-700 text-white',
            )}
            onClick={handleUpgrade}
          >
            {activeCTA.cta_label}
            <ArrowRight className="ml-1.5 h-3 w-3" />
          </Button>

          {!isHardBlock && (
            <button
              onClick={handleDismiss}
              aria-label="Dismiss"
              className="text-current opacity-60 hover:opacity-100 transition-opacity"
            >
              <X className="h-4 w-4" />
            </button>
          )}
        </div>
      </Alert>

      <UpgradeModal
        open={modalOpen}
        onClose={() => setModalOpen(false)}
        cta={activeCTA}
      />
    </>
  );
}
