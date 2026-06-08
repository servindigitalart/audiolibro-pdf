/**
 * CoverPanel — "Find Cover" island for the document detail sidebar.
 *
 * Renders a trigger button. On click, expands an inline panel with
 * CoverSuggestions. On cover selection or manual upload, refreshes
 * all [data-cover-img] elements and hides the panel.
 */

import { useState, useCallback } from 'react';
import CoverSuggestions from '@/components/upload/CoverSuggestions';
import { uploadCover, resetCover } from '@/lib/api/client';
import { cn } from '@/lib/utils';

interface Props {
  documentId: string;
  initialCoverUrl?: string;
}

export default function CoverPanel({ documentId, initialCoverUrl }: Props) {
  const [open,     setOpen]     = useState(false);
  const [coverUrl, setCoverUrl] = useState(initialCoverUrl ?? '');
  const [status,   setStatus]   = useState('');
  const [uploading, setUploading] = useState(false);

  const applyNewCover = useCallback((url: string) => {
    setCoverUrl(url);
    setOpen(false);
    setStatus('Cover updated!');
    setTimeout(() => setStatus(''), 3000);
    // Refresh all cover images rendered server-side
    document.querySelectorAll<HTMLImageElement>('[data-cover-img]').forEach((el) => {
      el.src = url;
    });
  }, []);

  const handleUpload = useCallback(() => {
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = 'image/jpeg,image/png,image/webp';
    input.onchange = async () => {
      const file = input.files?.[0];
      if (!file) return;
      setUploading(true);
      setStatus('Uploading…');
      try {
        const { cover_url } = await uploadCover(documentId, file);
        applyNewCover(cover_url);
      } catch {
        setStatus('Upload failed. Try a smaller image.');
      } finally {
        setUploading(false);
      }
    };
    input.click();
  }, [documentId, applyNewCover]);

  const handleReset = useCallback(async () => {
    setStatus('Resetting…');
    try {
      await resetCover(documentId);
      setCoverUrl('');
      setStatus('Cover reset.');
      setTimeout(() => setStatus(''), 3000);
      document.querySelectorAll<HTMLImageElement>('[data-cover-img]').forEach((el) => {
        el.removeAttribute('src');
      });
    } catch {
      setStatus('Could not reset cover.');
    }
  }, [documentId]);

  return (
    <div className="flex-1 min-w-0">
      {/* Cover actions row */}
      <div className="flex flex-wrap gap-2 mb-2">
        <button
          type="button"
          onClick={handleUpload}
          disabled={uploading}
          className="text-xs px-3 py-1.5 rounded-lg border border-sonoro-border text-sonoro-600 hover:text-sonoro-900 hover:border-sonoro-400 transition-colors disabled:opacity-50"
        >
          {uploading ? 'Uploading…' : 'Upload image'}
        </button>

        <button
          type="button"
          onClick={() => setOpen((o) => !o)}
          className={cn(
            'text-xs px-3 py-1.5 rounded-lg border transition-colors',
            open
              ? 'border-amber-400/50 bg-amber-50 text-sonoro-amber-dark'
              : 'border-amber-400/30 bg-amber-50/50 text-sonoro-amber-dark hover:bg-amber-50',
          )}
        >
          {open ? 'Close' : 'Find cover'}
        </button>

        {coverUrl && (
          <button
            type="button"
            onClick={handleReset}
            className="text-xs text-sonoro-400 hover:text-red-500 transition-colors"
          >
            Reset to generated
          </button>
        )}
      </div>

      {/* Status line */}
      {status && (
        <p className="text-xs text-sonoro-muted mb-2 min-h-[1rem]">{status}</p>
      )}

      {/* Inline suggestions panel */}
      {open && (
        <div className="mt-3 p-3 rounded-xl bg-sonoro-surface border border-sonoro-border/60">
          <CoverSuggestions
            documentId={documentId}
            autoLoad
            onSelect={(url) => applyNewCover(url)}
            onUpload={handleUpload}
            onSkip={() => setOpen(false)}
          />
        </div>
      )}
    </div>
  );
}
