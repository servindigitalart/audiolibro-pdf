/**
 * Chapter List Component
 * =====================
 * Displays detected chapters with metadata
 */

'use client';

import { Chapter } from '@/lib/document-service';
import { Card } from '@/components/ui/card';
import { StatusBadge } from './status-badge';
import { Play, FileText } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';

interface ChapterListProps {
  chapters: Chapter[];
  className?: string;
}

export function ChapterList({ chapters, className }: ChapterListProps) {
  if (chapters.length === 0) {
    return (
      <Card className={cn('p-6', className)}>
        <div className="text-center text-muted-foreground">
          <FileText className="h-12 w-12 mx-auto mb-3 opacity-50" />
          <p>No chapters detected yet</p>
          <p className="text-sm mt-1">Chapters will appear here as they are processed</p>
        </div>
      </Card>
    );
  }

  const formatDuration = (seconds?: number) => {
    if (!seconds) return 'N/A';
    const mins = Math.floor(seconds / 60);
    const secs = seconds % 60;
    return `${mins}:${secs.toString().padStart(2, '0')}`;
  };

  const getConfidenceColor = (score: number) => {
    if (score >= 0.8) return 'text-green-600 dark:text-green-400';
    if (score >= 0.6) return 'text-yellow-600 dark:text-yellow-400';
    return 'text-red-600 dark:text-red-400';
  };

  return (
    <div className={cn('space-y-3', className)}>
      {chapters.map((chapter) => (
        <Card key={chapter.id} className="p-4">
          <div className="flex items-start justify-between gap-4">
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2 mb-2">
                <span className="font-mono text-sm text-muted-foreground">
                  Ch. {chapter.chapter_number}
                </span>
                <StatusBadge status={chapter.status} showIcon={false} />
              </div>

              <h4 className="font-semibold mb-1 truncate">{chapter.title}</h4>

              <div className="flex flex-wrap gap-3 text-sm text-muted-foreground">
                <span>Pages {chapter.start_page}-{chapter.end_page}</span>
                <span className={cn('font-medium', getConfidenceColor(chapter.confidence_score))}>
                  {Math.round(chapter.confidence_score * 100)}% confidence
                </span>
                {chapter.duration_seconds && (
                  <span>{formatDuration(chapter.duration_seconds)}</span>
                )}
              </div>
            </div>

            {chapter.audio_url && chapter.status === 'completed' && (
              <Button
                size="sm"
                variant="outline"
                onClick={() => {
                  // Simple audio preview
                  const audio = new Audio(chapter.audio_url);
                  audio.play();
                }}
              >
                <Play className="h-4 w-4 mr-1" />
                Preview
              </Button>
            )}
          </div>
        </Card>
      ))}
    </div>
  );
}
