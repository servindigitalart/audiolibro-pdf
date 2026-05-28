import { useRef, useEffect } from 'react';

const KEY_PREFIX   = 'sonoro_progress_';
const LAST_PLAYED  = 'sonoro_last_played';
const SAVE_INTERVAL_MS = 5_000;

export interface PlaybackProgress {
  documentId:    string;
  documentTitle: string;
  chapterIdx:    number;
  chapterTitle:  string;
  currentTime:   number;
  totalDuration: number;
  timestamp:     number;
}

export function saveProgress(p: PlaybackProgress): void {
  try {
    localStorage.setItem(KEY_PREFIX + p.documentId, JSON.stringify(p));
    localStorage.setItem(LAST_PLAYED, p.documentId);
  } catch { /* storage unavailable */ }
}

export function loadProgress(documentId: string): PlaybackProgress | null {
  try {
    const raw = localStorage.getItem(KEY_PREFIX + documentId);
    return raw ? (JSON.parse(raw) as PlaybackProgress) : null;
  } catch {
    return null;
  }
}

export function loadLastPlayed(): PlaybackProgress | null {
  try {
    const id = localStorage.getItem(LAST_PLAYED);
    return id ? loadProgress(id) : null;
  } catch {
    return null;
  }
}

export function getAllProgress(): PlaybackProgress[] {
  const results: PlaybackProgress[] = [];
  try {
    for (let i = 0; i < localStorage.length; i++) {
      const key = localStorage.key(i);
      if (key?.startsWith(KEY_PREFIX)) {
        const raw = localStorage.getItem(key);
        if (raw) {
          try { results.push(JSON.parse(raw) as PlaybackProgress); } catch { /* skip */ }
        }
      }
    }
    results.sort((a, b) => b.timestamp - a.timestamp);
  } catch { /* storage unavailable */ }
  return results;
}

export function clearProgress(documentId: string): void {
  try {
    localStorage.removeItem(KEY_PREFIX + documentId);
    if (localStorage.getItem(LAST_PLAYED) === documentId) {
      localStorage.removeItem(LAST_PLAYED);
    }
  } catch { /* ignore */ }
}

/**
 * Saves playback progress to localStorage at most every SAVE_INTERVAL_MS while playing.
 * Uses a ref to throttle — runs on every render but only writes when the interval has elapsed.
 */
export function usePlaybackProgress(
  documentId:    string,
  documentTitle: string,
  chapterIdx:    number,
  chapterTitle:  string,
  currentTime:   number,
  totalDuration: number,
  isPlaying:     boolean,
) {
  const lastSave = useRef(0);

  useEffect(() => {
    if (!isPlaying || totalDuration <= 0 || currentTime < 3) return;
    const now = Date.now();
    if (now - lastSave.current < SAVE_INTERVAL_MS) return;
    lastSave.current = now;
    saveProgress({ documentId, documentTitle, chapterIdx, chapterTitle, currentTime, totalDuration, timestamp: now });
    console.log('[SONORO] continue_listening_saved');
  }); // intentionally no deps — runs every render, throttled by ref
}
