/**
 * UploadZone component — interaction and state transitions.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import UploadZone from '@/components/upload/UploadZone';
import * as clientApi from '@/lib/api/client';

vi.mock('@/lib/api/client', () => ({
  uploadDocument: vi.fn(),
  getErrorMessage: vi.fn((e: unknown) => String(e)),
}));

const mockUpload = clientApi.uploadDocument as ReturnType<typeof vi.fn>;

describe('UploadZone', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders the idle drop zone', () => {
    render(<UploadZone />);
    expect(screen.getByText(/Drop your PDF here/i)).toBeInTheDocument();
    expect(screen.getByText(/PDF only/i)).toBeInTheDocument();
  });

  it('shows success state after successful upload', async () => {
    mockUpload.mockResolvedValue({ document: { id: 'doc-123' } });

    render(<UploadZone />);

    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    const file  = new File(['%PDF-1.4'], 'test.pdf', { type: 'application/pdf' });

    Object.defineProperty(input, 'files', { value: [file], configurable: true });
    fireEvent.change(input);

    await waitFor(() => {
      expect(screen.getByText(/Conversion started/i)).toBeInTheDocument();
    });

    expect(mockUpload).toHaveBeenCalledWith(file, expect.any(Function));
  });

  it('shows error state when upload fails', async () => {
    mockUpload.mockRejectedValue('Network error');
    vi.mocked(clientApi.getErrorMessage).mockReturnValue('Network error');

    render(<UploadZone />);

    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    const file  = new File(['%PDF'], 'fail.pdf', { type: 'application/pdf' });
    Object.defineProperty(input, 'files', { value: [file], configurable: true });
    fireEvent.change(input);

    await waitFor(() => {
      expect(screen.getByText(/Upload failed/i)).toBeInTheDocument();
    });
  });
});
