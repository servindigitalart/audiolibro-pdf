import { useState, useEffect } from 'react';
import { loadLastPlayed } from '@/hooks/usePlaybackProgress';
import type { PlaybackProgress } from '@/hooks/usePlaybackProgress';
import { fmtDuration } from '@/lib/utils';
import BookCover from '@/components/ui/BookCover';

function formatRemaining(secs: number): string {
  const h = Math.floor(secs / 3600);
  const m = Math.floor((secs % 3600) / 60);
  if (h > 0 && m > 0) return `${h}h ${m}m remaining`;
  if (h > 0) return `${h}h remaining`;
  if (m > 1) return `${m} min remaining`;
  return 'Almost done';
}

export default function ContinueListening() {
  const [progress, setProgress] = useState<PlaybackProgress | null>(null);

  useEffect(() => {
    const p = loadLastPlayed();
    if (p && p.totalDuration > 0) {
      const pct = p.currentTime / p.totalDuration;
      if (p.currentTime >= 30 && pct < 0.95) {
        setProgress(p);
      }
    }
  }, []);

  if (!progress) return null;

  const pct       = Math.round((progress.currentTime / progress.totalDuration) * 100);
  const remaining = Math.max(0, progress.totalDuration - progress.currentTime);

  return (
    <div className="mb-6 animate-fade-in">
      <div className="flex items-center justify-between mb-3">
        <h2 className="text-sm font-semibold text-sonoro-900">Continue listening</h2>
      </div>

      <a
        href={`/dashboard/documents/${progress.documentId}?autoplay=1`}
        className="flex items-center gap-4 card-base p-4 hover:shadow-hover hover:-translate-y-px transition-all duration-200 group"
        aria-label={`Resume ${progress.documentTitle}`}
      >
        {/* Cover */}
        <BookCover title={progress.documentTitle} size="md" />

        {/* Info */}
        <div className="flex-1 min-w-0">
          <p className="text-sm font-semibold text-sonoro-900 truncate leading-snug mb-0.5">
            {progress.documentTitle}
          </p>

          {/* Chapter name if available */}
          {progress.chapterTitle ? (
            <p className="text-xs text-sonoro-amber-dark font-medium truncate mb-2">
              {progress.chapterTitle}
            </p>
          ) : (
            <p className="text-xs text-sonoro-muted mb-2">
              Chapter {progress.chapterIdx + 1}
            </p>
          )}

          {/* Progress bar */}
          <div className="h-1.5 w-full rounded-full bg-sonoro-border overflow-hidden mb-1.5">
            <div
              className="h-full rounded-full bg-sonoro-amber transition-all duration-500"
              style={{ width: `${pct}%` }}
            />
          </div>

          {/* Stats */}
          <div className="flex items-center justify-between gap-2">
            <p className="text-[11px] text-sonoro-muted">
              {formatRemaining(remaining)}
            </p>
            <p className="text-[11px] text-sonoro-400 tabular-nums">{pct}%</p>
          </div>
        </div>

        {/* Resume arrow */}
        <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-sonoro-surface border border-sonoro-border group-hover:bg-sonoro-amber group-hover:border-sonoro-amber group-hover:text-white transition-all duration-200">
          <svg
            className="w-4 h-4 text-sonoro-400 group-hover:text-white transition-colors translate-x-px"
            viewBox="0 0 16 16" fill="currentColor"
            aria-hidden="true"
          >
            <path d="M3.5 2.5l8 5.5-8 5.5V2.5z"/>
          </svg>
        </div>
      </a>
    </div>
  );
}
