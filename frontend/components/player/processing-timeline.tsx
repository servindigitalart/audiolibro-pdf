/**
 * Processing Timeline Component
 * =============================
 * Visual timeline showing document processing stages
 */

'use client';

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { CheckCircle2, Circle, Loader2, XCircle, Clock } from 'lucide-react';
import { cn } from '@/lib/utils';
import type { ProcessingJob } from '@/lib/document-service';

interface ProcessingTimelineProps {
  job: ProcessingJob;
  className?: string;
}

interface Stage {
  id: string;
  label: string;
  description: string;
}

const STAGES: Stage[] = [
  {
    id: 'analyzing',
    label: 'Structure Analysis',
    description: 'Extracting text and analyzing document structure',
  },
  {
    id: 'detecting_chapters',
    label: 'Chapter Detection',
    description: 'Identifying chapters and segmentation points',
  },
  {
    id: 'generating_audio',
    label: 'TTS Generation',
    description: 'Converting text to speech with AI voices',
  },
  {
    id: 'finalizing',
    label: 'Audio Assembly',
    description: 'Assembling chapters and finalizing audiobook',
  },
];

export function ProcessingTimeline({ job, className }: ProcessingTimelineProps) {
  const getCurrentStageIndex = (): number => {
    if (job.status === 'completed') return STAGES.length;
    if (job.status === 'failed') {
      const stageIndex = STAGES.findIndex(s => s.id === job.stage);
      return stageIndex >= 0 ? stageIndex : 0;
    }
    if (!job.stage) return 0;
    const index = STAGES.findIndex(s => s.id === job.stage);
    return index >= 0 ? index : 0;
  };

  const currentStageIndex = getCurrentStageIndex();

  const getStageStatus = (index: number): 'completed' | 'current' | 'pending' | 'failed' => {
    if (job.status === 'failed' && index === currentStageIndex) return 'failed';
    if (index < currentStageIndex) return 'completed';
    if (index === currentStageIndex) return 'current';
    return 'pending';
  };

  const getStageIcon = (status: 'completed' | 'current' | 'pending' | 'failed') => {
    switch (status) {
      case 'completed':
        return <CheckCircle2 className="h-5 w-5 text-green-600 dark:text-green-400" />;
      case 'current':
        return <Loader2 className="h-5 w-5 text-primary animate-spin" />;
      case 'failed':
        return <XCircle className="h-5 w-5 text-destructive" />;
      case 'pending':
        return <Circle className="h-5 w-5 text-muted-foreground/40" />;
    }
  };

  const formatTimestamp = (timestamp?: string) => {
    if (!timestamp) return null;
    const date = new Date(timestamp);
    return date.toLocaleTimeString('en-US', {
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
    });
  };

  const getProgressPercentage = (): number => {
    if (job.status === 'completed') return 100;
    if (job.status === 'failed') return (currentStageIndex / STAGES.length) * 100;
    
    const baseProgress = (currentStageIndex / STAGES.length) * 100;
    const stageProgress = (job.progress || 0) / STAGES.length;
    return Math.min(baseProgress + stageProgress, 99);
  };

  return (
    <Card className={className}>
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <CardTitle className="text-lg">Processing Timeline</CardTitle>
          <Badge variant={job.status === 'failed' ? 'destructive' : 'secondary'}>
            {Math.round(getProgressPercentage())}%
          </Badge>
        </div>
        
        {/* Progress bar */}
        <div className="w-full bg-muted rounded-full h-2 overflow-hidden">
          <div
            className={cn(
              'h-full transition-all duration-300 ease-out rounded-full',
              job.status === 'failed'
                ? 'bg-destructive'
                : 'bg-gradient-to-r from-primary to-primary/80'
            )}
            style={{ width: `${getProgressPercentage()}%` }}
          />
        </div>
      </CardHeader>

      <CardContent className="space-y-4">
        {STAGES.map((stage, index) => {
          const status = getStageStatus(index);
          const isLast = index === STAGES.length - 1;

          return (
            <div key={stage.id} className="relative">
              <div className="flex items-start gap-3">
                {/* Icon */}
                <div className="flex flex-col items-center">
                  <div className={cn(
                    'flex items-center justify-center w-8 h-8 rounded-full border-2',
                    status === 'completed' && 'border-green-600 dark:border-green-400 bg-green-50 dark:bg-green-950',
                    status === 'current' && 'border-primary bg-primary/10',
                    status === 'failed' && 'border-destructive bg-destructive/10',
                    status === 'pending' && 'border-muted bg-muted/20'
                  )}>
                    {getStageIcon(status)}
                  </div>
                  
                  {/* Connector line */}
                  {!isLast && (
                    <div className={cn(
                      'w-0.5 h-12 my-1',
                      status === 'completed' ? 'bg-green-300 dark:bg-green-700' : 'bg-muted'
                    )} />
                  )}
                </div>

                {/* Content */}
                <div className="flex-1 min-w-0 pb-6">
                  <div className="flex items-center gap-2 mb-1">
                    <h4 className={cn(
                      'font-medium',
                      status === 'current' && 'text-primary',
                      status === 'completed' && 'text-green-700 dark:text-green-300',
                      status === 'failed' && 'text-destructive',
                      status === 'pending' && 'text-muted-foreground'
                    )}>
                      {stage.label}
                    </h4>
                    
                    {status === 'current' && job.metadata && (
                      <Badge variant="outline" className="text-xs">
                        {job.metadata.processed_chapters || job.metadata.processed_pages || 0}/
                        {job.metadata.total_chapters || job.metadata.total_pages || 0}
                      </Badge>
                    )}
                  </div>
                  
                  <p className="text-sm text-muted-foreground mb-2">
                    {stage.description}
                  </p>

                  {/* Metadata */}
                  {status === 'current' && job.metadata?.current_chapter && (
                    <div className="text-xs text-muted-foreground">
                      Processing: {job.metadata.current_chapter}
                    </div>
                  )}

                  {/* Timestamp */}
                  {status === 'completed' && job.started_at && (
                    <div className="flex items-center gap-1 text-xs text-muted-foreground">
                      <Clock className="h-3 w-3" />
                      <span>{formatTimestamp(job.started_at)}</span>
                    </div>
                  )}

                  {/* Error message */}
                  {status === 'failed' && job.error_message && (
                    <div className="mt-2 text-xs text-destructive bg-destructive/10 p-2 rounded">
                      {job.error_message}
                    </div>
                  )}
                </div>
              </div>
            </div>
          );
        })}

        {/* Completion timestamp */}
        {job.status === 'completed' && job.completed_at && (
          <div className="pt-2 border-t">
            <div className="flex items-center justify-between text-sm">
              <span className="text-muted-foreground">Completed at</span>
              <span className="font-medium">{formatTimestamp(job.completed_at)}</span>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
