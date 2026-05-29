/**
 * Sonoro Analytics Client
 * =======================
 * Lightweight fire-and-forget behavioral event tracking.
 *
 * Design:
 *   - All calls are non-blocking (void / best-effort Promises)
 *   - Errors are silently swallowed — analytics must never break the UX
 *   - No third-party SaaS dependencies
 *   - Auth is handled by the shared `api` Axios instance (JWT cookie injection)
 *   - No PII is sent — user_id is resolved server-side from the JWT
 */

import api from '@/lib/api/client';

// ── Event type registry ───────────────────────────────────────────────────────

export type AnalyticsEventType =
  | 'audiobook_started'
  | 'audiobook_completed'
  | 'playback_paused'
  | 'playback_resumed'
  | 'chapter_changed'
  | 'voice_preview_played'
  | 'paywall_viewed'
  | 'paywall_dismissed'
  | 'upgrade_clicked'
  | 'continue_listening_opened'
  | 'player_opened'
  | 'audiobook_downloaded'
  | 'processing_started'
  | 'processing_completed'
  | 'processing_stage_changed'
  | 'mini_player_opened'
  | 'playback_resumed';

export type SessionSource = 'direct' | 'continue_listening' | 'autoplay';

// ── Core primitives ───────────────────────────────────────────────────────────

/**
 * Fire a behavioral event to the analytics DB endpoint.
 * Non-blocking — caller does not need to await this.
 */
export function track(
  eventType: AnalyticsEventType,
  properties: Record<string, unknown> = {},
): void {
  try {
    void api
      .post('/analytics/events', { event_type: eventType, properties })
      .catch(() => {});
  } catch {
    // Silent — analytics must never surface errors
  }
}

// ── Playback session management ───────────────────────────────────────────────

/**
 * Start a playback session.
 * Returns the server-issued session_id, or null if the call fails.
 * The session_id must be passed to `endPlaybackSession` when the user stops.
 */
export async function startPlaybackSession(
  documentId: string,
  source: SessionSource = 'direct',
  resumedFromCL = false,
): Promise<string | null> {
  try {
    const { data } = await api.post<{ session_id: string | null }>(
      '/analytics/sessions',
      {
        document_id: documentId,
        source,
        resumed_from_continue_listening: resumedFromCL,
      },
    );
    return data.session_id ?? null;
  } catch {
    return null;
  }
}

/**
 * End a playback session with final listening metrics.
 * Safe to call with a null session_id (becomes a no-op).
 */
export async function endPlaybackSession(
  sessionId: string | null,
  listenedSeconds: number,
  completionPct: number,
  speed: number,
  chaptersVisited: number[],
): Promise<void> {
  if (!sessionId) return;
  try {
    await api.patch(`/analytics/sessions/${sessionId}`, {
      listened_seconds: Math.round(listenedSeconds),
      completion_percentage: Math.min(100, Math.max(0, completionPct)),
      playback_speed: speed,
      chapters_visited: chaptersVisited,
    });
  } catch {
    // Silent
  }
}
