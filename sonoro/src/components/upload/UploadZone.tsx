import { useState, useCallback, useEffect, useRef } from 'react';
import { useDropzone } from 'react-dropzone';
import {
  uploadDocument,
  startProcessing,
  getProcessingJob,
  getChapters,
  getErrorMessage,
} from '@/lib/api/client';
import type { Chapter, ProcessingJob, PreflightResult } from '@/lib/api/types';
import { fmtFileSize, fmtDuration } from '@/lib/utils';
import { cn } from '@/lib/utils';

type Stage = 'idle' | 'uploading' | 'preflight' | 'processing' | 'ready' | 'error' | 'duplicate';
type ProcessStage = ProcessingJob['stage'];

interface DuplicateInfo {
  docId: string;
  message: string;
  canReprocess: boolean;
}

const PROCESS_STEPS: { key: NonNullable<ProcessStage>; label: string; desc: string }[] = [
  { key: 'analyzing',          label: 'Analyzing',      desc: 'Reading structure and content' },
  { key: 'detecting_chapters', label: 'Chapters',       desc: 'Finding natural breaks with AI' },
  { key: 'generating_audio',   label: 'Generating',     desc: 'Converting text to speech' },
  { key: 'finalizing',         label: 'Finalizing',     desc: 'Assembling your audiobook' },
];

// Deterministic heights — no Math.random() to avoid SSR/client mismatch
const WAVE_H = [38, 72, 54, 91, 63, 48, 85, 57, 76, 44, 88, 62, 71, 39, 80];
const WAVE_D = [0, 0.12, 0.24, 0.06, 0.18, 0.30, 0.09, 0.21, 0.03, 0.15, 0.27, 0.08, 0.20, 0.04, 0.16];

function stepIndex(stage?: ProcessStage): number {
  if (!stage) return 0;
  return PROCESS_STEPS.findIndex(s => s.key === stage);
}

