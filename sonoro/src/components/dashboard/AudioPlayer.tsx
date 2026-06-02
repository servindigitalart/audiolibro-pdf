import { useState, useRef, useEffect, useMemo } from 'react';
import type { Chapter } from '@/lib/api/types';
import { useAudioPlayer } from '@/hooks/useAudioPlayer';
import { usePlaybackProgress, loadProgress, saveProgress, clearProgress } from '@/hooks/usePlaybackProgress';
import { fmtDuration } from '@/lib/utils';
import { cn } from '@/lib/utils';
import BookCover from '@/components/ui/BookCover';
import { track, startPlaybackSession, endPlaybackSession } from '@/lib/analytics';

// Deterministic waveform heights — two overlapping sine waves give a natural shape
const WAVEFORM = Array.from({ length: 60 }, (_, i) =>
  Math.round(20 + Math.abs(Math.sin(i * 0.47 + 0.3) * 0.55 + Math.sin(i * 0.13 + 1.2) * 0.45) * 76)
);

const SPEEDS = [0.75, 1, 1.25, 1.5, 2];

// Sleep timer options in minutes (0 = off)
const SLEEP_OPTIONS = [0, 15, 30, 45, 60] as const;
type SleepOption = typeof SLEEP_OPTIONS[number];

// Ambient palette colours derived from BookCover palettes — same deterministic hash
const AMBIENT_PALETTES = [
  { from: '#D97706', to: '#92400E' },
  { from: '#1D4ED8', to: '#1E3A5F' },
  { from: '#059669', to: '#064E3B' },
  { from: '#7C3AED', to: '#3B0764' },
  { from: '#DB2777', to: '#831843' },
  { from: '#0891B2', to: '#164E63' },
  { from: '#4F46E5', to: '#1E1B4B' },
  { from: '#B45309', to: '#78350F' },
  { from: '#0F766E', to: '#042F2E' },
  { from: '#6D28D9', to: '#2E1065' },
];

function hashString(s: string): number {
  let h = 0;
  for (const c of s) h = (h * 31 + c.charCodeAt(0)) >>> 0;
  return h;
}

function getAmbient(title: string) {
  return AMBIENT_PALETTES[hashString(title) % AMBIENT_PALETTES.length];
}

// Generate a square cover art data URL for the Media Session API.
// Returns a 512×512 canvas PNG with the same gradient + initials as BookCover.
// Sizes are generated on demand from this single canvas to avoid 6 redraws.
const COVER_PALETTES = [
  { from: '#D97706', to: '#92400E', text: '#FFF8E7' },
  { from: '#1D4ED8', to: '#1E3A5F', text: '#EFF6FF' },
  { from: '#059669', to: '#064E3B', text: '#ECFDF5' },
  { from: '#7C3AED', to: '#3B0764', text: '#F5F3FF' },
  { from: '#DB2777', to: '#831843', text: '#FDF2F8' },
  { from: '#0891B2', to: '#164E63', text: '#ECFEFF' },
  { from: '#4F46E5', to: '#1E1B4B', text: '#EEF2FF' },
  { from: '#B45309', to: '#78350F', text: '#FFFBEB' },
  { from: '#0F766E', to: '#042F2E', text: '#F0FDFA' },
  { from: '#6D28D9', to: '#2E1065', text: '#FAF5FF' },
];

function generateCoverDataUrl(title: string, size = 512): string {
  try {
    const canvas = document.createElement('canvas');
    canvas.width  = size;
    canvas.height = size;
    const ctx = canvas.getContext('2d');
    if (!ctx) return '';

    const h       = hashString(title);
    const palette = COVER_PALETTES[h % COVER_PALETTES.length];

    // Background gradient
    const grad = ctx.createLinearGradient(0, 0, size, size);
    grad.addColorStop(0, palette.from);
    grad.addColorStop(1, palette.to);
    ctx.fillStyle = grad;
    ctx.fillRect(0, 0, size, size);

    // Subtle diagonal stripe overlay
    ctx.save();
    ctx.globalAlpha = 0.07;
    ctx.strokeStyle = palette.text;
    ctx.lineWidth   = size / 256;
    const angle = 30 + (h % 5) * 18;
    const rad   = (angle * Math.PI) / 180;
    const step  = size / 36;
    for (let i = -size; i < size * 2; i += step) {
      ctx.beginPath();
      ctx.moveTo(i * Math.cos(rad), i * Math.sin(rad));
      ctx.lineTo(i * Math.cos(rad) + size * 2, i * Math.sin(rad) + size * 2);
      ctx.stroke();
    }
    ctx.restore();

    // Initials / short title
    const words   = title.trim().split(/\s+/).filter(Boolean);
    const initials = words.slice(0, 2).map(w => w[0].toUpperCase()).join('');
    const fontSize = Math.round(size * 0.28);
    ctx.globalAlpha  = 1;
    ctx.fillStyle    = palette.text;
    ctx.font         = `bold ${fontSize}px -apple-system, system-ui, sans-serif`;
    ctx.textAlign    = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText(initials, size / 2, size / 2);

    // Bottom spine accent
    ctx.globalAlpha  = 0.2;
    ctx.fillStyle    = palette.text;
    ctx.fillRect(0, size - size * 0.015, size, size * 0.015);

    return canvas.toDataURL('image/png');
  } catch {
    return '';
  }
}

interface Props {
  chapters:      Chapter[];
  documentTitle: string;
  documentId?:   string;
  autoplay?:     boolean;
}

