/**
 * Document Detail Page
 * ===================
 * Premium audiobook experience with player, chapters, and processing status.
 */

'use client';

import { useQuery } from '@tanstack/react-query';
import { useParams } from 'next/navigation';
import {
  getDocument,
  getChapters,
  downloadAudiobook,
  triggerDownload,
  retryProcessing,
} from '@/lib/document-service';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { StatusBadge } from '@/components/documents/status-badge';
import { AudioPlayer } from '@/components/player/audio-player';
import { ChapterNavigation } from '@/components/player/chapter-navigation';
import { ProcessingTimeline } from '@/components/player/processing-timeline';
import { Skeleton } from '@/components/ui/skeleton';
import {
  ArrowLeft,
  Download,
  RefreshCw,
  FileText,
  Calendar,
  HardDrive,
  BookOpen,
  Clock,
  AlertCircle,
} from 'lucide-react';
import Link from 'next/link';
import { isProcessing, canDownload, canRetry } from '@/lib/document-status';
import { useState, useCallback, useEffect } from 'react';
import { track } from '@/lib/analytics';

export default function DocumentDetailPage() {
  const params = useParams();
  const documentId = params?.id as string;
  const [isRetrying, setIsRetrying] = useState(false);
  const [isDownloading, setIsDownloading] = useState(false);
  const [currentChapter, setCurrentChapter] = useState<number | null>(null);
  const [wasCancelled, setWasCancelled] = useState(false);

  // Fetch document (polling while processing)
  const { data: document, isLoading: isLoadingDoc, error: docError, refetch: refetchDoc } = useQuery({
    queryKey: ['document', documentId],
    queryFn: () => getDocument(documentId),
    enabled: !!documentId,
    refetchInterval: (query) => {
      const doc = query.state.data;
      return doc && isProcessing(doc.status) ? 3000 : false;
    },
  });

  // Fetch chapters (only when completed)
  const { data: chapters } = useQuery({
    queryKey: ['chapters', documentId],
    queryFn: () => getChapters(documentId),
    enabled: !!documentId && document?.status === 'completed',
  });

  // Track page view for processing screen
  useEffect(() => {
    if (document && isProcessing(document.status)) {
      track('processing_progress_view_opened', { document_id: documentId });
    }
  }, [documentId, document?.status]);

  const handleDownload = async () => {
    if (!document) return;
    setIsDownloading(true);
    try {
      const blob = await downloadAudiobook(documentId);
      triggerDownload(blob, `${document.title}.mp3`);
    } catch {
      // error handled silently — user can retry download
    } finally {
      setIsDownloading(false);
    }
  };

  const handleRetry = async () => {
    setIsRetrying(true);
    setWasCancelled(false);
    try {
      await retryProcessing(documentId);
      await refetchDoc();
    } catch {
      // error handled silently
    } finally {
      setIsRetrying(false);
    }
  };

  const handleChapterSelect = useCallback((chapterNumber: number, timestamp: number) => {
    setCurrentChapter(chapterNumber);
    window.dispatchEvent(new CustomEvent('seek-to-timestamp', { detail: { timestamp } }));
  }, []);

  const handleChapterChange = useCallback((chapterNumber: number) => {
    setCurrentChapter(chapterNumber);
  }, []);

  const handleCancelled = useCallback(() => {
    setWasCancelled(true);
    refetchDoc();
  }, [refetchDoc]);

  // Format utilities
  const formatDate = (dateString: string) =>
    new Date(dateString).toLocaleDateString('en-US', {
      month: 'long', day: 'numeric', year: 'numeric',
      hour: '2-digit', minute: '2-digit',
    });
  const formatFileSize = (bytes: number) => `${(bytes / 1024 / 1024).toFixed(2)} MB`;
  const formatDuration = (seconds?: number) => {
    if (!seconds) return 'N/A';
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    return h > 0 ? `${h}h ${m}m` : `${m}m`;
  };

  if (isLoadingDoc) {
    return (
      <div className="space-y-6 animate-in fade-in duration-300">
        <Skeleton className="h-8 w-64" />
        <Skeleton className="h-32" />
        <Skeleton className="h-96" />
      </div>
    );
  }

  if (docError || !document) {
    return (
      <div className="space-y-6">
        <Button asChild variant="ghost">
          <Link href="/documents">
            <ArrowLeft className="h-4 w-4 mr-2" />Back to Documents
          </Link>
        </Button>
        <Alert variant="destructive">
          <AlertCircle className="h-4 w-4" />
          <AlertDescription>Failed to load document. Please try again.</AlertDescription>
        </Alert>
      </div>
    );
  }

  const isCompleted = document.status === 'completed';
  const isFailed = document.status === 'failed';
  const isCancelled = document.status === 'cancelled' || wasCancelled;
  const isCurrentlyProcessing = isProcessing(document.status) && !isCancelled;

  return (
    <div className="space-y-6 animate-in fade-in duration-500">
      {/* Header */}
      <div className="space-y-4">
        <Button asChild variant="ghost" size="sm">
          <Link href="/documents">
            <ArrowLeft className="h-4 w-4 mr-2" />Back to Documents
          </Link>
        </Button>

        <div className="flex items-start justify-between gap-4">
          <div className="flex-1 min-w-0 space-y-2">
            <div className="flex items-center gap-3 flex-wrap">
              <h1 className="text-3xl font-bold tracking-tight">{document.title}</h1>
              <StatusBadge status={isCancelled ? 'cancelled' : document.status} />
            </div>
            <div className="flex flex-wrap items-center gap-4 text-sm text-muted-foreground">
              <div className="flex items-center gap-1">
                <Calendar className="h-4 w-4" />
                <span>{formatDate(document.upload_date)}</span>
              </div>
              <div className="flex items-center gap-1">
                <HardDrive className="h-4 w-4" />
                <span>{formatFileSize(document.file_size)}</span>
              </div>
              {document.metadata?.pages && (
                <div className="flex items-center gap-1">
                  <FileText className="h-4 w-4" />
                  <span>{document.metadata.pages} pages</span>
                </div>
              )}
              {document.metadata?.chapters && (
                <div className="flex items-center gap-1">
                  <BookOpen className="h-4 w-4" />
                  <span>{document.metadata.chapters} chapters</span>
                </div>
              )}
              {document.metadata?.duration_seconds && (
                <div className="flex items-center gap-1">
                  <Clock className="h-4 w-4" />
                  <span>{formatDuration(document.metadata.duration_seconds)}</span>
                </div>
              )}
            </div>
          </div>
        </div>

        {/* Actions */}
        <div className="flex flex-wrap gap-3">
          {canDownload(document.status) && document.audiobook_url && (
            <Button onClick={handleDownload} disabled={isDownloading}>
              <Download className="h-4 w-4 mr-2" />
              {isDownloading ? 'Downloading…' : 'Download MP3'}
            </Button>
          )}
          {(canRetry(document.status) || isCancelled) && (
            <Button onClick={handleRetry} disabled={isRetrying} variant="outline">
              <RefreshCw className={`h-4 w-4 mr-2 ${isRetrying ? 'animate-spin' : ''}`} />
              {isCancelled ? 'Restart conversion' : 'Retry processing'}
            </Button>
          )}
        </div>
      </div>

      {/* Error alert */}
      {isFailed && document.error_message && (
        <Alert variant="destructive">
          <AlertCircle className="h-4 w-4" />
          <AlertDescription>{document.error_message}</AlertDescription>
        </Alert>
      )}

      {/* Processing timeline — self-contained: has its own polling + cancel */}
      {isCurrentlyProcessing && (
        <ProcessingTimeline
          documentId={documentId}
          onCancelled={handleCancelled}
        />
      )}

      {/* Audio Player & Chapters — completed only */}
      {isCompleted && document.audiobook_url && (
        <div className="space-y-4">
          {/* Mobile chapters button — sits above player */}
          {chapters && chapters.length > 1 && (
            <div className="lg:hidden">
              <ChapterNavigation
                chapters={chapters}
                currentChapter={currentChapter}
                onChapterSelect={handleChapterSelect}
              />
            </div>
          )}

          <div className="grid gap-6 lg:grid-cols-3">
            <div className="lg:col-span-2 space-y-6">
              <AudioPlayer
                audioUrl={document.audiobook_url}
                chapters={chapters}
                documentId={documentId}
                title={document.title}
                onChapterChange={handleChapterChange}
              />

              {/* Document Details */}
              <Card>
                <CardHeader>
                  <CardTitle>Document Details</CardTitle>
                </CardHeader>
                <CardContent>
                  <dl className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    <div className="space-y-1">
                      <dt className="text-sm text-muted-foreground">Original File</dt>
                      <dd className="font-medium">{document.filename}</dd>
                    </div>
                    <div className="space-y-1">
                      <dt className="text-sm text-muted-foreground">Upload Date</dt>
                      <dd className="font-medium">{formatDate(document.upload_date)}</dd>
                    </div>
                    {document.completed_date && (
                      <div className="space-y-1">
                        <dt className="text-sm text-muted-foreground">Completed Date</dt>
                        <dd className="font-medium">{formatDate(document.completed_date)}</dd>
                      </div>
                    )}
                    <div className="space-y-1">
                      <dt className="text-sm text-muted-foreground">File Size</dt>
                      <dd className="font-medium">{formatFileSize(document.file_size)}</dd>
                    </div>
                    {document.metadata?.pages && (
                      <div className="space-y-1">
                        <dt className="text-sm text-muted-foreground">Total Pages</dt>
                        <dd className="font-medium">{document.metadata.pages}</dd>
                      </div>
                    )}
                    {document.metadata?.duration_seconds && (
                      <div className="space-y-1">
                        <dt className="text-sm text-muted-foreground">Total Duration</dt>
                        <dd className="font-medium">
                          {formatDuration(document.metadata.duration_seconds)}
                        </dd>
                      </div>
                    )}
                  </dl>
                </CardContent>
              </Card>
            </div>

            {/* Desktop chapter sidebar */}
            <div className="lg:col-span-1 hidden lg:block">
              {chapters && chapters.length > 0 && (
                <ChapterNavigation
                  chapters={chapters}
                  currentChapter={currentChapter}
                  onChapterSelect={handleChapterSelect}
                />
              )}
            </div>
          </div>
        </div>
      )}

      {/* Queued / pending state */}
      {document.status === 'pending' && !isCurrentlyProcessing && (
        <Card>
          <CardContent className="py-12 text-center">
            <div className="inline-flex items-center justify-center w-16 h-16 rounded-full bg-primary/10 mb-4">
              <Clock className="h-8 w-8 text-primary animate-pulse" />
            </div>
            <h3 className="text-lg font-semibold mb-2">Processing Queued</h3>
            <p className="text-muted-foreground max-w-md mx-auto">
              Your document is in the queue and will start processing soon. This page updates automatically.
            </p>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
