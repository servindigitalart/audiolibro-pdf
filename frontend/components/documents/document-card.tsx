/**
 * Document Card Component
 * ======================
 * Individual document card for the documents list
 */

'use client';

import { Document, ProcessingJob } from '@/lib/document-service';
import { Card, CardContent } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { StatusBadge } from './status-badge';
import { ProgressIndicator } from './progress-indicator';
import { FileText, Download, Eye, Calendar, HardDrive, Play, Clock } from 'lucide-react';
import Link from 'next/link';
import { cn } from '@/lib/utils';
import { isProcessing, canDownload } from '@/lib/document-status';

interface DocumentCardProps {
  document: Document;
  job?: ProcessingJob | null;
  onDownload?: () => void;
  className?: string;
}

export function DocumentCard({ document, job, onDownload, className }: DocumentCardProps) {
  const showProgress = job && isProcessing(document.status);
  const canDownloadAudio = canDownload(document.status) && document.audiobook_url;
  const isCompleted = document.status === 'completed';

  const formatDate = (dateString: string) => {
    return new Date(dateString).toLocaleDateString('en-US', {
      month: 'short',
      day: 'numeric',
      year: 'numeric',
    });
  };

  const formatFileSize = (bytes: number) => {
    const mb = bytes / 1024 / 1024;
    return `${mb.toFixed(1)} MB`;
  };

  const formatDuration = (seconds?: number) => {
    if (!seconds) return null;
    const hours = Math.floor(seconds / 3600);
    const mins = Math.floor((seconds % 3600) / 60);
    if (hours > 0) {
      return `${hours}h ${mins}m`;
    }
    return `${mins}m`;
  };

  return (
    <Card className={cn(
      'hover:shadow-lg transition-all duration-200 group',
      isCompleted && 'hover:border-primary/50',
      className
    )}>
      <CardContent className="p-6">
        <div className="space-y-4">
          {/* Header with Thumbnail Effect */}
          <div className="relative">
            <div className={cn(
              "flex items-start justify-between gap-4 p-4 rounded-lg transition-colors",
              isCompleted ? "bg-gradient-to-br from-primary/5 to-primary/10" : "bg-muted/30"
            )}>
              <div className="flex items-start gap-3 flex-1 min-w-0">
                <div className={cn(
                  "p-2.5 rounded-lg transition-colors",
                  isCompleted ? "bg-primary/20 group-hover:bg-primary/30" : "bg-background/50"
                )}>
                  <FileText className={cn(
                    "h-6 w-6 transition-colors",
                    isCompleted ? "text-primary" : "text-muted-foreground"
                  )} />
                </div>
                <div className="flex-1 min-w-0">
                  <h3 className="font-semibold text-lg mb-1 line-clamp-2 group-hover:text-primary transition-colors">
                    {document.title}
                  </h3>
                  <p className="text-sm text-muted-foreground truncate">
                    {document.filename}
                  </p>
                </div>
              </div>
              <StatusBadge status={document.status} />
            </div>
            
            {/* Quick Play Button Overlay (for completed docs) */}
            {isCompleted && (
              <Link 
                href={`/documents/${document.id}`}
                className="absolute inset-0 flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity bg-black/20 rounded-lg"
              >
                <div className="bg-primary text-primary-foreground rounded-full p-3 shadow-lg transform group-hover:scale-110 transition-transform">
                  <Play className="h-6 w-6 fill-current" />
                </div>
              </Link>
            )}
          </div>

          {/* Metadata */}
          <div className="flex flex-wrap gap-3 text-sm text-muted-foreground">
            <div className="flex items-center gap-1">
              <Calendar className="h-3.5 w-3.5" />
              <span>{formatDate(document.upload_date)}</span>
            </div>
            <div className="flex items-center gap-1">
              <HardDrive className="h-3.5 w-3.5" />
              <span>{formatFileSize(document.file_size)}</span>
            </div>
            {document.metadata?.pages && (
              <span className="flex items-center">
                {document.metadata.pages} pages
              </span>
            )}
            {document.metadata?.chapters && (
              <span className="flex items-center">
                •  {document.metadata.chapters} chapters
              </span>
            )}
          </div>

          {/* Duration Badge (prominent for completed docs) */}
          {document.metadata?.duration_seconds && isCompleted && (
            <div className="flex items-center gap-2 px-3 py-2 bg-primary/10 rounded-lg border border-primary/20">
              <Clock className="h-4 w-4 text-primary" />
              <span className="text-sm font-medium text-primary">
                {formatDuration(document.metadata.duration_seconds)} audiobook
              </span>
            </div>
          )}

          {/* Progress (if processing) */}
          {showProgress && job && (
            <ProgressIndicator job={job} showDetails={false} />
          )}

          {/* Error Message */}
          {document.status === 'failed' && document.error_message && (
            <div className="text-sm text-destructive bg-destructive/10 p-3 rounded-lg">
              {document.error_message}
            </div>
          )}

          {/* Actions */}
          <div className="flex items-center gap-2 pt-2">
            {isCompleted ? (
              <>
                <Button asChild size="sm" className="flex-1">
                  <Link href={`/documents/${document.id}`}>
                    <Play className="h-4 w-4 mr-2 fill-current" />
                    Play Now
                  </Link>
                </Button>
                {canDownloadAudio && (
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={onDownload}
                    className="flex-shrink-0"
                  >
                    <Download className="h-4 w-4" />
                  </Button>
                )}
              </>
            ) : (
              <Button asChild variant="outline" size="sm" className="w-full">
                <Link href={`/documents/${document.id}`}>
                  <Eye className="h-4 w-4 mr-2" />
                  View Details
                </Link>
              </Button>
            )}
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