// ── Waveform ─────────────────────────────────────────────────────────────────
function Waveform({
  progress,
  isPlaying,
  onSeek,
  compact = false,
}: {
  progress:  number;
  isPlaying: boolean;
  onSeek:    (p: number) => void;
  compact?:  boolean;
}) {
  const ref        = useRef<HTMLDivElement>(null);
  const dragging   = useRef(false);

  function getPct(clientX: number) {
    if (!ref.current) return 0;
    const { left, width } = ref.current.getBoundingClientRect();
    return Math.max(0, Math.min(1, (clientX - left) / width));
  }

  function onPointerDown(e: React.PointerEvent) {
    dragging.current = true;
    (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
    onSeek(getPct(e.clientX));
  }
  function onPointerMove(e: React.PointerEvent) {
    if (dragging.current) onSeek(getPct(e.clientX));
  }
  function onPointerUp(e: React.PointerEvent) {
    dragging.current = false;
    (e.currentTarget as HTMLElement).releasePointerCapture(e.pointerId);
  }

  return (
    <div
      ref={ref}
      className={cn(
        'relative flex items-end gap-px cursor-pointer select-none touch-none group/wf',
        compact ? 'h-10' : 'h-16',
      )}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      role="slider"
      aria-valuenow={Math.round(progress * 100)}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-label="Playback position"
    >
      {WAVEFORM.map((h, i) => {
        const barPct = i / WAVEFORM.length;
        const played = barPct <= progress;
        return (
          <div
            key={i}
            className={cn(
              'flex-1 rounded-[2px] transition-colors duration-100',
              played ? 'bg-sonoro-amber' : 'bg-sonoro-200',
            )}
            style={{
              height: `${h}%`,
              opacity: played ? 0.9 + (h / WAVEFORM.reduce((a, b) => a + b, 0)) * 0.1 : 0.45,
            }}
          />
        );
      })}

      {/* Playhead cursor */}
      <div
        className="absolute bottom-0 top-0 w-px bg-sonoro-amber-dark rounded-full pointer-events-none opacity-0 group-hover/wf:opacity-100 transition-opacity"
        style={{ left: `${progress * 100}%`, boxShadow: '0 0 6px rgba(245,158,11,0.5)' }}
        aria-hidden="true"
      />
    </div>
  );
}

// ── Seek bar (precision scrubber) ────────────────────────────────────────────
function SeekBar({
  progress,
  currentTime,
  duration,
  onSeek,
}: {
  progress:    number;
  currentTime: number;
  duration:    number;
  onSeek:      (p: number) => void;
}) {
  const ref      = useRef<HTMLDivElement>(null);
  const dragging = useRef(false);

  function getPct(clientX: number) {
    if (!ref.current) return 0;
    const { left, width } = ref.current.getBoundingClientRect();
    return Math.max(0, Math.min(1, (clientX - left) / width));
  }

  function onPointerDown(e: React.PointerEvent) {
    dragging.current = true;
    (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
    onSeek(getPct(e.clientX));
  }
  function onPointerMove(e: React.PointerEvent) {
    if (dragging.current) onSeek(getPct(e.clientX));
  }
  function onPointerUp(e: React.PointerEvent) {
    dragging.current = false;
    (e.currentTarget as HTMLElement).releasePointerCapture(e.pointerId);
  }

  const remaining = duration > 0 ? Math.max(0, duration - currentTime) : 0;

  return (
    <div className="select-none touch-none">
      {/* Hit area + track */}
      <div
        ref={ref}
        className="relative flex items-center h-5 cursor-pointer group/seek"
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
      >
        {/* Track */}
        <div className="absolute inset-x-0 h-1 bg-sonoro-200 rounded-full overflow-hidden">
          <div
            className="h-full bg-sonoro-amber rounded-full transition-all duration-75"
            style={{ width: `${progress * 100}%` }}
          />
        </div>
        {/* Thumb */}
        <div
          className="absolute h-3.5 w-3.5 -translate-x-1/2 rounded-full bg-sonoro-amber border-2 border-white shadow-md opacity-0 group-hover/seek:opacity-100 transition-opacity pointer-events-none"
          style={{ left: `${progress * 100}%` }}
        />
      </div>

      {/* Time labels */}
      <div className="flex justify-between mt-1.5">
        <span className="text-xs text-sonoro-muted tabular-nums">{fmtDuration(currentTime)}</span>
        <span className="text-xs text-sonoro-muted tabular-nums">
          {remaining > 0 ? `–${fmtDuration(remaining)}` : duration > 0 ? fmtDuration(duration) : '--:--'}
        </span>
      </div>
    </div>
  );
}

// ── Chapter list ─────────────────────────────────────────────────────────────
function ChapterList({
  chapters,
  currentIdx,
  isPlaying,
  onSelect,
  dark = false,
}: {
  chapters:   Chapter[];
  currentIdx: number;
  isPlaying:  boolean;
  onSelect:   (i: number) => void;
  dark?:      boolean;
}) {
  const activeRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    activeRef.current?.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
  }, [currentIdx]);

  return (
    <div className="max-h-64 overflow-y-auto">
      {chapters.map((ch, i) => {
        const active    = i === currentIdx;
        const available = ch.status === 'completed';
        return (
          <button
            key={ch.id}
            ref={active ? activeRef : null}
            onClick={() => available && onSelect(i)}
            disabled={!available}
            className={cn(
              'flex w-full items-center gap-3 px-5 py-3 text-left transition-all duration-150',
              active
                ? dark
                  ? 'bg-white/[0.08] border-l-2 border-sonoro-amber'
                  : 'bg-sonoro-amber-light/60 border-l-2 border-sonoro-amber'
                : dark
                  ? 'border-l-2 border-transparent hover:bg-white/[0.04]'
                  : 'border-l-2 border-transparent hover:bg-sonoro-surface',
              !available && 'opacity-40 cursor-not-allowed',
            )}
          >
            {/* Chapter number / playing indicator */}
            <div className={cn(
              'flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-[10px] font-bold',
              active
                ? 'bg-sonoro-amber text-sonoro-black'
                : dark ? 'bg-white/10 text-white/50' : 'bg-sonoro-border text-sonoro-muted',
            )}>
              {active && isPlaying ? (
                <span className="flex items-end gap-px h-3">
                  {[1, 2, 3].map(n => (
                    <span
                      key={n}
                      className="w-0.5 rounded-full bg-current"
                      style={{
                        height: '100%',
                        animation: `waveform 0.9s ease-in-out ${n * 0.18}s infinite`,
                        transformOrigin: 'bottom',
                      }}
                    />
                  ))}
                </span>
              ) : (
                i + 1
              )}
            </div>

            <span className={cn(
              'flex-1 text-xs font-medium truncate',
              active
                ? dark ? 'text-sonoro-amber' : 'text-sonoro-900'
                : dark ? 'text-white/70' : 'text-sonoro-700',
            )}>
              {ch.title}
            </span>

            {ch.duration_seconds ? (
              <span className={cn(
                'text-[10px] shrink-0 tabular-nums',
                dark ? 'text-white/30' : 'text-sonoro-400',
              )}>
                {fmtDuration(ch.duration_seconds)}
              </span>
            ) : ch.status === 'processing' ? (
              <span className="text-[10px] text-sonoro-amber shrink-0">…</span>
            ) : null}
          </button>
        );
      })}
    </div>
  );
}

