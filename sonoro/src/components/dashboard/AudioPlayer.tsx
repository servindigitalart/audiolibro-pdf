import { useState, useRef, useEffect } from 'react';
import type { Chapter } from '@/lib/api/types';
import { fmtDuration } from '@/lib/utils';
import { cn } from '@/lib/utils';

// Deterministic waveform heights computed once at module level.
// Using Math.random() inside render causes SSR/client hydration mismatches.
const WAVE_HEIGHTS = Array.from({ length: 40 }, (_, i) =>
  20 + (Math.abs(Math.sin(i * 0.47) * 0.6 + Math.sin(i * 0.13) * 0.4)) * 80
);

interface Props {
  chapters: Chapter[];
  documentTitle: string;
}

export default function AudioPlayer({ chapters, documentTitle }: Props) {
  const audioRef = useRef<HTMLAudioElement>(null);
  const [currentIdx, setCurrentIdx] = useState(0);
  const [isPlaying, setIsPlaying]   = useState(false);
  const [progress, setProgress]     = useState(0);    // 0–1
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration]     = useState(0);
  const [speed, setSpeed]           = useState(1.0);

  const chapter = chapters[currentIdx];

  useEffect(() => {
    const audio = audioRef.current;
    if (!audio || !chapter?.audio_url) return;
    audio.src = chapter.audio_url;
    audio.playbackRate = speed;
    if (isPlaying) audio.play().catch(() => setIsPlaying(false));
  }, [currentIdx, chapter?.audio_url]);

  useEffect(() => {
    const audio = audioRef.current;
    if (!audio) return;
    audio.playbackRate = speed;
  }, [speed]);

  function handleTimeUpdate() {
    const audio = audioRef.current;
    if (!audio) return;
    setCurrentTime(audio.currentTime);
    setProgress(audio.duration > 0 ? audio.currentTime / audio.duration : 0);
  }

  function handleLoadedMetadata() {
    const audio = audioRef.current;
    if (audio) setDuration(audio.duration);
  }

  function handleEnded() {
    if (currentIdx < chapters.length - 1) {
      setCurrentIdx((i) => i + 1);
    } else {
      setIsPlaying(false);
    }
  }

  async function togglePlay() {
    const audio = audioRef.current;
    if (!audio || !chapter?.audio_url) return;
    if (isPlaying) {
      audio.pause();
      setIsPlaying(false);
    } else {
      await audio.play().catch(() => {});
      setIsPlaying(true);
    }
  }

  function seek(e: React.PointerEvent<HTMLDivElement>) {
    const audio = audioRef.current;
    if (!audio || !audio.duration) return;
    const rect = e.currentTarget.getBoundingClientRect();
    const x = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
    audio.currentTime = x * audio.duration;
  }

  const speeds = [0.75, 1.0, 1.25, 1.5, 2.0];
  const completedChapters = chapters.filter((c) => c.status === 'completed');

  if (completedChapters.length === 0) {
    return (
      <div className="card-base p-8 text-center">
        <div className="flex items-end justify-center gap-1 h-10 mb-4">
          {Array.from({ length: 5 }).map((_, i) => (
            <div key={i} className="waveform-bar" style={{ animationDelay: `${i * 0.15}s` }} />
          ))}
        </div>
        <p className="text-sm font-medium text-sonoro-900 mb-1">Generating your audiobook…</p>
        <p className="text-xs text-sonoro-muted">This usually takes under 60 seconds. Check back shortly.</p>
      </div>
    );
  }

  return (
    <div className="card-base overflow-hidden">
      {/* Hidden audio element */}
      <audio
        ref={audioRef}
        onTimeUpdate={handleTimeUpdate}
        onLoadedMetadata={handleLoadedMetadata}
        onEnded={handleEnded}
      />

      {/* Chapter header */}
      <div className="border-b border-sonoro-border px-6 py-4">
        <p className="label-sm mb-1">Now playing</p>
        <p className="text-sm font-semibold text-sonoro-900 truncate">
          {chapter?.title ?? 'Loading…'}
        </p>
        <p className="text-xs text-sonoro-muted">{documentTitle}</p>
      </div>

      {/* Waveform + scrubber */}
      <div className="px-6 pt-5 pb-2">
        {/* Decorative waveform */}
        <div className="flex items-end gap-0.5 h-10 mb-4">
          {WAVE_HEIGHTS.map((h, i) => (
            <div
              key={i}
              className={cn('flex-1 rounded-sm transition-colors', i / 40 <= progress ? 'bg-sonoro-amber' : 'bg-sonoro-border')}
              style={{ height: `${h}%` }}
            />
          ))}
        </div>

        {/* Scrub bar */}
        <div
          className="relative h-1.5 w-full rounded-full bg-sonoro-border cursor-pointer group"
          onPointerDown={seek}
          role="slider"
          aria-valuenow={currentTime}
          aria-valuemin={0}
          aria-valuemax={duration}
          aria-label="Playback position"
        >
          <div
            className="absolute inset-y-0 left-0 rounded-full bg-sonoro-amber transition-all"
            style={{ width: `${progress * 100}%` }}
          />
          <div
            className="absolute top-1/2 -translate-y-1/2 h-3.5 w-3.5 rounded-full bg-sonoro-amber border-2 border-sonoro-white shadow-card opacity-0 group-hover:opacity-100 transition-opacity"
            style={{ left: `${progress * 100}%`, transform: 'translate(-50%, -50%)' }}
          />
        </div>

        <div className="flex justify-between mt-1.5">
          <span className="text-xs text-sonoro-muted">{fmtDuration(currentTime)}</span>
          <span className="text-xs text-sonoro-muted">{fmtDuration(duration)}</span>
        </div>
      </div>

      {/* Controls */}
      <div className="flex items-center justify-between px-6 py-4">
        {/* Speed */}
        <div className="flex items-center gap-1">
          {speeds.map((s) => (
            <button
              key={s}
              onClick={() => setSpeed(s)}
              className={cn(
                'px-2 py-1 rounded-full text-xs font-medium transition-colors',
                speed === s
                  ? 'bg-sonoro-black text-sonoro-white'
                  : 'text-sonoro-muted hover:text-sonoro-900 hover:bg-sonoro-surface'
              )}
              aria-label={`${s}× speed`}
            >
              {s}×
            </button>
          ))}
        </div>

        {/* Main controls */}
        <div className="flex items-center gap-4">
          <button
            onClick={() => setCurrentIdx((i) => Math.max(0, i - 1))}
            disabled={currentIdx === 0}
            className="text-sonoro-muted hover:text-sonoro-900 disabled:opacity-30 transition-colors"
            aria-label="Previous chapter"
          >
            <svg className="w-5 h-5" viewBox="0 0 20 20" fill="currentColor" aria-hidden="true">
              <path d="M4 5h2v10H4V5zm3.586 4.408L13 5.587A1 1 0 0115 6.179v7.642a1 1 0 01-1.414.908l-5.414-3.22a1 1 0 010-1.101z"/>
            </svg>
          </button>

          <button
            onClick={togglePlay}
            className="flex h-12 w-12 items-center justify-center rounded-full bg-sonoro-black text-sonoro-white hover:bg-sonoro-800 active:scale-95 transition-all shadow-card"
            aria-label={isPlaying ? 'Pause' : 'Play'}
          >
            {isPlaying ? (
              <svg className="w-5 h-5" viewBox="0 0 20 20" fill="currentColor" aria-hidden="true">
                <path d="M5 4h3v12H5V4zm7 0h3v12h-3V4z"/>
              </svg>
            ) : (
              <svg className="w-5 h-5" viewBox="0 0 20 20" fill="currentColor" aria-hidden="true">
                <path d="M6.3 2.841A1.5 1.5 0 004 4.11v11.78a1.5 1.5 0 002.3 1.269l9.344-5.89a1.5 1.5 0 000-2.538L6.3 2.84z"/>
              </svg>
            )}
          </button>

          <button
            onClick={() => setCurrentIdx((i) => Math.min(chapters.length - 1, i + 1))}
            disabled={currentIdx >= chapters.length - 1}
            className="text-sonoro-muted hover:text-sonoro-900 disabled:opacity-30 transition-colors"
            aria-label="Next chapter"
          >
            <svg className="w-5 h-5" viewBox="0 0 20 20" fill="currentColor" aria-hidden="true">
              <path d="M16 5h-2v10h2V5zm-9 .587A1 1 0 005 6.179v7.642a1 1 0 001.414.908l5.414-3.22a1 1 0 000-1.101L7 5.587z"/>
            </svg>
          </button>
        </div>

        {/* Chapter count */}
        <span className="text-xs text-sonoro-muted">
          {currentIdx + 1} / {chapters.length}
        </span>
      </div>

      {/* Chapter list */}
      <div className="border-t border-sonoro-border">
        <div className="max-h-52 overflow-y-auto">
          {chapters.map((ch, i) => (
            <button
              key={ch.id}
              onClick={() => { setCurrentIdx(i); setIsPlaying(true); }}
              disabled={ch.status !== 'completed'}
              className={cn(
                'flex w-full items-center gap-3 px-5 py-3 text-left transition-colors',
                i === currentIdx
                  ? 'bg-sonoro-amber-light'
                  : 'hover:bg-sonoro-surface',
                ch.status !== 'completed' && 'opacity-50 cursor-not-allowed'
              )}
            >
              <span className={cn(
                'flex h-5 w-5 items-center justify-center rounded-full text-[10px] font-bold shrink-0',
                i === currentIdx ? 'bg-sonoro-amber text-sonoro-black' : 'bg-sonoro-border text-sonoro-muted'
              )}>
                {i === currentIdx && isPlaying ? (
                  <svg className="w-2.5 h-2.5" viewBox="0 0 10 10" fill="currentColor" aria-hidden="true">
                    <rect x="1" y="1" width="3" height="8" rx="1"/><rect x="6" y="1" width="3" height="8" rx="1"/>
                  </svg>
                ) : (
                  i + 1
                )}
              </span>
              <span className="flex-1 text-xs font-medium text-sonoro-800 truncate">{ch.title}</span>
              {ch.duration_seconds && (
                <span className="text-[10px] text-sonoro-muted shrink-0">{fmtDuration(ch.duration_seconds)}</span>
              )}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
