/**
 * CoverSuggestions — ranked cover candidate carousel.
 *
 * Used in two places:
 *   1. UploadZone detected-book card (inline, after metadata poll)
 *   2. Document detail "Find Cover" modal (opened on demand)
 *
 * Props:
 *   documentId   — required to hit the suggestions endpoint
 *   onSelect     — called with { cover_url } after a cover is confirmed
 *   onUpload     — caller opens the file-picker for manual upload
 *   onSkip       — user explicitly keeps generated cover
 *   autoLoad     — fetch suggestions immediately on mount (default: false)
 */

import { useState, useEffect, useCallback } from 'react';
import type { CoverCandidate } from '@/lib/api/types';
import { getCoverSuggestions, selectCoverSuggestion } from '@/lib/api/client';
import { cn } from '@/lib/utils';

interface Props {
  documentId: string;
  onSelect?:  (coverUrl: string) => void;
  onUpload?:  () => void;
  onSkip?:    () => void;
  autoLoad?:  boolean;
  className?: string;
}

type LoadState = 'idle' | 'loading' | 'done' | 'error';
type SelectState = { [id: string]: 'idle' | 'selecting' | 'done' | 'error' };

const CONFIDENCE_COLORS: Record<string, string> = {
  high:   'bg-emerald-500/20 text-emerald-300 border-emerald-500/30',
  medium: 'bg-amber-500/20 text-amber-300 border-amber-500/30',
  low:    'bg-zinc-500/20 text-zinc-400 border-zinc-600/30',
};

const SOURCE_LABELS: Record<string, string> = {
  google_books: 'Google Books',
  open_library: 'Open Library',
  generated:    'Generated',
};

function CoverSkeleton() {
  return (
    <div className="flex gap-3">
      {[0, 1, 2].map((i) => (
        <div key={i} className="flex-shrink-0 animate-pulse">
          <div className="w-[88px] h-[132px] rounded-lg bg-white/8" />
          <div className="mt-2 h-3 w-16 rounded bg-white/8 mx-auto" />
          <div className="mt-1 h-3 w-12 rounded bg-white/8 mx-auto" />
        </div>
      ))}
    </div>
  );
}

function CoverCard({
  candidate,
  onUse,
  isSelecting,
  isDone,
}: {
  candidate:  CoverCandidate;
  onUse:      () => void;
  isSelecting: boolean;
  isDone:     boolean;
}) {
  const [imgError, setImgError] = useState(false);

  return (
    <div
      className={cn(
        'flex-shrink-0 flex flex-col items-center gap-1.5',
        isDone && 'opacity-50 pointer-events-none',
      )}
    >
      {/* Cover image */}
      <div
        className={cn(
          'relative w-[88px] h-[132px] rounded-lg overflow-hidden bg-white/8 border border-white/10 shadow-md cursor-pointer',
          'transition-all duration-150',
          !isDone && 'hover:border-amber-400/60 hover:shadow-amber-500/20 hover:scale-[1.03]',
        )}
        onClick={onUse}
        title={`Use: ${candidate.title || 'this cover'}`}
      >
        {!imgError ? (
          <img
            src={candidate.thumbnail_url}
            alt={candidate.title || 'Book cover'}
            className="absolute inset-0 w-full h-full object-cover"
            loading="lazy"
            onError={() => setImgError(true)}
          />
        ) : (
          <div className="absolute inset-0 flex items-center justify-center text-zinc-500 text-xs text-center px-2">
            No image
          </div>
        )}

        {/* Done overlay */}
        {isDone && (
          <div className="absolute inset-0 bg-emerald-500/30 flex items-center justify-center">
            <svg className="w-8 h-8 text-emerald-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
            </svg>
          </div>
        )}

        {/* Selecting spinner */}
        {isSelecting && !isDone && (
          <div className="absolute inset-0 bg-black/50 flex items-center justify-center">
            <svg className="w-6 h-6 animate-spin text-amber-400" fill="none" viewBox="0 0 24 24">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" />
            </svg>
          </div>
        )}
      </div>

      {/* Badges */}
      <div className="flex flex-col items-center gap-1">
        <span className={cn(
          'text-[10px] px-1.5 py-0.5 rounded border font-medium leading-none',
          CONFIDENCE_COLORS[candidate.confidence_label] ?? CONFIDENCE_COLORS.low,
        )}>
          {candidate.confidence_label}
        </span>
        <span className="text-[9px] text-zinc-500 leading-none">
          {SOURCE_LABELS[candidate.source] ?? candidate.source}
        </span>
      </div>

      {/* Use button */}
      <button
        onClick={onUse}
        disabled={isSelecting || isDone}
        className={cn(
          'text-[10px] px-2 py-1 rounded font-medium transition-colors',
          'bg-amber-500/20 text-amber-300 border border-amber-500/30',
          'hover:bg-amber-500/30 disabled:opacity-50 disabled:cursor-not-allowed',
        )}
      >
        {isSelecting ? 'Applying…' : isDone ? 'Applied' : 'Use cover'}
      </button>
    </div>
  );
}

