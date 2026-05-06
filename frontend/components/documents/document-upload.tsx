/**
 * Document Upload Component
 * ========================
 * Drag & drop file upload with progress tracking
 */

'use client';

import { useState, useCallback } from 'react';
import { useDropzone, FileRejection } from 'react-dropzone';
import { Card } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Progress } from '@/components/ui/progress';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Upload, FileText, X, AlertCircle, CheckCircle2 } from 'lucide-react';
import { uploadDocument, UploadProgress } from '@/lib/document-service';
import { cn } from '@/lib/utils';

interface DocumentUploadProps {
  onUploadComplete?: () => void;
  className?: string;
}

const MAX_FILE_SIZE = 50 * 1024 * 1024; // 50MB
const ACCEPTED_TYPES = {
  'application/pdf': ['.pdf'],
};

export function DocumentUpload({ onUploadComplete, className }: DocumentUploadProps) {
  const [uploading, setUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState<UploadProgress | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);

  const handleUpload = useCallback(async (file: File) => {
    setError(null);
    setSuccess(false);
    setUploading(true);
    setUploadProgress({ loaded: 0, total: file.size, percentage: 0 });

    try {
      await uploadDocument(file, (progress) => {
        setUploadProgress(progress);
      });

      setSuccess(true);
      setSelectedFile(null);
      setUploadProgress(null);

      // Call callback after short delay to show success message
      setTimeout(() => {
        setSuccess(false);
        onUploadComplete?.();
      }, 2000);
    } catch (err) {
      const errorMessage = err instanceof Error && 'response' in err 
        ? ((err as { response?: { data?: { detail?: string } } }).response?.data?.detail || 'Failed to upload document')
        : 'Failed to upload document';
      setError(errorMessage);
      setUploadProgress(null);
    } finally {
      setUploading(false);
    }
  }, [onUploadComplete]);

  const onDrop = useCallback((acceptedFiles: File[], rejectedFiles: FileRejection[]) => {
    setError(null);

    if (rejectedFiles.length > 0) {
      const rejection = rejectedFiles[0];
      if (rejection.errors[0]?.code === 'file-too-large') {
        setError(`File is too large. Maximum size is ${MAX_FILE_SIZE / 1024 / 1024}MB`);
      } else if (rejection.errors[0]?.code === 'file-invalid-type') {
        setError('Only PDF files are supported');
      } else {
        setError('Invalid file');
      }
      return;
    }

    if (acceptedFiles.length > 0) {
      const file = acceptedFiles[0];
      setSelectedFile(file);
    }
  }, []);

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: ACCEPTED_TYPES,
    maxSize: MAX_FILE_SIZE,
    maxFiles: 1,
    disabled: uploading,
  });

  const handleRemoveFile = () => {
    setSelectedFile(null);
    setError(null);
  };

  const handleConfirmUpload = () => {
    if (selectedFile) {
      handleUpload(selectedFile);
    }
  };

  return (
    <Card className={cn('p-6', className)}>
      <div className="space-y-4">
        <div>
          <h3 className="text-lg font-semibold mb-1">Upload Document</h3>
          <p className="text-sm text-muted-foreground">
            Upload a PDF to convert into an audiobook
          </p>
        </div>

        {error && (
          <Alert variant="destructive">
            <AlertCircle className="h-4 w-4" />
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}

        {success && (
          <Alert className="border-green-500 bg-green-50 dark:bg-green-950">
            <CheckCircle2 className="h-4 w-4 text-green-600 dark:text-green-400" />
            <AlertDescription className="text-green-600 dark:text-green-400">
              Document uploaded successfully! Processing will begin shortly.
            </AlertDescription>
          </Alert>
        )}

        {!selectedFile && !uploading && (
          <div
            {...getRootProps()}
            className={cn(
              'border-2 border-dashed rounded-lg p-8 text-center cursor-pointer transition-colors',
              isDragActive
                ? 'border-primary bg-primary/5'
                : 'border-muted-foreground/25 hover:border-primary/50'
            )}
          >
            <input {...getInputProps()} />
            <Upload className="h-12 w-12 mx-auto mb-4 text-muted-foreground" />
            {isDragActive ? (
              <p className="text-lg font-medium">Drop your PDF here...</p>
            ) : (
              <>
                <p className="text-lg font-medium mb-1">
                  Drag & drop your PDF here
                </p>
                <p className="text-sm text-muted-foreground mb-4">
                  or click to browse files
                </p>
                <Button type="button" variant="outline">
                  Choose File
                </Button>
              </>
            )}
            <p className="text-xs text-muted-foreground mt-4">
              Maximum file size: {MAX_FILE_SIZE / 1024 / 1024}MB
            </p>
          </div>
        )}

        {selectedFile && !uploading && (
          <div className="border rounded-lg p-4">
            <div className="flex items-center justify-between mb-4">
              <div className="flex items-center gap-3">
                <FileText className="h-8 w-8 text-primary" />
                <div>
                  <p className="font-medium">{selectedFile.name}</p>
                  <p className="text-sm text-muted-foreground">
                    {(selectedFile.size / 1024 / 1024).toFixed(2)} MB
                  </p>
                </div>
              </div>
              <Button
                variant="ghost"
                size="sm"
                onClick={handleRemoveFile}
              >
                <X className="h-4 w-4" />
              </Button>
            </div>
            <Button onClick={handleConfirmUpload} className="w-full">
              <Upload className="h-4 w-4 mr-2" />
              Upload & Process
            </Button>
          </div>
        )}

        {uploading && uploadProgress && (
          <div className="space-y-3">
            <div className="flex items-center gap-3">
              <FileText className="h-8 w-8 text-primary animate-pulse" />
              <div className="flex-1">
                <p className="font-medium mb-1">Uploading...</p>
                <Progress value={uploadProgress.percentage} className="h-2" />
                <p className="text-sm text-muted-foreground mt-1">
                  {uploadProgress.percentage}% • {(uploadProgress.loaded / 1024 / 1024).toFixed(1)} MB of{' '}
                  {(uploadProgress.total / 1024 / 1024).toFixed(1)} MB
                </p>
              </div>
            </div>
          </div>
        )}
      </div>
    </Card>
  );
}