// ── Volume control ────────────────────────────────────────────────────────────
function VolumeControl({
  volume,
  isMuted,
  onToggleMute,
  onVolumeChange,
  dark = false,
}: {
  volume:          number;
  isMuted:         boolean;
  onToggleMute:    () => void;
  onVolumeChange:  (v: number) => void;
  dark?:           boolean;
}) {
  const effective = isMuted ? 0 : volume;

  return (
    <div className="flex items-center gap-2">
      <button
        onClick={onToggleMute}
        className={cn(
          'flex h-7 w-7 items-center justify-center rounded-lg transition-colors',
          dark
            ? 'text-white/50 hover:text-white hover:bg-white/10'
            : 'text-sonoro-muted hover:text-sonoro-700 hover:bg-sonoro-surface',
        )}
        aria-label={isMuted ? 'Unmute' : 'Mute'}
      >
        {effective === 0 ? (
          <svg className="w-3.5 h-3.5" viewBox="0 0 20 20" fill="currentColor" aria-hidden="true">
            <path d="M9.25 3.75a.75.75 0 0 0-1.28-.53L4.72 6.5H2.5A1.5 1.5 0 0 0 1 8v4a1.5 1.5 0 0 0 1.5 1.5h2.22l3.25 3.28a.75.75 0 0 0 1.28-.53V3.75ZM14.47 6.22a.75.75 0 0 1 1.06 0l1.72 1.72 1.72-1.72a.75.75 0 1 1 1.06 1.06L18.31 9l1.72 1.72a.75.75 0 1 1-1.06 1.06l-1.72-1.72-1.72 1.72a.75.75 0 1 1-1.06-1.06L16.19 9l-1.72-1.72a.75.75 0 0 1 0-1.06Z"/>
          </svg>
        ) : effective < 0.5 ? (
          <svg className="w-3.5 h-3.5" viewBox="0 0 20 20" fill="currentColor" aria-hidden="true">
            <path d="M9.25 3.75a.75.75 0 0 0-1.28-.53L4.72 6.5H2.5A1.5 1.5 0 0 0 1 8v4a1.5 1.5 0 0 0 1.5 1.5h2.22l3.25 3.28a.75.75 0 0 0 1.28-.53V3.75ZM12.53 6.22a.75.75 0 0 1 1.06 1.06 4.5 4.5 0 0 1 0 5.44.75.75 0 0 1-1.06-1.06 3 3 0 0 0 0-3.32.75.75 0 0 1 0-1.06v-.06Z"/>
          </svg>
        ) : (
          <svg className="w-3.5 h-3.5" viewBox="0 0 20 20" fill="currentColor" aria-hidden="true">
            <path d="M9.25 3.75a.75.75 0 0 0-1.28-.53L4.72 6.5H2.5A1.5 1.5 0 0 0 1 8v4a1.5 1.5 0 0 0 1.5 1.5h2.22l3.25 3.28a.75.75 0 0 0 1.28-.53V3.75ZM12.53 6.22a.75.75 0 0 1 1.06 1.06 4.5 4.5 0 0 1 0 5.44.75.75 0 0 1-1.06-1.06 3 3 0 0 0 0-3.32.75.75 0 0 1 0-1.06v-.06ZM15.28 4.22a.75.75 0 0 1 1.06 1.06 8.25 8.25 0 0 1 0 9.44.75.75 0 1 1-1.06-1.06 6.75 6.75 0 0 0 0-7.32.75.75 0 0 1 0-1.06v-.06Z"/>
          </svg>
        )}
      </button>
      <input
        type="range"
        min="0"
        max="1"
        step="0.02"
        value={effective}
        onChange={e => onVolumeChange(parseFloat(e.target.value))}
        aria-label="Volume"
        className="player-volume-slider w-16 h-1 cursor-pointer rounded-full appearance-none"
        style={{ accentColor: '#F59E0B' }}
      />
    </div>
  );
}

// ── Generating placeholder ───────────────────────────────────────────────────
function GeneratingState() {
  return (
    <div className="card-base p-8 text-center">
      <div className="flex items-end justify-center gap-1 h-10 mb-4" aria-hidden="true">
        {[35, 65, 90, 55, 80, 40, 70].map((h, i) => (
          <div key={i} className="waveform-bar w-1.5" style={{ height: `${h}%`, animationDelay: `${i * 0.14}s` }} />
        ))}
      </div>
      <p className="text-sm font-semibold text-sonoro-900 mb-1">Generating your audiobook…</p>
      <p className="text-xs text-sonoro-muted max-w-xs mx-auto leading-relaxed">
        Chapters are being converted to audio. This usually takes under 60 seconds.
      </p>
    </div>
  );
}

// ── Completion overlay ────────────────────────────────────────────────────────
function CompletionOverlay({
  chapters,
  documentTitle,
  documentId,
  totalListeningTime,
  onListenAgain,
}: {
  chapters:          Chapter[];
  documentTitle:     string;
  documentId:        string;
  totalListeningTime: number;
  onListenAgain:     () => void;
}) {
  const ambient = getAmbient(documentTitle);
  const completedCount = chapters.filter(c => c.status === 'completed').length;

  return (
    <div className="card-base overflow-hidden animate-fade-in relative">
      {/* Ambient glow */}
      <div
        className="absolute inset-0 pointer-events-none opacity-[0.08]"
        style={{ background: `radial-gradient(ellipse at 50% 20%, ${ambient.from}, transparent 70%)` }}
        aria-hidden="true"
      />

      <div className="relative flex flex-col items-center py-10 px-8 text-center">
        {/* Book cover */}
        <BookCover title={documentTitle} size="lg" className="mb-5 shadow-amber" />

        {/* Completion star */}
        <div className="mb-3 flex h-10 w-10 items-center justify-center rounded-full bg-sonoro-amber/10 ring-4 ring-sonoro-amber/20">
          <svg className="w-5 h-5 text-sonoro-amber" viewBox="0 0 20 20" fill="currentColor" aria-hidden="true">
            <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.857-9.809a.75.75 0 00-1.214-.882l-3.483 4.79-1.88-1.88a.75.75 0 10-1.06 1.061l2.5 2.5a.75.75 0 001.137-.089l4-5.5z" clipRule="evenodd"/>
          </svg>
        </div>

        <h2 className="text-lg font-bold text-sonoro-900 mb-1">Finished listening</h2>
        <p className="text-sm text-sonoro-muted mb-6 leading-relaxed max-w-xs">
          You completed <span className="text-sonoro-900 font-medium">{documentTitle}</span>
        </p>

        {/* Stats */}
        <div className="flex items-center gap-6 mb-8">
          <div className="text-center">
            <p className="text-xl font-bold text-sonoro-900 tabular-nums">
              {totalListeningTime > 0 ? fmtDuration(totalListeningTime) : '—'}
            </p>
            <p className="text-[11px] text-sonoro-muted mt-0.5">Listening time</p>
          </div>
          <div className="w-px h-8 bg-sonoro-border" aria-hidden="true" />
          <div className="text-center">
            <p className="text-xl font-bold text-sonoro-900 tabular-nums">{completedCount}</p>
            <p className="text-[11px] text-sonoro-muted mt-0.5">Chapters</p>
          </div>
        </div>

        {/* CTAs */}
        <div className="flex flex-col gap-3 w-full max-w-xs">
          <button
            onClick={onListenAgain}
            className="btn-primary w-full justify-center"
          >
            Listen again
          </button>
          <a href="/dashboard/upload" className="btn-outline w-full justify-center">
            Upload next PDF →
          </a>
        </div>
      </div>
    </div>
  );
}

