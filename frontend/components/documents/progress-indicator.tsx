/**
 * Progress Indicator Component
 * ===========================
 * Displays processing progress with stage information
 */

'use client';

import { Progress } from '@/components/ui/progress';
import { getStageConfig, calculateProgress } from '@/lib/document-status';
import { ProcessingJob } from '@/lib/document-service';
import { cn } from '@/lib/utils';

interface ProgressIndicatorProps {
  job: ProcessingJob;
  className?: string;
  showDetails?: boolean;
}

export function ProgressIndicator({ job, className, showDetails = true }: ProgressIndicatorProps) {
  const progress = calculateProgress(job);
  const stageConfig = job.stage ? getStageConfig(job.stage) : null;

  return (
    <div className={cn('space-y-2', className)}>
      <div className="flex items-center justify-between text-sm">
        <span className="font-medium">
          {stageConfig?.label || 'Processing'}
        </span>
        <span className="text-muted-foreground">{progress}%</span>
      </div>

      <Progress value={progress} className="h-2" />

      {showDetails && stageConfig && (
        <p className="text-xs text-muted-foreground">
          {stageConfig.description}
        </p>
      )}

      {showDetails && job.metadata && (
        <div className="text-xs text-muted-foreground space-y-1">
          {job.metadata.current_chapter && (
            <div>Current: {job.metadata.current_chapter}</div>
          )}
          {job.metadata.processed_chapters !== undefined && job.metadata.total_chapters && (
            <div>
              Chapters: {job.metadata.processed_chapters} / {job.metadata.total_chapters}
            </div>
          )}
          {job.metadata.processed_pages !== undefined && job.metadata.total_pages && (
            <div>
              Pages: {job.metadata.processed_pages} / {job.metadata.total_pages}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
