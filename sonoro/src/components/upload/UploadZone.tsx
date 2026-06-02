import { useState, useCallback, useEffect, useRef } from 'react';
import { track } from '@/lib/analytics';
import { useDropzone } from 'react-dropzone';
import {
  uploadDocument,
  startProcessing,
  getProcessingJob,
  getDocument,
  getChapters,
  getErrorMessage,
} from '@/lib/api/client';
import type { Chapter, ProcessingJob, PreflightResult } from '@/lib/api/types';
import { fmtFileSize, fmtDuration, fmtChars } from '@/lib/utils';
import { cn } from '@/lib/utils';
import VoicePicker from '@/components/upload/VoicePicker';

type Stage = 'idle' | 'uploading' | 'preflight' | 'processing' | 'ready' | 'error' | 'duplicate';
type ProcessStage = ProcessingJob['stage'];

// ── Narration styles ─────────────────────────────────────────────────────────

interface NarrationStyle {
  id:           string;
  label:        string;
  desc:         string;
  emoji:        string;
  voiceKeywords: string[];  // matched against voice display names (lowercase)
}

const NARRATION_STYLES: NarrationStyle[] = [
  { id: 'calm',          label: 'Calm',          desc: 'Peaceful and unhurried',        emoji: '🌿', voiceKeywords: ['rachel', 'bella', 'grace', 'lucia', 'freja'] },
  { id: 'storytelling',  label: 'Storytelling',  desc: 'Warm and expressive',           emoji: '📖', voiceKeywords: ['matilda', 'charlotte', 'emily', 'aria', 'rachel'] },
  { id: 'documentary',   label: 'Documentary',   desc: 'Assured and measured',          emoji: '🎬', voiceKeywords: ['charlie', 'ethan', 'liam', 'callum'] },
  { id: 'podcast',       label: 'Podcast',       desc: 'Conversational and engaging',   emoji: '🎙️', voiceKeywords: ['elli', 'sam', 'josh', 'river'] },
  { id: 'educational',   label: 'Educational',   desc: 'Clear and easy to follow',      emoji: '🎓', voiceKeywords: ['domi', 'will', 'river', 'grace'] },
];

// Given a style and available voices, return the best-matching voice_id (or null)
function bestVoiceForStyle(style: NarrationStyle, voices: { voice_id: string; display_name: string }[]): string | null {
  for (const keyword of style.voiceKeywords) {
    const match = voices.find(v => v.display_name.toLowerCase().includes(keyword));
    if (match) return match.voice_id;
  }
  return null;
}

interface DuplicateInfo {
  docId: string;
  message: string;
  canReprocess: boolean;
}

// ── Stage resolution ────────────────────────────────────────────────────────

// 5-step visual timeline (mobile-safe width)
const VISUAL_STEPS = ['Analyzing', 'Chapters', 'Generating', 'Mastering', 'Finalizing'];

// Map raw backend current_stage → visual step index (0–4)
function resolveVisualStep(raw: string, stage?: ProcessStage): number {
  const r = raw.toLowerCase();
  if (r === 'analyzing' || r === 'language_detection')                        return 0;
  if (r === 'chapter_detection' || r === 'detecting_chapters')                return 1;
  if (r.startsWith('tts') || r === 'preparing_narration' || r === 'generating_audio') return 2;
  if (r === 'final_assembly' || r === 'assembling')                          return 3;
  if (r === 'upload_finalize' || r === 'finalizing')                         return 4;
  // Fallback: mapped 4-step enum
  if (stage === 'analyzing')          return 0;
  if (stage === 'detecting_chapters') return 1;
  if (stage === 'generating_audio')   return 2;
  if (stage === 'finalizing')         return 3;
  return 0;
}

// Map raw stage + chunk info → display label + microcopy
function resolveMicrocopy(
  raw: string,
  stage?: ProcessStage,
  chunks?: { done: number; total: number } | null,
): { label: string; desc: string } {
  const r = raw.toLowerCase();
  // 1-based: "done" = completed chunks, so current = done + 1
  const chunkDesc =
    chunks && chunks.total > 0
      ? `Part ${chunks.done + 1} of ${chunks.total}`
      : 'Generating your narration';

  if (r === 'analyzing')           return { label: 'Analyzing document',    desc: 'Reading structure and extracting text' };
  if (r === 'language_detection')  return { label: 'Detecting language',    desc: 'Choosing the best narration voice' };
  if (r === 'chapter_detection')   return { label: 'Detecting chapters',    desc: 'Finding natural chapter breaks' };
  if (r === 'preparing_narration' || r === 'tts_prepare')
                                   return { label: 'Preparing narration',   desc: 'Setting up audio generation' };
  if (r.startsWith('tts') || r === 'generating_audio')
                                   return { label: 'Generating audiobook',  desc: chunkDesc };
  if (r === 'final_assembly' || r === 'assembling')
                                   return { label: 'Assembling audiobook',  desc: 'Assembling your audiobook...' };
  if (r === 'upload_finalize' || r === 'finalizing')
                                   return { label: 'Finalizing',            desc: 'Saving your audiobook to your library' };

  // Fallback to 4-step enum
  if (stage === 'analyzing')          return { label: 'Analyzing document',   desc: 'Reading structure and extracting text' };
  if (stage === 'detecting_chapters') return { label: 'Detecting chapters',   desc: 'Finding natural chapter breaks' };
  if (stage === 'generating_audio')   return { label: 'Generating audiobook', desc: chunkDesc };
  if (stage === 'finalizing')         return { label: 'Assembling audiobook', desc: 'Assembling your audiobook...' };

  return { label: 'Processing', desc: 'Working on your audiobook…' };
}

// Map a seconds estimate to a confident, non-precise ETA string
export function formatEtaConfident(secs: number): string {
  if (secs <= 90)  return 'Usually under 2 minutes';
  if (secs <= 300) return 'Usually 2–5 minutes';
  if (secs <= 600) return 'Usually 5–10 minutes';
  return 'Usually over 10 minutes';
}

// Weighted progress: maps stage + chunk data to a 0–100 display percentage.
//   Analyzing 0–14 · Chapter detection 15–24 · Generation 25–85 · Assembly 86–96 · Finalize 97+
export function weightedProgress(
  rawStage: string,
  stage: ProcessStage,
  backendPct: number,
  chunks: { done: number; total: number } | null,
): number {
  const r = (rawStage || '').toLowerCase();
  if (r === 'upload_finalize' || r === 'finalizing') return 97;
  if (r === 'final_assembly'  || r === 'assembling' || stage === 'finalizing') return 90;
  if (r.startsWith('tts') || r === 'generating_audio' || stage === 'generating_audio') {
    if (chunks && chunks.total > 0) return Math.round(25 + (chunks.done / chunks.total) * 60);
    return 25;
  }
  if (r === 'chapter_detection' || r === 'detecting_chapters' || stage === 'detecting_chapters') return 20;
  return Math.min(14, Math.max(0, backendPct));
}

