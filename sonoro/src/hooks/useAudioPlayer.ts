import { useState, useRef, useEffect, useCallback } from 'react';
import type { Chapter } from '@/lib/api/types';

interface Options {
  chapters: Chapter[];
}

export interface AudioState {
  currentIdx:  number;
  isPlaying:   boolean;
  currentTime: number;
  duration:    number;
  progress:    number;
  speed:       number;
  volume:      number;
  isMuted:     boolean;
  isBuffering: boolean;
}

export interface AudioActions {
  togglePlay:  () => void;
  seek:        (pct: number) => void;
  skipBack:    (secs?: number) => void;
  skipForward: (secs?: number) => void;
  setSpeed:    (s: number) => void;
  setVolume:   (v: number) => void;
  toggleMute:  () => void;
  nextChapter: () => void;
  prevChapter: () => void;
  goToChapter: (idx: number) => void;
}

export function useAudioPlayer({ chapters }: Options) {
  const audioRef = useRef<HTMLAudioElement>(null);

  const [currentIdx,  setCurrentIdx]  = useState(0);
  const [isPlaying,   setIsPlaying]   = useState(false);
  const [currentTime, setCurrentTime] = useState(0);
  const [duration,    setDuration]    = useState(0);
  const [speed,       setSpeedState]  = useState(1);
  const [volume,      setVolumeState] = useState(1);
  const [isMuted,     setIsMuted]     = useState(false);
  const [isBuffering, setIsBuffering] = useState(false);

  const progress = duration > 0 ? currentTime / duration : 0;

  // Stable refs so event listeners never become stale
  const isPlayingRef  = useRef(isPlaying);
  const currentIdxRef = useRef(currentIdx);
  const chaptersRef   = useRef(chapters);
  const speedRef      = useRef(speed);
  const volumeRef     = useRef(volume);
  const isMutedRef    = useRef(isMuted);

  useEffect(() => { isPlayingRef.current  = isPlaying; },  [isPlaying]);
  useEffect(() => { currentIdxRef.current = currentIdx; }, [currentIdx]);
  useEffect(() => { chaptersRef.current   = chapters; },   [chapters]);
  useEffect(() => { speedRef.current      = speed; },      [speed]);
  useEffect(() => { volumeRef.current     = volume; },     [volume]);
  useEffect(() => { isMutedRef.current    = isMuted; },    [isMuted]);

  // Load chapter when currentIdx changes
  useEffect(() => {
    const audio = audioRef.current;
    if (!audio) return;
    const url = chapters[currentIdx]?.audio_url;
    setCurrentTime(0);
    setDuration(0);
    if (!url) return;
    audio.src = url;
    audio.playbackRate = speedRef.current;
    audio.volume = isMutedRef.current ? 0 : volumeRef.current;
    if (isPlayingRef.current) {
      audio.play().catch(() => setIsPlaying(false));
    }
  }, [currentIdx]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (audioRef.current) audioRef.current.playbackRate = speed;
  }, [speed]);

  useEffect(() => {
    if (audioRef.current) audioRef.current.volume = isMuted ? 0 : volume;
  }, [volume, isMuted]);

  // Keyboard shortcuts — registered once, reads state via refs
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      const tag = (e.target as HTMLElement)?.tagName ?? '';
      if (['INPUT', 'TEXTAREA', 'SELECT'].includes(tag)) return;
      const audio = audioRef.current;
      if (!audio) return;

      switch (e.key) {
        case ' ':
          e.preventDefault();
          if (audio.paused && chaptersRef.current[currentIdxRef.current]?.audio_url) {
            audio.play().catch(() => {});
            setIsPlaying(true);
          } else {
            audio.pause();
            setIsPlaying(false);
          }
          break;
        case 'ArrowLeft':
          e.preventDefault();
          if (e.shiftKey) setCurrentIdx(i => Math.max(0, i - 1));
          else audio.currentTime = Math.max(0, audio.currentTime - 5);
          break;
        case 'ArrowRight':
          e.preventDefault();
          if (e.shiftKey) setCurrentIdx(i => Math.min(chaptersRef.current.length - 1, i + 1));
          else audio.currentTime = Math.min(audio.duration || 0, audio.currentTime + 5);
          break;
        case 'm':
        case 'M':
          setIsMuted(m => !m);
          break;
      }
    }
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const togglePlay = useCallback(() => {
    const audio = audioRef.current;
    if (!audio) return;
    if (audio.paused) {
      audio.play().catch(() => {});
      setIsPlaying(true);
    } else {
      audio.pause();
      setIsPlaying(false);
    }
  }, []);

  const seek = useCallback((pct: number) => {
    const audio = audioRef.current;
    if (!audio || !audio.duration) return;
    audio.currentTime = Math.max(0, Math.min(1, pct)) * audio.duration;
  }, []);

  const skipBack    = useCallback((secs = 10) => {
    const audio = audioRef.current;
    if (audio) audio.currentTime = Math.max(0, audio.currentTime - secs);
  }, []);

  const skipForward = useCallback((secs = 10) => {
    const audio = audioRef.current;
    if (audio) audio.currentTime = Math.min(audio.duration || 0, audio.currentTime + secs);
  }, []);

  const setSpeed   = useCallback((s: number) => setSpeedState(s), []);
  const setVolume  = useCallback((v: number) => setVolumeState(v), []);
  const toggleMute = useCallback(() => setIsMuted(m => !m), []);

  const nextChapter = useCallback(() => {
    setCurrentIdx(i => Math.min(chaptersRef.current.length - 1, i + 1));
  }, []);

  const prevChapter = useCallback(() => {
    const audio = audioRef.current;
    if (audio && audio.currentTime > 3) {
      audio.currentTime = 0;
    } else {
      setCurrentIdx(i => Math.max(0, i - 1));
    }
  }, []);

  const goToChapter = useCallback((idx: number) => {
    const audio = audioRef.current;
    const url   = chaptersRef.current[idx]?.audio_url;
    if (!url) return;
    setCurrentIdx(idx);
    setIsPlaying(true);
    // If audio src is already this chapter (from the currentIdx effect), just play.
    // Otherwise, set src and play immediately — the currentIdx effect fires async.
    if (audio) {
      audio.src = url;
      audio.playbackRate = speedRef.current;
      audio.volume = isMutedRef.current ? 0 : volumeRef.current;
      audio.play().catch(() => setIsPlaying(false));
    }
  }, []);

  const audioProps = {
    onTimeUpdate:     () => { if (audioRef.current) setCurrentTime(audioRef.current.currentTime); },
    onLoadedMetadata: () => { if (audioRef.current) setDuration(audioRef.current.duration); },
    onEnded: () => {
      const next = currentIdxRef.current + 1;
      if (next < chaptersRef.current.length && chaptersRef.current[next]?.audio_url) {
        setCurrentIdx(next);
        setIsPlaying(true);
      } else {
        setIsPlaying(false);
      }
    },
    onWaiting: () => setIsBuffering(true),
    onCanPlay: () => setIsBuffering(false),
    onError:   () => setIsBuffering(false),
  };

  return {
    audioRef,
    chapter: chapters[currentIdx] as Chapter | undefined,
    state:   { currentIdx, isPlaying, currentTime, duration, progress, speed, volume, isMuted, isBuffering } as AudioState,
    actions: { togglePlay, seek, skipBack, skipForward, setSpeed, setVolume, toggleMute, nextChapter, prevChapter, goToChapter } as AudioActions,
    audioProps,
  };
}
