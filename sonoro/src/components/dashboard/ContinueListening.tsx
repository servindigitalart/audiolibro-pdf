import { useState, useEffect } from 'react';
import { useStore } from '@nanostores/react';
import { $user } from '@/stores/auth';
import { loadLastPlayed, setCurrentUserId } from '@/hooks/usePlaybackProgress';
import type { PlaybackProgress } from '@/hooks/usePlaybackProgress';
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
  const user = useStore($user);
  const [progress, setProgress] = useState<PlaybackProgress | null>(null);

  useEffect(() => {
    setCurrentUserId(user?.id ?? null);
    const p = loadLastPlayed();
    if (!p || p.totalDuration <= 0 || p.currentTime < 30) return;
    setProgress(p);
  }, [user?.id]);

  if (!progress) return null;

  const pct       = Math.round((progress.currentTime / progress.totalDuration) * 100);
  const remaining = Math.max(0, progress.totalDuration - progress.currentTime);
  const isComplete = progress.completed ?? false;
  const resumeHref = `/dashboard/documents/${progress.documentId}?autoplay=1`;

  return (
    <div className="mb-6 animate-fade-in">
      <div className="flex items-center justify-between mb-3">
        <h2 className="text-sm font-semibold text-sonoro-900">
          {isComplete ? 'Recently finished' : 'Continue listening'}
        </h2>
      </div>

      <a
        href={resumeHref}
        className="flex items-center gap-4 card-base p-4 hover:shadow-hover hover:-translate-y-px transition-all duration-200 group"
        aria-label={isComplete ? `Listen to ${progress.documentTitle} again` : `Resume ${progress.documentTitle}`}
      >
        {/* Cover */}
        <BookCover title={progress.documentTitle} size="md" />

        {/* Info */}
        <div className="flex-1 min-w-0">
          <p className="text-sm font-semibold text-sonoro-900 truncate leading-snug mb-0.5">
            {progress.documentTitle}
          </p>

          {isComplete ? (
            <p className="text-xs text-emerald-600 font-medium mb-2">Finished</p>
          ) : progress.chapterTitle && progress.chapterTitle !== 'Full Document' ? (
            <p className="text-xs text-sonoro-amber-dark font-medium truncate mb-2">
              {progress.chapterTitle}
            </p>
          ) : (
            <p className="text-xs text-sonoro-muted mb-2">
              Part {progress.chapterIdx + 1}
            </p>
          )}

          {/* Progress bar — only for in-progress books */}
          {!isComplete && (
            <>
              <div className="h-1.5 w-full rounded-full bg-sonoro-border overflow-hidden mb-1.5">
                <div
                  className="h-full rounded-full bg-sonoro-amber transition-all duration-500"
                  style={{ width: `${pct}%` }}
                />
              </div>
              <div className="flex items-center justify-between gap-2">
                <p className="text-[11px] text-sonoro-muted">{formatRemaining(remaining)}</p>
                <p className="text-[11px] text-sonoro-400 tabular-nums">{pct}%</p>
              </div>
            </>
          )}
        </div>

        {/* CTA arrow */}
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
