/**
 * Audio Player Component
 * =====================
 * Premium audiobook player with chapter navigation, speed control, Media Session,
 * and resume playback.
 */

'use client';

import { useRef, useState, useEffect, useCallback } from 'react';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Slider } from '@/components/ui/slider';
import {
  Play,
  Pause,
  SkipForward,
  SkipBack,
  Volume2,
  VolumeX,
  ChevronLeft,
  ChevronRight,
} from 'lucide-react';
import { cn } from '@/lib/utils';
import { track } from '@/lib/analytics';
import type { Chapter } from '@/lib/document-service';

interface AudioPlayerProps {
  audioUrl: string;
  chapters?: Chapter[];
  documentId: string;
  title: string;
  onChapterChange?: (chapterNumber: number) => void;
  className?: string;
}

const PLAYBACK_SPEEDS = [0.75, 1, 1.25, 1.5, 2];
const SKIP_SECONDS = 10;
const STORAGE_PREFIX = 'sonoro_player_';

export function AudioPlayer({
  audioUrl,
  chapters = [],
  documentId,
  title,
  onChapterChange,
  className,
}: AudioPlayerProps) {
  const audioRef = useRef<HTMLAudioElement>(null);
  const [isPlaying, setIsPlaying] = useState(false);
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(0);
  const [volume, setVolume] = useState(1);
  const [isMuted, setIsMuted] = useState(false);
  const [playbackSpeed, setPlaybackSpeed] = useState(1);
  const [isLoading, setIsLoading] = useState(true);
  const [currentChapterIdx, setCurrentChapterIdx] = useState<number>(0);
  const [isDragging, setIsDragging] = useState(false);

  // Sorted chapters with start_time_seconds
  const sortedChapters = [...chapters].sort((a, b) => a.chapter_number - b.chapter_number);

  // Build cumulative start times: prefer start_time_seconds from backend,
  // fall back to accumulating duration_seconds.
  const chapterStarts = useCallback((): number[] => {
    const starts: number[] = [];
    let cumulative = 0;
    for (const ch of sortedChapters) {
      if (ch.start_time_seconds != null) {
        starts.push(ch.start_time_seconds);
      } else {
        starts.push(cumulative);
        cumulative += ch.duration_seconds ?? 0;
      }
    }
    return starts;
  }, [sortedChapters]);

  // Load saved playback position
  useEffect(() => {
    const savedPosition = localStorage.getItem(`${STORAGE_PREFIX}${documentId}_position`);
    const savedSpeed = localStorage.getItem(`${STORAGE_PREFIX}${documentId}_speed`);

    if (savedPosition) {
      const position = parseFloat(savedPosition);
      if (audioRef.current && !isNaN(position)) {
        audioRef.current.currentTime = position;
        setCurrentTime(position);
      }
    }

    if (savedSpeed) {
      const speed = parseFloat(savedSpeed);
      if (!isNaN(speed) && PLAYBACK_SPEEDS.includes(speed)) {
        setPlaybackSpeed(speed);
        if (audioRef.current) audioRef.current.playbackRate = speed;
      }
    }
  }, [documentId]);

  // Save playback position periodically
  useEffect(() => {
    const interval = setInterval(() => {
      if (audioRef.current && isPlaying) {
        localStorage.setItem(
          `${STORAGE_PREFIX}${documentId}_position`,
          audioRef.current.currentTime.toString(),
        );
      }
    }, 5000);
    return () => clearInterval(interval);
  }, [documentId, isPlaying]);

  // Media Session API
  useEffect(() => {
    if (!('mediaSession' in navigator)) return;
    navigator.mediaSession.metadata = new MediaMetadata({
      title,
      artist: 'Sonoro Audiobook',
    });
  }, [title]);

  useEffect(() => {
    if (!('mediaSession' in navigator)) return;

    navigator.mediaSession.setActionHandler('play', () => {
      audioRef.current?.play();
      setIsPlaying(true);
    });
    navigator.mediaSession.setActionHandler('pause', () => {
      audioRef.current?.pause();
      setIsPlaying(false);
    });
    navigator.mediaSession.setActionHandler('seekbackward', () => skipBackward());
    navigator.mediaSession.setActionHandler('seekforward', () => skipForward());
    navigator.mediaSession.setActionHandler('previoustrack', () => goToPrevChapter());
    navigator.mediaSession.setActionHandler('nexttrack', () => goToNextChapter());

    return () => {
      const actions: MediaSessionAction[] = ['play', 'pause', 'seekbackward', 'seekforward', 'previoustrack', 'nexttrack'];
      actions.forEach(a => {
        try { navigator.mediaSession.setActionHandler(a, null); } catch {}
      });
    };
  });

  // Determine current chapter index from currentTime
  const updateCurrentChapter = useCallback((time: number) => {
    if (sortedChapters.length === 0) return;
    const starts = chapterStarts();
    let idx = 0;
    for (let i = starts.length - 1; i >= 0; i--) {
      if (time >= starts[i]) { idx = i; break; }
    }
    if (idx !== currentChapterIdx) {
      setCurrentChapterIdx(idx);
      onChapterChange?.(sortedChapters[idx]?.chapter_number ?? 1);
    }
  }, [sortedChapters, chapterStarts, currentChapterIdx, onChapterChange]);

  // Listen for seek-to-timestamp events from ChapterNavigation
  useEffect(() => {
    const handle = (event: Event) => {
      const e = event as CustomEvent<{ timestamp: number }>;
      if (audioRef.current && e.detail?.timestamp !== undefined) {
        audioRef.current.currentTime = e.detail.timestamp;
        if (!isPlaying) { audioRef.current.play(); setIsPlaying(true); }
      }
    };
    window.addEventListener('seek-to-timestamp', handle);
    return () => window.removeEventListener('seek-to-timestamp', handle);
  }, [isPlaying]);

  // Audio events
  const handleLoadedMetadata = () => {
    if (audioRef.current) { setDuration(audioRef.current.duration); setIsLoading(false); }
  };
  const handleTimeUpdate = () => {
    if (audioRef.current && !isDragging) {
      const t = audioRef.current.currentTime;
      setCurrentTime(t);
      updateCurrentChapter(t);
    }
  };
  const handleEnded = () => {
    setIsPlaying(false);
    localStorage.removeItem(`${STORAGE_PREFIX}${documentId}_position`);
  };
  const handleCanPlay = () => setIsLoading(false);
  const handleWaiting = () => setIsLoading(true);

  // Playback controls
  const togglePlayPause = () => {
    if (!audioRef.current) return;
    if (isPlaying) { audioRef.current.pause(); } else { audioRef.current.play(); }
    setIsPlaying(!isPlaying);
  };

  const skipForward = useCallback(() => {
    if (audioRef.current) audioRef.current.currentTime = Math.min(audioRef.current.currentTime + SKIP_SECONDS, duration);
  }, [duration]);

  const skipBackward = useCallback(() => {
    if (audioRef.current) audioRef.current.currentTime = Math.max(audioRef.current.currentTime - SKIP_SECONDS, 0);
  }, []);

  const seekToChapterIndex = useCallback((idx: number) => {
    if (idx < 0 || idx >= sortedChapters.length) return;
    const starts = chapterStarts();
    const ts = starts[idx] ?? 0;
    if (audioRef.current) {
      audioRef.current.currentTime = ts;
      if (!isPlaying) { audioRef.current.play(); setIsPlaying(true); }
    }
    setCurrentChapterIdx(idx);
    onChapterChange?.(sortedChapters[idx].chapter_number);
  }, [sortedChapters, chapterStarts, isPlaying, onChapterChange]);

  const goToPrevChapter = useCallback(() => {
    if (sortedChapters.length === 0) { skipBackward(); return; }
    track('chapter_previous_clicked', { document_id: documentId });
    // If more than 3s into current chapter, restart it; otherwise go to previous
    const starts = chapterStarts();
    const chStart = starts[currentChapterIdx] ?? 0;
    if (currentTime - chStart > 3 && currentChapterIdx > 0) {
      seekToChapterIndex(currentChapterIdx);
    } else {
      seekToChapterIndex(Math.max(0, currentChapterIdx - 1));
    }
  }, [sortedChapters, chapterStarts, currentChapterIdx, currentTime, skipBackward, seekToChapterIndex, documentId]);

  const goToNextChapter = useCallback(() => {
    if (sortedChapters.length === 0) { skipForward(); return; }
    track('chapter_next_clicked', { document_id: documentId });
    seekToChapterIndex(Math.min(sortedChapters.length - 1, currentChapterIdx + 1));
  }, [sortedChapters, currentChapterIdx, skipForward, seekToChapterIndex, documentId]);

  const handleProgressChange = (values: number[]) => {
    const newTime = values[0];
    setCurrentTime(newTime);
    if (audioRef.current) audioRef.current.currentTime = newTime;
  };
  const handleProgressDragStart = () => setIsDragging(true);
  const handleProgressDragEnd = () => setIsDragging(false);

  const handleVolumeChange = (values: number[]) => {
    const v = values[0];
    setVolume(v);
    if (audioRef.current) audioRef.current.volume = v;
    if (v === 0) setIsMuted(true);
    else if (isMuted) setIsMuted(false);
  };

  const toggleMute = () => {
    if (audioRef.current) audioRef.current.muted = !isMuted;
    setIsMuted(!isMuted);
  };

  const cyclePlaybackSpeed = () => {
    const next = PLAYBACK_SPEEDS[(PLAYBACK_SPEEDS.indexOf(playbackSpeed) + 1) % PLAYBACK_SPEEDS.length];
    setPlaybackSpeed(next);
    if (audioRef.current) audioRef.current.playbackRate = next;
    localStorage.setItem(`${STORAGE_PREFIX}${documentId}_speed`, next.toString());
  };

  const formatTime = (seconds: number) => {
    if (isNaN(seconds)) return '0:00';
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    const s = Math.floor(seconds % 60);
    if (h > 0) return `${h}:${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
    return `${m}:${s.toString().padStart(2, '0')}`;
  };

  const currentChapter = sortedChapters[currentChapterIdx];
  const hasPrev = currentChapterIdx > 0 || (sortedChapters.length === 0);
  const hasNext = currentChapterIdx < sortedChapters.length - 1 || (sortedChapters.length === 0);

  return (
    <Card className={cn('w-full', className)}>
      <CardContent className="p-6 space-y-6">
        <audio
          ref={audioRef}
          src={audioUrl}
          onLoadedMetadata={handleLoadedMetadata}
          onTimeUpdate={handleTimeUpdate}
          onEnded={handleEnded}
          onCanPlay={handleCanPlay}
          onWaiting={handleWaiting}
          preload="metadata"
        />

        {/* Title + current chapter */}
        <div className="text-center space-y-1">
          <h3 className="font-semibold text-lg line-clamp-2">{title}</h3>
          {sortedChapters.length > 1 && currentChapter && (
            <p className="text-sm text-muted-foreground">
              {currentChapter.title.startsWith('Chapter') || currentChapter.title.startsWith('Part')
                ? currentChapter.title
                : `Chapter ${currentChapter.chapter_number} — ${currentChapter.title}`}
            </p>
          )}
        </div>

        {/* Progress bar */}
        <div className="space-y-2">
          <Slider
            value={[currentTime]}
            min={0}
            max={duration || 100}
            step={0.1}
            onValueChange={handleProgressChange}
            onPointerDown={handleProgressDragStart}
            onPointerUp={handleProgressDragEnd}
            disabled={isLoading}
            className="cursor-pointer"
            aria-label="Playback progress"
          />
          <div className="flex justify-between text-xs text-muted-foreground">
            <span>{formatTime(currentTime)}</span>
            <span>{formatTime(duration)}</span>
          </div>
        </div>

        {/* Main Controls */}
        <div className="flex items-center justify-center gap-2">
          {/* Prev chapter */}
          <Button
            variant="ghost"
            size="icon"
            onClick={goToPrevChapter}
            disabled={isLoading || (!hasPrev && sortedChapters.length > 0)}
            aria-label="Previous chapter"
            className="h-10 w-10"
          >
            <ChevronLeft className="h-5 w-5" />
          </Button>

          <Button
            variant="ghost"
            size="icon"
            onClick={skipBackward}
            disabled={isLoading}
            aria-label="Skip backward 10 seconds"
            className="h-10 w-10"
          >
            <SkipBack className="h-5 w-5" />
          </Button>

          <Button
            size="icon"
            onClick={togglePlayPause}
            disabled={isLoading}
            aria-label={isPlaying ? 'Pause' : 'Play'}
            className="h-14 w-14 rounded-full"
          >
            {isPlaying
              ? <Pause className="h-6 w-6" fill="currentColor" />
              : <Play className="h-6 w-6" fill="currentColor" />
            }
          </Button>

          <Button
            variant="ghost"
            size="icon"
            onClick={skipForward}
            disabled={isLoading}
            aria-label="Skip forward 10 seconds"
            className="h-10 w-10"
          >
            <SkipForward className="h-5 w-5" />
          </Button>

          {/* Next chapter */}
          <Button
            variant="ghost"
            size="icon"
            onClick={goToNextChapter}
            disabled={isLoading || (!hasNext && sortedChapters.length > 0)}
            aria-label="Next chapter"
            className="h-10 w-10"
          >
            <ChevronRight className="h-5 w-5" />
          </Button>
        </div>

        {/* Secondary Controls */}
        <div className="flex items-center justify-between gap-4">
          <div className="flex items-center gap-2 flex-1 max-w-[140px]">
            <Button
              variant="ghost"
              size="icon"
              onClick={toggleMute}
              className="h-8 w-8 shrink-0"
              aria-label={isMuted ? 'Unmute' : 'Mute'}
            >
              {isMuted || volume === 0
                ? <VolumeX className="h-4 w-4" />
                : <Volume2 className="h-4 w-4" />
              }
            </Button>
            <Slider
              value={[isMuted ? 0 : volume]}
              min={0}
              max={1}
              step={0.01}
              onValueChange={handleVolumeChange}
              className="cursor-pointer"
              aria-label="Volume"
            />
          </div>

          <Button
            variant="outline"
            size="sm"
            onClick={cyclePlaybackSpeed}
            className="font-mono"
            aria-label={`Playback speed: ${playbackSpeed}x`}
          >
            {playbackSpeed}x
          </Button>
        </div>

        {isLoading && (
          <div className="text-center text-sm text-muted-foreground">Loading audio…</div>
        )}
      </CardContent>
    </Card>
  );
}