export default function UploadZone() {
  const [stage, setStage]                       = useState<Stage>('idle');
  const [uploadPct, setUploadPct]               = useState(0);
  const [file, setFile]                         = useState<File | null>(null);
  const [error, setError]                       = useState<string | null>(null);
  const [docId, setDocId]                       = useState<string | null>(null);
  const [preflight, setPreflight]               = useState<PreflightResult | null>(null);
  const [selectedVoice, setSelectedVoice]       = useState<string>('');
  const [processStage, setProcessStage]         = useState<ProcessStage>(undefined);
  const [processPct, setProcessPct]             = useState(0);
  const [chunkProgress, setChunkProgress]       = useState<{ done: number; total: number } | null>(null);
  const [estimatedSecs, setEstimatedSecs]       = useState<number | null>(null);
  const [chapters, setChapters]                 = useState<Chapter[]>([]);
  const [duplicate, setDuplicate]               = useState<DuplicateInfo | null>(null);
  const [startingConversion, setStartingConversion] = useState(false);
  const pollRef                                 = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    if (stage !== 'processing' || !docId) return;

    async function poll() {
      const job: ProcessingJob | null = await getProcessingJob(docId!);
      if (!job) return;

      if (job.stage) setProcessStage(job.stage);
      // Never go backward — a retry resets progress on the backend but the
      // user has already seen a higher number, so clamp to the previous max.
      setProcessPct(prev => Math.max(prev, job.progress ?? 0));

      if (job.total_chunks && job.total_chunks > 0) {
        setChunkProgress({ done: job.completed_chunks ?? 0, total: job.total_chunks });
      }
      if (job.estimated_seconds_remaining != null) {
        setEstimatedSecs(job.estimated_seconds_remaining);
      }

      if (job.status === 'completed') {
        clearInterval(pollRef.current!);
        try {
          const raw = await getChapters(docId!);
          setChapters(Array.isArray(raw) ? raw : (raw?.chapters ?? []));
        } catch {}
        setStage('ready');
      } else if (job.status === 'failed') {
        clearInterval(pollRef.current!);
        setError(job.error_message ?? 'Processing failed. Please try again.');
        setStage('error');
      }
    }

    poll();
    pollRef.current = setInterval(poll, 2500);
    return () => { if (pollRef.current) clearInterval(pollRef.current); };
  }, [stage, docId]);

  const onDrop = useCallback(async (accepted: File[], forceReprocess = false) => {
    const f = accepted[0];
    if (!f) return;
    setFile(f);
    setError(null);
    setDuplicate(null);
    setPreflight(null);
    setSelectedVoice('');
    setStage('uploading');
    setUploadPct(0);
    try {
      const result = await uploadDocument(f, setUploadPct, forceReprocess);
      if (!result?.id) throw new Error('Upload succeeded but the server returned an invalid response.');
      setDocId(result.id);

      if (result.is_duplicate) {
        const activeStatuses = ['queued', 'processing', 'assembling', 'finalizing'];
        if (activeStatuses.includes(result.processing_status)) {
          // Already in-flight — just poll the existing job
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
        // Show analysis card — user must click "Start conversion"
        setPreflight(result.preflight);
        setSelectedVoice(result.preflight.voice_id);
        setStage('preflight');
      } else {
        // No preflight (legacy path or force-reprocess with auto-enqueue)
        setStage('processing');
      }
    } catch (err) {
      setError(getErrorMessage(err));
      setStage('error');
    }
  }, []);

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
    setProcessStage(undefined);
    setProcessPct(0);
    setChunkProgress(null);
    setEstimatedSecs(null);
    setChapters([]);
    setDuplicate(null);
    setStartingConversion(false);
  }

  /* ── Preflight ─────────────────────────────────────────────────────── */
  if (stage === 'preflight' && preflight && docId) {
    const durSecs  = preflight.estimated_duration_seconds;
    const durH     = Math.floor(durSecs / 3600);
    const durM     = Math.floor((durSecs % 3600) / 60);
    const durLabel = durH > 0 ? `${durH}h ${durM}m` : `${durM}m`;

    const procMins = preflight.estimated_processing_minutes;
    const procLabel = procMins < 1 ? 'less than a minute'
                    : procMins < 60 ? `~${Math.ceil(procMins)} min`
                    : `~${Math.ceil(procMins / 60)}h`;

    const pctUsed = preflight.chars_limit > 0
      ? Math.min(100, Math.round((preflight.chars_used / preflight.chars_limit) * 100))
      : 0;
    const pctAfter = preflight.chars_limit > 0
      ? Math.min(100, Math.round(((preflight.chars_used + preflight.estimated_characters) / preflight.chars_limit) * 100))
      : 0;

    async function handleStartConversion() {
      if (!docId) return;
      setStartingConversion(true);
      try {
        await startProcessing(docId);
        setStage('processing');
      } catch (err) {
        setError(getErrorMessage(err));
        setStage('error');
      } finally {
        setStartingConversion(false);
      }
    }

    return (
      <div className="card-base overflow-hidden animate-scale-in">
        {/* Accent bar */}
        <div
          className="h-1 w-full"
          style={{ background: 'linear-gradient(90deg, #D97706, #F59E0B, #FBBF24)' }}
          aria-hidden="true"
        />

        <div className="px-8 py-8">
          {/* Header */}
          <div className="flex items-center gap-3 mb-6">
            <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-sonoro-amber-light border border-sonoro-amber/30 shrink-0">
              <svg className="w-5 h-5 text-sonoro-amber-dark" viewBox="0 0 20 20" fill="currentColor" aria-hidden="true">
                <path fillRule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7-4a1 1 0 11-2 0 1 1 0 012 0zM9 9a.75.75 0 000 1.5h.253a.25.25 0 01.244.304l-.459 2.066A1.75 1.75 0 0010.747 15H11a.75.75 0 000-1.5h-.253a.25.25 0 01-.244-.304l.459-2.066A1.75 1.75 0 009.253 9H9z" clipRule="evenodd"/>
              </svg>
            </div>
            <div className="min-w-0">
              <p className="text-base font-bold text-sonoro-900 leading-tight">Ready to convert</p>
              <p className="text-xs text-sonoro-muted truncate">{file?.name}</p>
            </div>
          </div>

          {/* Analysis grid */}
          <div className="grid grid-cols-2 gap-3 mb-6">
            <div className="rounded-xl bg-sonoro-surface border border-sonoro-border/60 px-4 py-3">
              <p className="text-[10px] font-semibold text-sonoro-400 uppercase tracking-wider mb-1">Language</p>
              <p className="text-sm font-semibold text-sonoro-900">{preflight.language_name}</p>
            </div>
            <div className="rounded-xl bg-sonoro-surface border border-sonoro-border/60 px-4 py-3">
              <p className="text-[10px] font-semibold text-sonoro-400 uppercase tracking-wider mb-1">Audiobook length</p>
              <p className="text-sm font-semibold text-sonoro-900">{durLabel}</p>
            </div>
            <div className="rounded-xl bg-sonoro-surface border border-sonoro-border/60 px-4 py-3">
              <p className="text-[10px] font-semibold text-sonoro-400 uppercase tracking-wider mb-1">Chapters detected</p>
              <p className="text-sm font-semibold text-sonoro-900">~{preflight.estimated_chapters}</p>
            </div>
            <div className="rounded-xl bg-sonoro-surface border border-sonoro-border/60 px-4 py-3">
              <p className="text-[10px] font-semibold text-sonoro-400 uppercase tracking-wider mb-1">Characters</p>
              <p className="text-sm font-semibold text-sonoro-900">{preflight.estimated_characters.toLocaleString()}</p>
            </div>
          </div>

          {/* Voice selector */}
          <div className="mb-5">
            <label className="text-[10px] font-semibold text-sonoro-400 uppercase tracking-wider block mb-1.5">
              Voice
            </label>
            <select
              value={selectedVoice}
              onChange={(e) => setSelectedVoice(e.target.value)}
              className="w-full rounded-xl border border-sonoro-border bg-sonoro-surface px-3 py-2 text-sm text-sonoro-900 focus:outline-none focus:ring-2 focus:ring-sonoro-amber/40"
            >
              {preflight.available_voices.map((v) => (
                <option key={v.voice_id} value={v.voice_id}>{v.display_name}</option>
              ))}
            </select>
          </div>

          {/* Quota bar */}
          <div className="mb-6">
            <div className="flex items-center justify-between mb-1.5">
              <p className="text-[10px] font-semibold text-sonoro-400 uppercase tracking-wider">
                Quota — {preflight.plan_display_name} plan
              </p>
              <p className="text-[10px] text-sonoro-400">
                {preflight.chars_used.toLocaleString()} / {preflight.chars_limit.toLocaleString()} chars
              </p>
            </div>
            <div className="relative h-2 rounded-full bg-sonoro-border overflow-hidden">
              {/* Used */}
              <div
                className="absolute inset-y-0 left-0 rounded-l-full"
                style={{
                  width: `${pctUsed}%`,
                  background: 'linear-gradient(90deg, #D97706, #F59E0B)',
                }}
              />
              {/* This document's portion */}
              {!preflight.quota_exceeded && (
                <div
                  className="absolute inset-y-0 bg-sonoro-amber/30"
                  style={{ left: `${pctUsed}%`, width: `${pctAfter - pctUsed}%` }}
                />
              )}
            </div>
            {preflight.quota_exceeded ? (
              <p className="mt-1.5 text-xs text-red-600 font-medium">
                This document exceeds your {preflight.plan_display_name} plan quota.{' '}
                <a href="/dashboard/billing" className="underline hover:no-underline">Upgrade</a> to convert it.
              </p>
            ) : (
              <p className="mt-1.5 text-xs text-sonoro-400">
                {preflight.chars_remaining_after.toLocaleString()} chars remaining after conversion
              </p>
            )}
          </div>

          {/* Processing time estimate */}
          <p className="text-xs text-sonoro-400 mb-6">
            Estimated processing time: <span className="font-medium text-sonoro-600">{procLabel}</span>
          </p>

          {/* CTAs */}
          <div className="flex flex-col sm:flex-row items-stretch sm:items-center gap-3">
            {preflight.quota_exceeded ? (
              <a
                href="/dashboard/billing"
                className="btn-accent py-2.5 px-6 rounded-full text-sm flex items-center justify-center gap-2"
              >
                Upgrade plan
              </a>
            ) : (
              <button
                onClick={handleStartConversion}
                disabled={startingConversion}
                className="btn-accent py-2.5 px-6 rounded-full text-sm flex items-center justify-center gap-2 disabled:opacity-60 disabled:cursor-not-allowed"
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
            )}
            <button onClick={reset} className="btn-outline py-2.5 px-6 rounded-full text-sm">
              Upload different file
            </button>
          </div>
        </div>
      </div>
    );
  }

  /* ── Duplicate ─────────────────────────────────────────────────────── */
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
            <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-indigo-50 border border-indigo-100 shrink-0 mt-0.5">
              <svg className="w-5 h-5 text-indigo-500" viewBox="0 0 20 20" fill="currentColor" aria-hidden="true">
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
                onClick={() => onDrop([file], true)}
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

  /* ── Ready ─────────────────────────────────────────────────────────── */
  if (stage === 'ready' && docId) {
    const totalSecs = chapters.reduce((s, c) => s + (c.duration_seconds ?? 0), 0);
    return (
      <div className="card-base overflow-hidden animate-scale-in">
        <div
          className="h-1 w-full"
          style={{ background: 'linear-gradient(90deg, #D97706, #F59E0B, #FBBF24)' }}
          aria-hidden="true"
        />
        <div className="px-8 py-10 relative">
          <div
            className="absolute inset-0 pointer-events-none"
            style={{ background: 'radial-gradient(ellipse at 50% 0%, rgba(254,243,199,0.5) 0%, transparent 55%)' }}
            aria-hidden="true"
          />
          <div className="relative">
            {/* Header */}
            <div className="flex items-center gap-3 mb-6">
              <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-emerald-50 border border-emerald-100 shrink-0">
                <svg className="w-5 h-5 text-emerald-500" viewBox="0 0 20 20" fill="currentColor" aria-hidden="true">
                  <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.857-9.809a.75.75 0 00-1.214-.882l-3.483 4.79-1.88-1.88a.75.75 0 10-1.06 1.061l2.5 2.5a.75.75 0 001.137-.089l4-5.5z" clipRule="evenodd"/>
                </svg>
              </div>
              <div className="min-w-0">
                <p className="text-base font-bold text-sonoro-900 leading-tight">Your audiobook is ready</p>
                <p className="text-xs text-sonoro-muted truncate">{file?.name}</p>
              </div>
            </div>

            {/* Waveform */}
            <div className="flex items-end gap-0.5 h-10 mb-6" aria-hidden="true">
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
                  {chapters.length} chapter{chapters.length !== 1 ? 's' : ''}
                  {totalSecs > 0 && ` · ${fmtDuration(totalSecs)}`}
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
            <div className="flex flex-col sm:flex-row items-stretch sm:items-center gap-3">
              <a
                href={`/dashboard/documents/${docId}`}
                className="btn-accent py-2.5 px-6 rounded-full text-sm flex items-center justify-center gap-2"
              >
                <svg className="w-4 h-4" viewBox="0 0 20 20" fill="currentColor" aria-hidden="true">
                  <path fillRule="evenodd" d="M2 10a8 8 0 1116 0 8 8 0 01-16 0zm6.39-2.908a.75.75 0 01.766.027l3.5 2.25a.75.75 0 010 1.262l-3.5 2.25A.75.75 0 018 12.25v-4.5a.75.75 0 01.39-.658z" clipRule="evenodd"/>
                </svg>
                Listen now
              </a>
              <button onClick={reset} className="btn-outline py-2.5 px-6 rounded-full text-sm">
                Upload another
              </button>
            </div>
          </div>
        </div>
      </div>
    );
  }

  /* ── Processing ─────────────────────────────────────────────────────── */
  if (stage === 'processing') {
    const idx     = stepIndex(processStage);
    const current = PROCESS_STEPS[Math.max(0, idx)];

    const showChunks = chunkProgress && chunkProgress.total > 0;
    const estMins =
      estimatedSecs != null && estimatedSecs > 0
        ? estimatedSecs < 60
          ? 'less than a minute'
          : `~${Math.ceil(estimatedSecs / 60)} min`
        : null;

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

          <p className="text-base font-semibold text-sonoro-900 mb-0.5">{current.label}</p>

          {/* Chunk-level detail when TTS is running */}
          {showChunks ? (
            <p className="text-sm text-sonoro-muted mb-1">
              {chunkProgress!.done} of {chunkProgress!.total} segments completed
            </p>
          ) : (
            <p className="text-sm text-sonoro-muted mb-1">{current.desc}</p>
          )}

          {/* Estimated time remaining */}
          {estMins && (
            <p className="text-xs text-sonoro-400 mb-5">{estMins} remaining</p>
          )}
          {!estMins && <div className="mb-5" />}

          {/* Progress bar — transition-all with duration-700 gives smoothing */}
          <div className="relative h-1.5 w-full max-w-xs mx-auto rounded-full bg-sonoro-border overflow-hidden mb-2">
            <div
              className="absolute inset-y-0 left-0 rounded-full transition-all duration-700 ease-out"
              style={{
                width: `${processPct}%`,
                background: 'linear-gradient(90deg, #D97706, #F59E0B)',
              }}
            />
          </div>
          <p className="text-xs text-sonoro-400 tabular-nums mb-8">{processPct}%</p>

          {/* 4-step timeline */}
          <div className="flex items-start justify-center">
            {PROCESS_STEPS.map((step, i) => {
              const done   = i < idx;
              const active = i === idx;
              return (
                <div key={step.key} className="flex items-center">
                  <div className="flex flex-col items-center gap-1.5 w-16">
                    <div className={cn(
                      'h-7 w-7 rounded-full flex items-center justify-center border-2 transition-all duration-500',
                      done   ? 'bg-sonoro-amber border-sonoro-amber'
                             : active ? 'border-sonoro-amber bg-sonoro-white animate-pulse-slow'
                             : 'border-sonoro-border bg-sonoro-white',
                    )}>
                      {done ? (
                        <svg className="w-3.5 h-3.5 text-white" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="2.5" aria-hidden="true">
                          <path d="M2.5 7l3 3 6-6" strokeLinecap="round" strokeLinejoin="round"/>
                        </svg>
                      ) : active ? (
                        <div className="h-2.5 w-2.5 rounded-full bg-sonoro-amber" />
                      ) : null}
                    </div>
                    <p className={cn(
                      'text-[10px] leading-tight text-center',
                      done || active ? 'text-sonoro-700 font-medium' : 'text-sonoro-400',
                    )}>
                      {step.label}
                    </p>
                  </div>
                  {i < PROCESS_STEPS.length - 1 && (
                    <div
                      className={cn(
                        'h-0.5 w-8 mb-5 transition-colors duration-500 shrink-0',
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

  /* ── Uploading ──────────────────────────────────────────────────────── */
  if (stage === 'uploading') {
    return (
      <div className="card-base px-8 py-10 text-center">
        <div className="flex items-end justify-center gap-1 h-10 mb-6" aria-hidden="true">
          {[40, 70, 100, 75, 55, 90, 65, 80, 45, 95].map((h, i) => (
            <div key={i} className="waveform-bar w-1.5" style={{ height: `${h}%`, animationDelay: `${i * 0.11}s` }} />
          ))}
        </div>
        <p className="text-sm font-semibold text-sonoro-900 mb-0.5 truncate max-w-xs mx-auto">
          {file?.name ?? 'Uploading…'}
        </p>
        <p className="text-xs text-sonoro-muted mb-6">{fmtFileSize(file?.size ?? 0)}</p>
        <div className="relative h-1.5 w-full max-w-xs mx-auto rounded-full bg-sonoro-border overflow-hidden">
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

  /* ── Idle / error ───────────────────────────────────────────────────── */
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
        <div className="mt-4 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700 flex items-start gap-3" role="alert">
          <svg className="w-4 h-4 shrink-0 mt-0.5" viewBox="0 0 20 20" fill="currentColor" aria-hidden="true">
            <path fillRule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7 4a1 1 0 11-2 0 1 1 0 012 0zm-1-9a1 1 0 00-1 1v4a1 1 0 102 0V6a1 1 0 00-1-1z" clipRule="evenodd"/>
          </svg>
          <div className="flex-1">
            <span className="font-medium">Upload failed: </span>{error}
            <button onClick={reset} className="ml-2 underline hover:no-underline">Try again</button>
          </div>
        </div>
      )}
    </div>
  );
}
