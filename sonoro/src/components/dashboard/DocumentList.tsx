import { useState } from 'react';
import type { Document } from '@/lib/api/types';
import { deleteDocument, retryProcessing, getErrorMessage } from '@/lib/api/client';
import { fmtRelative, fmtFileSize } from '@/lib/utils';
import { cn } from '@/lib/utils';

const STATUS_CONFIG = {
  pending:    { label: 'Queued',     cls: 'badge-neutral', dot: 'bg-sonoro-muted' },
  processing: { label: 'Processing', cls: 'badge-warning',  dot: 'bg-amber-500'   },
  completed:  { label: 'Ready',      cls: 'badge-success',  dot: 'bg-emerald-500' },
  failed:     { label: 'Failed',     cls: 'badge-error',    dot: 'bg-red-500'     },
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
      setDocs((prev) => prev.filter((d) => d.id !== id));
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
      setDocs((prev) => prev.map((d) => d.id === id ? { ...d, status: 'pending' } : d));
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
          {[35, 65, 90, 55, 80].map((h, i) => (
            <div key={i} className="waveform-bar" style={{ animationDelay: `${i * 0.15}s` }} />
          ))}
        </div>
        <h3 className="text-base font-semibold text-sonoro-900 mb-2">No audiobooks yet</h3>
        <p className="text-sm text-sonoro-muted mb-6 max-w-xs leading-relaxed">
          Upload your first PDF and it'll be converted to audio in under 60 seconds.
        </p>
        <a href="/dashboard/upload" className="btn-accent btn-sm">
          Upload a PDF
        </a>
      </div>
    );
  }

  return (
    <div className="space-y-2.5">
      {docs.map((doc) => {
        const s           = STATUS_CONFIG[doc.status] ?? STATUS_CONFIG.pending;
        const isActive    = doc.status === 'processing' || doc.status === 'pending';
        const isCompleted = doc.status === 'completed';
        const isFailed    = doc.status === 'failed';
        const title       = doc.title || doc.filename;

        return (
          <div
            key={doc.id}
            className={cn(
              'group card-base px-5 py-4 flex items-center gap-4 transition-all duration-200 ease-smooth',
              isCompleted && 'hover:shadow-hover hover:-translate-y-px cursor-pointer',
            )}
          >
            {/* PDF icon */}
            <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-red-50 border border-red-100/80 shrink-0">
              <svg className="w-5 h-5 text-red-400" viewBox="0 0 20 20" fill="currentColor" aria-hidden="true">
                <path fillRule="evenodd" d="M4 4a2 2 0 012-2h4.586A2 2 0 0112 2.586L15.414 6A2 2 0 0116 7.414V16a2 2 0 01-2 2H6a2 2 0 01-2-2V4z" clipRule="evenodd"/>
              </svg>
            </div>

            {/* Info */}
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2 mb-0.5 flex-wrap">
                <p className="text-sm font-semibold text-sonoro-900 truncate leading-snug">{title}</p>
                <span className={s.cls}>
                  <span
                    className={cn('h-1.5 w-1.5 rounded-full', s.dot, isActive && 'animate-pulse')}
                    aria-hidden="true"
                  />
                  {s.label}
                </span>
              </div>
              <p className="text-xs text-sonoro-400 tabular">
                {fmtFileSize(doc.file_size)}
                {doc.metadata?.pages ? ` · ${doc.metadata.pages} pages` : ''}
                {' · '}{fmtRelative(doc.upload_date)}
              </p>

              {/* Processing indeterminate bar */}
              {isActive && (
                <div className="mt-2 h-1 w-28 rounded-full bg-sonoro-border overflow-hidden">
                  <div className="h-full w-3/5 rounded-full bg-sonoro-amber animate-pulse-slow" />
                </div>
              )}
            </div>

            {/* Actions — reveal on row hover */}
            <div className="flex items-center gap-1.5 shrink-0 opacity-0 group-hover:opacity-100 transition-opacity duration-150">
              {isCompleted && (
                <a
                  href={`/dashboard/documents/${doc.id}`}
                  className="btn-primary btn-sm gap-1.5"
                  aria-label={`Listen to ${title}`}
                >
                  <svg className="w-3.5 h-3.5" viewBox="0 0 16 16" fill="currentColor" aria-hidden="true">
                    <path d="M4.5 3.5l8 4.5-8 4.5V3.5z"/>
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

              <button
                onClick={() => handleDelete(doc.id, title)}
                disabled={deleting === doc.id}
                className={cn(
                  'flex h-8 w-8 items-center justify-center rounded-xl text-sonoro-muted hover:text-red-600 hover:bg-red-50 transition-colors duration-150',
                  deleting === doc.id && 'opacity-50 cursor-not-allowed'
                )}
                aria-label={`Delete ${title}`}
              >
                {deleting === doc.id ? (
                  <svg className="w-4 h-4 animate-spin" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                    <circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" strokeOpacity=".2"/>
                    <path d="M12 2a10 10 0 0 1 10 10" stroke="currentColor" strokeWidth="4" strokeLinecap="round"/>
                  </svg>
                ) : (
                  <svg className="w-4 h-4" viewBox="0 0 20 20" fill="currentColor" aria-hidden="true">
                    <path fillRule="evenodd" d="M9 2a1 1 0 00-.894.553L7.382 4H4a1 1 0 000 2v10a2 2 0 002 2h8a2 2 0 002-2V6a1 1 0 100-2h-3.382l-.724-1.447A1 1 0 0011 2H9zM7 8a1 1 0 012 0v6a1 1 0 11-2 0V8zm5-1a1 1 0 00-1 1v6a1 1 0 102 0V8a1 1 0 00-1-1z" clipRule="evenodd"/>
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
