/**
 * Documents Page
 * =============
 * Document management and upload interface
 */

'use client';

import { useQuery } from '@tanstack/react-query';
import { getDocuments, getProcessingJob, downloadAudiobook, triggerDownload } from '@/lib/document-service';

import { DocumentUpload } from '@/components/documents/document-upload';
import { DocumentCard } from '@/components/documents/document-card';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Skeleton } from '@/components/ui/skeleton';
import { FileText, AlertCircle } from 'lucide-react';
import { isProcessing } from '@/lib/document-status';

export default function DocumentsPage() {
  // Fetch documents
  const { data: documents, isLoading, error, refetch } = useQuery({
    queryKey: ['documents'],
    queryFn: getDocuments,
    refetchInterval: (query) => {
      // Auto-refetch every 5 seconds if any document is processing
      const hasProcessing = query.state.data?.some((doc) => isProcessing(doc.status));
      return hasProcessing ? 5000 : false;
    },
  });

  // Fetch jobs for processing documents
  const processingDocs = documents?.filter((doc) => isProcessing(doc.status)) || [];
  const jobQueries = useQuery({
    queryKey: ['processing-jobs', processingDocs.map((d) => d.id)],
    queryFn: async () => {
      const jobs = await Promise.all(
        processingDocs.map((doc) => getProcessingJob(doc.id))
      );
      return Object.fromEntries(
        processingDocs.map((doc, i) => [doc.id, jobs[i]])
      );
    },
    enabled: processingDocs.length > 0,
    refetchInterval: 3000, // Poll every 3 seconds for job updates
  });

  const handleDownload = async (documentId: string, filename: string) => {
    try {
      const blob = await downloadAudiobook(documentId);
      triggerDownload(blob, `${filename}.mp3`);
    } catch (error) {
      console.error('Download failed:', error);
    }
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Documents</h1>
        <p className="text-muted-foreground mt-2">
          Upload PDFs and convert them into audiobooks
        </p>
      </div>

      {/* Upload Component */}
      <DocumentUpload onUploadComplete={refetch} />

      {/* Error State */}
      {error && (
        <Alert variant="destructive">
          <AlertCircle className="h-4 w-4" />
          <AlertDescription>
            Failed to load documents. Please try refreshing the page.
          </AlertDescription>
        </Alert>
      )}

      {/* Loading State */}
      {isLoading && (
        <div className="grid gap-6 md:grid-cols-2 lg:grid-cols-3">
          {[1, 2, 3].map((i) => (
            <Skeleton key={i} className="h-64" />
          ))}
        </div>
      )}

      {/* Documents Grid */}
      {!isLoading && documents && documents.length > 0 && (
        <div>
          <h2 className="text-xl font-semibold mb-4">Your Documents</h2>
          <div className="grid gap-6 md:grid-cols-2 lg:grid-cols-3">
            {documents.map((doc) => (
              <DocumentCard
                key={doc.id}
                document={doc}
                job={jobQueries.data?.[doc.id]}
                onDownload={() => handleDownload(doc.id, doc.title)}
              />
            ))}
          </div>
        </div>
      )}

      {/* Empty State */}
      {!isLoading && documents && documents.length === 0 && (
        <div className="text-center py-16 animate-in fade-in duration-500">
          <div className="inline-flex items-center justify-center w-20 h-20 rounded-full bg-primary/10 mb-6">
            <FileText className="h-10 w-10 text-primary" />
          </div>
          <h3 className="text-2xl font-bold mb-3">No documents yet</h3>
          <p className="text-muted-foreground max-w-md mx-auto mb-6">
            Upload your first PDF to create an audiobook. Our AI will detect chapters 
            and convert them to high-quality speech.
          </p>
          <div className="flex justify-center">
            <div className="text-left space-y-2 text-sm text-muted-foreground">
              <div className="flex items-center gap-2">
                <div className="h-1.5 w-1.5 rounded-full bg-primary" />
                <span>Automatic chapter detection</span>
              </div>
              <div className="flex items-center gap-2">
                <div className="h-1.5 w-1.5 rounded-full bg-primary" />
                <span>Natural AI voices</span>
              </div>
              <div className="flex items-center gap-2">
                <div className="h-1.5 w-1.5 rounded-full bg-primary" />
                <span>Download as MP3</span>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
