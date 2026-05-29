/**
 * Sticky mini-player — reads last-played state from localStorage.
 *
 * Navigation UX: shows the in-progress (or recently completed) audiobook and
 * links back to the document page with ?autoplay=1 to resume. Does not own
 * a live audio element — Astro SSR navigates between full pages.
 *
 * Mounted in DashboardLayout so it persists across all dashboard pages.
 */
import { useState, useEffect } from 'react';
import { loadLastPlayed } from '@/hooks/usePlaybackProgress';
import type { PlaybackProgress } from '@/hooks/usePlaybackProgress';
import BookCover from '@/components/ui/BookCover';
import { track } from '@/lib/analytics';
import { cn } from '@/lib/utils';

export default function MiniPlayer() {
  const [progress, setProgress]   = useState<PlaybackProgress | null>(null);
  const [dismissed, setDismissed] = useState(false);
  const [visible, setVisible]     = useState(false);

  useEffect(() => {
    const p = loadLastPlayed();
    if (!p || p.totalDuration <= 0) return;
    if (p.currentTime < 30) return;

    // Hide on the document page that's already showing this book
    const isOnDocumentPage = window.location.pathname === `/dashboard/documents/${p.documentId}`;
    if (isOnDocumentPage) return;

    // Only show if in-progress (not completed and not at very end without completed flag)
    const pct = p.currentTime / p.totalDuration;
    if (!p.completed && pct >= 0.95) return;

    setProgress(p);
    // Slide up after the page has settled
    requestAnimationFrame(() => {
      requestAnimationFrame(() => {
        setVisible(true);
        track('mini_player_opened', {
          document_id: p.documentId,
          progress_pct: p.progressPct ?? Math.round(pct * 100),
          completed: p.completed ?? false,
        });
      });
    });
  }, []);

  if (!progress || dismissed) return null;

  const pct        = Math.round((progress.currentTime / progress.totalDuration) * 100);
  const remaining  = Math.max(0, progress.totalDuration - progress.currentTime);
  const isComplete = progress.completed ?? false;
  const resumeHref = `/dashboard/documents/${progress.documentId}?autoplay=1`;

  function formatRemaining(secs: number): string {
    const h = Math.floor(secs / 3600);
    const m = Math.floor((secs % 3600) / 60);
    if (h > 0) return `${h}h ${m}m left`;
    if (m > 0) return `${m}m left`;
    return `<1m left`;
  }

  return (
    <div
      role="complementary"
      aria-label="Mini player — currently playing"
      className={cn(
        'fixed bottom-0 left-0 right-0 z-40 transition-transform duration-300 ease-smooth',
        visible ? 'translate-y-0' : 'translate-y-full',
      )}
    >
      {/* Gradient fade behind the bar so content below doesn't feel cut off */}
      <div
        className="h-6 pointer-events-none"
        style={{ background: 'linear-gradient(to bottom, transparent, rgba(247,246,243,0.9))' }}
        aria-hidden="true"
      />

      {/* Bar */}
      <div className="bg-sonoro-white border-t border-sonoro-border shadow-modal">
        {/* Progress stripe — only shown when in-progress */}
        {!isComplete && (
          <div
            className="h-0.5 w-full"
            style={{ background: `linear-gradient(90deg, #D97706 ${pct}%, #E8E7E3 ${pct}%)` }}
            aria-hidden="true"
          />
        )}

        <div className="flex items-center gap-3 px-4 py-2.5 max-w-screen-xl mx-auto">
          {/* Cover */}
          <a href={resumeHref} aria-label={progress.documentTitle} className="shrink-0">
            <BookCover title={progress.documentTitle} size="sm" />
          </a>

          {/* Info */}
          <a href={resumeHref} className="flex-1 min-w-0 group">
            <p className="text-xs font-semibold text-sonoro-900 truncate leading-snug group-hover:text-sonoro-amber-dark transition-colors">
              {progress.documentTitle}
            </p>
            <p className="text-[11px] text-sonoro-muted truncate mt-0.5">
              {isComplete ? (
                'Finished listening'
              ) : (
                <>
                  {progress.chapterTitle || `Chapter ${progress.chapterIdx + 1}`}
                  {' · '}
                  {formatRemaining(remaining)}
                </>
              )}
            </p>
          </a>

          {/* Progress bar — in-progress only, hidden on mobile */}
          {!isComplete && (
            <div className="hidden sm:block w-24 shrink-0">
              <div className="h-1 rounded-full bg-sonoro-border overflow-hidden">
                <div
                  className="h-full rounded-full bg-sonoro-amber"
                  style={{ width: `${pct}%` }}
                />
              </div>
              <p className="text-[9px] text-sonoro-400 mt-0.5 text-right tabular-nums">{pct}%</p>
            </div>
          )}

          {/* Resume / Listen again button */}
          <a
            href={resumeHref}
            className="flex h-9 items-center justify-center rounded-full bg-sonoro-black text-white hover:bg-sonoro-800 active:scale-95 transition-all shadow-card shrink-0 px-3 gap-1.5 text-xs font-semibold"
            aria-label={isComplete ? `Listen to ${progress.documentTitle} again` : 'Resume playback'}
          >
            {isComplete ? (
              'Listen again'
            ) : (
              <>
                <svg className="w-3.5 h-3.5 translate-x-px" viewBox="0 0 20 20" fill="currentColor" aria-hidden="true">
                  <path d="M6.3 2.84A1.5 1.5 0 0 0 4 4.11v11.78a1.5 1.5 0 0 0 2.3 1.27l9.344-5.891a1.5 1.5 0 0 0 0-2.538L6.3 2.841Z"/>
                </svg>
                Resume
              </>
            )}
          </a>

          {/* Dismiss */}
          <button
            onClick={() => { setVisible(false); setTimeout(() => setDismissed(true), 300); }}
            className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg text-sonoro-300 hover:text-sonoro-700 hover:bg-sonoro-surface transition-colors"
            aria-label="Dismiss mini player"
          >
            <svg className="w-3.5 h-3.5" viewBox="0 0 14 14" fill="currentColor" aria-hidden="true">
              <path d="M3.22 3.22a.75.75 0 0 1 1.06 0L7 5.94l2.72-2.72a.75.75 0 1 1 1.06 1.06L8.06 7l2.72 2.72a.75.75 0 1 1-1.06 1.06L7 8.06l-2.72 2.72a.75.75 0 0 1-1.06-1.06L5.94 7 3.22 4.28a.75.75 0 0 1 0-1.06Z"/>
            </svg>
          </button>
        </div>
      </div>
    </div>
  );
}