// Encouraging status copy based on weighted progress thresholds
export function stageThresholdMessage(weightedPct: number): string {
  if (weightedPct < 30) return 'Preparing your audiobook';
  if (weightedPct < 60) return 'Generating audio';
  if (weightedPct < 85) return 'More than halfway done';
  if (weightedPct < 95) return 'Assembling audiobook';
  return 'Final touches';
}

// Map raw error strings to friendly user copy
export function mapErrorMessage(raw: string): string {
  const r = raw.toLowerCase();
  if (r.includes('quota') || r.includes('limit exceeded') || r.includes('character limit') || r.includes('chars_remaining'))
    return 'Your plan quota has been reached. Upgrade your plan or try a smaller PDF.';
  if (r.includes('not authenticated') || r.includes('not authorized') || r.includes('401') || r.includes('session expired'))
    return 'Your session expired. Please refresh the page and sign in again.';
  if (r.includes('unsupported') || r.includes('invalid pdf') || r.includes('not a valid') || r.includes('corrupted'))
    return "This doesn't appear to be a valid PDF. Please try a different file.";
  if (r.includes('too large') || r.includes('file size') || r.includes('max size') || r.includes('100 mb'))
    return 'This file is too large. Please use a PDF under 100 MB.';
  if (r.includes('duplicate') || r.includes('already uploaded'))
    return 'This PDF was already uploaded. See your library for the existing audiobook.';
  if (r.includes('tts') || r.includes('audio generation') || r.includes('elevenlabs') || r.includes('voice'))
    return 'Audio generation failed. Please try again — if the problem persists, contact support.';
  if (r.includes('processing failed') || r.includes('celery') || r.includes('task'))
    return 'Audiobook generation failed. Please try again.';
  return raw;
}

// ── Micro progress indicator ─────────────────────────────────────────────────

function MicroProgress({ done, total }: { done: number; total: number }) {
  if (total <= 0) return null;
  type Item = { type: 'done' | 'active' | 'pending'; n: number };
  const items: Item[] = [];
  if (done > 0)          items.push({ type: 'done',    n: done });
  if (done < total)      items.push({ type: 'active',  n: done + 1 });
  if (done + 1 < total)  items.push({ type: 'pending', n: done + 2 });
  return (
    <div className="mt-3 mb-1 space-y-1 text-left max-w-[180px] mx-auto" aria-label="Chapter progress">
      {items.map(({ type, n }) => (
        <div key={n} className="flex items-center gap-2">
          {type === 'done' && (
            <svg className="w-3.5 h-3.5 text-emerald-500 shrink-0" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="2.5" aria-hidden="true">
              <path d="M2.5 7l3 3 6-6" strokeLinecap="round" strokeLinejoin="round"/>
            </svg>
          )}
          {type === 'active' && (
            <div className="w-3.5 h-3.5 rounded-full bg-sonoro-amber animate-pulse-slow shrink-0" aria-hidden="true" />
          )}
          {type === 'pending' && (
            <div className="w-3.5 h-3.5 rounded-full border-2 border-sonoro-border shrink-0" aria-hidden="true" />
          )}
          <span className={cn(
            'text-xs leading-none',
            type === 'done'    ? 'text-sonoro-500'              :
            type === 'active'  ? 'text-sonoro-900 font-medium'  :
                                 'text-sonoro-400',
          )}>
            {type === 'done'   ? `Part ${n} complete`   :
             type === 'active' ? `Generating part ${n}` :
                                 `Part ${n} pending`}
          </span>
        </div>
      ))}
    </div>
  );
}

// ── Visual constants ─────────────────────────────────────────────────────────

// Deterministic heights — no Math.random() to avoid SSR/client mismatch
const WAVE_H = [38, 72, 54, 91, 63, 48, 85, 57, 76, 44, 88, 62, 71, 39, 80];
const WAVE_D = [0, 0.12, 0.24, 0.06, 0.18, 0.30, 0.09, 0.21, 0.03, 0.15, 0.27, 0.08, 0.20, 0.04, 0.16];

// ── Component ────────────────────────────────────────────────────────────────

