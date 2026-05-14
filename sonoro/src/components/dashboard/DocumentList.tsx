import { useState } from 'react';
import type { Document } from '@/lib/api/types';
import { deleteDocument, getErrorMessage } from '@/lib/api/client';
import { fmtDate, fmtRelative, fmtFileSize } from '@/lib/utils';
import { cn } from '@/lib/utils';

const STATUS_CONFIG = {
  pending:    { label: 'Queued',      cls: 'badge-neutral' },
  processing: { label: 'Processing',  cls: 'badge-warning'  },
  completed:  { label: 'Ready',       cls: 'badge-success'  },
  failed:     { label: 'Failed',      cls: 'badge-error'    },
} as const;

interface Props {
  initialDocuments: Document[];
}

export default function DocumentList({ initialDocuments }: Props) {
  const [docs, setDocs] = useState<Document[]>(initialDocuments);
  const [deleting, setDeleting] = useState<string | null>(null);

  async function handleDelete(id: string) {
    if (!confirm('Delete this document and its audiobook? This cannot be undone.')) return;
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

  if (docs.length === 0) {
    return (
      <div className="card-base flex flex-col items-center justify-center py-20 text-center">
        <div className="flex h-16 w-16 items-center justify-center rounded-2xl bg-sonoro-surface border border-sonoro-border mb-5">
          <svg className="w-7 h-7 text-sonoro-muted" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true">
            <path d="M9 12h6m-6 4h6m2 5H7a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5.586a1 1 0 0 1 .707.293l5.414 5.414a1 1 0 0 1 .293.707V19a2 2 0 0 1-2 2Z" strokeLinecap="round" strokeLinejoin="round"/>
          </svg>
        </div>
        <h3 className="text-base font-semibold text-sonoro-900 mb-2">No audiobooks yet</h3>
        <p className="text-sm text-sonoro-muted mb-6 max-w-xs">
          Upload your first PDF and it'll be converted to audio in under 60 seconds.
        </p>
        <a href="/dashboard/upload" className="btn-accent btn-lg">
          Upload a PDF
        </a>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {docs.map((doc) => {
        const status = STATUS_CONFIG[doc.status] ?? STATUS_CONFIG.pending;
        const isProcessing = doc.status === 'processing' || doc.status === 'pending';

        return (
          <div
            key={doc.id}
            className="card-base p-5 flex items-center gap-4 hover:shadow-hover transition-all duration-200"
          >
            {/* File icon */}
            <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-red-50 border border-red-100 shrink-0">
              <svg className="w-5 h-5 text-red-500" viewBox="0 0 20 20" fill="currentColor" aria-hidden="true">
                <path d="M4 3a2 2 0 00-2 2v10a2 2 0 002 2h12a2 2 0 002-2V7l-4-4H4zm8 0v4h4"/>
              </svg>
            </div>

            {/* Info */}
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2 mb-0.5 flex-wrap">
                <p className="text-sm font-semibold text-sonoro-900 truncate">{doc.title || doc.filename}</p>
                <span className={status.cls}>{status.label}</span>
              </div>
              <p className="text-xs text-sonoro-muted">
                {fmtFileSize(doc.file_size)} ·{' '}
                {doc.metadata?.pages ? `${doc.metadata.pages} pages · ` : ''}
                {fmtRelative(doc.upload_date)}
              </p>
              {isProcessing && (
                <div className="mt-2 h-1 w-32 rounded-full bg-sonoro-border overflow-hidden">
                  <div className="h-full rounded-full bg-sonoro-amber animate-pulse-slow" style={{ width: '60%' }} />
                </div>
              )}
            </div>

            {/* Actions */}
            <div className="flex items-center gap-2 shrink-0">
              {doc.status === 'completed' && (
                <a
                  href={`/dashboard/documents/${doc.id}`}
                  className="btn-outline btn-sm"
                  aria-label={`Listen to ${doc.title || doc.filename}`}
                >
                  <svg className="w-3.5 h-3.5" viewBox="0 0 16 16" fill="currentColor" aria-hidden="true">
                    <path d="M6 3.5l6 4.5-6 4.5V3.5z"/>
                  </svg>
                  Listen
                </a>
              )}
              <button
                onClick={() => handleDelete(doc.id)}
                disabled={deleting === doc.id}
                className={cn(
                  'flex h-8 w-8 items-center justify-center rounded-lg text-sonoro-muted hover:text-red-600 hover:bg-red-50 transition-colors',
                  deleting === doc.id && 'opacity-50 cursor-not-allowed'
                )}
                aria-label={`Delete ${doc.title || doc.filename}`}
              >
                <svg className="w-4 h-4" viewBox="0 0 20 20" fill="currentColor" aria-hidden="true">
                  <path fillRule="evenodd" d="M9 2a1 1 0 00-.894.553L7.382 4H4a1 1 0 000 2v10a2 2 0 002 2h8a2 2 0 002-2V6a1 1 0 100-2h-3.382l-.724-1.447A1 1 0 0011 2H9zM7 8a1 1 0 012 0v6a1 1 0 11-2 0V8zm5-1a1 1 0 00-1 1v6a1 1 0 102 0V8a1 1 0 00-1-1z" clipRule="evenodd"/>
                </svg>
              </button>
            </div>
          </div>
        );
      })}
    </div>
  );
}
