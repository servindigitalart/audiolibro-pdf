/**
 * Document Service
 * ===============
 * API service layer for document operations
 */

import { apiClient } from './api-client';
import { AxiosProgressEvent } from 'axios';

// Types
export interface Document {
  id: string;
  title: string;
  filename: string;
  file_size: number;
  status: 'pending' | 'processing' | 'completed' | 'failed';
  upload_date: string;
  completed_date?: string;
  error_message?: string;
  audiobook_url?: string;
  metadata?: {
    pages?: number;
    chapters?: number;
    duration_seconds?: number;
    file_type?: string;
  };
}

export interface ProcessingJob {
  id: string;
  document_id: string;
  status: 'queued' | 'processing' | 'completed' | 'failed';
  stage?: 'analyzing' | 'detecting_chapters' | 'generating_audio' | 'finalizing';
  progress: number;
  started_at?: string;
  completed_at?: string;
  error_message?: string;
  metadata?: {
    total_pages?: number;
    processed_pages?: number;
    total_chapters?: number;
    processed_chapters?: number;
    current_chapter?: string;
  };
}

export interface Chapter {
  id: string;
  document_id: string;
  chapter_number: number;
  title: string;
  start_page: number;
  end_page: number;
  confidence_score: number;
  audio_url?: string;
  duration_seconds?: number;
  status: 'pending' | 'processing' | 'completed' | 'failed';
}

export interface UploadProgress {
  loaded: number;
  total: number;
  percentage: number;
}

/**
 * Upload a document
 */
export async function uploadDocument(
  file: File,
  onProgress?: (progress: UploadProgress) => void
): Promise<{ document: Document; job: ProcessingJob }> {
  const formData = new FormData();
  formData.append('file', file);

  const response = await apiClient.post('/documents/upload', formData, {
    headers: {
      'Content-Type': 'multipart/form-data',
    },
    onUploadProgress: (progressEvent: AxiosProgressEvent) => {
      if (onProgress && progressEvent.total) {
        const percentage = Math.round((progressEvent.loaded * 100) / progressEvent.total);
        onProgress({
          loaded: progressEvent.loaded,
          total: progressEvent.total,
          percentage,
        });
      }
    },
  });

  return response.data;
}

/**
 * Get all documents for the current user
 */
export async function getDocuments(): Promise<Document[]> {
  const response = await apiClient.get('/documents');
  return response.data;
}

/**
 * Get a specific document by ID
 */
export async function getDocument(id: string): Promise<Document> {
  const response = await apiClient.get(`/documents/${id}`);
  return response.data;
}

/**
 * Delete a document
 */
export async function deleteDocument(id: string): Promise<void> {
  await apiClient.delete(`/documents/${id}`);
}

/**
 * Get processing job for a document
 */
export async function getProcessingJob(documentId: string): Promise<ProcessingJob | null> {
  try {
    const response = await apiClient.get(`/documents/${documentId}/job`);
    return response.data;
  } catch {
    // If no job exists, return null
    return null;
  }
}

/**
 * Retry processing a failed document
 */
export async function retryProcessing(documentId: string): Promise<ProcessingJob> {
  const response = await apiClient.post(`/documents/${documentId}/retry`);
  return response.data;
}

/**
 * Get chapters for a document
 */
export async function getChapters(documentId: string): Promise<Chapter[]> {
  const response = await apiClient.get(`/documents/${documentId}/chapters`);
  return response.data;
}

/**
 * Download audiobook
 */
export async function downloadAudiobook(documentId: string): Promise<Blob> {
  const response = await apiClient.get(`/documents/${documentId}/download`, {
    responseType: 'blob',
  });
  return response.data;
}

/**
 * Trigger download in browser
 */
export function triggerDownload(blob: Blob, filename: string): void {
  const url = window.URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  window.URL.revokeObjectURL(url);
}
