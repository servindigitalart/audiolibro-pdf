import { useState, useRef, useEffect } from 'react';
import type { Chapter } from '@/lib/api/types';
import { useAudioPlayer } from '@/hooks/useAudioPlayer';
import { fmtDuration } from '@/lib/utils';
import { cn } from '@/lib/utils';

// Deterministic waveform heights — two overlapping sine waves give a natural shape
const WAVEFORM = Array.from({ length: 60 }, (_, i) =>
  Math.round(20 + Math.abs(Math.sin(i * 0.47 + 0.3) * 0.55 + Math.sin(i * 0.13 + 1.2) * 0.45) * 76)
);

const SPEEDS = [0.75, 1, 1.25, 1.5, 2];

interface Props {
  chapters:      Chapter[];
  documentTitle: string;
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
            className="h-full bg-sonoro-amber rounded-full"
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
        <span className="text-xs text-sonoro-muted tabular-nums">{duration > 0 ? fmtDuration(duration) : '--:--'}</span>
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

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-sonoro-black/96 backdrop-blur-md"
      role="dialog"
      aria-modal="true"
      aria-label="Immersive listening mode"
    >
      {/* Ambient orbs */}
      <div
        className="absolute top-[-20%] right-[-10%] w-[700px] h-[700px] pointer-events-none animate-float"
        style={{ background: 'radial-gradient(ellipse, rgba(245,158,11,0.12) 0%, transparent 65%)', filter: 'blur(40px)' }}
        aria-hidden="true"
      />
      <div
        className="absolute bottom-[-20%] left-[-10%] w-[500px] h-[500px] pointer-events-none animate-float-delayed"
        style={{ background: 'radial-gradient(ellipse, rgba(245,158,11,0.07) 0%, transparent 65%)', filter: 'blur(40px)' }}
        aria-hidden="true"
      />

      {/* Close */}
      <button
        onClick={onClose}
        className="absolute top-6 right-6 flex h-9 w-9 items-center justify-center rounded-full bg-white/10 text-white/70 hover:bg-white/20 hover:text-white transition-colors"
        aria-label="Exit immersive mode"
      >
        <svg className="w-4 h-4" viewBox="0 0 20 20" fill="currentColor" aria-hidden="true">
          <path d="M6.28 5.22a.75.75 0 0 0-1.06 1.06L8.94 10l-3.72 3.72a.75.75 0 1 0 1.06 1.06L10 11.06l3.72 3.72a.75.75 0 1 0 1.06-1.06L11.06 10l3.72-3.72a.75.75 0 0 0-1.06-1.06L10 8.94 6.28 5.22Z"/>
        </svg>
      </button>

      <div className="relative w-full max-w-4xl mx-6 grid grid-cols-1 lg:grid-cols-[280px_1fr] gap-4 animate-fade-in">
        {/* Chapter list */}
        {chapters.length > 1 && (
          <div className="hidden lg:flex flex-col">
            <p className="label-sm text-white/40 px-5 mb-3">Chapters</p>
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

        {/* Player */}
        <div className="rounded-2xl border border-white/[0.08] bg-white/[0.03] overflow-hidden">
          {/* Now playing header */}
          <div className="px-7 pt-7 pb-5">
            <p className="label-sm text-white/40 mb-3">Now playing</p>
            <p className="text-2xl font-bold text-white tracking-tight leading-snug mb-1">
              {chapter?.title ?? '—'}
            </p>
            <p className="text-sm text-white/50">{documentTitle}</p>
          </div>

          {/* Waveform */}
          <div className="px-7 pb-2">
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
            <div className="flex items-center justify-center gap-5">
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
                className="flex h-14 w-14 items-center justify-center rounded-full bg-white text-sonoro-black hover:bg-sonoro-100 active:scale-95 transition-all shadow-lg disabled:opacity-40"
                aria-label={isPlaying ? 'Pause' : 'Play'}
              >
                {isBuffering ? (
                  <svg className="w-5 h-5 animate-spin text-sonoro-400" viewBox="0 0 24 24" fill="none" aria-hidden="true">
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
      <p className="absolute bottom-5 text-[10px] text-white/20 tracking-wide select-none">
        Space · ← → seek · Shift+← → chapters · M mute · Esc exit
      </p>
    </div>
  );
}

// ── Main AudioPlayer ──────────────────────────────────────────────────────────
export default function AudioPlayer({ chapters, documentTitle }: Props) {
  const { audioRef, chapter, state, actions, audioProps } = useAudioPlayer({ chapters });
  const [immersive, setImmersive] = useState(false);

  const { currentIdx, isPlaying, currentTime, duration, progress, speed, volume, isMuted, isBuffering } = state;

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

  const hasAudio = !!chapter?.audio_url;

  return (
    <>
      {/* Hidden audio element — lives outside any conditional rendering */}
      <audio ref={audioRef} preload="metadata" {...audioProps} />

      <div className="card-base overflow-hidden animate-fade-in">
        {/* Amber top accent */}
        <div
          className="h-0.5 w-full"
          style={{ background: `linear-gradient(90deg, #D97706 ${progress * 100}%, #E8E7E3 ${progress * 100}%)` }}
          aria-hidden="true"
        />

        {/* Header: now playing */}
        <div className="flex items-start justify-between gap-4 px-6 pt-5 pb-4 border-b border-sonoro-border">
          <div className="min-w-0">
            <p className="label-sm mb-1.5">Now playing</p>
            <p className="text-sm font-bold text-sonoro-900 truncate leading-snug">
              {chapter?.title ?? (hasAudio ? '—' : 'No audio available')}
            </p>
            <p className="text-xs text-sonoro-muted mt-0.5 truncate">{documentTitle}</p>
          </div>

          {/* Immersive toggle */}
          <button
            onClick={() => setImmersive(true)}
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
          {/* Speed */}
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

            <VolumeControl
              volume={volume}
              isMuted={isMuted}
              onToggleMute={actions.toggleMute}
              onVolumeChange={actions.setVolume}
            />
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
              onClick={actions.togglePlay}
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
