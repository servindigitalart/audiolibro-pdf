import { useState, useEffect } from 'react';
import { getAllProgress } from '@/hooks/usePlaybackProgress';
import type { PlaybackProgress } from '@/hooks/usePlaybackProgress';
import BookCover from '@/components/ui/BookCover';
import { cn } from '@/lib/utils';

const MAX_ITEMS = 5;

function fmtAge(timestamp: number): string {
  const diffMs = Date.now() - timestamp;
  const diffMin = Math.floor(diffMs / 60_000);
  if (diffMin < 2)   return 'Just now';
  if (diffMin < 60)  return `${diffMin}m ago`;
  const diffH = Math.floor(diffMin / 60);
  if (diffH < 24)    return `${diffH}h ago`;
  const diffD = Math.floor(diffH / 24);
  if (diffD === 1)   return 'Yesterday';
  if (diffD < 7)     return `${diffD}d ago`;
  return new Date(timestamp).toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
}

export default function ListeningHistory() {
  const [items, setItems] = useState<PlaybackProgress[]>([]);

  useEffect(() => {
    const all = getAllProgress();
    // Filter out entries that are nearly at the beginning (< 30s) — not meaningfully started
    const meaningful = all.filter(p => p.currentTime >= 30 && p.totalDuration > 0);
    setItems(meaningful.slice(0, MAX_ITEMS));
    console.log('[SONORO] listening_history_loaded', meaningful.length);
  }, []);

  if (items.length === 0) return null;

  return (
    <div className="mb-6 animate-fade-in" style={{ animationDelay: '200ms', animationFillMode: 'both' }}>
      <div className="flex items-center justify-between mb-3">
        <h2 className="text-sm font-semibold text-sonoro-900">Recently played</h2>
      </div>

      <div className="space-y-1">
        {items.map((p, i) => {
          const pct       = Math.round((p.currentTime / p.totalDuration) * 100);
          const completed = pct >= 95;

          return (
            <a
              key={p.documentId}
              href={`/dashboard/documents/${p.documentId}${completed ? '' : '?autoplay=1'}`}
              className={cn(
                'flex items-center gap-3 rounded-2xl px-4 py-3 transition-all duration-150',
                'hover:bg-sonoro-surface group',
              )}
              style={{ animationDelay: `${i * 50}ms` }}
              aria-label={`${completed ? 'Listen to' : 'Resume'} ${p.documentTitle}`}
            >
              {/* Cover */}
              <BookCover title={p.documentTitle} size="sm" />

              {/* Info */}
              <div className="flex-1 min-w-0">
                <p className="text-xs font-semibold text-sonoro-900 truncate leading-snug mb-1">
                  {p.documentTitle}
                </p>
                <div className="flex items-center gap-2">
                  {/* Inline progress bar */}
                  <div className="flex-1 h-1 rounded-full bg-sonoro-border overflow-hidden">
                    <div
                      className={cn(
                        'h-full rounded-full',
                        completed ? 'bg-emerald-400' : 'bg-sonoro-amber',
                      )}
                      style={{ width: `${Math.min(pct, 100)}%` }}
                    />
                  </div>
                  <span className="text-[10px] text-sonoro-400 tabular-nums shrink-0 w-6 text-right">
                    {pct}%
                  </span>
                </div>
              </div>

              {/* Age + status */}
              <div className="shrink-0 text-right">
                <p className="text-[10px] text-sonoro-400">{fmtAge(p.timestamp)}</p>
                {completed && (
                  <span className="inline-flex items-center gap-1 text-[9px] font-medium text-emerald-600 mt-0.5">
                    <svg className="w-2.5 h-2.5" viewBox="0 0 10 10" fill="currentColor" aria-hidden="true">
                      <path fillRule="evenodd" d="M5 10A5 5 0 1 0 5 0a5 5 0 0 0 0 10zm2.5-6.25a.5.5 0 0 0-.808-.39L4.35 5.527l-.881-.837a.5.5 0 0 0-.688.727l1.25 1.187a.5.5 0 0 0 .752-.059l2.75-3.75-.033-.044Z" clipRule="evenodd"/>
                    </svg>
                    Done
                  </span>
                )}
              </div>
            </a>
          );
        })}
      </div>
    </div>
  );
}
