/**
 * Document Status Utilities
 * ========================
 * Maps backend document/job statuses to UI-friendly labels, colors, and descriptions
 */

export type DocumentStatus = 
  | 'pending' 
  | 'processing' 
  | 'completed' 
  | 'failed' 
  | 'queued';

export type ProcessingStage = 
  | 'uploading'
  | 'queued'
  | 'analyzing'
  | 'detecting_chapters'
  | 'generating_audio'
  | 'finalizing'
  | 'completed'
  | 'failed';

export interface StatusConfig {
  label: string;
  color: 'default' | 'secondary' | 'destructive' | 'success' | 'warning';
  description: string;
  progressPercent: number;
}

export const statusConfig: Record<DocumentStatus, StatusConfig> = {
  pending: {
    label: 'Pending',
    color: 'secondary',
    description: 'Document is queued for processing',
    progressPercent: 5,
  },
  queued: {
    label: 'Queued',
    color: 'secondary',
    description: 'Waiting in processing queue',
    progressPercent: 10,
  },
  processing: {
    label: 'Processing',
    color: 'warning',
    description: 'Document is being processed',
    progressPercent: 50,
  },
  completed: {
    label: 'Completed',
    color: 'success',
    description: 'Audiobook is ready',
    progressPercent: 100,
  },
  failed: {
    label: 'Failed',
    color: 'destructive',
    description: 'Processing failed',
    progressPercent: 0,
  },
};

export const stageConfig: Record<ProcessingStage, StatusConfig> = {
  uploading: {
    label: 'Uploading',
    color: 'secondary',
    description: 'Uploading document to server',
    progressPercent: 5,
  },
  queued: {
    label: 'Queued',
    color: 'secondary',
    description: 'Waiting in processing queue',
    progressPercent: 10,
  },
  analyzing: {
    label: 'Analyzing',
    color: 'warning',
    description: 'Analyzing document structure',
    progressPercent: 25,
  },
  detecting_chapters: {
    label: 'Detecting Chapters',
    color: 'warning',
    description: 'Identifying chapters and sections',
    progressPercent: 40,
  },
  generating_audio: {
    label: 'Generating Audio',
    color: 'warning',
    description: 'Converting text to speech',
    progressPercent: 70,
  },
  finalizing: {
    label: 'Finalizing',
    color: 'warning',
    description: 'Assembling final audiobook',
    progressPercent: 90,
  },
  completed: {
    label: 'Completed',
    color: 'success',
    description: 'Audiobook is ready',
    progressPercent: 100,
  },
  failed: {
    label: 'Failed',
    color: 'destructive',
    description: 'Processing encountered an error',
    progressPercent: 0,
  },
};

/**
 * Get status configuration
 */
export function getStatusConfig(status: string): StatusConfig {
  return statusConfig[status as DocumentStatus] || statusConfig.pending;
}

/**
 * Get stage configuration
 */
export function getStageConfig(stage: string): StatusConfig {
  return stageConfig[stage as ProcessingStage] || stageConfig.queued;
}

/**
 * Calculate overall progress from job metadata
 */
export function calculateProgress(job: {
  status: string;
  stage?: string;
  metadata?: {
    total_pages?: number;
    processed_pages?: number;
    total_chapters?: number;
    processed_chapters?: number;
  };
}): number {
  // If completed or failed, use their base progress
  if (job.status === 'completed') return 100;
  if (job.status === 'failed') return 0;

  // Get base progress from stage
  const stageProgress = job.stage 
    ? getStageConfig(job.stage).progressPercent 
    : getStatusConfig(job.status).progressPercent;

  // Fine-tune based on metadata
  if (job.metadata) {
    const { total_pages, processed_pages, total_chapters, processed_chapters } = job.metadata;
    
    // If we have chapter progress data
    if (total_chapters && processed_chapters) {
      const chapterProgress = (processed_chapters / total_chapters) * 100;
      // Blend with stage progress (70% stage, 30% actual progress)
      return Math.round(stageProgress * 0.7 + chapterProgress * 0.3);
    }
    
    // If we have page progress data
    if (total_pages && processed_pages) {
      const pageProgress = (processed_pages / total_pages) * 100;
      // Blend with stage progress
      return Math.round(stageProgress * 0.7 + pageProgress * 0.3);
    }
  }

  return stageProgress;
}

/**
 * Check if document is actively processing
 */
export function isProcessing(status: string): boolean {
  return status === 'processing' || status === 'queued' || status === 'pending';
}

/**
 * Check if document can be retried
 */
export function canRetry(status: string): boolean {
  return status === 'failed';
}

/**
 * Check if document can be downloaded
 */
export function canDownload(status: string): boolean {
  return status === 'completed';
}
