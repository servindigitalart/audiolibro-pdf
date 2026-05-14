/**
 * QuotaBar
 * ========
 * Animated progress bar showing a single quota dimension.
 * Color shifts from green → amber → red as usage increases.
 */

'use client';

import { cn } from '@/lib/utils';

interface QuotaBarProps {
  /** Fraction 0–1 */
  value: number;
  label: string;
  usedLabel: string;
  limitLabel: string;
  className?: string;
}

function getColor(v: number): string {
  if (v >= 1.0) return 'bg-red-500';
  if (v >= 0.80) return 'bg-amber-500';
  if (v >= 0.60) return 'bg-yellow-400';
  return 'bg-green-500';
}

function getTrackColor(v: number): string {
  if (v >= 1.0) return 'bg-red-100 dark:bg-red-950/30';
  if (v >= 0.80) return 'bg-amber-100 dark:bg-amber-950/30';
  return 'bg-muted';
}

function getLabelColor(v: number): string {
  if (v >= 1.0) return 'text-red-600 dark:text-red-400';
  if (v >= 0.80) return 'text-amber-600 dark:text-amber-400';
  return 'text-muted-foreground';
}

export function QuotaBar({ value, label, usedLabel, limitLabel, className }: QuotaBarProps) {
  const pct = Math.min(1, Math.max(0, value));
  const displayPct = Math.round(pct * 100);

  return (
    <div className={cn('space-y-1.5', className)}>
      <div className="flex items-center justify-between text-sm">
        <span className="font-medium">{label}</span>
        <span className={cn('text-xs', getLabelColor(pct))}>
          {usedLabel} / {limitLabel}
          <span className="ml-1.5 font-semibold">{displayPct}%</span>
        </span>
      </div>

      <div
        className={cn('h-2 rounded-full overflow-hidden', getTrackColor(pct))}
        role="progressbar"
        aria-valuenow={displayPct}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label={`${label}: ${displayPct}% used`}
      >
        <div
          className={cn(
            'h-full rounded-full transition-all duration-500',
            getColor(pct),
          )}
          style={{ width: `${displayPct}%` }}
        />
      </div>
    </div>
  );
}

/** Compact inline version for sidebar / header */
export function QuotaChip({ value, label }: { value: number; label: string }) {
  const pct = Math.min(1, Math.max(0, value));
  return (
    <div className="flex items-center gap-2 text-xs">
      <div className="h-1.5 w-20 rounded-full bg-muted overflow-hidden">
        <div
          className={cn('h-full rounded-full transition-all', getColor(pct))}
          style={{ width: `${Math.round(pct * 100)}%` }}
        />
      </div>
      <span className={cn(getLabelColor(pct))}>{label}</span>
    </div>
  );
}
