'use client';

/**
 * useProcessingProgress
 * =====================
 * Polls the backend for job progress and interpolates smoothly between
 * backend anchors using requestAnimationFrame so the bar never jumps.
 *
 * Rules:
 *  - Progress is monotonic (never goes backward).
 *  - Progress never reaches 100 until backend confirms completed.
 *  - Each stage has a cap; the bar "breathes" toward the cap when idle.
 *  - Interpolation speed: ~3% per second toward the target value.
 */

import { useEffect, useRef, useState, useCallback } from 'react';
import { getProcessingJob } from '@/lib/document-service';
import type { ProcessingJob } from '@/lib/document-service';

// Stage caps — the bar never exceeds these until the next stage is reached.
const STAGE_CAPS: Record<string, number> = {
  queued:           8,
  analyzing:        20,
  detecting_chapters: 28,
  chapter_detection:  28,
  generating_audio: 88,
  tts_generation:   88,
  final_assembly:   96,
  finalizing:       96,
  upload_finalize:  99,
  completed:        100,
  failed:           0,
  cancelled:        0,
};

function capForJob(job: ProcessingJob): number {
  if (job.status === 'completed') return 100;
  if (job.status === 'failed' || job.status === 'cancelled') return 0;

  const stageKey = job.current_stage ?? job.stage ?? job.status;
  const cap = STAGE_CAPS[stageKey ?? ''];
  if (cap !== undefined) return cap;

  // Fallback: use backend progress_percentage capped at 99
  return Math.min(job.progress ?? 0, 99);
}

function targetForJob(job: ProcessingJob): number {
  if (job.status === 'completed') return 100;
  if (job.status === 'failed' || job.status === 'cancelled') return 0;

  // For TTS generation use chunk-level progress for a precise anchor
  if (
    (job.current_stage === 'tts_generation' || job.stage === 'generating_audio') &&
    job.total_chunks > 0
  ) {
    return Math.min(28 + (job.completed_chunks / job.total_chunks) * 60, 88);
  }

  const raw = job.progress ?? 0;
  const cap = capForJob(job);
  return Math.min(raw, cap);
}

export interface ProgressState {
  displayProgress: number; // 0–100, smooth interpolated value
  job: ProcessingJob | null;
  isPolling: boolean;
  isStalled: boolean;     // true when no backend update for >30s
}

const POLL_INTERVAL_MS = 2500;
const INTERP_SPEED = 3;         // % per second toward target
const STALL_THRESHOLD_MS = 30_000;
const IDLE_BREATHE_RATE = 0.15; // % per second while stalled under cap

export function useProcessingProgress(
  documentId: string | null,
  enabled: boolean,
): ProgressState {
  const [displayProgress, setDisplayProgress] = useState(0);
  const [job, setJob] = useState<ProcessingJob | null>(null);
  const [isStalled, setIsStalled] = useState(false);

  const targetRef = useRef(0);
  const capRef = useRef(99);
  const displayRef = useRef(0);
  const lastUpdateRef = useRef(Date.now());
  const rafRef = useRef<number | null>(null);
  const lastFrameRef = useRef<number | null>(null);
  const isTerminalRef = useRef(false);

  // rAF interpolation loop
  const animate = useCallback((now: number) => {
    const deltaMs = lastFrameRef.current !== null ? now - lastFrameRef.current : 16;
    lastFrameRef.current = now;
    const deltaS = deltaMs / 1000;

    const current = displayRef.current;
    const target = targetRef.current;
    const cap = capRef.current;

    let next: number;

    if (isTerminalRef.current) {
      // Snap to final value
      next = target;
    } else {
      const stalled = Date.now() - lastUpdateRef.current > STALL_THRESHOLD_MS;
      setIsStalled(stalled);

      if (Math.abs(current - target) < 0.05) {
        // At target — if stalled and below cap, breathe slowly forward
        if (stalled && current < cap - 0.1) {
          next = Math.min(current + IDLE_BREATHE_RATE * deltaS, cap - 0.1);
        } else {
          next = current;
        }
      } else if (target > current) {
        // Ease toward target
        next = Math.min(current + INTERP_SPEED * deltaS, target);
      } else {
        // Backend went backward — hold current (monotonic)
        next = current;
      }
    }

    if (next !== current) {
      displayRef.current = next;
      setDisplayProgress(Math.round(next * 10) / 10);
    }

    if (!isTerminalRef.current) {
      rafRef.current = requestAnimationFrame(animate);
    }
  }, []);

  // Start / stop rAF loop
  useEffect(() => {
    if (!enabled || !documentId) return;

    lastFrameRef.current = null;
    rafRef.current = requestAnimationFrame(animate);

    return () => {
      if (rafRef.current !== null) {
        cancelAnimationFrame(rafRef.current);
        rafRef.current = null;
      }
    };
  }, [enabled, documentId, animate]);

  // Poll backend
  useEffect(() => {
    if (!enabled || !documentId) return;

    let cancelled = false;

    async function poll() {
      if (cancelled) return;
      try {
        const fetched = await getProcessingJob(documentId!);
        if (cancelled || !fetched) return;

        setJob(fetched);
        lastUpdateRef.current = Date.now();

        const newTarget = targetForJob(fetched);
        const newCap = capForJob(fetched);
        capRef.current = newCap;

        // Monotonic: never lower the target
        if (newTarget > targetRef.current) {
          targetRef.current = newTarget;
        }

        const terminal = fetched.status === 'completed' || fetched.status === 'failed' || fetched.status === 'cancelled';
        isTerminalRef.current = terminal;

        if (terminal) {
          targetRef.current = newTarget;
          return; // stop polling
        }
      } catch {
        // silently ignore — stall detection handles UI feedback
      }

      if (!cancelled) {
        setTimeout(poll, POLL_INTERVAL_MS);
      }
    }

    poll();

    return () => {
      cancelled = true;
    };
  }, [enabled, documentId]);

  const isPolling = enabled && !!documentId && !isTerminalRef.current;

  return { displayProgress, job, isPolling, isStalled };
}
