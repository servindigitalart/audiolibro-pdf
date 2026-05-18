import { useState } from 'react';
import type { Document } from '@/lib/api/types';
import { deleteDocument, retryProcessing, getErrorMessage } from '@/lib/api/client';
import { fmtRelative, fmtFileSize } from '@/lib/utils';
import { cn } from '@/lib/utils';

const STATUS_CONFIG = {
  pending:    { label: 'Queued',     cls: 'badge-neutral', dot: 'bg-sonoro-400'  },
  processing: { label: 'Processing', cls: 'badge-warning',  dot: 'bg-amber-500'  },
  completed:  { label: 'Ready',      cls: 'badge-success',  dot: 'bg-emerald-500' },
  failed:     { label: 'Failed',     cls: 'badge-error',    dot: 'bg-red-500'    },
} as const;

interface Props {
  initialDocuments: Document[];
}

export default function DocumentList({ initialDocuments }: Props) {
  const [docs, setDocs]         = useState<Document[]>(initialDocuments);
  const [deleting, setDeleting] = useState<string | null>(null);
  const [retrying, setRetrying] = useState<string | null>(null);

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

  async function handleRetry(id: string) {
    setRetrying(id);
    try {
      await retryProcessing(id);
      setDocs(prev => prev.map(d => d.id === id ? { ...d, status: 'pending' } : d));
    } catch (err) {
      alert(getErrorMessage(err));
    } finally {
      setRetrying(null);
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
        const s           = STATUS_CONFIG[doc.status] ?? STATUS_CONFIG.pending;
        const isActive    = doc.status === 'processing' || doc.status === 'pending';
        const isCompleted = doc.status === 'completed';
        const isFailed    = doc.status === 'failed';
        const title       = doc.title || doc.filename;

        return (
          <div
            key={doc.id}
            className={cn(
              'group card-base flex items-center gap-4 px-5 py-4 transition-all duration-200',
              isCompleted && 'hover:shadow-hover hover:-translate-y-px',
            )}
            style={{ animationDelay: `${listIdx * 40}ms` }}
          >
            {/* Document type icon */}
            <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-red-50 border border-red-100 transition-transform duration-200 group-hover:scale-105">
              <svg className="w-5 h-5 text-red-400" viewBox="0 0 20 20" fill="currentColor" aria-hidden="true">
                <path fillRule="evenodd" d="M4 4a2 2 0 012-2h4.586A2 2 0 0112 2.586L15.414 6A2 2 0 0116 7.414V16a2 2 0 01-2 2H6a2 2 0 01-2-2V4z" clipRule="evenodd"/>
              </svg>
            </div>

            {/* Document info */}
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2 mb-0.5 flex-wrap">
                <p className="text-sm font-semibold text-sonoro-900 truncate leading-snug">{title}</p>
                <span className={s.cls}>
                  <span className={cn('h-1.5 w-1.5 rounded-full', s.dot, isActive && 'animate-pulse')} aria-hidden="true" />
                  {s.label}
                </span>
              </div>
              <p className="text-xs text-sonoro-400 tabular">
                {fmtFileSize(doc.file_size)}
                {doc.metadata?.pages ? ` · ${doc.metadata.pages}p` : ''}
                {' · '}{fmtRelative(doc.upload_date)}
              </p>

              {/* Processing indeterminate bar */}
              {isActive && (
                <div className="mt-2 h-0.5 w-24 rounded-full bg-sonoro-border overflow-hidden">
                  <div className="h-full rounded-full bg-sonoro-amber animate-shimmer" style={{ backgroundSize: '200% 100%', background: 'linear-gradient(90deg, transparent 0%, #F59E0B 50%, transparent 100%)' }} />
                </div>
              )}
            </div>

            {/* Row actions — revealed on hover */}
            <div className="flex items-center gap-1 shrink-0 opacity-0 group-hover:opacity-100 transition-opacity duration-150">
              {isCompleted && (
                <a
                  href={`/dashboard/documents/${doc.id}`}
                  className="btn-primary btn-sm gap-1.5"
                  aria-label={`Listen to ${title}`}
                >
                  <svg className="w-3 h-3" viewBox="0 0 12 12" fill="currentColor" aria-hidden="true">
                    <path d="M2.5 2.5l7 3.5-7 3.5V2.5z"/>
                  </svg>
                  Listen
                </a>
              )}

              {isFailed && (
                <button
                  onClick={() => handleRetry(doc.id)}
                  disabled={retrying === doc.id}
                  className="btn-outline btn-sm gap-1.5"
                  aria-label={`Retry ${title}`}
                >
                  {retrying === doc.id ? (
                    <svg className="w-3.5 h-3.5 animate-spin" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                      <circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" strokeOpacity=".2"/>
                      <path d="M12 2a10 10 0 0 1 10 10" stroke="currentColor" strokeWidth="4" strokeLinecap="round"/>
                    </svg>
                  ) : (
                    <svg className="w-3.5 h-3.5" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                      <path d="M1.5 4.5A6.5 6.5 0 0 1 13 3M14.5 11.5A6.5 6.5 0 0 1 3 13M14.5 8V4.5H11"/>
                    </svg>
                  )}
                  Retry
                </button>
              )}

              {/* Delete button */}
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
                  <svg className="w-3.5 h-3.5 animate-spin" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                    <circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" strokeOpacity=".2"/>
                    <path d="M12 2a10 10 0 0 1 10 10" stroke="currentColor" strokeWidth="4" strokeLinecap="round"/>
                  </svg>
                ) : (
                  <svg className="w-3.5 h-3.5" viewBox="0 0 16 16" fill="currentColor" aria-hidden="true">
                    <path fillRule="evenodd" d="M5 3.25V4H2.75a.75.75 0 000 1.5h.3l.815 8.15A1.5 1.5 0 005.357 15h5.285a1.5 1.5 0 001.493-1.35l.815-8.15h.3a.75.75 0 000-1.5H11v-.75A2.25 2.25 0 008.75 1h-1.5A2.25 2.25 0 005 3.25zm2.25-.75a.75.75 0 00-.75.75V4h3v-.75a.75.75 0 00-.75-.75h-1.5zM6.05 6a.75.75 0 01.787.713l.275 5.5a.75.75 0 01-1.498.075l-.275-5.5A.75.75 0 016.05 6zm3.9 0a.75.75 0 01.712.787l-.275 5.5a.75.75 0 01-1.498-.075l.275-5.5a.75.75 0 01.786-.712z" clipRule="evenodd"/>
                  </svg>
                )}
              </button>
            </div>
          </div>
        );
      })}
    </div>
  );
}
