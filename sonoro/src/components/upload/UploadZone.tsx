import { useState, useCallback } from 'react';
import { useDropzone } from 'react-dropzone';
import { uploadDocument, getErrorMessage } from '@/lib/api/client';
import { fmtFileSize } from '@/lib/utils';
import { cn } from '@/lib/utils';

type Stage = 'idle' | 'uploading' | 'processing' | 'done' | 'error';

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
    maxSize: 100 * 1024 * 1024, // 100 MB
    disabled: stage === 'uploading' || stage === 'processing',
  });

  function reset() {
    setStage('idle');
    setFile(null);
    setProgress(0);
    setError(null);
    setDocId(null);
  }

  return (
    <div className="w-full">
      {stage === 'done' && docId ? (
        <div className="card-base p-8 text-center">
          <div className="flex h-16 w-16 items-center justify-center rounded-2xl bg-green-50 border border-green-100 mx-auto mb-4">
            <svg className="w-8 h-8 text-green-500" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true">
              <path d="M9 12.75 11.25 15 15 9.75M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z" strokeLinecap="round" strokeLinejoin="round"/>
            </svg>
          </div>
          <h3 className="text-lg font-semibold text-sonoro-900 mb-1">Upload successful!</h3>
          <p className="text-sm text-sonoro-600 mb-6">
            {file?.name} is being converted. We'll notify you when it's ready.
          </p>
          <div className="flex flex-col sm:flex-row items-center justify-center gap-3">
            <a
              href={`/dashboard/documents/${docId}`}
              className="btn-primary btn-lg"
            >
              Track progress →
            </a>
            <button onClick={reset} className="btn-outline btn-lg">
              Upload another
            </button>
          </div>
        </div>
      ) : stage === 'uploading' ? (
        <div className="card-base p-8 text-center">
          <div className="flex items-end justify-center gap-1 h-12 mb-5">
            {Array.from({ length: 5 }).map((_, i) => (
              <div
                key={i}
                className="waveform-bar"
                style={{ animationDelay: `${i * 0.15}s` }}
              />
            ))}
          </div>
          <p className="text-sm font-medium text-sonoro-900 mb-1">
            Uploading {file?.name}…
          </p>
          <p className="text-xs text-sonoro-muted mb-4">
            {fmtFileSize(file?.size ?? 0)}
          </p>
          <div className="h-1.5 w-full max-w-xs mx-auto rounded-full bg-sonoro-border overflow-hidden">
            <div
              className="h-full rounded-full bg-sonoro-amber transition-all duration-300"
              style={{ width: `${progress}%` }}
            />
          </div>
          <p className="mt-2 text-xs text-sonoro-muted">{progress}%</p>
        </div>
      ) : (
        <div>
          <div
            {...getRootProps()}
            className={cn(
              'relative flex flex-col items-center justify-center rounded-2xl border-2 border-dashed transition-all duration-200 cursor-pointer p-12 text-center',
              isDragActive && !isDragReject
                ? 'border-sonoro-amber bg-sonoro-amber-light scale-[1.01]'
                : isDragReject
                ? 'border-red-400 bg-red-50'
                : 'border-sonoro-border bg-sonoro-surface hover:border-sonoro-amber/50 hover:bg-sonoro-amber-light/30'
            )}
            role="button"
            aria-label="Upload PDF — drag and drop or click"
          >
            <input {...getInputProps()} />

            <div className={cn(
              'flex h-16 w-16 items-center justify-center rounded-2xl mb-5 transition-colors duration-200',
              isDragActive && !isDragReject
                ? 'bg-sonoro-amber text-sonoro-black'
                : 'bg-sonoro-white border border-sonoro-border text-sonoro-muted'
            )}>
              <svg className="w-7 h-7" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true">
                <path d="M12 16.5V9.75m0 0 3 3m-3-3-3 3M6.75 19.5a4.5 4.5 0 0 1-1.41-8.775 5.25 5.25 0 0 1 10.233-2.33 3 3 0 0 1 3.758 3.848A3.752 3.752 0 0 1 18 19.5H6.75Z" strokeLinecap="round" strokeLinejoin="round"/>
              </svg>
            </div>

            {isDragActive && !isDragReject ? (
              <p className="text-base font-semibold text-sonoro-amber-dark">Drop it here</p>
            ) : isDragReject ? (
              <p className="text-base font-semibold text-red-600">Only PDF files are accepted</p>
            ) : (
              <>
                <p className="text-base font-semibold text-sonoro-900 mb-1">
                  Drop your PDF here
                </p>
                <p className="text-sm text-sonoro-muted mb-5">
                  or <span className="text-sonoro-amber-dark font-medium">browse to choose</span> a file
                </p>
                <p className="text-xs text-sonoro-400">
                  PDF only · Max 100 MB · Up to 500 pages
                </p>
              </>
            )}
          </div>

          {error && stage === 'error' && (
            <div className="mt-4 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700" role="alert">
              <strong>Upload failed:</strong> {error}
              <button onClick={reset} className="ml-2 underline hover:no-underline">Try again</button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
