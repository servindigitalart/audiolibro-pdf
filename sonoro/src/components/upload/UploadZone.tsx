import { useState, useCallback } from 'react';
import { useDropzone } from 'react-dropzone';
import { uploadDocument, getErrorMessage } from '@/lib/api/client';
import { fmtFileSize } from '@/lib/utils';
import { cn } from '@/lib/utils';

type Stage = 'idle' | 'uploading' | 'done' | 'error';

export default function UploadZone() {
  const [stage, setStage]       = useState<Stage>('idle');
  const [progress, setProgress] = useState(0);
  const [file, setFile]         = useState<File | null>(null);
  const [error, setError]       = useState<string | null>(null);
  const [docId, setDocId]       = useState<string | null>(null);

  const onDrop = useCallback(async (accepted: File[]) => {
    const f = accepted[0];
    if (!f) return;
    setFile(f);
    setError(null);
    setStage('uploading');
    setProgress(0);
    try {
      const { document } = await uploadDocument(f, setProgress);
      setDocId(document.id);
      setStage('done');
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
    disabled: stage === 'uploading',
  });

  function reset() {
    setStage('idle');
    setFile(null);
    setProgress(0);
    setError(null);
    setDocId(null);
  }

  /* ── Success state — the "wow moment" ── */
  if (stage === 'done' && docId) {
    return (
      <div className="card-base overflow-hidden animate-scale-in">
        {/* Amber gradient header strip */}
        <div
          className="h-1.5 w-full"
          style={{ background: 'linear-gradient(90deg, #D97706, #F59E0B, #FBBF24)' }}
          aria-hidden="true"
        />
        <div className="px-8 py-12 text-center relative">
          {/* Background glow */}
          <div
            className="absolute inset-0 pointer-events-none"
            style={{ background: 'radial-gradient(ellipse at 50% 0%, rgba(254,243,199,0.6) 0%, transparent 60%)' }}
            aria-hidden="true"
          />

          <div className="relative">
            {/* Success icon with ring glow */}
            <div className="relative flex h-16 w-16 items-center justify-center rounded-2xl bg-emerald-50 border border-emerald-100 mx-auto mb-6 shadow-soft">
              <svg className="w-8 h-8 text-emerald-500" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
                <path d="M9 12.75 11.25 15 15 9.75M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z" strokeLinecap="round" strokeLinejoin="round"/>
              </svg>
              {/* Pulse ring */}
              <span className="absolute inset-0 rounded-2xl border-2 border-emerald-300 animate-ping opacity-40" aria-hidden="true" />
            </div>

            <h3 className="text-xl font-bold text-sonoro-900 tracking-tight mb-2">
              Conversion started!
            </h3>
            <p className="text-sm text-sonoro-600 leading-relaxed mb-2">
              <span className="font-medium text-sonoro-900">{file?.name}</span> is being processed.
            </p>
            <p className="text-sm text-sonoro-muted mb-8">
              Your audiobook will be ready in under 60 seconds.
            </p>

            <div className="flex flex-col sm:flex-row items-center justify-center gap-3">
              <a href={`/dashboard/documents/${docId}`} className="btn-primary btn-lg">
                Watch it convert
                <svg className="w-4 h-4" viewBox="0 0 16 16" fill="none" aria-hidden="true">
                  <path d="M3 8h10M9 4l4 4-4 4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
                </svg>
              </a>
              <button onClick={reset} className="btn-outline btn-lg">
                Upload another
              </button>
            </div>
          </div>
        </div>
      </div>
    );
  }

  /* ── Uploading state ── */
  if (stage === 'uploading') {
    return (
      <div className="card-base px-8 py-12 text-center">
        {/* Animated waveform */}
        <div className="flex items-end justify-center gap-1 h-12 mb-6" aria-hidden="true">
          {[40, 70, 100, 75, 55, 90, 65, 80, 45, 95].map((h, i) => (
            <div key={i} className="waveform-bar w-1.5" style={{ height: `${h}%`, animationDelay: `${i * 0.11}s` }} />
          ))}
        </div>

        <p className="text-sm font-semibold text-sonoro-900 mb-1">
          Uploading{file?.name ? ` ${file.name}` : ''}…
        </p>
        <p className="text-xs text-sonoro-muted mb-6">
          {fmtFileSize(file?.size ?? 0)}
        </p>

        {/* Progress bar */}
        <div className="relative h-1.5 w-full max-w-xs mx-auto rounded-full bg-sonoro-border overflow-hidden">
          <div
            className="absolute inset-y-0 left-0 rounded-full transition-all duration-300"
            style={{
              width: `${progress}%`,
              background: 'linear-gradient(90deg, #D97706, #F59E0B)',
            }}
          />
        </div>
        <p className="mt-2 text-xs tabular text-sonoro-muted">{progress}%</p>
      </div>
    );
  }

  /* ── Idle / error state ── */
  return (
    <div className="w-full">
      <div
        {...getRootProps()}
        className={cn(
          'relative flex flex-col items-center justify-center rounded-2xl border-2 border-dashed transition-all duration-200 ease-smooth cursor-pointer p-14 text-center group',
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

        {/* Upload icon */}
        <div className={cn(
          'flex h-16 w-16 items-center justify-center rounded-2xl mb-6 transition-all duration-200',
          isDragActive && !isDragReject
            ? 'bg-sonoro-amber text-sonoro-black shadow-amber scale-110'
            : isDragReject
            ? 'bg-red-100 text-red-500'
            : 'bg-sonoro-white border border-sonoro-border text-sonoro-muted group-hover:border-sonoro-amber/40 group-hover:text-sonoro-amber-dark',
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
            <p className="text-base font-semibold text-sonoro-900 mb-1.5">
              Drop your PDF here
            </p>
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