// ── Immersive overlay ────────────────────────────────────────────────────────
function ImmersiveOverlay({
  chapters,
  documentTitle,
  state,
  actions,
  onClose,
}: {
  chapters:      Chapter[];
  documentTitle: string;
  state:         ReturnType<typeof useAudioPlayer>['state'];
  actions:       ReturnType<typeof useAudioPlayer>['actions'];
  onClose:       () => void;
}) {
  const { currentIdx, isPlaying, currentTime, duration, progress, speed, volume, isMuted, isBuffering } = state;
  const chapter = chapters[currentIdx];
  const ambient = getAmbient(documentTitle);
  const remaining = duration > 0 ? Math.max(0, duration - currentTime) : 0;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center overflow-y-auto"
      style={{ background: '#0C0B0A' }}
      role="dialog"
      aria-modal="true"
      aria-label="Immersive listening mode"
    >
      {/* Ambient background orbs — derived from book palette */}
      <div
        className="absolute top-[-15%] right-[-10%] w-[600px] h-[600px] pointer-events-none animate-float"
        style={{ background: `radial-gradient(ellipse, ${ambient.from}20 0%, transparent 65%)`, filter: 'blur(60px)' }}
        aria-hidden="true"
      />
      <div
        className="absolute bottom-[-20%] left-[-10%] w-[500px] h-[500px] pointer-events-none animate-float-delayed"
        style={{ background: `radial-gradient(ellipse, ${ambient.to}14 0%, transparent 65%)`, filter: 'blur(60px)' }}
        aria-hidden="true"
      />

      {/* Close */}
      <button
        onClick={onClose}
        className="absolute top-5 right-5 flex h-9 w-9 items-center justify-center rounded-full bg-white/8 text-white/60 hover:bg-white/15 hover:text-white transition-colors"
        aria-label="Exit immersive mode"
      >
        <svg className="w-4 h-4" viewBox="0 0 20 20" fill="currentColor" aria-hidden="true">
          <path d="M6.28 5.22a.75.75 0 0 0-1.06 1.06L8.94 10l-3.72 3.72a.75.75 0 1 0 1.06 1.06L10 11.06l3.72 3.72a.75.75 0 1 0 1.06-1.06L11.06 10l3.72-3.72a.75.75 0 0 0-1.06-1.06L10 8.94 6.28 5.22Z"/>
        </svg>
      </button>

      <div className="relative w-full max-w-4xl mx-5 py-12 grid grid-cols-1 lg:grid-cols-[260px_1fr] gap-5 animate-fade-in">

        {/* Left — cover + chapter list */}
        <div className="flex flex-col items-center gap-5">
          {/* Large cover art */}
          <div className="animate-scale-in" style={{ animationDelay: '60ms', animationFillMode: 'both' }}>
            <BookCover title={documentTitle} size="lg" className="shadow-modal" />
          </div>

          {/* Chapter list */}
          {chapters.length > 1 && (
            <div className="w-full hidden lg:block">
              <p className="label-sm text-white/35 px-5 mb-2">Chapters</p>
              <div className="rounded-2xl border border-white/[0.07] bg-white/[0.03] overflow-hidden">
                <ChapterList
                  chapters={chapters}
                  currentIdx={currentIdx}
                  isPlaying={isPlaying}
                  onSelect={actions.goToChapter}
                  dark
                />
              </div>
            </div>
          )}
        </div>

        {/* Right — player */}
        <div className="rounded-2xl border border-white/[0.08] bg-white/[0.03] overflow-hidden">
          {/* Now playing header */}
          <div className="px-7 pt-7 pb-5 border-b border-white/[0.06]">
            <p className="label-sm text-white/35 mb-3">Now playing</p>
            <p className="text-2xl font-bold text-white tracking-tight leading-snug mb-1">
              {chapter?.title ?? '—'}
            </p>
            <div className="flex items-center gap-2">
              <p className="text-sm text-white/45">{documentTitle}</p>
              {remaining > 0 && (
                <>
                  <span className="text-white/20 text-xs" aria-hidden="true">·</span>
                  <p className="text-xs text-white/35 tabular-nums">–{fmtDuration(remaining)} left</p>
                </>
              )}
            </div>
          </div>

          {/* Waveform */}
          <div className="px-7 py-5">
            <Waveform progress={progress} isPlaying={isPlaying} onSeek={actions.seek} />
          </div>

          {/* Scrubber + time */}
          <div className="px-7 pb-5">
            <SeekBar
              progress={progress}
              currentTime={currentTime}
              duration={duration}
              onSeek={actions.seek}
            />
          </div>

          {/* Controls */}
          <div className="px-7 pb-7 flex flex-col gap-5">
            {/* Speed pills */}
            <div className="flex items-center gap-1.5">
              {SPEEDS.map(s => (
                <button
                  key={s}
                  onClick={() => actions.setSpeed(s)}
                  className={cn(
                    'px-2.5 py-1 rounded-full text-xs font-medium transition-colors',
                    speed === s
                      ? 'bg-sonoro-amber text-sonoro-black'
                      : 'text-white/40 hover:text-white/70',
                  )}
                  aria-label={`${s}× speed`}
                >
                  {s}×
                </button>
              ))}
              <div className="ml-auto">
                <VolumeControl
                  volume={volume}
                  isMuted={isMuted}
                  onToggleMute={actions.toggleMute}
                  onVolumeChange={actions.setVolume}
                  dark
                />
              </div>
            </div>

            {/* Main controls */}
            <div className="flex items-center justify-center gap-6">
              <button
                onClick={actions.prevChapter}
                disabled={currentIdx === 0}
                className="text-white/40 hover:text-white/80 disabled:opacity-20 transition-colors"
                aria-label="Previous chapter"
              >
                <svg className="w-5 h-5" viewBox="0 0 20 20" fill="currentColor" aria-hidden="true">
                  <path d="M3.5 5a.5.5 0 0 1 1 0v3.536l7.996-4.982A.5.5 0 0 1 13.5 4v12a.5.5 0 0 1-.754.432L5.5 11.458V15a.5.5 0 0 1-1 0V5Z"/>
                </svg>
              </button>

              <button
                onClick={() => actions.skipBack(10)}
                className="text-white/40 hover:text-white/80 transition-colors relative"
                aria-label="Skip back 10 seconds"
              >
                <svg className="w-6 h-6" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
                  <path d="M12 5V2L8 6l4 4V7c3.31 0 6 2.69 6 6s-2.69 6-6 6-6-2.69-6-6H4c0 4.42 3.58 8 8 8s8-3.58 8-8-3.58-8-8-8z"/>
                </svg>
                <span className="absolute inset-0 flex items-center justify-center text-[8px] font-bold mt-0.5" aria-hidden="true">10</span>
              </button>

              <button
                onClick={actions.togglePlay}
                disabled={!chapter?.audio_url}
                className="flex h-16 w-16 items-center justify-center rounded-full bg-white text-sonoro-black hover:bg-sonoro-100 active:scale-95 transition-all shadow-lg disabled:opacity-40"
                aria-label={isPlaying ? 'Pause' : 'Play'}
              >
                {isBuffering ? (
                  <svg className="w-6 h-6 animate-spin text-sonoro-400" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                    <circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="3" strokeOpacity=".2"/>
                    <path d="M12 2a10 10 0 0 1 10 10" stroke="currentColor" strokeWidth="3" strokeLinecap="round"/>
                  </svg>
                ) : isPlaying ? (
                  <svg className="w-6 h-6" viewBox="0 0 20 20" fill="currentColor" aria-hidden="true">
                    <path d="M5.75 3a.75.75 0 0 0-.75.75v12.5c0 .414.336.75.75.75h1.5a.75.75 0 0 0 .75-.75V3.75A.75.75 0 0 0 7.25 3h-1.5ZM12.75 3a.75.75 0 0 0-.75.75v12.5c0 .414.336.75.75.75h1.5a.75.75 0 0 0 .75-.75V3.75a.75.75 0 0 0-.75-.75h-1.5Z"/>
                  </svg>
                ) : (
                  <svg className="w-6 h-6 translate-x-0.5" viewBox="0 0 20 20" fill="currentColor" aria-hidden="true">
                    <path d="M6.3 2.84A1.5 1.5 0 0 0 4 4.11v11.78a1.5 1.5 0 0 0 2.3 1.27l9.344-5.891a1.5 1.5 0 0 0 0-2.538L6.3 2.841Z"/>
                  </svg>
                )}
              </button>

              <button
                onClick={() => actions.skipForward(10)}
                className="text-white/40 hover:text-white/80 transition-colors relative"
                aria-label="Skip forward 10 seconds"
              >
                <svg className="w-6 h-6 scale-x-[-1]" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
                  <path d="M12 5V2L8 6l4 4V7c3.31 0 6 2.69 6 6s-2.69 6-6 6-6-2.69-6-6H4c0 4.42 3.58 8 8 8s8-3.58 8-8-3.58-8-8-8z"/>
                </svg>
                <span className="absolute inset-0 flex items-center justify-center text-[8px] font-bold mt-0.5" aria-hidden="true">10</span>
              </button>

              <button
                onClick={actions.nextChapter}
                disabled={currentIdx >= chapters.length - 1}
                className="text-white/40 hover:text-white/80 disabled:opacity-20 transition-colors"
                aria-label="Next chapter"
              >
                <svg className="w-5 h-5" viewBox="0 0 20 20" fill="currentColor" aria-hidden="true">
                  <path d="M16.5 5a.5.5 0 0 0-1 0v3.536L8.504 3.554A.5.5 0 0 0 7.5 4v12a.5.5 0 0 0 .754.432L15.5 11.458V15a.5.5 0 0 0 1 0V5Z"/>
                </svg>
              </button>
            </div>
          </div>
        </div>
      </div>

      {/* Keyboard hint */}
      <p className="absolute bottom-4 text-[10px] text-white/18 tracking-wide select-none">
        Space · ← → seek · Shift+← → chapters · M mute · Esc exit
      </p>
    </div>
  );
}

