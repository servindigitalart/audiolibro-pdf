import { useState, useEffect, useRef } from 'react';
import type { Document } from '@/lib/api/types';
import {
  deleteDocument, retryProcessing, cancelDocument,
  renameDocumentTitle, getProcessingJob, getErrorMessage,
} from '@/lib/api/client';
import { track } from '@/lib/analytics';
import { getAllProgress } from '@/hooks/usePlaybackProgress';
import type { PlaybackProgress } from '@/hooks/usePlaybackProgress';
import { fmtRelative, fmtFileSize } from '@/lib/utils';
import { cn } from '@/lib/utils';
import BookCover from '@/components/ui/BookCover';

/**
 * Polls /documents/{id}/job every 3 s while the job is active and surfaces
 * a live percentage badge.  Stops automatically on completion / failure.
 * Intended to show progress after a Library retry — the UploadZone is not
 * re-entered in that flow so there's nowhere else to display it.
 */
function LiveProgressBadge({ documentId }: { documentId: string }) {
  const [pct, setPct] = useState<number | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let stopped = false;
    const id = setInterval(async () => {
      if (stopped) return;
      try {
        const job = await getProcessingJob(documentId);
        if (!job) return;
        if (job.status === 'processing' || job.status === 'queued') {
          setPct(typeof job.progress === 'number' ? job.progress : null);
        } else if (job.status === 'completed') {
          clearInterval(id);
          stopped = true;
          window.location.reload(); // refresh card to show "Ready"
        } else if (job.status === 'failed') {
          clearInterval(id);
          stopped = true;
          setFailed(true);
          setPct(null);
        }
      } catch {
        // non-fatal — just skip this tick
      }
    }, 3000);
    return () => { stopped = true; clearInterval(id); };
  }, [documentId]);

  if (failed) return (
    <span className="text-[10px] font-medium text-red-500 tabular-nums">Failed</span>
  );
  if (pct === null) return (
    <span className="text-[10px] text-sonoro-400 animate-pulse">Queued…</span>
  );
  return (
    <span className="text-[10px] font-medium text-sonoro-amber-dark tabular-nums">{pct}%</span>
  );
}

// Stuck threshold: pending job older than 10 minutes is considered stuck
const STUCK_MS = 10 * 60 * 1000;

function isStuck(doc: Document): boolean {
  if (doc.status !== 'pending' && doc.status !== 'processing') return false;
  const ts = doc.updated_at ?? doc.upload_date;
  if (!ts) return false;
  return Date.now() - new Date(ts).getTime() > STUCK_MS;
}

const STATUS_CONFIG = {
  pending:    { label: 'Queued',     cls: 'badge-neutral', dot: 'bg-sonoro-400'  },
  processing: { label: 'Processing', cls: 'badge-warning',  dot: 'bg-amber-500'  },
  completed:  { label: 'Ready',      cls: 'badge-success',  dot: 'bg-emerald-500' },
  failed:     { label: 'Failed',     cls: 'badge-error',    dot: 'bg-red-500'    },
  stuck:      { label: 'Stuck',      cls: 'badge-error',    dot: 'bg-red-400'    },
} as const;

interface Props {
  initialDocuments: Document[];
}

function remainingLabel(p: PlaybackProgress): string {
  const rem = Math.max(0, p.totalDuration - p.currentTime);
  const h   = Math.floor(rem / 3600);
  const m   = Math.floor((rem % 3600) / 60);
  if (h > 0) return `${h}h ${m}m remaining`;
  if (m > 1) return `${m} min remaining`;
  return 'Almost done';
}

// Spinner SVG reused across buttons
const Spinner = () => (
  <svg className="w-3.5 h-3.5 animate-spin" viewBox="0 0 24 24" fill="none" aria-hidden="true">
    <circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" strokeOpacity=".2"/>
    <path d="M12 2a10 10 0 0 1 10 10" stroke="currentColor" strokeWidth="4" strokeLinecap="round"/>
  </svg>
);

const RetryIcon = () => (
  <svg className="w-3.5 h-3.5" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M1.5 4.5A6.5 6.5 0 0 1 13 3M14.5 11.5A6.5 6.5 0 0 1 3 13M14.5 8V4.5H11"/>
  </svg>
);

