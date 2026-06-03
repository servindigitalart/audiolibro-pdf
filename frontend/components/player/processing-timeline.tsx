/**
 * Processing Timeline Component
 * =============================
 * Visual timeline with smooth progress, cancel button, and live microcopy.
 */

'use client';

import { useState } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { CheckCircle2, Circle, Loader2, XCircle, Clock, X, RotateCcw, Upload } from 'lucide-react';
import { cn } from '@/lib/utils';
import { useProcessingProgress } from '@/hooks/use-processing-progress';
import { cancelProcessing } from '@/lib/document-service';
import { track } from '@/lib/analytics';
import Link from 'next/link';

interface ProcessingTimelineProps {
  documentId: string;
  onCancelled?: () => void;
  className?: string;
}

interface Stage {
  id: string;
  label: string;
  description: string;
}

const STAGES: Stage[] = [
  { id: 'analyzing',         label: 'Structure Analysis',  description: 'Extracting text and analyzing document structure' },
  { id: 'detecting_chapters', label: 'Chapter Detection',  description: 'Identifying chapters and segmentation points' },
  { id: 'generating_audio',  label: 'TTS Generation',      description: 'Converting text to speech with AI voices' },
  { id: 'finalizing',        label: 'Audio Assembly',       description: 'Assembling chapters and finalizing audiobook' },
];

const STAGE_ORDER = ['analyzing', 'detecting_chapters', 'generating_audio', 'finalizing'];

function formatEta(seconds?: number): string | null {
  if (!seconds || seconds <= 0) return null;
  if (seconds < 60) return `~${seconds}s left`;
  const mins = Math.ceil(seconds / 60);
  return `~${mins} min left`;
}

