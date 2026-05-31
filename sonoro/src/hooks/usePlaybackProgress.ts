import { useRef, useEffect } from 'react';

const KEY_PREFIX   = 'sonoro_progress_';
const LAST_PLAYED  = 'sonoro_last_played';
const SAVE_INTERVAL_MS = 5_000;
const COMPLETED_THRESHOLD = 0.98;

// Current authenticated user ID — set by auth-aware components on login/logout.
// When set, all keys are namespaced to prevent cross-account state leakage.
let _currentUserId: string | null = null;

export function setCurrentUserId(id: string | null): void {
  _currentUserId = id;
}

export interface PlaybackProgress {
  documentId:    string;
  documentTitle: string;
  chapterIdx:    number;
  chapterTitle:  string;
  currentTime:   number;
  totalDuration: number;
  timestamp:     number;
  // Optional — added in Phase 5E, backward-compatible
  playbackSpeed?: number;
  progressPct?:   number;
  completed?:     boolean;
}

// ── Key helpers ───────────────────────────────────────────────────────────────
// When a userId is active, keys are namespaced: "sonoro_progress_{userId}*{docId}"
// When no userId (anonymous / legacy), fall back to unscoped keys for backward compat.

function _progressKey(documentId: string): string {
  return _currentUserId
    ? `${KEY_PREFIX}${_currentUserId}*${documentId}`
    : `${KEY_PREFIX}${documentId}`;
}

function _lastPlayedKey(): string {
  return _currentUserId
    ? `${LAST_PLAYED}*${_currentUserId}`
    : LAST_PLAYED;
}

function _userKeyPrefix(): string {
  return _currentUserId
    ? `${KEY_PREFIX}${_currentUserId}*`
    : KEY_PREFIX;
}

// ── Public API ────────────────────────────────────────────────────────────────

export function saveProgress(p: PlaybackProgress): void {
  try {
    const progressPct = p.totalDuration > 0
      ? Math.round((p.currentTime / p.totalDuration) * 100)
      : (p.progressPct ?? 0);
    const completed = p.completed ?? progressPct / 100 >= COMPLETED_THRESHOLD;
    const enriched: PlaybackProgress = { ...p, progressPct, completed };
    localStorage.setItem(_progressKey(p.documentId), JSON.stringify(enriched));
    localStorage.setItem(_lastPlayedKey(), p.documentId);
  } catch { /* storage unavailable */ }
}

export function loadProgress(documentId: string): PlaybackProgress | null {
  try {
    const raw = localStorage.getItem(_progressKey(documentId));
    return raw ? (JSON.parse(raw) as PlaybackProgress) : null;
  } catch {
    return null;
  }
}

export function loadLastPlayed(): PlaybackProgress | null {
  try {
    const id = localStorage.getItem(_lastPlayedKey());
    return id ? loadProgress(id) : null;
  } catch {
    return null;
  }
}

export function getAllProgress(): PlaybackProgress[] {
  const results: PlaybackProgress[] = [];
  const prefix = _userKeyPrefix();
  try {
    for (let i = 0; i < localStorage.length; i++) {
      const key = localStorage.key(i);
      if (key?.startsWith(prefix)) {
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
    localStorage.removeItem(_progressKey(documentId));
    if (localStorage.getItem(_lastPlayedKey()) === documentId) {
      localStorage.removeItem(_lastPlayedKey());
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
  playbackSpeed  = 1,
) {
  const lastSave = useRef(0);

  useEffect(() => {
    if (!isPlaying || totalDuration <= 0 || currentTime < 3) return;
    const now = Date.now();
    if (now - lastSave.current < SAVE_INTERVAL_MS) return;
    lastSave.current = now;
    saveProgress({
      documentId, documentTitle, chapterIdx, chapterTitle,
      currentTime, totalDuration, timestamp: now, playbackSpeed,
    });
    console.log('[SONORO] continue_listening_saved');
  }); // intentionally no deps — runs every render, throttled by ref
}