export default function DocumentList({ initialDocuments }: Props) {
  const [docs, setDocs]               = useState<Document[]>(initialDocuments);
  const [deleting, setDeleting]       = useState<string | null>(null);
  const [retrying, setRetrying]       = useState<string | null>(null);
  const [cancelling, setCancelling]   = useState<string | null>(null);
  // IDs that were retried in this session — show LiveProgressBadge for them
  const [monitoring, setMonitoring]   = useState<Set<string>>(new Set());
  const [editingTitle, setEditingTitle] = useState<string | null>(null);
  const [editValue, setEditValue]       = useState('');
  const [savingTitle, setSavingTitle]   = useState<string | null>(null);
  const titleInputRef = useRef<HTMLInputElement>(null);
  const [progressMap, setProgressMap] = useState<Record<string, PlaybackProgress>>({});
  // Track client-side time so isStuck() is evaluated reactively
  const [now, setNow] = useState(Date.now());

  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 30_000);
    return () => clearInterval(id);
  }, []);

  // Load playback progress from localStorage (client-only)
  useEffect(() => {
    const all = getAllProgress();
    const map: Record<string, PlaybackProgress> = {};
    for (const p of all) map[p.documentId] = p;
    setProgressMap(map);
  }, []);

  async function handleDelete(id: string, title: string) {
    if (!confirm(`Delete "${title}"? This cannot be undone.`)) return;
    setDeleting(id);
    try {
      await deleteDocument(id);
      setDocs(prev => prev.filter(d => d.id !== id));
    } catch (err) {
      alert(getErrorMessage(err));
    } finally {
      setDeleting(null);
    }
  }

  async function handleRetry(id: string, stuck: boolean) {
    setRetrying(id);
    try {
      await retryProcessing(id);
      setDocs(prev => prev.map(d => d.id === id ? { ...d, status: 'pending', updated_at: new Date().toISOString() } : d));
      // Start polling this job for live progress — the UploadZone is not re-entered
      // after a Library retry, so we show the badge directly in the card.
      setMonitoring(prev => new Set(prev).add(id));
      track(stuck ? 'stuck_job_retried' : 'audiobook_started', { document_id: id });
    } catch (err) {
      alert(getErrorMessage(err));
    } finally {
      setRetrying(null);
    }
  }

  async function handleCancel(id: string) {
    setCancelling(id);
    try {
      await cancelDocument(id);
      setDocs(prev => prev.filter(d => d.id !== id));
      track('stuck_job_cancelled', { document_id: id });
    } catch (err) {
      alert(getErrorMessage(err));
    } finally {
      setCancelling(null);
    }
  }

  function startRename(doc: Document) {
    setEditingTitle(doc.id);
    setEditValue(doc.title);
    requestAnimationFrame(() => titleInputRef.current?.select());
  }

  async function commitRename(id: string) {
    const trimmed = editValue.trim();
    if (!trimmed) { setEditingTitle(null); return; }
    setSavingTitle(id);
    try {
      await renameDocumentTitle(id, trimmed);
      setDocs(prev => prev.map(d => d.id === id ? { ...d, title: trimmed, display_title: trimmed } : d));
      track('audiobook_renamed', { document_id: id });
    } catch (err) {
      alert(getErrorMessage(err));
    } finally {
      setSavingTitle(null);
      setEditingTitle(null);
    }
  }

  if (docs.length === 0) {
    return (
      <div className="card-base flex flex-col items-center justify-center py-20 text-center">
        <div className="flex items-end justify-center gap-1 h-10 mb-5" aria-hidden="true">
          {[35, 65, 90, 55, 80, 45, 70].map((h, i) => (
            <div key={i} className="waveform-bar w-1.5" style={{ animationDelay: `${i * 0.13}s`, height: `${h}%` }} />
          ))}
        </div>
        <h3 className="text-base font-semibold text-sonoro-900 mb-2">No audiobooks yet</h3>
        <p className="text-sm text-sonoro-muted mb-6 max-w-xs leading-relaxed">
          Upload a PDF and it'll be converted to audio in under 60 seconds.
        </p>
        <a href="/dashboard/upload" className="btn-accent btn-sm">
          Upload your first PDF →
        </a>
      </div>
    );
  }

  return (
    <div className="space-y-2">
      {docs.map((doc, listIdx) => {
        const stuck      = isStuck(doc);
        const statusKey  = stuck && (doc.status === 'pending' || doc.status === 'processing') ? 'stuck' : doc.status;
        const s          = STATUS_CONFIG[statusKey] ?? STATUS_CONFIG.pending;
        const isActive   = doc.status === 'processing' || (doc.status === 'pending' && !stuck);
        const isCompleted = doc.status === 'completed';
        const isFailed   = doc.status === 'failed';
        const isPending  = doc.status === 'pending';
        const title      = doc.title || doc.filename;
        const saved      = isCompleted ? progressMap[doc.id] : undefined;
        const savedPct   = saved && saved.totalDuration > 0
          ? Math.round((saved.currentTime / saved.totalDuration) * 100)
          : 0;

        // CTA for completed docs
        let listenLabel = 'Start listening';
        let listenHref  = `/dashboard/documents/${doc.id}`;
        if (saved?.completed) {
          listenLabel = 'Listen again';
        } else if (saved && savedPct > 0) {
          listenLabel = 'Resume';
          listenHref  = `/dashboard/documents/${doc.id}?autoplay=1`;
        }

        return (
          <div
            key={doc.id}
            className={cn(
              'group card-base flex items-center gap-3 px-4 py-3.5 sm:px-5 sm:py-4 transition-all duration-200',
              isCompleted && 'hover:shadow-hover hover:-translate-y-px',
              stuck && 'border-red-200',
            )}
            style={{ animationDelay: `${listIdx * 40}ms` }}
          >
            {/* Book cover */}
            <div className="shrink-0 transition-transform duration-200 group-hover:scale-105">
              <BookCover title={title} size="sm" imageUrl={doc.cover_url} />
            </div>

            {/* Document info */}
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2 mb-0.5 flex-wrap">
                {editingTitle === doc.id ? (
                  <input
                    ref={titleInputRef}
                    value={editValue}
                    onChange={e => setEditValue(e.target.value)}
                    onBlur={() => commitRename(doc.id)}
                    onKeyDown={e => {
                      if (e.key === 'Enter') commitRename(doc.id);
                      if (e.key === 'Escape') setEditingTitle(null);
                    }}
                    className="text-sm font-semibold text-sonoro-900 bg-sonoro-surface border border-sonoro-amber rounded px-1.5 py-0.5 leading-snug min-w-0 flex-1 focus:outline-none"
                    aria-label="Edit audiobook title"
                    disabled={savingTitle === doc.id}
                  />
                ) : (
                  <button
                    onClick={() => startRename(doc)}
                    className="text-sm font-semibold text-sonoro-900 truncate leading-snug hover:text-sonoro-amber-dark transition-colors text-left"
                    title="Click to rename"
                    aria-label={`Rename: ${title}`}
                  >
                    {title}
                  </button>
                )}
                <span className={s.cls}>
                  <span className={cn('h-1.5 w-1.5 rounded-full', s.dot, isActive && 'animate-pulse')} aria-hidden="true" />
                  {s.label}
                </span>
              </div>
              <p className="text-xs text-sonoro-400 tabular">
                {doc.file_size ? fmtFileSize(doc.file_size) : '—'}
                {doc.metadata?.pages ? ` · ${doc.metadata.pages}p` : ''}
                {doc.upload_date ? ` · ${fmtRelative(doc.upload_date)}` : ''}
              </p>

              {/* Stuck microcopy */}
              {stuck && (
                <p className="text-[11px] text-red-500 mt-1 leading-snug">
                  This conversion is taking longer than expected.
                </p>
              )}

              {/* Playback progress bar (completed docs with history) */}
              {isCompleted && saved && savedPct > 0 && !saved.completed && (
                <div className="mt-2">
                  <div
                    className="h-1 w-full max-w-[160px] rounded-full bg-sonoro-border overflow-hidden"
                    role="progressbar"
                    aria-valuenow={savedPct}
                    aria-valuemin={0}
                    aria-valuemax={100}
                    aria-label={`${savedPct}% listened`}
                  >
                    <div
                      className="h-full rounded-full bg-sonoro-amber transition-all duration-500"
                      style={{ width: `${savedPct}%` }}
                    />
                  </div>
                  <p className="text-[10px] text-sonoro-400 mt-0.5">
                    {remainingLabel(saved)}
                  </p>
                </div>
              )}

              {/* Processing indeterminate bar + live progress badge after retry */}
              {isActive && (
                <div className="mt-2 flex items-center gap-2">
                  <div className="h-0.5 w-24 rounded-full bg-sonoro-border overflow-hidden">
                    <div className="h-full rounded-full bg-sonoro-amber animate-shimmer" style={{ backgroundSize: '200% 100%', background: 'linear-gradient(90deg, transparent 0%, #F59E0B 50%, transparent 100%)' }} />
                  </div>
                  {monitoring.has(doc.id) && (
                    <LiveProgressBadge documentId={doc.id} />
                  )}
                </div>
              )}
            </div>

            {/* Row actions — always visible on mobile, revealed on hover on desktop */}
            <div className="flex items-center gap-1 shrink-0 sm:opacity-0 sm:group-hover:opacity-100 transition-opacity duration-150">

              {/* Completed: Listen/Resume */}
              {isCompleted && (
                <a
                  href={listenHref}
                  className="btn-primary btn-sm gap-1.5"
                  aria-label={`${listenLabel} — ${title}`}
                >
                  <svg className="w-3 h-3" viewBox="0 0 12 12" fill="currentColor" aria-hidden="true">
                    <path d="M2.5 2.5l7 3.5-7 3.5V2.5z"/>
                  </svg>
                  {listenLabel}
                </a>
              )}

              {/* Failed: Retry */}
              {isFailed && (
                <button
                  onClick={() => handleRetry(doc.id, false)}
                  disabled={retrying === doc.id}
                  className="btn-outline btn-sm gap-1.5"
                  aria-label={`Retry ${title}`}
                >
                  {retrying === doc.id ? <Spinner /> : <RetryIcon />}
                  Retry
                </button>
              )}

              {/* Stuck queued/processing: Retry + Cancel */}
              {stuck && (
                <>
                  <button
                    onClick={() => handleRetry(doc.id, true)}
                    disabled={retrying === doc.id}
                    className="btn-outline btn-sm gap-1.5"
                    aria-label={`Retry ${title}`}
                  >
                    {retrying === doc.id ? <Spinner /> : <RetryIcon />}
                    Retry
                  </button>
                  <button
                    onClick={() => handleCancel(doc.id)}
                    disabled={cancelling === doc.id}
                    className="btn-outline btn-sm gap-1.5 text-red-500 border-red-200 hover:bg-red-50"
                    aria-label={`Cancel ${title}`}
                  >
                    {cancelling === doc.id ? <Spinner /> : null}
                    Cancel
                  </button>
                </>
              )}

              {/* Fresh queued: Cancel only */}
              {isPending && !stuck && (
                <button
                  onClick={() => handleCancel(doc.id)}
                  disabled={cancelling === doc.id}
                  className="btn-outline btn-sm gap-1.5 text-sonoro-500"
                  aria-label={`Cancel ${title}`}
                >
                  {cancelling === doc.id ? <Spinner /> : null}
                  Cancel
                </button>
              )}

              {/* Delete button — shown for failed, stuck, and completed */}
              {(isFailed || stuck || isCompleted) && (
                <button
                  onClick={() => handleDelete(doc.id, title)}
                  disabled={deleting === doc.id}
                  className={cn(
                    'flex h-8 w-8 items-center justify-center rounded-xl text-sonoro-300 hover:text-red-500 hover:bg-red-50 transition-all duration-150',
                    deleting === doc.id && 'opacity-50 pointer-events-none',
                  )}
                  aria-label={`Delete ${title}`}
                >
                  {deleting === doc.id ? (
                    <Spinner />
                  ) : (
                    <svg className="w-3.5 h-3.5" viewBox="0 0 16 16" fill="currentColor" aria-hidden="true">
                      <path fillRule="evenodd" d="M5 3.25V4H2.75a.75.75 0 000 1.5h.3l.815 8.15A1.5 1.5 0 005.357 15h5.285a1.5 1.5 0 001.493-1.35l.815-8.15h.3a.75.75 0 000-1.5H11v-.75A2.25 2.25 0 008.75 1h-1.5A2.25 2.25 0 005 3.25zm2.25-.75a.75.75 0 00-.75.75V4h3v-.75a.75.75 0 00-.75-.75h-1.5zM6.05 6a.75.75 0 01.787.713l.275 5.5a.75.75 0 01-1.498.075l-.275-5.5A.75.75 0 016.05 6zm3.9 0a.75.75 0 01.712.787l-.275 5.5a.75.75 0 01-1.498-.075l.275-5.5a.75.75 0 01.786-.712z" clipRule="evenodd"/>
                    </svg>
                  )}
                </button>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}
