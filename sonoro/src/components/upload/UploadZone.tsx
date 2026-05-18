import { useState, useCallback, useEffect, useRef } from 'react';
import { useDropzone } from 'react-dropzone';
import {
  uploadDocument,
  getProcessingJob,
  getChapters,
  getErrorMessage,
} from '@/lib/api/client';
import type { Chapter, ProcessingJob } from '@/lib/api/types';
import { fmtFileSize, fmtDuration } from '@/lib/utils';
import { cn } from '@/lib/utils';

type Stage = 'idle' | 'uploading' | 'processing' | 'ready' | 'error';
type ProcessStage = ProcessingJob['stage'];

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
  const [processStage, setProcessStage]         = useState<ProcessStage>(undefined);
  const [processPct, setProcessPct]             = useState(0);
  const [chapters, setChapters]                 = useState<Chapter[]>([]);
  const pollRef                                 = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    if (stage !== 'processing' || !docId) return;

    async function poll() {
      const job: ProcessingJob | null = await getProcessingJob(docId!);
      if (!job) return;
      if (job.stage) setProcessStage(job.stage);
      setProcessPct(job.progress ?? 0);

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

  const onDrop = useCallback(async (accepted: File[]) => {
    const f = accepted[0];
    if (!f) return;
    setFile(f);
    setError(null);
    setStage('uploading');
    setUploadPct(0);
    try {
      const { document } = await uploadDocument(f, setUploadPct);
      setDocId(document.id);
      setStage('processing');
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
    disabled: stage === 'uploading' || stage === 'processing',
  });

  function reset() {
    if (pollRef.current) clearInterval(pollRef.current);
    setStage('idle');
    setFile(null);
    setUploadPct(0);
    setError(null);
    setDocId(null);
    setProcessStage(undefined);
    setProcessPct(0);
    setChapters([]);
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
          <p className="text-sm text-sonoro-muted mb-6">{current.desc}</p>

          {/* Progress bar */}
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