export default function CoverSuggestions({
  documentId,
  onSelect,
  onUpload,
  onSkip,
  autoLoad = false,
  className,
}: Props) {
  const [loadState,    setLoadState]    = useState<LoadState>(autoLoad ? 'loading' : 'idle');
  const [candidates,  setCandidates]   = useState<CoverCandidate[]>([]);
  const [selectState, setSelectState]  = useState<SelectState>({});
  const [errorMsg,    setErrorMsg]     = useState('');
  const [selectedId,  setSelectedId]   = useState<string | null>(null);

  const loadSuggestions = useCallback(async () => {
    setLoadState('loading');
    setErrorMsg('');
    try {
      const res = await getCoverSuggestions(documentId);
      setCandidates(res.candidates);
      setLoadState('done');
    } catch (err: unknown) {
      setErrorMsg('Could not load cover suggestions. Try again.');
      setLoadState('error');
    }
  }, [documentId]);

  useEffect(() => {
    if (autoLoad) loadSuggestions();
  }, [autoLoad, loadSuggestions]);

  const handleSelect = useCallback(async (candidate: CoverCandidate) => {
    if (selectState[candidate.id] === 'selecting') return;
    setSelectState((s) => ({ ...s, [candidate.id]: 'selecting' }));
    try {
      const { cover_url } = await selectCoverSuggestion(documentId, candidate);
      setSelectState((s) => ({ ...s, [candidate.id]: 'done' }));
      setSelectedId(candidate.id);
      onSelect?.(cover_url);
    } catch {
      setSelectState((s) => ({ ...s, [candidate.id]: 'error' }));
    }
  }, [documentId, onSelect, selectState]);

  // ── Idle state — show "Find cover" trigger ────────────────────────────────
  if (loadState === 'idle') {
    return (
      <div className={cn('flex items-center gap-2', className)}>
        <button
          onClick={loadSuggestions}
          className="text-xs px-3 py-1.5 rounded-lg border border-amber-500/30 bg-amber-500/10 text-amber-300 hover:bg-amber-500/20 transition-colors"
        >
          Find cover
        </button>
        {onUpload && (
          <button
            onClick={onUpload}
            className="text-xs px-3 py-1.5 rounded-lg border border-white/10 text-zinc-400 hover:text-zinc-300 hover:border-white/20 transition-colors"
          >
            Upload image
          </button>
        )}
      </div>
    );
  }

  // ── Loading skeleton ──────────────────────────────────────────────────────
  if (loadState === 'loading') {
    return (
      <div className={cn('space-y-3', className)}>
        <p className="text-xs text-zinc-500">Searching for covers…</p>
        <CoverSkeleton />
      </div>
    );
  }

  // ── Error state ───────────────────────────────────────────────────────────
  if (loadState === 'error') {
    return (
      <div className={cn('space-y-2', className)}>
        <p className="text-xs text-red-400">{errorMsg}</p>
        <div className="flex gap-2">
          <button
            onClick={loadSuggestions}
            className="text-xs px-3 py-1.5 rounded-lg border border-white/10 text-zinc-400 hover:text-zinc-300 transition-colors"
          >
            Retry
          </button>
          {onUpload && (
            <button
              onClick={onUpload}
              className="text-xs px-3 py-1.5 rounded-lg border border-white/10 text-zinc-400 hover:text-zinc-300 transition-colors"
            >
              Upload image
            </button>
          )}
        </div>
      </div>
    );
  }

  // ── No results ────────────────────────────────────────────────────────────
  if (candidates.length === 0) {
    return (
      <div className={cn('space-y-2', className)}>
        <p className="text-xs text-zinc-500">No covers found for this book.</p>
        <div className="flex gap-2">
          {onUpload && (
            <button
              onClick={onUpload}
              className="text-xs px-3 py-1.5 rounded-lg border border-white/10 text-zinc-400 hover:text-zinc-300 transition-colors"
            >
              Upload image
            </button>
          )}
          {onSkip && (
            <button
              onClick={onSkip}
              className="text-xs px-3 py-1.5 rounded-lg text-zinc-500 hover:text-zinc-400 transition-colors"
            >
              Keep generated cover
            </button>
          )}
        </div>
      </div>
    );
  }

  // ── Results carousel ──────────────────────────────────────────────────────
  return (
    <div className={cn('space-y-3', className)}>
      <div className="flex items-center justify-between">
        <p className="text-xs text-zinc-400 font-medium">
          {candidates.length} cover{candidates.length !== 1 ? 's' : ''} found
        </p>
        <button
          onClick={loadSuggestions}
          className="text-[10px] text-zinc-600 hover:text-zinc-400 transition-colors"
        >
          Refresh
        </button>
      </div>

      {/* Horizontally scrollable carousel */}
      <div className="flex gap-3 overflow-x-auto pb-1 scrollbar-hide">
        {candidates.map((c) => (
          <CoverCard
            key={c.id}
            candidate={c}
            onUse={() => handleSelect(c)}
            isSelecting={selectState[c.id] === 'selecting'}
            isDone={selectState[c.id] === 'done' || selectedId === c.id}
          />
        ))}
      </div>

      {/* Secondary actions */}
      <div className="flex gap-3 pt-0.5">
        {onUpload && !selectedId && (
          <button
            onClick={onUpload}
            className="text-xs text-zinc-500 hover:text-zinc-300 transition-colors"
          >
            Upload image instead
          </button>
        )}
        {onSkip && !selectedId && (
          <button
            onClick={onSkip}
            className="text-xs text-zinc-600 hover:text-zinc-400 transition-colors"
          >
            Keep generated cover
          </button>
        )}
        {selectedId && (
          <p className="text-xs text-emerald-400">Cover applied to your audiobook.</p>
        )}
      </div>
    </div>
  );
}