// ── Sleep timer control ───────────────────────────────────────────────────────
function SleepTimer({
  sleepMinutes,
  sleepRemaining,
  onSelect,
  dark = false,
}: {
  sleepMinutes:   SleepOption;
  sleepRemaining: number;
  onSelect:       (m: SleepOption) => void;
  dark?:          boolean;
}) {
  const [open, setOpen] = useState(false);

  return (
    <div className="relative">
      <button
        onClick={() => setOpen(o => !o)}
        className={cn(
          'flex items-center gap-1.5 text-[10px] font-semibold px-2.5 py-1.5 rounded-full border transition-all',
          sleepMinutes > 0
            ? dark
              ? 'bg-sonoro-amber/20 border-sonoro-amber/40 text-sonoro-amber'
              : 'bg-sonoro-amber-light border-sonoro-amber/40 text-sonoro-amber-dark'
            : dark
            ? 'border-white/15 text-white/40 hover:text-white/70'
            : 'border-sonoro-border text-sonoro-400 hover:text-sonoro-700 hover:border-sonoro-300',
        )}
        aria-label={sleepMinutes > 0 ? `Sleep timer: ${Math.ceil(sleepRemaining / 60)} min left` : 'Set sleep timer'}
      >
        <svg className="w-3 h-3" viewBox="0 0 16 16" fill="currentColor" aria-hidden="true">
          <path d="M8 1a7 7 0 1 0 0 14A7 7 0 0 0 8 1zm0 1.5a5.5 5.5 0 1 1 0 11 5.5 5.5 0 0 1 0-11zm.75 2.5a.75.75 0 0 0-1.5 0V8c0 .199.079.39.22.53l2.5 2.5a.75.75 0 1 0 1.06-1.06L8.75 7.69V5z"/>
        </svg>
        {sleepMinutes > 0 ? `${Math.ceil(sleepRemaining / 60)}m` : 'Sleep'}
      </button>

      {open && (
        <div
          className={cn(
            'absolute bottom-full right-0 mb-2 z-20 rounded-2xl border shadow-lg overflow-hidden',
            dark ? 'bg-sonoro-900 border-white/10' : 'bg-white border-sonoro-border',
          )}
        >
          <p className={cn(
            'px-4 pt-3 pb-1.5 text-[10px] font-semibold uppercase tracking-wider',
            dark ? 'text-white/40' : 'text-sonoro-400',
          )}>
            Sleep timer
          </p>
          {SLEEP_OPTIONS.map(m => (
            <button
              key={m}
              onClick={() => { onSelect(m); setOpen(false); }}
              className={cn(
                'flex w-full items-center gap-2 px-4 py-2.5 text-xs transition-colors text-left',
                sleepMinutes === m
                  ? dark ? 'text-sonoro-amber' : 'text-sonoro-amber-dark font-semibold'
                  : dark ? 'text-white/70 hover:bg-white/5' : 'text-sonoro-700 hover:bg-sonoro-surface',
              )}
            >
              {m === 0 ? 'Off' : `${m} minutes`}
              {sleepMinutes === m && (
                <svg className="ml-auto w-3.5 h-3.5 text-sonoro-amber shrink-0" viewBox="0 0 14 14" fill="currentColor" aria-hidden="true">
                  <path fillRule="evenodd" d="M7 14A7 7 0 1 0 7 0a7 7 0 0 0 0 14zm3.5-8.7a.75.75 0 0 0-1.2-.9L6.15 8.52 4.78 7.22a.75.75 0 1 0-1.06 1.06l2 1.75a.75.75 0 0 0 1.12-.08l3.66-4.65Z" clipRule="evenodd"/>
                </svg>
              )}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

// ── Main AudioPlayer ──────────────────────────────────────────────────────────
export default function AudioPlayer({ chapters, documentTitle, documentId = '', autoplay = false }: Props) {
  // Load saved position once on mount — drives initialChapterIdx + initialTime in the hook
  const savedProgress = useMemo(() => documentId ? loadProgress(documentId) : null, [documentId]);

  const { audioRef, chapter, state, actions, audioProps } = useAudioPlayer({
    chapters,
    initialChapterIdx: savedProgress?.chapterIdx ?? 0,
    initialTime:       savedProgress?.currentTime ?? 0,
  });
  const [immersive,      setImmersive]      = useState(false);
  const [isCompleted,    setIsCompleted]    = useState(false);
  const [sleepMinutes,   setSleepMinutes]   = useState<SleepOption>(0);
  const [sleepRemaining, setSleepRemaining] = useState(0);

  const { currentIdx, isPlaying, currentTime, duration, progress, speed, volume, isMuted, isBuffering } = state;

  const totalDuration = chapters.reduce((acc, ch) => acc + (ch.duration_seconds ?? 0), 0) || duration;

  // Periodic throttled save during playback (every 5 s)
  usePlaybackProgress(
    documentId, documentTitle, currentIdx, chapter?.title ?? '',
    currentTime, totalDuration, isPlaying, speed,
  );

  // Stable ref so beforeunload handler captures current values without stale closure
  const saveStateRef = useRef({ currentTime, currentIdx, totalDuration, speed });
  useEffect(() => { saveStateRef.current = { currentTime, currentIdx, totalDuration, speed }; });

  // Save on pause
  const prevIsPlayingRef = useRef(isPlaying);
  useEffect(() => {
    if (prevIsPlayingRef.current && !isPlaying && saveStateRef.current.currentTime > 0 && documentId) {
      const { currentTime: t, currentIdx: idx, totalDuration: dur, speed: spd } = saveStateRef.current;
      saveProgress({
        documentId, documentTitle,
        chapterIdx: idx, chapterTitle: chapters[idx]?.title ?? '',
        currentTime: t, totalDuration: dur,
        timestamp: Date.now(), playbackSpeed: spd,
      });
    }
    prevIsPlayingRef.current = isPlaying;
  }, [isPlaying]); // eslint-disable-line react-hooks/exhaustive-deps

  // Save before the page is unloaded (navigation / tab close)
  useEffect(() => {
    if (!documentId) return;
    function onUnload() {
      const { currentTime: t, currentIdx: idx, totalDuration: dur, speed: spd } = saveStateRef.current;
      if (t > 0) {
        saveProgress({
          documentId, documentTitle,
          chapterIdx: idx, chapterTitle: chapters[idx]?.title ?? '',
          currentTime: t, totalDuration: dur,
          timestamp: Date.now(), playbackSpeed: spd,
        });
      }
    }
    window.addEventListener('beforeunload', onUnload);
    return () => window.removeEventListener('beforeunload', onUnload);
  }, [documentId, documentTitle]); // eslint-disable-line react-hooks/exhaustive-deps

  // ── Analytics: session tracking ───────────────────────────────────────────
  const sessionIdRef = useRef<string | null>(null);
  const sessionSourceRef = useRef<'direct' | 'autoplay'>('direct');
  if (autoplay) sessionSourceRef.current = 'autoplay';

  // Fire player_opened once on mount
  useEffect(() => {
    if (!documentId) return;
    track('player_opened', { document_id: documentId });
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // Start session on first play; end session on unmount
  useEffect(() => {
    if (!isPlaying || sessionIdRef.current || !documentId) return;
    void startPlaybackSession(documentId, sessionSourceRef.current, autoplay)
      .then(id => { sessionIdRef.current = id; });
  }, [isPlaying]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    return () => {
      if (!sessionIdRef.current) return;
      const pct = totalDuration > 0 ? Math.min(100, (currentTime / totalDuration) * 100) : 0;
      void endPlaybackSession(sessionIdRef.current, Math.round(currentTime), pct, speed, [currentIdx]);
    };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // Track chapter changes
  useEffect(() => {
    if (!documentId || currentIdx < 0) return;
    track('chapter_changed', { document_id: documentId, chapter_index: currentIdx });
  }, [currentIdx]); // eslint-disable-line react-hooks/exhaustive-deps

  // ── Media Session API — lock screen + notification controls ──────────────────
  // Sets metadata (title/artist) and action handlers so users can control
  // playback from the lock screen, notification bar, and Bluetooth headsets.

  // Update metadata whenever the chapter changes
  useEffect(() => {
    if (!('mediaSession' in navigator)) return;
    // Generate a square cover and produce the required sizes from the same source image.
    // We generate at 512px (cheapest canvas size that looks sharp on all lock screens)
    // and declare all sizes — the OS picks its preferred one.
    const coverDataUrl = generateCoverDataUrl(documentTitle, 512);
    const artwork: MediaImage[] = coverDataUrl
      ? [96, 128, 192, 256, 512].map(sz => ({
          src:   coverDataUrl,
          sizes: `${sz}x${sz}`,
          type:  'image/png',
        }))
      : [];
    navigator.mediaSession.metadata = new MediaMetadata({
      title:  chapter?.title ?? documentTitle,
      artist: documentTitle,
      album:  'Sonoro',
      artwork,
    });
  }, [currentIdx, documentTitle]); // eslint-disable-line react-hooks/exhaustive-deps

  // Keep playback state in sync with the OS
  useEffect(() => {
    if (!('mediaSession' in navigator)) return;
    navigator.mediaSession.playbackState = isPlaying ? 'playing' : 'paused';
  }, [isPlaying]);

  // Register action handlers once on mount (stable via refs in the hook)
  useEffect(() => {
    if (!('mediaSession' in navigator)) return;
    const ms = navigator.mediaSession;

    ms.setActionHandler('play',          () => actions.togglePlay());
    ms.setActionHandler('pause',         () => actions.togglePlay());
    ms.setActionHandler('previoustrack', () => actions.prevChapter());
    ms.setActionHandler('nexttrack',     () => actions.nextChapter());
    ms.setActionHandler('seekbackward',  (d) => actions.skipBack(d.seekOffset ?? 10));
    ms.setActionHandler('seekforward',   (d) => actions.skipForward(d.seekOffset ?? 10));
    try {
      ms.setActionHandler('seekto', (d) => {
        if (d.seekTime !== undefined && audioRef.current) {
          audioRef.current.currentTime = d.seekTime;
        }
      });
    } catch { /* seekto not universally supported */ }

    return () => {
      (['play', 'pause', 'previoustrack', 'nexttrack', 'seekbackward', 'seekforward'] as const).forEach(a => {
        try { ms.setActionHandler(a, null); } catch { /* ignore */ }
      });
    };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // Update the lock-screen scrubber position
  useEffect(() => {
    if (!('mediaSession' in navigator) || !('setPositionState' in navigator.mediaSession)) return;
    if (duration <= 0) return;
    try {
      navigator.mediaSession.setPositionState({
        duration,
        playbackRate: speed,
        position:     Math.min(currentTime, duration),
      });
    } catch { /* ignore */ }
  }, [currentTime, duration, speed]);

  // ── Autoplay on mount when navigated with ?autoplay=1 ─────────────────────
  useEffect(() => {
    if (!autoplay) return;
    const audio = audioRef.current;
    const url = chapter?.audio_url;
    if (!audio || !url) return;
    audio.play().catch(() => {});
    // actions.togglePlay not needed — the hook's load-effect handles it,
    // but we need to ensure isPlaying state is set
    // Delay slightly to let the audio element initialize
    const t = setTimeout(() => {
      if (audio.paused) audio.play().catch(() => {});
    }, 300);
    return () => clearTimeout(t);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // Detect completion — last chapter ended
  const originalOnEnded = audioProps.onEnded;
  const patchedAudioProps = {
    ...audioProps,
    onEnded: () => {
      const next = currentIdx + 1;
      const hasNext = next < chapters.length && !!chapters[next]?.audio_url;
      if (!hasNext) {
        setIsCompleted(true);
        console.log('[SONORO] playback_completed', documentId);
        track('audiobook_completed', {
          document_id:      documentId,
          duration_seconds: totalDuration,
          chapter_count:    chapters.length,
        });
        // Mark completed in localStorage then clear the resume pointer
        if (documentId) {
          saveProgress({
            documentId, documentTitle,
            chapterIdx: currentIdx, chapterTitle: chapter?.title ?? '',
            currentTime: totalDuration, totalDuration,
            timestamp: Date.now(), playbackSpeed: speed, completed: true,
          });
          clearProgress(documentId);
        }
        if (sessionIdRef.current) {
          void endPlaybackSession(sessionIdRef.current, Math.round(totalDuration), 100, speed, [currentIdx]);
          sessionIdRef.current = null;
        }
      }
      originalOnEnded();
    },
  };

  // Sleep timer countdown
  useEffect(() => {
    if (sleepMinutes === 0) { setSleepRemaining(0); return; }
    setSleepRemaining(sleepMinutes * 60);
  }, [sleepMinutes]);

  useEffect(() => {
    if (!isPlaying || sleepRemaining <= 0) return;
    const interval = setInterval(() => {
      setSleepRemaining(prev => {
        if (prev <= 1) {
          clearInterval(interval);
          actions.togglePlay();
          setSleepMinutes(0);
          console.log('[SONORO] sleep_timer_triggered');
          return 0;
        }
        return prev - 1;
      });
    }, 1000);
    return () => clearInterval(interval);
  }, [isPlaying, sleepRemaining > 0]); // eslint-disable-line react-hooks/exhaustive-deps

  // ESC to close immersive mode
  useEffect(() => {
    if (!immersive) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setImmersive(false);
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [immersive]);

  // Lock body scroll in immersive mode
  useEffect(() => {
    document.body.style.overflow = immersive ? 'hidden' : '';
    return () => { document.body.style.overflow = ''; };
  }, [immersive]);

  const completedChapters = chapters.filter(c => c.status === 'completed');

  if (completedChapters.length === 0) return <GeneratingState />;

  // Show completion overlay when last chapter finished
  if (isCompleted) {
    return (
      <CompletionOverlay
        chapters={chapters}
        documentTitle={documentTitle}
        documentId={documentId}
        totalListeningTime={totalDuration}
        onListenAgain={() => {
          setIsCompleted(false);
          actions.goToChapter(0);
        }}
      />
    );
  }

  const hasAudio = !!chapter?.audio_url;
  const remaining = duration > 0 ? Math.max(0, duration - currentTime) : 0;

  return (
    <>
      {/* Hidden audio element — lives outside any conditional rendering */}
      <audio ref={audioRef} preload="metadata" {...patchedAudioProps} />

      <div className="card-base overflow-hidden animate-fade-in">
        {/* Amber top accent — progress stripe */}
        <div
          className="h-0.5 w-full transition-all duration-150"
          style={{ background: `linear-gradient(90deg, #D97706 ${progress * 100}%, #E8E7E3 ${progress * 100}%)` }}
          aria-hidden="true"
        />

        {/* Header: now playing */}
        <div className="flex items-start justify-between gap-4 px-6 pt-5 pb-4 border-b border-sonoro-border">
          <div className="flex items-center gap-3 min-w-0">
            <BookCover title={documentTitle} size="sm" />
            <div className="min-w-0">
              <p className="label-sm mb-1">Now playing</p>
              <p className="text-sm font-bold text-sonoro-900 truncate leading-snug">
                {chapter?.title ?? (hasAudio ? '—' : 'No audio available')}
              </p>
              <div className="flex items-center gap-1.5 mt-0.5">
                <p className="text-xs text-sonoro-muted truncate">{documentTitle}</p>
                {remaining > 0 && (
                  <>
                    <span className="text-sonoro-300 text-[10px]" aria-hidden="true">·</span>
                    <p className="text-xs text-sonoro-muted tabular-nums shrink-0">–{fmtDuration(remaining)}</p>
                  </>
                )}
              </div>
              {/* Resume position hint — shown before first play when saved progress exists */}
              {!isPlaying && currentTime < 3 && savedProgress && savedProgress.currentTime > 30 && !savedProgress.completed && (
                <p className="text-[11px] text-sonoro-amber-dark mt-0.5 font-medium">
                  Resume from {fmtDuration(savedProgress.currentTime)}
                </p>
              )}
            </div>
          </div>

          {/* Immersive toggle */}
          <button
            onClick={() => { setImmersive(true); console.log('[SONORO] player_opened', documentId); }}
            className="flex h-8 w-8 shrink-0 items-center justify-center rounded-xl text-sonoro-muted hover:text-sonoro-900 hover:bg-sonoro-surface transition-colors"
            aria-label="Open immersive listening mode"
            title="Immersive mode"
          >
            <svg className="w-4 h-4" viewBox="0 0 20 20" fill="currentColor" aria-hidden="true">
              <path d="M3.28 2.22a.75.75 0 0 0-1.06 1.06L5.44 6.5H2.75a.75.75 0 0 0 0 1.5H7a.75.75 0 0 0 .75-.75V2.75a.75.75 0 0 0-1.5 0v2.69L3.28 2.22ZM13 2.75a.75.75 0 0 1 .75-.75h4.25a.75.75 0 0 1 .75.75V7a.75.75 0 0 1-1.5 0V4.31l-3.22 3.22a.75.75 0 1 1-1.06-1.06L16.19 3.5H13.75A.75.75 0 0 1 13 2.75ZM2.75 13a.75.75 0 0 1 .75.75v2.69l3.22-3.22a.75.75 0 1 1 1.06 1.06L4.56 16.5h2.69a.75.75 0 0 1 0 1.5H2.75A.75.75 0 0 1 2 17.25V13a.75.75 0 0 1 .75-.75ZM17.25 13a.75.75 0 0 1 .75.75v4.25a.75.75 0 0 1-.75.75H13a.75.75 0 0 1 0-1.5h2.69l-3.22-3.22a.75.75 0 1 1 1.06-1.06l3.22 3.22V13.75a.75.75 0 0 1 .75-.75Z"/>
            </svg>
          </button>
        </div>

        {/* Waveform */}
        <div className="px-6 pt-5 pb-2">
          <Waveform progress={progress} isPlaying={isPlaying} onSeek={actions.seek} />
        </div>

        {/* Scrubber + time */}
        <div className="px-6 pb-4">
          <SeekBar
            progress={progress}
            currentTime={currentTime}
            duration={duration}
            onSeek={actions.seek}
          />
        </div>

        {/* Controls row */}
        <div className="px-6 pb-5">
          {/* Speed + volume + sleep timer */}
          <div className="flex items-center justify-between mb-4">
            <div className="flex items-center gap-1">
              {SPEEDS.map(s => (
                <button
                  key={s}
                  onClick={() => actions.setSpeed(s)}
                  className={cn(
                    'px-2 py-0.5 rounded-full text-xs font-medium transition-colors',
                    speed === s
                      ? 'bg-sonoro-black text-white'
                      : 'text-sonoro-muted hover:text-sonoro-900 hover:bg-sonoro-surface',
                  )}
                  aria-label={`${s}× speed`}
                >
                  {s}×
                </button>
              ))}
            </div>

            <div className="flex items-center gap-2">
              <SleepTimer
                sleepMinutes={sleepMinutes}
                sleepRemaining={sleepRemaining}
                onSelect={setSleepMinutes}
              />
              <VolumeControl
                volume={volume}
                isMuted={isMuted}
                onToggleMute={actions.toggleMute}
                onVolumeChange={actions.setVolume}
              />
            </div>
          </div>

          {/* Transport controls */}
          <div className="flex items-center justify-center gap-5">
            <button
              onClick={actions.prevChapter}
              disabled={currentIdx === 0}
              className="text-sonoro-muted hover:text-sonoro-700 disabled:opacity-30 transition-colors"
              aria-label="Previous chapter"
            >
              <svg className="w-5 h-5" viewBox="0 0 20 20" fill="currentColor" aria-hidden="true">
                <path d="M3.5 5a.5.5 0 0 1 1 0v3.536l7.996-4.982A.5.5 0 0 1 13.5 4v12a.5.5 0 0 1-.754.432L5.5 11.458V15a.5.5 0 0 1-1 0V5Z"/>
              </svg>
            </button>

            {/* Skip back 10 */}
            <button
              onClick={() => actions.skipBack(10)}
              className="relative text-sonoro-muted hover:text-sonoro-700 transition-colors"
              aria-label="Skip back 10 seconds"
            >
              <svg className="w-5 h-5" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
                <path d="M12 5V2L8 6l4 4V7c3.31 0 6 2.69 6 6s-2.69 6-6 6-6-2.69-6-6H4c0 4.42 3.58 8 8 8s8-3.58 8-8-3.58-8-8-8z"/>
              </svg>
              <span className="absolute inset-0 flex items-center justify-center text-[7px] font-bold mt-0.5" aria-hidden="true">10</span>
            </button>

            {/* Play / Pause */}
            <button
              onClick={() => {
                if (!isPlaying) console.log('[SONORO] player_started', documentId);
                actions.togglePlay();
              }}
              disabled={!hasAudio}
              className="flex h-12 w-12 items-center justify-center rounded-full bg-sonoro-black text-white hover:bg-sonoro-800 active:scale-95 transition-all shadow-card disabled:opacity-40"
              aria-label={isPlaying ? 'Pause' : 'Play'}
            >
              {isBuffering ? (
                <svg className="w-5 h-5 animate-spin opacity-60" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                  <circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="3" strokeOpacity=".2"/>
                  <path d="M12 2a10 10 0 0 1 10 10" stroke="currentColor" strokeWidth="3" strokeLinecap="round"/>
                </svg>
              ) : isPlaying ? (
                <svg className="w-5 h-5" viewBox="0 0 20 20" fill="currentColor" aria-hidden="true">
                  <path d="M5.75 3a.75.75 0 0 0-.75.75v12.5c0 .414.336.75.75.75h1.5a.75.75 0 0 0 .75-.75V3.75A.75.75 0 0 0 7.25 3h-1.5ZM12.75 3a.75.75 0 0 0-.75.75v12.5c0 .414.336.75.75.75h1.5a.75.75 0 0 0 .75-.75V3.75a.75.75 0 0 0-.75-.75h-1.5Z"/>
                </svg>
              ) : (
                <svg className="w-5 h-5 translate-x-0.5" viewBox="0 0 20 20" fill="currentColor" aria-hidden="true">
                  <path d="M6.3 2.84A1.5 1.5 0 0 0 4 4.11v11.78a1.5 1.5 0 0 0 2.3 1.27l9.344-5.891a1.5 1.5 0 0 0 0-2.538L6.3 2.841Z"/>
                </svg>
              )}
            </button>

            {/* Skip forward 10 */}
            <button
              onClick={() => actions.skipForward(10)}
              className="relative text-sonoro-muted hover:text-sonoro-700 transition-colors"
              aria-label="Skip forward 10 seconds"
            >
              <svg className="w-5 h-5 scale-x-[-1]" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
                <path d="M12 5V2L8 6l4 4V7c3.31 0 6 2.69 6 6s-2.69 6-6 6-6-2.69-6-6H4c0 4.42 3.58 8 8 8s8-3.58 8-8-3.58-8-8-8z"/>
              </svg>
              <span className="absolute inset-0 flex items-center justify-center text-[7px] font-bold mt-0.5" aria-hidden="true">10</span>
            </button>

            <button
              onClick={actions.nextChapter}
              disabled={currentIdx >= chapters.length - 1}
              className="text-sonoro-muted hover:text-sonoro-700 disabled:opacity-30 transition-colors"
              aria-label="Next chapter"
            >
              <svg className="w-5 h-5" viewBox="0 0 20 20" fill="currentColor" aria-hidden="true">
                <path d="M16.5 5a.5.5 0 0 0-1 0v3.536L8.504 3.554A.5.5 0 0 0 7.5 4v12a.5.5 0 0 0 .754.432L15.5 11.458V15a.5.5 0 0 0 1 0V5Z"/>
              </svg>
            </button>
          </div>

          {/* Keyboard hint */}
          <p className="mt-4 text-center text-[10px] text-sonoro-400 select-none">
            Space · ← → seek · M mute · Shift+← → chapters
          </p>
        </div>

        {/* Chapter list */}
        {chapters.length > 1 && (
          <div className="border-t border-sonoro-border">
            <div className="flex items-center justify-between px-6 py-3">
              <p className="label-sm">Chapters</p>
              <span className="text-[10px] text-sonoro-400">
                {currentIdx + 1} of {chapters.length}
              </span>
            </div>
            <ChapterList
              chapters={chapters}
              currentIdx={currentIdx}
              isPlaying={isPlaying}
              onSelect={actions.goToChapter}
            />
          </div>
        )}
      </div>

      {/* Immersive mode overlay */}
      {immersive && (
        <ImmersiveOverlay
          chapters={chapters}
          documentTitle={documentTitle}
          state={state}
          actions={actions}
          onClose={() => setImmersive(false)}
        />
      )}
    </>
  );
}
