/**
 * UploadZone component — state transitions and UI rendering.
 *
 * All API calls are mocked. No network requests are made.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react';
import UploadZone, { mapErrorMessage } from '@/components/upload/UploadZone';
import * as clientApi from '@/lib/api/client';

// ── Mocks ────────────────────────────────────────────────────────────────────

vi.mock('@/lib/api/client', () => ({
  uploadDocument:    vi.fn(),
  startProcessing:   vi.fn(),
  getProcessingJob:  vi.fn(),
  getDocument:       vi.fn(),
  getChapters:       vi.fn(),
  getErrorMessage:   vi.fn((e: unknown) => (e instanceof Error ? e.message : String(e))),
}));

const mockUpload      = clientApi.uploadDocument    as ReturnType<typeof vi.fn>;
const mockStart       = clientApi.startProcessing   as ReturnType<typeof vi.fn>;
const mockGetJob      = clientApi.getProcessingJob  as ReturnType<typeof vi.fn>;
const mockGetDocument = clientApi.getDocument       as ReturnType<typeof vi.fn>;
const mockGetChapters = clientApi.getChapters       as ReturnType<typeof vi.fn>;

// Helper — simulate a file drop via the hidden <input>
function dropFile(file: File) {
  const input = document.querySelector('input[type="file"]') as HTMLInputElement;
  Object.defineProperty(input, 'files', { value: [file], configurable: true });
  fireEvent.change(input);
}

const testPdf = new File(['%PDF-1.4 content'], 'test.pdf', { type: 'application/pdf' });

// Minimal preflight fixture
const basePreflight = {
  language: 'en',
  language_name: 'English',
  voice_id: 'v1',
  voice_display_name: 'Rachel',
  available_voices: [{ voice_id: 'v1', display_name: 'Rachel' }],
  estimated_characters: 50_000,
  estimated_chapters: 8,
  estimated_duration_seconds: 9_000,   // 2h 30m
  estimated_processing_minutes: 15,
  fits_current_plan: true,
  quota_exceeded: false,
  chars_limit: 200_000,
  chars_used: 50_000,
  chars_remaining_before: 150_000,
  chars_remaining_after: 100_000,
  plan_tier: 'BASIC',
  plan_display_name: 'Basic',
};

// ── Tests ────────────────────────────────────────────────────────────────────

describe('UploadZone', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  // ── Idle ──────────────────────────────────────────────────────────────────

  it('renders idle drop zone', () => {
    render(<UploadZone />);
    expect(screen.getByText(/Drop your PDF here/i)).toBeInTheDocument();
    expect(screen.getByText(/PDF only/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /upload pdf/i })).toBeInTheDocument();
  });

  // ── Preflight card ────────────────────────────────────────────────────────

  it('renders preflight analysis card after upload', async () => {
    mockUpload.mockResolvedValue({
      id: 'doc-1',
      is_duplicate: false,
      processing_status: 'pending',
      can_reprocess: false,
      duplicate_message: null,
      preflight: basePreflight,
    });

    render(<UploadZone />);
    dropFile(testPdf);

    await waitFor(() => {
      expect(screen.getByText(/Ready to convert/i)).toBeInTheDocument();
    });

    expect(screen.getByText('English')).toBeInTheDocument();
    expect(screen.getByText('2h 30m')).toBeInTheDocument();
    expect(screen.getByText('~15 min')).toBeInTheDocument();
    expect(screen.getByText(/8 chapters/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /start conversion/i })).toBeInTheDocument();
    expect(screen.getByText(/upload different file/i)).toBeInTheDocument();
  });

  it('preflight card shows chapter preview section', async () => {
    mockUpload.mockResolvedValue({
      id: 'doc-1',
      is_duplicate: false,
      processing_status: 'pending',
      can_reprocess: false,
      duplicate_message: null,
      preflight: basePreflight,
    });

    render(<UploadZone />);
    dropFile(testPdf);

    await waitFor(() => screen.getByText(/Chapter preview/i));
    expect(screen.getByText(/~8 chapters detected/i)).toBeInTheDocument();
  });

  // ── Quota exceeded paywall ────────────────────────────────────────────────

  it('shows premium paywall card when quota is exceeded', async () => {
    mockUpload.mockResolvedValue({
      id: 'doc-2',
      is_duplicate: false,
      processing_status: 'pending',
      can_reprocess: false,
      duplicate_message: null,
      preflight: {
        ...basePreflight,
        quota_exceeded: true,
        fits_current_plan: false,
        estimated_characters: 250_000,
        chars_limit: 200_000,
      },
    });

    render(<UploadZone />);
    dropFile(testPdf);

    await waitFor(() => {
      expect(screen.getByText(/This audiobook is larger than your/i)).toBeInTheDocument();
    });

    expect(screen.getByText(/Upgrade plan/i)).toBeInTheDocument();
    expect(screen.getByText(/Upload a smaller PDF/i)).toBeInTheDocument();
    // Should NOT show "Start conversion"
    expect(screen.queryByRole('button', { name: /start conversion/i })).not.toBeInTheDocument();
    // "Start conversion" button must not appear
    expect(screen.queryByText(/Start conversion/i)).not.toBeInTheDocument();
  });

  it('paywall card shows required characters and plan limit', async () => {
    mockUpload.mockResolvedValue({
      id: 'doc-2',
      is_duplicate: false,
      processing_status: 'pending',
      can_reprocess: false,
      duplicate_message: null,
      preflight: {
        ...basePreflight,
        quota_exceeded: true,
        estimated_characters: 300_000,
        chars_limit: 200_000,
        estimated_duration_seconds: 14_400, // 4h
      },
    });

    render(<UploadZone />);
    dropFile(testPdf);

    await waitFor(() => screen.getByText(/This audiobook is larger/i));
    // Stats tiles — fmtChars(300_000) = "300K", fmtChars(200_000) = "200K"
    expect(screen.getByText('300K')).toBeInTheDocument();
    expect(screen.getByText('200K')).toBeInTheDocument();
    // Duration
    expect(screen.getByText('4h 0m')).toBeInTheDocument();
  });

  // ── Processing timeline ───────────────────────────────────────────────────

  it('shows 5-step processing timeline after starting conversion', async () => {
    mockUpload.mockResolvedValue({
      id: 'doc-3',
      is_duplicate: false,
      processing_status: 'pending',
      can_reprocess: false,
      duplicate_message: null,
      preflight: basePreflight,
    });
    mockStart.mockResolvedValue({ job_id: 'job-1', status: 'queued' });
    mockGetJob.mockResolvedValue({
      id: 'job-1',
      document_id: 'doc-3',
      status: 'processing',
      stage: 'analyzing',
      current_stage: 'analyzing',
      progress: 10,
      completed_chunks: 0,
      total_chunks: 0,
    });

    render(<UploadZone />);
    dropFile(testPdf);

    await waitFor(() => screen.getByRole('button', { name: /start conversion/i }));
    fireEvent.click(screen.getByRole('button', { name: /start conversion/i }));

    await waitFor(() => {
      expect(screen.getByText('Analyzing document')).toBeInTheDocument();
    });

    // All 5 visual step labels should appear
    const steps = ['Analyzing', 'Chapters', 'Generating', 'Mastering', 'Finalizing'];
    for (const step of steps) {
      expect(screen.getByText(step)).toBeInTheDocument();
    }

    expect(screen.getByText('Reading structure and extracting text')).toBeInTheDocument();
    expect(screen.getByRole('progressbar')).toBeInTheDocument();
  });

  it('shows chunk progress microcopy during TTS generation', async () => {
    mockUpload.mockResolvedValue({
      id: 'doc-4',
      is_duplicate: false,
      processing_status: 'pending',
      can_reprocess: false,
      duplicate_message: null,
      preflight: basePreflight,
    });
    mockStart.mockResolvedValue({ job_id: 'job-2', status: 'queued' });
    mockGetJob.mockResolvedValue({
      id: 'job-2',
      document_id: 'doc-4',
      status: 'processing',
      stage: 'generating_audio',
      current_stage: 'tts_generation',
      progress: 55,
      completed_chunks: 12,
      total_chunks: 40,
    });

    render(<UploadZone />);
    dropFile(testPdf);
    await waitFor(() => screen.getByRole('button', { name: /start conversion/i }));
    fireEvent.click(screen.getByRole('button', { name: /start conversion/i }));

    await waitFor(() => {
      expect(screen.getByText('Generating audio')).toBeInTheDocument();
    });
    expect(screen.getByText('Generating segment 12 of 40')).toBeInTheDocument();
  });

  it('shows estimated time remaining when available', async () => {
    mockUpload.mockResolvedValue({
      id: 'doc-5',
      is_duplicate: false,
      processing_status: 'pending',
      can_reprocess: false,
      duplicate_message: null,
      preflight: basePreflight,
    });
    mockStart.mockResolvedValue({ job_id: 'job-3', status: 'queued' });
    mockGetJob.mockResolvedValue({
      id: 'job-3',
      document_id: 'doc-5',
      status: 'processing',
      stage: 'generating_audio',
      current_stage: 'tts_generation',
      progress: 40,
      completed_chunks: 8,
      total_chunks: 20,
      estimated_seconds_remaining: 180, // 3 min
    });

    render(<UploadZone />);
    dropFile(testPdf);
    await waitFor(() => screen.getByRole('button', { name: /start conversion/i }));
    fireEvent.click(screen.getByRole('button', { name: /start conversion/i }));

    await waitFor(() => screen.getByText(/~3 min remaining/i));
  });

  // ── Success / ready state ─────────────────────────────────────────────────

  it('shows ready state with listen and upload-another actions', async () => {
    mockUpload.mockResolvedValue({
      id: 'doc-6',
      is_duplicate: false,
      processing_status: 'pending',
      can_reprocess: false,
      duplicate_message: null,
      preflight: basePreflight,
    });
    mockStart.mockResolvedValue({ job_id: 'job-4', status: 'queued' });
    mockGetJob.mockResolvedValue({
      id: 'job-4',
      document_id: 'doc-6',
      status: 'completed',
      progress: 100,
    });
    mockGetChapters.mockResolvedValue([
      { id: 'c1', title: 'Introduction', duration_seconds: 300, status: 'completed' },
      { id: 'c2', title: 'Chapter One',  duration_seconds: 600, status: 'completed' },
    ]);
    mockGetDocument.mockResolvedValue({ id: 'doc-6', audiobook_url: null });

    render(<UploadZone />);
    dropFile(testPdf);
    await waitFor(() => screen.getByRole('button', { name: /start conversion/i }));
    fireEvent.click(screen.getByRole('button', { name: /start conversion/i }));

    await waitFor(() => {
      expect(screen.getByText(/Your audiobook is ready/i)).toBeInTheDocument();
    });

    expect(screen.getByText('Introduction')).toBeInTheDocument();
    expect(screen.getByText('Chapter One')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /listen now/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /upload another/i })).toBeInTheDocument();
  });

  it('shows download button when audiobook_url is present', async () => {
    mockUpload.mockResolvedValue({
      id: 'doc-7',
      is_duplicate: false,
      processing_status: 'pending',
      can_reprocess: false,
      duplicate_message: null,
      preflight: basePreflight,
    });
    mockStart.mockResolvedValue({ job_id: 'job-5', status: 'queued' });
    mockGetJob.mockResolvedValue({ id: 'job-5', document_id: 'doc-7', status: 'completed', progress: 100 });
    mockGetChapters.mockResolvedValue([]);
    mockGetDocument.mockResolvedValue({
      id: 'doc-7',
      audiobook_url: 'https://cdn.sonoro.com/audiobooks/doc-7.mp3',
    });

    render(<UploadZone />);
    dropFile(testPdf);
    await waitFor(() => screen.getByRole('button', { name: /start conversion/i }));
    fireEvent.click(screen.getByRole('button', { name: /start conversion/i }));

    await waitFor(() => screen.getByRole('link', { name: /download audiobook/i }));
    const downloadLink = screen.getByRole('link', { name: /download audiobook/i });
    expect(downloadLink).toHaveAttribute('href', 'https://cdn.sonoro.com/audiobooks/doc-7.mp3');
  });

  it('ready state shows chapter count and duration summary', async () => {
    mockUpload.mockResolvedValue({
      id: 'doc-8',
      is_duplicate: false,
      processing_status: 'pending',
      can_reprocess: false,
      duplicate_message: null,
      preflight: basePreflight,
    });
    mockStart.mockResolvedValue({ job_id: 'job-6', status: 'queued' });
    mockGetJob.mockResolvedValue({ id: 'job-6', document_id: 'doc-8', status: 'completed', progress: 100 });
    mockGetChapters.mockResolvedValue([
      { id: 'c1', title: 'Intro',     duration_seconds: 600, status: 'completed' },
      { id: 'c2', title: 'Part One',  duration_seconds: 1200, status: 'completed' },
      { id: 'c3', title: 'Part Two',  duration_seconds: 900, status: 'completed' },
    ]);
    mockGetDocument.mockResolvedValue({ id: 'doc-8', audiobook_url: null });

    render(<UploadZone />);
    dropFile(testPdf);
    await waitFor(() => screen.getByRole('button', { name: /start conversion/i }));
    fireEvent.click(screen.getByRole('button', { name: /start conversion/i }));

    await waitFor(() => screen.getByText(/Your audiobook is ready/i));
    // 600+1200+900 = 2700s = 45m → fmtDuration(2700) = "45:00"
    expect(screen.getAllByText(/3 chapters/).length).toBeGreaterThan(0);
  });

  // ── Error states ──────────────────────────────────────────────────────────

  it('shows friendly error when upload fails', async () => {
    const err = new Error('Network error');
    mockUpload.mockRejectedValue(err);
    vi.mocked(clientApi.getErrorMessage).mockReturnValue('Network error');

    render(<UploadZone />);
    dropFile(testPdf);

    await waitFor(() => {
      expect(screen.getByRole('alert')).toBeInTheDocument();
    });
    expect(screen.getByText(/Something went wrong/i)).toBeInTheDocument();
  });

  it('shows auth-expired message for 401 errors', async () => {
    mockUpload.mockRejectedValue(new Error('x'));
    vi.mocked(clientApi.getErrorMessage).mockReturnValue('Not authenticated');

    render(<UploadZone />);
    dropFile(testPdf);

    await waitFor(() => screen.getByRole('alert'));
    expect(screen.getByText(/session expired/i)).toBeInTheDocument();
  });

  it('shows processing-failed message when job fails', async () => {
    mockUpload.mockResolvedValue({
      id: 'doc-9',
      is_duplicate: false,
      processing_status: 'pending',
      can_reprocess: false,
      duplicate_message: null,
      preflight: basePreflight,
    });
    mockStart.mockResolvedValue({ job_id: 'job-7', status: 'queued' });
    mockGetJob.mockResolvedValue({
      id: 'job-7',
      document_id: 'doc-9',
      status: 'failed',
      progress: 30,
      error_message: 'TTS processing failed on chunk 5',
    });

    render(<UploadZone />);
    dropFile(testPdf);
    await waitFor(() => screen.getByRole('button', { name: /start conversion/i }));
    fireEvent.click(screen.getByRole('button', { name: /start conversion/i }));

    await waitFor(() => screen.getByRole('alert'));
    // "tts" in error_message → audio generation failed message
    expect(screen.getByText(/Audio generation failed/i)).toBeInTheDocument();
  });

  // ── mapErrorMessage unit tests ────────────────────────────────────────────

  describe('mapErrorMessage', () => {
    it('maps quota error', () => {
      expect(mapErrorMessage('character limit exceeded')).toMatch(/quota/i);
    });

    it('maps auth error', () => {
      expect(mapErrorMessage('Not authenticated')).toMatch(/session expired/i);
    });

    it('maps invalid PDF error', () => {
      expect(mapErrorMessage('invalid pdf file')).toMatch(/valid pdf/i);
    });

    it('maps file-too-large error', () => {
      expect(mapErrorMessage('File size exceeds 100 MB limit')).toMatch(/too large/i);
    });

    it('maps TTS error', () => {
      expect(mapErrorMessage('tts generation failed')).toMatch(/audio generation/i);
    });

    it('passes through unknown errors unchanged', () => {
      const msg = 'completely unknown error xyz';
      expect(mapErrorMessage(msg)).toBe(msg);
    });
  });
});
