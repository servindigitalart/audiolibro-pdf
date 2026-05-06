/**
 * Audio Player Component
 * =====================
 * Premium audiobook player with chapter support, speed control, and resume playback
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
} from 'lucide-react';
import { cn } from '@/lib/utils';
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
  const [currentChapter, setCurrentChapter] = useState<number | null>(null);
  const [isDragging, setIsDragging] = useState(false);

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
        if (audioRef.current) {
          audioRef.current.playbackRate = speed;
        }
      }
    }
  }, [documentId]);

  // Save playback position periodically
  useEffect(() => {
    const interval = setInterval(() => {
      if (audioRef.current && isPlaying) {
        localStorage.setItem(
          `${STORAGE_PREFIX}${documentId}_position`,
          audioRef.current.currentTime.toString()
        );
      }
    }, 5000); // Save every 5 seconds

    return () => clearInterval(interval);
  }, [documentId, isPlaying]);

  // Listen for seek-to-timestamp events from chapter navigation
  useEffect(() => {
    const handleSeekEvent = (event: Event) => {
      const customEvent = event as CustomEvent<{ timestamp: number }>;
      if (audioRef.current && customEvent.detail?.timestamp !== undefined) {
        audioRef.current.currentTime = customEvent.detail.timestamp;
        if (!isPlaying) {
          audioRef.current.play();
          setIsPlaying(true);
        }
      }
    };

    window.addEventListener('seek-to-timestamp', handleSeekEvent);
    return () => window.removeEventListener('seek-to-timestamp', handleSeekEvent);
  }, [isPlaying]);

  // Determine current chapter based on timestamp
  const determineCurrentChapter = useCallback((time: number) => {
    if (!chapters.length) return null;

    // Chapters should have timestamp_start in seconds
    // Assuming chapters are ordered and have timestamp_start
    for (let i = chapters.length - 1; i >= 0; i--) {
      const chapter = chapters[i];
      // If chapter has audio_url, use its duration to calculate start time
      // For now, assume chapters are sequential
      const startTime = i === 0 ? 0 : chapters[i - 1].duration_seconds || 0;
      if (time >= startTime) {
        return chapter.chapter_number;
      }
    }
    return chapters[0]?.chapter_number || null;
  }, [chapters]);

  // Update current chapter when time changes
  useEffect(() => {
    const chapterNum = determineCurrentChapter(currentTime);
    if (chapterNum !== currentChapter) {
      setCurrentChapter(chapterNum);
      onChapterChange?.(chapterNum);
    }
  }, [currentTime, currentChapter, determineCurrentChapter, onChapterChange]);

  // Audio event handlers
  const handleLoadedMetadata = () => {
    if (audioRef.current) {
      setDuration(audioRef.current.duration);
      setIsLoading(false);
    }
  };

  const handleTimeUpdate = () => {
    if (audioRef.current && !isDragging) {
      setCurrentTime(audioRef.current.currentTime);
    }
  };

  const handleEnded = () => {
    setIsPlaying(false);
    localStorage.removeItem(`${STORAGE_PREFIX}${documentId}_position`);
  };

  const handleCanPlay = () => {
    setIsLoading(false);
  };

  const handleWaiting = () => {
    setIsLoading(true);
  };

  // Playback controls
  const togglePlayPause = () => {
    if (audioRef.current) {
      if (isPlaying) {
        audioRef.current.pause();
      } else {
        audioRef.current.play();
      }
      setIsPlaying(!isPlaying);
    }
  };

  const skipForward = () => {
    if (audioRef.current) {
      audioRef.current.currentTime = Math.min(
        audioRef.current.currentTime + SKIP_SECONDS,
        duration
      );
    }
  };

  const skipBackward = () => {
    if (audioRef.current) {
      audioRef.current.currentTime = Math.max(
        audioRef.current.currentTime - SKIP_SECONDS,
        0
      );
    }
  };

  const handleProgressChange = (values: number[]) => {
    const newTime = values[0];
    setCurrentTime(newTime);
    if (audioRef.current) {
      audioRef.current.currentTime = newTime;
    }
  };

  const handleProgressDragStart = () => {
    setIsDragging(true);
  };

  const handleProgressDragEnd = () => {
    setIsDragging(false);
  };

  const handleVolumeChange = (values: number[]) => {
    const newVolume = values[0];
    setVolume(newVolume);
    if (audioRef.current) {
      audioRef.current.volume = newVolume;
    }
    if (newVolume === 0) {
      setIsMuted(true);
    } else if (isMuted) {
      setIsMuted(false);
    }
  };

  const toggleMute = () => {
    if (audioRef.current) {
      audioRef.current.muted = !isMuted;
      setIsMuted(!isMuted);
    }
  };

  const cyclePlaybackSpeed = () => {
    const currentIndex = PLAYBACK_SPEEDS.indexOf(playbackSpeed);
    const nextIndex = (currentIndex + 1) % PLAYBACK_SPEEDS.length;
    const newSpeed = PLAYBACK_SPEEDS[nextIndex];
    setPlaybackSpeed(newSpeed);
    if (audioRef.current) {
      audioRef.current.playbackRate = newSpeed;
    }
    localStorage.setItem(`${STORAGE_PREFIX}${documentId}_speed`, newSpeed.toString());
  };

  const formatTime = (seconds: number) => {
    if (isNaN(seconds)) return '0:00';
    const hrs = Math.floor(seconds / 3600);
    const mins = Math.floor((seconds % 3600) / 60);
    const secs = Math.floor(seconds % 60);
    
    if (hrs > 0) {
      return `${hrs}:${mins.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`;
    }
    return `${mins}:${secs.toString().padStart(2, '0')}`;
  };

  return (
    <Card className={cn('w-full', className)}>
      <CardContent className="p-6 space-y-6">
        {/* Hidden audio element */}
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

        {/* Title */}
        <div className="text-center space-y-1">
          <h3 className="font-semibold text-lg line-clamp-2">{title}</h3>
          {currentChapter !== null && chapters.length > 0 && (
            <p className="text-sm text-muted-foreground">
              Chapter {currentChapter}
              {chapters.find(c => c.chapter_number === currentChapter)?.title && 
                ` - ${chapters.find(c => c.chapter_number === currentChapter)?.title}`
              }
            </p>
          )}
        </div>

        {/* Progress Bar */}
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
        <div className="flex items-center justify-center gap-4">
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
            {isPlaying ? (
              <Pause className="h-6 w-6" fill="currentColor" />
            ) : (
              <Play className="h-6 w-6" fill="currentColor" />
            )}
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
        </div>

        {/* Secondary Controls */}
        <div className="flex items-center justify-between gap-4">
          {/* Volume Control */}
          <div className="flex items-center gap-2 flex-1 max-w-[140px]">
            <Button
              variant="ghost"
              size="icon"
              onClick={toggleMute}
              className="h-8 w-8 shrink-0"
              aria-label={isMuted ? 'Unmute' : 'Mute'}
            >
              {isMuted || volume === 0 ? (
                <VolumeX className="h-4 w-4" />
              ) : (
                <Volume2 className="h-4 w-4" />
              )}
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

          {/* Playback Speed */}
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

        {/* Loading indicator */}
        {isLoading && (
          <div className="text-center text-sm text-muted-foreground">
            Loading audio...
          </div>
        )}
      </CardContent>
    </Card>
  );
}