export default function UploadZone() {
  const [stage, setStage]                 = useState<Stage>('idle');
  const [uploadPct, setUploadPct]         = useState(0);
  const [file, setFile]                   = useState<File | null>(null);
  const [error, setError]                 = useState<string | null>(null);
  const [docId, setDocId]                 = useState<string | null>(null);
  const [preflight, setPreflight]         = useState<PreflightResult | null>(null);
  const [selectedVoice, setSelectedVoice] = useState<string>('');
  const [selectedStyle, setSelectedStyle] = useState<string | null>(null);
  const [processStage, setProcessStage]   = useState<ProcessStage>(undefined);
  const [rawStage, setRawStage]           = useState<string>('');
  const [processPct, setProcessPct]       = useState(0);
  const [chunkProgress, setChunkProgress] = useState<{ done: number; total: number } | null>(null);
  const [estimatedSecs, setEstimatedSecs] = useState<number | null>(null);
  const [chapters, setChapters]           = useState<Chapter[]>([]);
  const [audiobookUrl, setAudiobookUrl]   = useState<string | null>(null);
  const [duplicate, setDuplicate]         = useState<DuplicateInfo | null>(null);
  const [startingConversion, setStartingConversion]   = useState(false);
  const [stuckMessage, setStuckMessage]               = useState<string | null>(null);
  const [showingCompletion, setShowingCompletion]     = useState(false);
  const [failedChunks, setFailedChunks]               = useState<{ done: number; total: number } | null>(null);
  // Smooth display percentage — interpolated toward the backend-confirmed target
  const [displayPct, setDisplayPct]                   = useState(0);
  const targetPctRef    = useRef(0);
  const displayPctRef   = useRef(0);
  const rafRef          = useRef<number | null>(null);
  const pollRef         = useRef<ReturnType<typeof setInterval> | null>(null);
  const lastProgressRef = useRef<{ pct: number; time: number }>({ pct: -1, time: Date.now() });
  const prevStageRef    = useRef<string>('');

  // ── Analytics ──────────────────────────────────────────────────────────────

  const paywallVisible = stage === 'preflight' && !!preflight?.quota_exceeded;
  useEffect(() => {
    if (!paywallVisible || !preflight) return;
    track('paywall_viewed', {
      plan:            preflight.plan_display_name,
      chars_required:  preflight.estimated_characters,
      chars_limit:     preflight.chars_limit,
    });
  }, [paywallVisible]); // eslint-disable-line react-hooks/exhaustive-deps

  // ── Polling ────────────────────────────────────────────────────────────────

  useEffect(() => {
    if (stage !== 'processing' || !docId) return;

    async function poll() {
      const job: ProcessingJob | null = await getProcessingJob(docId!);
      if (!job) return;

      if (job.stage)         setProcessStage(job.stage);
      if (job.current_stage) setRawStage(job.current_stage);
      // Never go backward — clamp to the highest seen value
      const newPct = Math.max(0, job.progress ?? 0);
      setProcessPct(prev => {
        const next = Math.max(prev, newPct);
        if (next !== lastProgressRef.current.pct) {
          lastProgressRef.current = { pct: next, time: Date.now() };
          setStuckMessage(null);
        }
        return next;
      });

      // Update interpolation target (weighted, monotonic)
      const newStageRaw = job.current_stage ?? '';
      const chks = job.total_chunks && job.total_chunks > 0
        ? { done: job.completed_chunks ?? 0, total: job.total_chunks }
        : null;
      const newWeighted = weightedProgress(newStageRaw, job.stage, newPct, chks);
      targetPctRef.current = Math.max(targetPctRef.current, newWeighted);

      if (job.total_chunks && job.total_chunks > 0) {
        setChunkProgress({ done: job.completed_chunks ?? 0, total: job.total_chunks });
      }
      if (job.estimated_seconds_remaining != null) {
        setEstimatedSecs(job.estimated_seconds_remaining);
      }

      // Analytics: fire processing_stage_changed when the pipeline stage advances
      const newStage = job.current_stage ?? '';
      if (newStage && newStage !== prevStageRef.current) {
        prevStageRef.current = newStage;
        const chks = job.total_chunks ? { done: job.completed_chunks ?? 0, total: job.total_chunks } : null;
        track('processing_stage_changed', {
          stage:            newStage,
          completed_chunks: job.completed_chunks ?? 0,
          total_chunks:     job.total_chunks ?? 0,
          percentage:       weightedProgress(newStage, job.stage, job.progress ?? 0, chks),
        });
      }

      if (job.status === 'completed') {
        clearInterval(pollRef.current!);
        track('processing_completed', {
          completed_chunks: job.completed_chunks ?? 0,
          total_chunks:     job.total_chunks ?? 0,
        });
        setShowingCompletion(true);
        try {
          const [rawChapters, doc] = await Promise.all([
            getChapters(docId!),
            getDocument(docId!),
          ]);
          setChapters(Array.isArray(rawChapters) ? rawChapters : (rawChapters?.chapters ?? []));
          if (doc?.audiobook_url) setAudiobookUrl(doc.audiobook_url);
        } catch { /* non-fatal — chapter list just stays empty */ }
        setTimeout(() => {
          setShowingCompletion(false);
          setStage('ready');
        }, 1_500);
      } else if (job.status === 'failed') {
        clearInterval(pollRef.current!);
        const doneF  = job.completed_chunks ?? 0;
        const totalF = job.total_chunks ?? 0;
        if (doneF > 0 && totalF > 0) {
          setFailedChunks({ done: doneF, total: totalF });
          setError("We couldn't finish this audiobook.");
        } else {
          setError(mapErrorMessage(job.error_message ?? 'Processing failed. Please try again.'));
        }
        setStage('error');
      }
    }

    poll();
    pollRef.current = setInterval(poll, 2500);
    return () => { if (pollRef.current) clearInterval(pollRef.current); };
  }, [stage, docId]);

  // Stuck-job detection: show a reassurance message if progress stalls > 60 s
  useEffect(() => {
    if (stage !== 'processing') { setStuckMessage(null); return; }
    const id = setInterval(() => {
      const { pct, time } = lastProgressRef.current;
      if (pct > 0 && pct < 95 && Date.now() - time > 60_000) {
        setStuckMessage(
          'This part is taking longer than usual. Your audiobook is still being generated.'
        );
      }
    }, 5_000);
    return () => clearInterval(id);
  }, [stage]);

  // Smooth interpolation: animate displayPct toward the backend-confirmed target.
  // Uses rAF for fluid 60fps updates; progress is strictly monotonic (never goes back).
  // Speed: ~1.5 pp/frame at 60fps = ~90pp/sec — reaches a 60pp jump in <1 s.
  useEffect(() => {
    if (stage !== 'processing') {
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
      return;
    }

    function tick() {
      const target  = targetPctRef.current;
      const current = displayPctRef.current;
      // Clamp advance: at most 1.5pp/frame (≈90pp/s) so it looks animated, not instant
      const delta   = Math.min(target - current, 1.5);
      if (delta > 0.05) {
        const next = current + delta;
        displayPctRef.current = next;
        setDisplayPct(Math.round(next * 10) / 10);
      }
      rafRef.current = requestAnimationFrame(tick);
    }
    rafRef.current = requestAnimationFrame(tick);
    return () => { if (rafRef.current) cancelAnimationFrame(rafRef.current); };
  }, [stage]);

  // ── Upload handler ─────────────────────────────────────────────────────────

  const handleFiles = useCallback(async (accepted: File[], forceReprocess = false) => {
    const f = accepted[0];
    if (!f) return;
    setFile(f);
    setError(null);
    setDuplicate(null);
    setPreflight(null);
    setSelectedVoice('');
    setAudiobookUrl(null);
    setStage('uploading');
    setUploadPct(0);
    try {
      const result = await uploadDocument(f, setUploadPct, forceReprocess);
      if (!result?.id) throw new Error('Upload succeeded but the server returned an invalid response.');
      setDocId(result.id);

      if (result.is_duplicate) {
        const activeStatuses = ['queued', 'processing', 'assembling', 'finalizing'];
        if (activeStatuses.includes(result.processing_status)) {
          setStage('processing');
        } else {
          setDuplicate({
            docId: result.id,
            message: result.duplicate_message ?? 'You already uploaded this PDF.',
            canReprocess: result.can_reprocess,
          });
          setStage('duplicate');
        }
      } else if (result.preflight) {
        setPreflight(result.preflight);
        setSelectedVoice(result.preflight.voice_id);
        setStage('preflight');
      } else {
        setStage('processing');
      }
    } catch (err) {
      setError(mapErrorMessage(getErrorMessage(err)));
      setStage('error');
    }
  }, []);

  // Dropzone-compatible wrapper — signature matches react-dropzone's expected type
  const onDrop = useCallback((accepted: File[]) => handleFiles(accepted), [handleFiles]);

  const { getRootProps, getInputProps, isDragActive, isDragReject } = useDropzone({
    onDrop,
    accept: { 'application/pdf': ['.pdf'] },
    maxFiles: 1,
    maxSize: 100 * 1024 * 1024,
    disabled: stage === 'uploading' || stage === 'processing' || stage === 'preflight',
  });

  function reset() {
    if (pollRef.current) clearInterval(pollRef.current);
    setStage('idle');
    setFile(null);
    setUploadPct(0);
    setError(null);
    setDocId(null);
    setPreflight(null);
    setSelectedVoice('');
    setSelectedStyle(null);
    setProcessStage(undefined);
    setRawStage('');
    setProcessPct(0);
    setChunkProgress(null);
    setEstimatedSecs(null);
    setChapters([]);
    setAudiobookUrl(null);
    setDuplicate(null);
    setStartingConversion(false);
    setStuckMessage(null);
    setShowingCompletion(false);
    setFailedChunks(null);
    lastProgressRef.current = { pct: -1, time: Date.now() };
    prevStageRef.current    = '';
    targetPctRef.current    = 0;
    displayPctRef.current   = 0;
    setDisplayPct(0);
  }

  // ── Preflight ──────────────────────────────────────────────────────────────

  if (stage === 'preflight' && preflight && docId) {
    const durSecs  = preflight.estimated_duration_seconds;
    const durH     = Math.floor(durSecs / 3600);
    const durM     = Math.floor((durSecs % 3600) / 60);
    const durLabel = durH > 0 ? `${durH}h ${durM}m` : `${durM}m`;

    const procMins  = preflight.estimated_processing_minutes;
    const procLabel =
      procMins < 1    ? 'Under 1 min' :
      procMins < 60   ? `~${Math.ceil(procMins)} min` :
                        `~${Math.ceil(procMins / 60)}h`;

    const pctUsed  = preflight.chars_limit > 0
      ? Math.min(100, Math.round((preflight.chars_used / preflight.chars_limit) * 100))
      : 0;
    const pctAfter = preflight.chars_limit > 0
      ? Math.min(100, Math.round(((preflight.chars_used + preflight.estimated_characters) / preflight.chars_limit) * 100))
      : 0;

    async function handleStartConversion() {
      if (!docId) return;
      setStartingConversion(true);
      try {
        console.log('[SONORO] narration_style_selected', selectedStyle ?? 'default');
        await startProcessing(
          docId,
          selectedVoice || undefined,
          selectedStyle || undefined,
        );
        track('processing_started', {
          voice_id:        selectedVoice || null,
          narration_style: selectedStyle || null,
        });
        setStage('processing');
      } catch (err) {
        setError(mapErrorMessage(getErrorMessage(err)));
        setStage('error');
      } finally {
        setStartingConversion(false);
      }
    }

    // ── Premium paywall card ─────────────────────────────────────────────────
    if (preflight.quota_exceeded) {
      return (
        <div
          className="card-base overflow-hidden animate-scale-in"
          role="alert"
          aria-label="Plan limit reached"
        >
          <div
            className="h-1 w-full"
            style={{ background: 'linear-gradient(90deg, #EF4444, #F97316, #FBBF24)' }}
            aria-hidden="true"
          />
          <div className="px-8 py-10">
            {/* Header */}
            <div className="flex items-start gap-4 mb-8">
              <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-red-50 border border-red-100 shrink-0">
                <svg className="w-5 h-5 text-red-500" viewBox="0 0 20 20" fill="currentColor" aria-hidden="true">
                  <path fillRule="evenodd" d="M10 1a4.5 4.5 0 00-4.5 4.5V9H5a2 2 0 00-2 2v6a2 2 0 002 2h10a2 2 0 002-2v-6a2 2 0 00-2-2h-.5V5.5A4.5 4.5 0 0010 1zm3 8V5.5a3 3 0 10-6 0V9h6z" clipRule="evenodd" />
                </svg>
              </div>
              <div>
                <p className="text-base font-bold text-sonoro-900 leading-tight">
                  This audiobook is larger than your {preflight.plan_display_name} plan
                </p>
                <p className="text-sm text-sonoro-muted mt-1">
                  Upgrade to convert longer documents and unlock higher limits.
                </p>
              </div>
            </div>

            {/* Quota stats */}
            {(() => {
              const CHARS_PER_HR = 50_000;
              const limitHrs = preflight.chars_limit / CHARS_PER_HR;
              const limitHrsLabel = limitHrs >= 1
                ? `~${Math.round(limitHrs)}h audio/mo`
                : `~${Math.round(limitHrs * 60)}m audio/mo`;
              return (
                <div className="grid grid-cols-3 gap-3 mb-8">
                  <div className="rounded-xl bg-red-50 border border-red-100 px-4 py-3 text-center">
                    <p className="text-[10px] font-semibold text-red-400 uppercase tracking-wider mb-1.5">Required</p>
                    <p className="text-sm font-bold text-red-700">{fmtChars(preflight.estimated_characters)}</p>
                    <p className="text-[10px] text-red-400 mt-0.5">characters</p>
                  </div>
                  <div className="rounded-xl bg-sonoro-surface border border-sonoro-border/60 px-4 py-3 text-center">
                    <p className="text-[10px] font-semibold text-sonoro-400 uppercase tracking-wider mb-1.5">Plan limit</p>
                    <p className="text-sm font-bold text-sonoro-700">{fmtChars(preflight.chars_limit)}</p>
                    <p className="text-[10px] text-sonoro-400 mt-0.5">per month</p>
                    <p className="text-[10px] text-sonoro-300 mt-0.5">{limitHrsLabel}</p>
                  </div>
                  <div className="rounded-xl bg-sonoro-surface border border-sonoro-border/60 px-4 py-3 text-center">
                    <p className="text-[10px] font-semibold text-sonoro-400 uppercase tracking-wider mb-1.5">Length</p>
                    <p className="text-sm font-bold text-sonoro-700">{durLabel}</p>
                    <p className="text-[10px] text-sonoro-400 mt-0.5">audiobook</p>
                  </div>
                </div>
              );
            })()}

            {/* CTAs */}
            <div className="flex flex-col sm:flex-row items-stretch sm:items-center gap-3">
              <a
                href="/dashboard/billing"
                onClick={() => track('upgrade_clicked', {
                  trigger:        'quota_exceeded',
                  plan:           preflight.plan_display_name,
                  chars_required: preflight.estimated_characters,
                })}
                className="btn-accent py-2.5 px-6 rounded-full text-sm flex items-center justify-center gap-2"
              >
                <svg className="w-4 h-4" viewBox="0 0 20 20" fill="currentColor" aria-hidden="true">
                  <path fillRule="evenodd" d="M10.868 2.884c-.321-.772-1.415-.772-1.736 0l-1.83 4.401-4.753.381c-.833.067-1.171 1.107-.536 1.651l3.62 3.102-1.106 4.637c-.194.813.691 1.456 1.405 1.02L10 15.591l4.069 2.485c.713.436 1.598-.207 1.404-1.02l-1.106-4.637 3.62-3.102c.635-.544.297-1.584-.536-1.65l-4.752-.382-1.831-4.401z" clipRule="evenodd" />
                </svg>
                Upgrade plan
              </a>
              <button onClick={reset} className="btn-outline py-2.5 px-6 rounded-full text-sm">
                Upload a smaller PDF
              </button>
            </div>
          </div>
        </div>
      );
    }

    // ── Normal preflight card ────────────────────────────────────────────────
    return (
      <div className="card-base overflow-hidden animate-scale-in">
        <div
          className="h-1 w-full"
          style={{ background: 'linear-gradient(90deg, #D97706, #F59E0B, #FBBF24)' }}
          aria-hidden="true"
        />
        <div className="px-8 py-8">
          {/* Header */}
          <div className="flex items-center gap-3 mb-6">
            <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-sonoro-amber-light border border-sonoro-amber/30 shrink-0" aria-hidden="true">
              <svg className="w-5 h-5 text-sonoro-amber-dark" viewBox="0 0 20 20" fill="currentColor">
                <path fillRule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7-4a1 1 0 11-2 0 1 1 0 012 0zM9 9a.75.75 0 000 1.5h.253a.25.25 0 01.244.304l-.459 2.066A1.75 1.75 0 0010.747 15H11a.75.75 0 000-1.5h-.253a.25.25 0 01-.244-.304l.459-2.066A1.75 1.75 0 009.253 9H9z" clipRule="evenodd"/>
              </svg>
            </div>
            <div className="min-w-0">
              <p className="text-base font-bold text-sonoro-900 leading-tight">Ready to convert</p>
              <p className="text-xs text-sonoro-muted truncate" title={file?.name}>{file?.name}</p>
            </div>
          </div>

          {/* Analysis grid — 2×2 (Voice moved to picker below) */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-5">
            <div className="rounded-xl bg-sonoro-surface border border-sonoro-border/60 px-4 py-3">
              <p className="text-[10px] font-semibold text-sonoro-400 uppercase tracking-wider mb-1">Language</p>
              <p className="text-sm font-semibold text-sonoro-900">{preflight.language_name}</p>
            </div>
            <div className="rounded-xl bg-sonoro-surface border border-sonoro-border/60 px-4 py-3">
              <p className="text-[10px] font-semibold text-sonoro-400 uppercase tracking-wider mb-1">Duration</p>
              <p className="text-sm font-semibold text-sonoro-900">{durLabel}</p>
            </div>
            <div className="rounded-xl bg-sonoro-surface border border-sonoro-border/60 px-4 py-3">
              <p className="text-[10px] font-semibold text-sonoro-400 uppercase tracking-wider mb-1">Characters</p>
              <p className="text-sm font-semibold text-sonoro-900">{fmtChars(preflight.estimated_characters)}</p>
            </div>
            <div className="rounded-xl bg-sonoro-surface border border-sonoro-border/60 px-4 py-3">
              <p className="text-[10px] font-semibold text-sonoro-400 uppercase tracking-wider mb-1">Est. time</p>
              <p className="text-sm font-semibold text-sonoro-900">{procLabel}</p>
            </div>
          </div>

          {/* Chapter preview */}
          <div className="mb-5 rounded-xl border border-sonoro-border/60 bg-sonoro-surface/50 px-4 py-3">
            <p className="text-[10px] font-semibold text-sonoro-400 uppercase tracking-wider mb-1.5">Chapter preview</p>
            <p className="text-sm text-sonoro-700">
              ~{preflight.estimated_chapters} chapter{preflight.estimated_chapters !== 1 ? 's' : ''} detected
              <span className="text-sonoro-400 ml-1">· exact count confirmed during processing</span>
            </p>
          </div>

          {/* Narration style presets */}
          <div className="mb-5">
            <div className="flex items-center justify-between mb-2.5">
              <p className="text-[10px] font-semibold text-sonoro-400 uppercase tracking-wider">
                Narration style
              </p>
              {selectedStyle && (
                <button
                  type="button"
                  onClick={() => {
                    setSelectedStyle(null);
                    setSelectedVoice(preflight.voice_id);
                  }}
                  className="text-[10px] text-sonoro-400 hover:text-sonoro-700 transition-colors"
                >
                  Clear
                </button>
              )}
            </div>
            <div className="flex flex-wrap gap-2">
              {NARRATION_STYLES.map(style => {
                const isActive = selectedStyle === style.id;
                return (
                  <button
                    key={style.id}
                    type="button"
                    onClick={() => {
                      const newStyle = isActive ? null : style.id;
                      setSelectedStyle(newStyle);
                      if (newStyle) {
                        const best = bestVoiceForStyle(style, preflight.available_voices);
                        if (best) setSelectedVoice(best);
                        console.log('[SONORO] narration_style_selected', newStyle);
                      } else {
                        setSelectedVoice(preflight.voice_id);
                      }
                    }}
                    className={cn(
                      'flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-medium border transition-all duration-150',
                      isActive
                        ? 'bg-sonoro-amber border-sonoro-amber text-sonoro-black shadow-amber'
                        : 'bg-white border-sonoro-border text-sonoro-600 hover:border-sonoro-amber/50 hover:text-sonoro-amber-dark',
                    )}
                    aria-pressed={isActive}
                    title={style.desc}
                  >
                    <span aria-hidden="true">{style.emoji}</span>
                    {style.label}
                  </button>
                );
              })}
            </div>
            {selectedStyle && (
              <p className="mt-2 text-[11px] text-sonoro-muted animate-fade-in">
                {NARRATION_STYLES.find(s => s.id === selectedStyle)?.desc} — voice selected for you
              </p>
            )}
          </div>

          {/* Voice picker */}
          <div className="mb-5">
            <VoicePicker
              voices={preflight.available_voices}
              defaultVoiceId={preflight.voice_id}
              language={preflight.language}
              languageName={preflight.language_name}
              selected={selectedVoice}
              onSelect={setSelectedVoice}
              narrationStyle={selectedStyle ?? undefined}
            />
            {selectedStyle && (
              <p className="mt-1.5 text-[11px] text-sonoro-400 animate-fade-in">
                Style adjusts pace and tone. Preview reflects your selection.
              </p>
            )}
          </div>

          {/* Quota bar */}
          <div className="mb-7">
            <div className="flex items-center justify-between mb-1.5">
              <p className="text-[10px] font-semibold text-sonoro-400 uppercase tracking-wider">Quota</p>
              <p className="text-[10px] text-sonoro-400">
                {fmtChars(preflight.chars_used)} / {fmtChars(preflight.chars_limit)} used
              </p>
            </div>
            <div className="relative h-2 rounded-full bg-sonoro-border overflow-hidden" role="progressbar" aria-valuenow={pctAfter} aria-valuemin={0} aria-valuemax={100}>
              <div
                className="absolute inset-y-0 left-0 rounded-l-full"
                style={{ width: `${pctUsed}%`, background: 'linear-gradient(90deg, #D97706, #F59E0B)' }}
              />
              <div
                className="absolute inset-y-0 bg-sonoro-amber/30"
                style={{ left: `${pctUsed}%`, width: `${pctAfter - pctUsed}%` }}
              />
            </div>
            <p className="mt-1.5 text-xs text-sonoro-400">
              {fmtChars(preflight.chars_remaining_after)} remaining after conversion
            </p>
          </div>

          {/* CTAs */}
          <div className="flex flex-col sm:flex-row items-stretch sm:items-center gap-3">
            <button
              onClick={handleStartConversion}
              disabled={startingConversion}
              className="btn-accent py-2.5 px-6 rounded-full text-sm flex items-center justify-center gap-2 disabled:opacity-60 disabled:cursor-not-allowed"
              aria-label="Start conversion"
            >
              {startingConversion ? (
                <>
                  <svg className="w-4 h-4 animate-spin" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/>
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z"/>
                  </svg>
                  Starting…
                </>
              ) : (
                <>
                  <svg className="w-4 h-4" viewBox="0 0 20 20" fill="currentColor" aria-hidden="true">
                    <path fillRule="evenodd" d="M2 10a8 8 0 1116 0 8 8 0 01-16 0zm6.39-2.908a.75.75 0 01.766.027l3.5 2.25a.75.75 0 010 1.262l-3.5 2.25A.75.75 0 018 12.25v-4.5a.75.75 0 01.39-.658z" clipRule="evenodd"/>
                  </svg>
                  Start conversion
                </>
              )}
            </button>
            <button onClick={reset} className="btn-outline py-2.5 px-6 rounded-full text-sm">
              Upload different file
            </button>
          </div>
        </div>
      </div>
    );
  }

  // ── Duplicate ──────────────────────────────────────────────────────────────

  if (stage === 'duplicate' && duplicate) {
    return (
      <div className="card-base overflow-hidden animate-scale-in">
        <div
          className="h-1 w-full"
          style={{ background: 'linear-gradient(90deg, #6366F1, #818CF8)' }}
          aria-hidden="true"
        />
        <div className="px-8 py-10">
          <div className="flex items-start gap-3 mb-6">
            <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-indigo-50 border border-indigo-100 shrink-0 mt-0.5" aria-hidden="true">
              <svg className="w-5 h-5 text-indigo-500" viewBox="0 0 20 20" fill="currentColor">
                <path d="M7 3.5A1.5 1.5 0 018.5 2h3.879a1.5 1.5 0 011.06.44l3.122 3.12A1.5 1.5 0 0117 6.622V12.5a1.5 1.5 0 01-1.5 1.5h-1v-3.379a3 3 0 00-.879-2.121L10.5 5.379A3 3 0 008.379 4.5H7v-1z"/>
                <path d="M4.5 6A1.5 1.5 0 003 7.5v9A1.5 1.5 0 004.5 18h7a1.5 1.5 0 001.5-1.5v-5.879a1.5 1.5 0 00-.44-1.06L9.44 6.439A1.5 1.5 0 008.378 6H4.5z"/>
              </svg>
            </div>
            <div className="min-w-0">
              <p className="text-base font-bold text-sonoro-900 leading-tight">Already converted</p>
              <p className="text-sm text-sonoro-muted mt-0.5">{duplicate.message}</p>
            </div>
          </div>

          <div className="flex flex-col sm:flex-row items-stretch sm:items-center gap-3">
            <a
              href={`/dashboard/documents/${duplicate.docId}`}
              className="btn-accent py-2.5 px-6 rounded-full text-sm flex items-center justify-center gap-2"
            >
              <svg className="w-4 h-4" viewBox="0 0 20 20" fill="currentColor" aria-hidden="true">
                <path fillRule="evenodd" d="M2 10a8 8 0 1116 0 8 8 0 01-16 0zm6.39-2.908a.75.75 0 01.766.027l3.5 2.25a.75.75 0 010 1.262l-3.5 2.25A.75.75 0 018 12.25v-4.5a.75.75 0 01.39-.658z" clipRule="evenodd"/>
              </svg>
              Open existing audiobook
            </a>
            {duplicate.canReprocess && file && (
              <button
                onClick={() => handleFiles([file], true)}
                className="btn-outline py-2.5 px-6 rounded-full text-sm"
              >
                Reprocess anyway
              </button>
            )}
            <button onClick={reset} className="btn-outline py-2.5 px-6 rounded-full text-sm">
              Upload different file
            </button>
          </div>
        </div>
      </div>
    );
  }

  // ── Ready ──────────────────────────────────────────────────────────────────

  if (stage === 'ready' && docId) {
    const totalSecs  = chapters.reduce((s, c) => s + (c.duration_seconds ?? 0), 0);
    const chapterStr = chapters.length > 0
      ? `${chapters.length} chapter${chapters.length !== 1 ? 's' : ''}`
      : null;
    const durStr     = totalSecs > 0 ? fmtDuration(totalSecs) : null;

    return (
      <div className="card-base overflow-hidden animate-scale-in">
        <div
          className="h-1 w-full"
          style={{ background: 'linear-gradient(90deg, #D97706, #F59E0B, #FBBF24)' }}
          aria-hidden="true"
        />
        <div className="px-8 py-10 relative">
          {/* Warm glow */}
          <div
            className="absolute inset-0 pointer-events-none"
            style={{ background: 'radial-gradient(ellipse at 50% 0%, rgba(254,243,199,0.5) 0%, transparent 55%)' }}
            aria-hidden="true"
          />
          <div className="relative">
            {/* Header */}
            <div className="flex items-start gap-3 mb-2">
              <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-emerald-50 border border-emerald-100 shrink-0 mt-0.5" aria-hidden="true">
                <svg className="w-5 h-5 text-emerald-500" viewBox="0 0 20 20" fill="currentColor">
                  <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.857-9.809a.75.75 0 00-1.214-.882l-3.483 4.79-1.88-1.88a.75.75 0 10-1.06 1.061l2.5 2.5a.75.75 0 001.137-.089l4-5.5z" clipRule="evenodd"/>
                </svg>
              </div>
              <div className="min-w-0">
                <p className="text-base font-bold text-sonoro-900 leading-tight">Your audiobook is ready</p>
                <p className="text-xs text-sonoro-muted truncate mt-0.5" title={file?.name}>{file?.name}</p>
                {(chapterStr || durStr) && (
                  <p className="text-xs text-sonoro-500 mt-1 font-medium">
                    {[chapterStr, durStr].filter(Boolean).join(' · ')}
                  </p>
                )}
              </div>
            </div>

            {/* Waveform */}
            <div className="flex items-end gap-0.5 h-10 mb-6 mt-5" aria-hidden="true">
              {WAVE_H.map((h, i) => (
                <div
                  key={i}
                  className="waveform-bar flex-1"
                  style={{ height: `${h}%`, animationDelay: `${WAVE_D[i]}s` }}
                />
              ))}
            </div>

            {/* Chapter list */}
            {chapters.length > 0 && (
              <div className="mb-6">
                <p className="text-xs font-semibold text-sonoro-500 uppercase tracking-wider mb-2.5">
                  {chapterStr}{durStr && ` · ${durStr}`}
                </p>
                <div className="space-y-1 max-h-44 overflow-y-auto pr-1">
                  {chapters.map((ch, i) => (
                    <div
                      key={ch.id}
                      className="flex items-center gap-3 rounded-lg px-3 py-2 bg-sonoro-surface border border-sonoro-border/50 hover:border-sonoro-amber/30 hover:bg-sonoro-amber-light/10 transition-all duration-150"
                    >
                      <span className="text-xs font-mono text-sonoro-400 w-4 shrink-0 tabular-nums">{i + 1}</span>
                      <span className="text-sm text-sonoro-800 flex-1 truncate">{ch.title}</span>
                      {ch.duration_seconds ? (
                        <span className="text-xs text-sonoro-400 shrink-0 tabular-nums">{fmtDuration(ch.duration_seconds)}</span>
                      ) : null}
                      {ch.status === 'completed' && (
                        <svg className="w-3.5 h-3.5 text-emerald-400 shrink-0" viewBox="0 0 16 16" fill="currentColor" aria-hidden="true">
                          <path fillRule="evenodd" d="M8 16A8 8 0 108 0a8 8 0 000 16zm3.78-9.72a.75.75 0 00-1.06-1.06L6.75 9.19 5.28 7.72a.75.75 0 00-1.06 1.06l2 2a.75.75 0 001.06 0l4.5-4.5z" clipRule="evenodd"/>
                        </svg>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* CTAs */}
            <div className="flex flex-col sm:flex-row items-stretch sm:items-center gap-3 flex-wrap">
              <a
                href={`/dashboard/documents/${docId}`}
                className="btn-accent py-2.5 px-6 rounded-full text-sm flex items-center justify-center gap-2"
              >
                <svg className="w-4 h-4" viewBox="0 0 20 20" fill="currentColor" aria-hidden="true">
                  <path fillRule="evenodd" d="M2 10a8 8 0 1116 0 8 8 0 01-16 0zm6.39-2.908a.75.75 0 01.766.027l3.5 2.25a.75.75 0 010 1.262l-3.5 2.25A.75.75 0 018 12.25v-4.5a.75.75 0 01.39-.658z" clipRule="evenodd"/>
                </svg>
                Listen now
              </a>
              {audiobookUrl && (
                <a
                  href={audiobookUrl}
                  download
                  target="_blank"
                  rel="noopener noreferrer"
                  className="btn-outline py-2.5 px-6 rounded-full text-sm flex items-center justify-center gap-2"
                  aria-label="Download audiobook file"
                >
                  <svg className="w-4 h-4" viewBox="0 0 20 20" fill="currentColor" aria-hidden="true">
                    <path fillRule="evenodd" d="M10 3a.75.75 0 01.75.75v8.19l2.22-2.22a.75.75 0 111.06 1.06l-3.5 3.5a.75.75 0 01-1.06 0l-3.5-3.5a.75.75 0 111.06-1.06l2.22 2.22V3.75A.75.75 0 0110 3zm-6.75 13.5a.75.75 0 000 1.5h13.5a.75.75 0 000-1.5H3.25z" clipRule="evenodd"/>
                  </svg>
                  Download
                </a>
              )}
              <button onClick={reset} className="btn-outline py-2.5 px-6 rounded-full text-sm">
                Upload another
              </button>
            </div>
          </div>
        </div>
      </div>
    );
  }

  // ── Processing ─────────────────────────────────────────────────────────────

  if (stage === 'processing') {
    const visualIdx    = resolveVisualStep(rawStage, processStage);
    const copy         = resolveMicrocopy(rawStage, processStage, chunkProgress);
    const weightedPct  = weightedProgress(rawStage, processStage, processPct, chunkProgress);
    // displayPct interpolates smoothly toward weightedPct — use for the visual bar
    const smoothPct    = Math.min(Math.max(displayPct, 0), 99); // cap at 99 until backend confirms done
    const thresholdMsg = stageThresholdMessage(smoothPct);
    const r            = (rawStage || '').toLowerCase();
    const isGenStage   = r.startsWith('tts') || r === 'generating_audio' || processStage === 'generating_audio';

    return (
      <div className="card-base px-8 py-10 text-center relative overflow-hidden">
        <div
          className="absolute inset-0 pointer-events-none"
          style={{ background: 'radial-gradient(ellipse at 50% 0%, rgba(245,158,11,0.08) 0%, transparent 60%)' }}
          aria-hidden="true"
        />
        <div className="relative">
          {/* Waveform */}
          <div className="flex items-end justify-center gap-1 h-12 mb-8" aria-hidden="true">
            {WAVE_H.map((h, i) => (
              <div
                key={i}
                className="waveform-bar w-1.5"
                style={{ height: `${h}%`, animationDelay: `${WAVE_D[i]}s` }}
              />
            ))}
          </div>

          {showingCompletion ? (
            <div className="py-2 animate-scale-in" role="status" aria-label="Audiobook ready">
              <div className="mx-auto mb-3 flex h-12 w-12 items-center justify-center rounded-full bg-emerald-50 border border-emerald-200">
                <svg className="w-6 h-6 text-emerald-500" viewBox="0 0 20 20" fill="currentColor" aria-hidden="true">
                  <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.857-9.809a.75.75 0 00-1.214-.882l-3.483 4.79-1.88-1.88a.75.75 0 10-1.06 1.061l2.5 2.5a.75.75 0 001.137-.089l4-5.5z" clipRule="evenodd"/>
                </svg>
              </div>
              <p className="text-base font-semibold text-emerald-700 mb-1">Audiobook ready</p>
              <p className="text-sm text-sonoro-muted">Loading your chapters…</p>
            </div>
          ) : (
            <>
              {/* Stage label + chunk progress */}
              <p className="text-base font-semibold text-sonoro-900 mb-1" aria-live="polite">
                {copy.label}
              </p>
              <p className="text-sm text-sonoro-muted mb-1">{copy.desc}</p>

              {/* Per-chapter micro progress indicator */}
              {isGenStage && chunkProgress && chunkProgress.total > 0 && (
                <MicroProgress done={chunkProgress.done} total={chunkProgress.total} />
              )}

              {/* Threshold-based encouragement message */}
              <p className="text-xs text-sonoro-400 mb-3">{thresholdMsg}</p>

              {/* Stuck-job reassurance */}
              {stuckMessage && (
                <p className="text-xs text-sonoro-400 mb-2 animate-fade-in" role="status">
                  {stuckMessage}
                </p>
              )}

              {/* Progress bar — smoothPct interpolates toward backend-confirmed weightedPct */}
              <div
                className="relative h-1.5 w-full max-w-xs mx-auto rounded-full bg-sonoro-border overflow-hidden mb-2"
                role="progressbar"
                aria-valuenow={weightedPct}
                aria-valuemin={0}
                aria-valuemax={100}
                aria-label={`${Math.round(smoothPct)}% complete`}
              >
                <div
                  className="absolute inset-y-0 left-0 rounded-full"
                  style={{
                    width: `${smoothPct}%`,
                    background: 'linear-gradient(90deg, #D97706, #F59E0B)',
                    transition: 'width 0.08s linear',
                  }}
                />
              </div>
              <p className="text-xs text-sonoro-400 tabular-nums mb-8">{Math.round(smoothPct)}%</p>
            </>
          )}

          {/* 5-step visual timeline — always visible */}
          <div className="flex items-start justify-center" role="list" aria-label="Processing stages">
            {VISUAL_STEPS.map((label, i) => {
              const done   = i < visualIdx;
              const active = i === visualIdx;
              return (
                <div key={label} className="flex items-center" role="listitem">
                  <div className="flex flex-col items-center gap-1.5 w-14 sm:w-16">
                    <div
                      className={cn(
                        'h-7 w-7 rounded-full flex items-center justify-center border-2 transition-all duration-500',
                        done   ? 'bg-sonoro-amber border-sonoro-amber'
                               : active ? 'border-sonoro-amber bg-sonoro-white animate-pulse-slow'
                               : 'border-sonoro-border bg-sonoro-white',
                      )}
                      aria-label={done ? `${label} — complete` : active ? `${label} — in progress` : label}
                    >
                      {done ? (
                        <svg className="w-3.5 h-3.5 text-white" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="2.5" aria-hidden="true">
                          <path d="M2.5 7l3 3 6-6" strokeLinecap="round" strokeLinejoin="round"/>
                        </svg>
                      ) : active ? (
                        <div className="h-2.5 w-2.5 rounded-full bg-sonoro-amber" aria-hidden="true" />
                      ) : null}
                    </div>
                    <p className={cn(
                      'text-[10px] leading-tight text-center',
                      done || active ? 'text-sonoro-700 font-medium' : 'text-sonoro-400',
                    )}>
                      {label}
                    </p>
                  </div>
                  {i < VISUAL_STEPS.length - 1 && (
                    <div
                      className={cn(
                        'h-0.5 w-6 sm:w-8 mb-5 transition-colors duration-500 shrink-0',
                        done ? 'bg-sonoro-amber' : 'bg-sonoro-border',
                      )}
                      aria-hidden="true"
                    />
                  )}
                </div>
              );
            })}
          </div>
        </div>
      </div>
    );
  }

  // ── Uploading ──────────────────────────────────────────────────────────────

  if (stage === 'uploading') {
    return (
      <div className="card-base px-8 py-10 text-center">
        <div className="flex items-end justify-center gap-1 h-10 mb-6" aria-hidden="true">
          {[40, 70, 100, 75, 55, 90, 65, 80, 45, 95].map((h, i) => (
            <div key={i} className="waveform-bar w-1.5" style={{ height: `${h}%`, animationDelay: `${i * 0.11}s` }} />
          ))}
        </div>
        <p className="text-sm font-semibold text-sonoro-900 mb-0.5 truncate max-w-xs mx-auto" title={file?.name}>
          {file?.name ?? 'Uploading…'}
        </p>
        <p className="text-xs text-sonoro-muted mb-6">{fmtFileSize(file?.size ?? 0)}</p>
        <div
          className="relative h-1.5 w-full max-w-xs mx-auto rounded-full bg-sonoro-border overflow-hidden"
          role="progressbar"
          aria-valuenow={uploadPct}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-label={`Uploading ${uploadPct}%`}
        >
          <div
            className="absolute inset-y-0 left-0 rounded-full transition-all duration-300"
            style={{
              width: `${uploadPct}%`,
              background: 'linear-gradient(90deg, #D97706, #F59E0B)',
            }}
          />
        </div>
        <p className="mt-2 text-xs text-sonoro-400 tabular-nums">{uploadPct}%</p>
      </div>
    );
  }

  // ── Idle + error ───────────────────────────────────────────────────────────

  return (
    <div className="w-full">
      <div
        {...getRootProps()}
        className={cn(
          'relative flex flex-col items-center justify-center rounded-2xl border-2 border-dashed transition-all duration-200 cursor-pointer p-14 text-center group',
          isDragActive && !isDragReject
            ? 'border-sonoro-amber bg-sonoro-amber-light/60 scale-[1.01]'
            : isDragReject
            ? 'border-red-400 bg-red-50'
            : 'border-sonoro-border bg-sonoro-surface hover:border-sonoro-amber/50 hover:bg-sonoro-amber-light/20',
        )}
        role="button"
        aria-label="Upload PDF — drag and drop or click to browse"
      >
        <input {...getInputProps()} />

        <div className={cn(
          'flex h-16 w-16 items-center justify-center rounded-2xl mb-6 transition-all duration-200',
          isDragActive && !isDragReject
            ? 'bg-sonoro-amber text-sonoro-black scale-110'
            : isDragReject
            ? 'bg-red-100 text-red-500'
            : 'bg-sonoro-white border border-sonoro-border text-sonoro-muted group-hover:border-sonoro-amber/40 group-hover:text-sonoro-amber-dark group-hover:scale-105',
        )}>
          <svg className="w-7 h-7" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true">
            <path d="M12 16.5V9.75m0 0 3 3m-3-3-3 3M6.75 19.5a4.5 4.5 0 0 1-1.41-8.775 5.25 5.25 0 0 1 10.233-2.33 3 3 0 0 1 3.758 3.848A3.752 3.752 0 0 1 18 19.5H6.75Z" strokeLinecap="round" strokeLinejoin="round"/>
          </svg>
        </div>

        {isDragActive && !isDragReject ? (
          <p className="text-base font-semibold text-sonoro-amber-dark">Drop to upload</p>
        ) : isDragReject ? (
          <p className="text-base font-semibold text-red-600">PDF files only</p>
        ) : (
          <>
            <p className="text-base font-semibold text-sonoro-900 mb-1.5">Drop your PDF here</p>
            <p className="text-sm text-sonoro-muted mb-5">
              or <span className="text-sonoro-amber-dark font-medium">browse your files</span>
            </p>
            <p className="text-xs text-sonoro-400">PDF only · Max 100 MB · Up to 500 pages</p>
          </>
        )}
      </div>

      {stage === 'error' && error && (
        <div
          className="mt-4 rounded-xl border border-red-200 bg-red-50 px-5 py-4 flex items-start gap-3"
          role="alert"
          aria-live="assertive"
        >
          <svg className="w-4 h-4 shrink-0 mt-0.5 text-red-500" viewBox="0 0 20 20" fill="currentColor" aria-hidden="true">
            <path fillRule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7 4a1 1 0 11-2 0 1 1 0 012 0zm-1-9a1 1 0 00-1 1v4a1 1 0 102 0V6a1 1 0 00-1-1z" clipRule="evenodd"/>
          </svg>
          <div className="flex-1 min-w-0">
            <p className="text-sm font-semibold text-red-800 mb-0.5">Something went wrong</p>
            <p className="text-sm text-red-700">{error}</p>
            {failedChunks && (
              <p className="text-xs text-red-600 mt-1">
                Completed {failedChunks.done} of {failedChunks.total} chapters
              </p>
            )}
            <button
              onClick={reset}
              className="mt-2 text-xs font-medium text-red-700 underline hover:no-underline focus:outline-none focus:ring-2 focus:ring-red-400 rounded"
            >
              Try again
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