export function ProcessingTimeline({ documentId, onCancelled, className }: ProcessingTimelineProps) {
  const [isCancelling, setIsCancelling] = useState(false);
  const [cancelled, setCancelled] = useState(false);

  const { displayProgress, job, isStalled } = useProcessingProgress(
    documentId,
    !cancelled,
  );

  const handleCancel = async () => {
    track('processing_cancel_clicked', { document_id: documentId });
    setIsCancelling(true);
    try {
      await cancelProcessing(documentId);
      track('processing_cancelled', { document_id: documentId });
      setCancelled(true);
      onCancelled?.();
    } catch {
      // If the API fails, the document detail page will pick up via polling
    } finally {
      setIsCancelling(false);
    }
  };

  // ── Cancelled state ────────────────────────────────────────────────────────
  if (cancelled || job?.status === 'cancelled') {
    return (
      <Card className={cn('border-orange-200 dark:border-orange-800', className)}>
        <CardContent className="py-12 text-center space-y-4">
          <div className="inline-flex items-center justify-center w-16 h-16 rounded-full bg-orange-100 dark:bg-orange-950 mb-2">
            <XCircle className="h-8 w-8 text-orange-600 dark:text-orange-400" />
          </div>
          <div>
            <h3 className="text-lg font-semibold mb-1">Conversion cancelled</h3>
            <p className="text-sm text-muted-foreground">
              Your quota was not charged for this conversion.
            </p>
          </div>
          <div className="flex flex-wrap items-center justify-center gap-3 pt-2">
            <Button asChild variant="default">
              <Link href={`/documents/${documentId}`}>
                <RotateCcw className="h-4 w-4 mr-2" />
                Restart conversion
              </Link>
            </Button>
            <Button asChild variant="outline">
              <Link href="/dashboard">
                <Upload className="h-4 w-4 mr-2" />
                Upload another file
              </Link>
            </Button>
            <Button asChild variant="ghost">
              <Link href="/documents">Back to library</Link>
            </Button>
          </div>
        </CardContent>
      </Card>
    );
  }

  // ── Derive stage index ─────────────────────────────────────────────────────
  const currentStageName = job?.current_stage ?? job?.stage ?? 'analyzing';
  // Map backend stage keys to the STAGE_ORDER list
  const stageKeyMap: Record<string, string> = {
    tts_generation:    'generating_audio',
    chapter_detection: 'detecting_chapters',
    final_assembly:    'finalizing',
    upload_finalize:   'finalizing',
  };
  const mappedStage = stageKeyMap[currentStageName] ?? currentStageName;
  const currentStageIndex = job?.status === 'completed'
    ? STAGES.length
    : Math.max(0, STAGE_ORDER.indexOf(mappedStage));

  const getStageStatus = (index: number): 'completed' | 'current' | 'pending' | 'failed' => {
    if (job?.status === 'failed' && index === currentStageIndex) return 'failed';
    if (index < currentStageIndex) return 'completed';
    if (index === currentStageIndex) return 'current';
    return 'pending';
  };

  const getStageIcon = (s: 'completed' | 'current' | 'pending' | 'failed') => {
    switch (s) {
      case 'completed': return <CheckCircle2 className="h-5 w-5 text-green-600 dark:text-green-400" />;
      case 'current':   return <Loader2 className="h-5 w-5 text-primary animate-spin" />;
      case 'failed':    return <XCircle className="h-5 w-5 text-destructive" />;
      case 'pending':   return <Circle className="h-5 w-5 text-muted-foreground/40" />;
    }
  };

  const canCancel = !job || job.status === 'queued' || job.status === 'processing';
  const isFailed = job?.status === 'failed';
  const isCompleted = job?.status === 'completed';
  const eta = formatEta(job?.estimated_seconds_remaining);

  const progressInt = Math.round(displayProgress);
  const progressStyle = isFailed ? 'bg-destructive' : 'bg-gradient-to-r from-primary to-primary/80';

  return (
    <Card className={className}>
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between gap-3">
          <CardTitle className="text-lg">Processing</CardTitle>
          <div className="flex items-center gap-2">
            {eta && !isCompleted && !isFailed && (
              <span className="text-xs text-muted-foreground hidden sm:inline">{eta}</span>
            )}
            <Badge variant={isFailed ? 'destructive' : isCompleted ? 'default' : 'secondary'}>
              {progressInt}%
            </Badge>
          </div>
        </div>

        {/* Large numeric + circular feel */}
        <div className="flex items-center gap-4 pt-1">
          <div className="text-5xl font-bold tabular-nums leading-none text-primary">
            {progressInt}
            <span className="text-2xl text-muted-foreground">%</span>
          </div>
          <div className="flex-1 space-y-1">
            {/* Progress bar */}
            <div className="w-full bg-muted rounded-full h-3 overflow-hidden">
              <div
                className={cn('h-full rounded-full', progressStyle)}
                style={{ width: `${displayProgress}%`, transition: 'width 0.1s linear' }}
              />
            </div>
            {/* Microcopy */}
            <p className="text-xs text-muted-foreground">
              {isCompleted
                ? 'Your audiobook is ready!'
                : isFailed
                ? 'Processing encountered an error.'
                : isStalled
                ? 'Still working — long books can take a few minutes.'
                : job?.status === 'queued'
                ? 'Waiting in queue…'
                : `${STAGES[currentStageIndex]?.label ?? 'Processing'}…`
              }
            </p>
          </div>
        </div>
      </CardHeader>

      <CardContent className="space-y-4">
        {STAGES.map((stage, index) => {
          const stageStatus = getStageStatus(index);
          const isLast = index === STAGES.length - 1;

          return (
            <div key={stage.id} className="relative">
              <div className="flex items-start gap-3">
                <div className="flex flex-col items-center">
                  <div className={cn(
                    'flex items-center justify-center w-8 h-8 rounded-full border-2',
                    stageStatus === 'completed' && 'border-green-600 dark:border-green-400 bg-green-50 dark:bg-green-950',
                    stageStatus === 'current'   && 'border-primary bg-primary/10',
                    stageStatus === 'failed'    && 'border-destructive bg-destructive/10',
                    stageStatus === 'pending'   && 'border-muted bg-muted/20',
                  )}>
                    {getStageIcon(stageStatus)}
                  </div>
                  {!isLast && (
                    <div className={cn(
                      'w-0.5 h-12 my-1',
                      stageStatus === 'completed' ? 'bg-green-300 dark:bg-green-700' : 'bg-muted',
                    )} />
                  )}
                </div>

                <div className="flex-1 min-w-0 pb-6">
                  <div className="flex items-center gap-2 mb-1">
                    <h4 className={cn(
                      'font-medium',
                      stageStatus === 'current'   && 'text-primary',
                      stageStatus === 'completed' && 'text-green-700 dark:text-green-300',
                      stageStatus === 'failed'    && 'text-destructive',
                      stageStatus === 'pending'   && 'text-muted-foreground',
                    )}>
                      {stage.label}
                    </h4>

                    {stageStatus === 'current' && job?.total_chunks > 0 && (
                      <Badge variant="outline" className="text-xs">
                        {job.completed_chunks}/{job.total_chunks} chunks
                      </Badge>
                    )}
                  </div>

                  <p className="text-sm text-muted-foreground">{stage.description}</p>

                  {stageStatus === 'failed' && job?.error_message && (
                    <div className="mt-2 text-xs text-destructive bg-destructive/10 p-2 rounded">
                      {job.error_message}
                    </div>
                  )}
                </div>
              </div>
            </div>
          );
        })}

        {/* Cancel button */}
        {canCancel && (
          <div className="pt-2 border-t flex justify-center">
            <Button
              variant="ghost"
              size="sm"
              onClick={handleCancel}
              disabled={isCancelling}
              className="text-muted-foreground hover:text-destructive hover:bg-destructive/10"
            >
              <X className="h-4 w-4 mr-2" />
              {isCancelling ? 'Cancelling…' : 'Cancel conversion'}
            </Button>
          </div>
        )}

        {/* Completion timestamp */}
        {isCompleted && job?.completed_at && (
          <div className="pt-2 border-t">
            <div className="flex items-center justify-between text-sm">
              <span className="text-muted-foreground">Completed at</span>
              <span className="font-medium flex items-center gap-1">
                <Clock className="h-3 w-3" />
                {new Date(job.completed_at).toLocaleTimeString('en-US', {
                  hour: '2-digit', minute: '2-digit', second: '2-digit',
                })}
              </span>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
