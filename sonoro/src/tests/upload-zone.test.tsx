/**
 * UploadZone component — state transitions and UI rendering.
 *
 * All API calls are mocked. No network requests are made.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react';
import {
  formatEtaConfident,
  weightedProgress,
  stageThresholdMessage,
} from '@/components/upload/UploadZone';
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
      expect(screen.getByText('Generating audiobook')).toBeInTheDocument();
    });
    // 1-based: 12 chunks done → currently on chapter 13
    expect(screen.getByText('Chapter 13 of 40')).toBeInTheDocument();
  });

  it('shows threshold progress message during generation', async () => {
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
      // weightedPct = 25 + (8/20 * 60) = 49 → "Generating audio"
    });

    render(<UploadZone />);
    dropFile(testPdf);
    await waitFor(() => screen.getByRole('button', { name: /start conversion/i }));
    fireEvent.click(screen.getByRole('button', { name: /start conversion/i }));

    // Threshold message replaces the old ETA
    await waitFor(() => screen.getByText('Generating audio'));
    expect(screen.queryByText(/Usually .+ minutes/i)).not.toBeInTheDocument();
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
    }, { timeout: 4000 });

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

    await waitFor(() => screen.getByRole('link', { name: /download audiobook/i }), { timeout: 4000 });
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

    await waitFor(() => screen.getByText(/Your audiobook is ready/i), { timeout: 4000 });
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

  // ── Narration style → startProcessing payload ────────────────────────────

  it('sends narration_style and voice_id when style is selected', async () => {
    mockUpload.mockResolvedValue({
      id: 'doc-ns1',
      is_duplicate: false,
      processing_status: 'pending',
      can_reprocess: false,
      duplicate_message: null,
      preflight: {
        ...basePreflight,
        available_voices: [
          { voice_id: 'v1', display_name: 'Rachel' },
          { voice_id: 'v2', display_name: 'Charlie' },
        ],
      },
    });
    mockStart.mockResolvedValue({ job_id: 'job-ns1', status: 'queued' });
    mockGetJob.mockResolvedValue({ id: 'job-ns1', status: 'processing', progress: 10 });

    render(<UploadZone />);
    dropFile(testPdf);

    // Wait for the preflight card, then find the style chip
    await waitFor(() => screen.getByText(/Ready to convert/i));

    // Click the Calm style chip (aria-pressed button)
    const calmBtn = screen.getByRole('button', { name: /Calm/i });
    fireEvent.click(calmBtn);

    // Start conversion
    await waitFor(() => screen.getByRole('button', { name: /start conversion/i }));
    fireEvent.click(screen.getByRole('button', { name: /start conversion/i }));

    await waitFor(() => expect(mockStart).toHaveBeenCalled());

    const [docId, voiceId, style] = mockStart.mock.calls[0];
    expect(docId).toBe('doc-ns1');
    expect(style).toBe('calm');
    expect(typeof voiceId).toBe('string');
  });

  it('sends no narration_style when no style is selected', async () => {
    mockUpload.mockResolvedValue({
      id: 'doc-ns2',
      is_duplicate: false,
      processing_status: 'pending',
      can_reprocess: false,
      duplicate_message: null,
      preflight: basePreflight,
    });
    mockStart.mockResolvedValue({ job_id: 'job-ns2', status: 'queued' });
    mockGetJob.mockResolvedValue({ id: 'job-ns2', status: 'processing', progress: 5 });

    render(<UploadZone />);
    dropFile(testPdf);
    await waitFor(() => screen.getByRole('button', { name: /start conversion/i }));
    fireEvent.click(screen.getByRole('button', { name: /start conversion/i }));

    await waitFor(() => expect(mockStart).toHaveBeenCalled());
    const [, , style] = mockStart.mock.calls[0];
    expect(style).toBeUndefined();
  });

  // ── 1-based chunk indexing ────────────────────────────────────────────────

  it('never shows "segment 0" in the processing view', async () => {
    mockUpload.mockResolvedValue({
      id: 'doc-idx1',
      is_duplicate: false,
      processing_status: 'pending',
      can_reprocess: false,
      duplicate_message: null,
      preflight: basePreflight,
    });
    mockStart.mockResolvedValue({ job_id: 'job-idx1', status: 'queued' });
    mockGetJob.mockResolvedValue({
      id: 'job-idx1',
      status: 'processing',
      stage: 'generating_audio',
      current_stage: 'tts_generation',
      progress: 30,
      completed_chunks: 0,
      total_chunks: 4,
    });

    render(<UploadZone />);
    dropFile(testPdf);
    await waitFor(() => screen.getByRole('button', { name: /start conversion/i }));
    fireEvent.click(screen.getByRole('button', { name: /start conversion/i }));

    await waitFor(() => screen.getByText('Generating audiobook'));
    // 1-based: 0 done → currently on chapter 1
    expect(screen.getByText('Chapter 1 of 4')).toBeInTheDocument();
    expect(screen.queryByText(/segment 0/i)).not.toBeInTheDocument();
  });

  // ── Stuck-job detection ───────────────────────────────────────────────────

  it('shows stuck-job message after 60 s without progress', async () => {
    mockUpload.mockResolvedValue({
      id: 'doc-stuck',
      is_duplicate: false,
      processing_status: 'pending',
      can_reprocess: false,
      duplicate_message: null,
      preflight: basePreflight,
    });
    mockStart.mockResolvedValue({ job_id: 'job-stuck', status: 'queued' });
    mockGetJob.mockResolvedValue({
      id: 'job-stuck',
      status: 'processing',
      stage: 'generating_audio',
      current_stage: 'tts_generation',
      progress: 40,
      completed_chunks: 4,
      total_chunks: 10,
    });

    render(<UploadZone />);
    dropFile(testPdf);

    // Use real timers for the async upload/preflight step
    await waitFor(() => screen.getByRole('button', { name: /start conversion/i }));

    // Enable fake timers before the processing phase so all intervals are faked
    vi.useFakeTimers();
    try {
      fireEvent.click(screen.getByRole('button', { name: /start conversion/i }));

      // Flush: startProcessing resolves → stage='processing' → polling starts → first poll runs
      await act(async () => { await vi.advanceTimersByTimeAsync(100); });

      // Advance 65 s — stuck-detection interval fires every 5 s; at 65 s the condition triggers
      await act(async () => { await vi.advanceTimersByTimeAsync(65_000); });

      expect(screen.getByText(/taking longer than usual/i)).toBeInTheDocument();
    } finally {
      vi.useRealTimers();
    }
  });

  // ── Weighted progress ─────────────────────────────────────────────────────────

  describe('weightedProgress', () => {
    it('maps generation chunks to 25–85 range', () => {
      const gen = (done: number) => weightedProgress('tts_generation', 'generating_audio', 40, { done, total: 4 });
      expect(gen(0)).toBe(25);
      expect(gen(1)).toBe(40);
      expect(gen(2)).toBe(55);
      expect(gen(3)).toBe(70);
      expect(gen(4)).toBe(85);
    });

    it('returns 25 when in generation with no chunk data', () => {
      expect(weightedProgress('tts_generation', 'generating_audio', 40, null)).toBe(25);
    });

    it('returns 90 for final_assembly stage', () => {
      expect(weightedProgress('final_assembly', 'finalizing', 90, null)).toBe(90);
    });

    it('returns 97 for upload_finalize stage', () => {
      expect(weightedProgress('upload_finalize', undefined, 96, null)).toBe(97);
    });

    it('returns 20 for chapter_detection stage', () => {
      expect(weightedProgress('chapter_detection', 'detecting_chapters', 15, null)).toBe(20);
    });

    it('clamps analyzing to 0–14', () => {
      expect(weightedProgress('analyzing', 'analyzing', 5, null)).toBe(5);
      expect(weightedProgress('analyzing', 'analyzing', 20, null)).toBe(14);
    });

    it('is backward-compatible with unknown stages', () => {
      const pct = weightedProgress('', undefined, 30, null);
      expect(pct).toBeGreaterThanOrEqual(0);
      expect(pct).toBeLessThanOrEqual(100);
    });
  });

  // ── Stage threshold messages ───────────────────────────────────────────────────

  describe('stageThresholdMessage', () => {
    it('returns "Preparing your audiobook" for 0–29%', () => {
      expect(stageThresholdMessage(0)).toBe('Preparing your audiobook');
      expect(stageThresholdMessage(29)).toBe('Preparing your audiobook');
    });

    it('returns "Generating audio" for 30–59%', () => {
      expect(stageThresholdMessage(30)).toBe('Generating audio');
      expect(stageThresholdMessage(59)).toBe('Generating audio');
    });

    it('returns "More than halfway done" for 60–84%', () => {
      expect(stageThresholdMessage(60)).toBe('More than halfway done');
      expect(stageThresholdMessage(84)).toBe('More than halfway done');
    });

    it('returns "Assembling audiobook" for 85–94%', () => {
      expect(stageThresholdMessage(85)).toBe('Assembling audiobook');
      expect(stageThresholdMessage(94)).toBe('Assembling audiobook');
    });

    it('returns "Final touches" for 95–100%', () => {
      expect(stageThresholdMessage(95)).toBe('Final touches');
      expect(stageThresholdMessage(100)).toBe('Final touches');
    });
  });

  // ── Chapter-level progress copy ────────────────────────────────────────────────

  it('shows "Chapter X of Y" during audio generation', async () => {
    mockUpload.mockResolvedValue({
      id: 'doc-ch1', is_duplicate: false, processing_status: 'pending',
      can_reprocess: false, duplicate_message: null, preflight: basePreflight,
    });
    mockStart.mockResolvedValue({ job_id: 'job-ch1', status: 'queued' });
    mockGetJob.mockResolvedValue({
      id: 'job-ch1', status: 'processing',
      stage: 'generating_audio', current_stage: 'tts_generation',
      progress: 40, completed_chunks: 2, total_chunks: 8,
    });

    render(<UploadZone />);
    dropFile(testPdf);
    await waitFor(() => screen.getByRole('button', { name: /start conversion/i }));
    fireEvent.click(screen.getByRole('button', { name: /start conversion/i }));

    await waitFor(() => screen.getByText('Chapter 3 of 8'));
  });

  it('shows "Generating your narration" when chunk data is absent', async () => {
    mockUpload.mockResolvedValue({
      id: 'doc-ch2', is_duplicate: false, processing_status: 'pending',
      can_reprocess: false, duplicate_message: null, preflight: basePreflight,
    });
    mockStart.mockResolvedValue({ job_id: 'job-ch2', status: 'queued' });
    mockGetJob.mockResolvedValue({
      id: 'job-ch2', status: 'processing',
      stage: 'generating_audio', current_stage: 'tts_generation',
      progress: 40,
      // no completed_chunks / total_chunks — backward compat path
    });

    render(<UploadZone />);
    dropFile(testPdf);
    await waitFor(() => screen.getByRole('button', { name: /start conversion/i }));
    fireEvent.click(screen.getByRole('button', { name: /start conversion/i }));

    await waitFor(() => screen.getByText('Generating your narration'));
    expect(screen.queryByText(/Chapter \d+ of/i)).not.toBeInTheDocument();
  });

  // ── Micro progress indicator ────────────────────────────────────────────────────

  it('shows three-item micro progress during generation', async () => {
    mockUpload.mockResolvedValue({
      id: 'doc-mp1', is_duplicate: false, processing_status: 'pending',
      can_reprocess: false, duplicate_message: null, preflight: basePreflight,
    });
    mockStart.mockResolvedValue({ job_id: 'job-mp1', status: 'queued' });
    mockGetJob.mockResolvedValue({
      id: 'job-mp1', status: 'processing',
      stage: 'generating_audio', current_stage: 'tts_generation',
      progress: 40, completed_chunks: 1, total_chunks: 4,
    });

    render(<UploadZone />);
    dropFile(testPdf);
    await waitFor(() => screen.getByRole('button', { name: /start conversion/i }));
    fireEvent.click(screen.getByRole('button', { name: /start conversion/i }));

    await waitFor(() => {
      expect(screen.getByText('Chapter 1 complete')).toBeInTheDocument();
      expect(screen.getByText('Generating chapter 2')).toBeInTheDocument();
      expect(screen.getByText('Chapter 3 pending')).toBeInTheDocument();
    });
  });

  it('omits the previous-completed row when no chunks are done yet', async () => {
    mockUpload.mockResolvedValue({
      id: 'doc-mp2', is_duplicate: false, processing_status: 'pending',
      can_reprocess: false, duplicate_message: null, preflight: basePreflight,
    });
    mockStart.mockResolvedValue({ job_id: 'job-mp2', status: 'queued' });
    mockGetJob.mockResolvedValue({
      id: 'job-mp2', status: 'processing',
      stage: 'generating_audio', current_stage: 'tts_generation',
      progress: 25, completed_chunks: 0, total_chunks: 4,
    });

    render(<UploadZone />);
    dropFile(testPdf);
    await waitFor(() => screen.getByRole('button', { name: /start conversion/i }));
    fireEvent.click(screen.getByRole('button', { name: /start conversion/i }));

    await waitFor(() => screen.getByText('Generating chapter 1'));
    expect(screen.queryByText(/Chapter 0/i)).not.toBeInTheDocument();
  });

  // ── Weighted progress bar ─────────────────────────────────────────────────────

  it('progress bar reflects weighted percentage based on chunk data', async () => {
    mockUpload.mockResolvedValue({
      id: 'doc-wp1', is_duplicate: false, processing_status: 'pending',
      can_reprocess: false, duplicate_message: null, preflight: basePreflight,
    });
    mockStart.mockResolvedValue({ job_id: 'job-wp1', status: 'queued' });
    // 2 of 4 chunks done → weightedPct = 25 + 2/4 * 60 = 55
    mockGetJob.mockResolvedValue({
      id: 'job-wp1', status: 'processing',
      stage: 'generating_audio', current_stage: 'tts_generation',
      progress: 56, completed_chunks: 2, total_chunks: 4,
    });

    render(<UploadZone />);
    dropFile(testPdf);
    await waitFor(() => screen.getByRole('button', { name: /start conversion/i }));
    fireEvent.click(screen.getByRole('button', { name: /start conversion/i }));

    await waitFor(() => {
      expect(screen.getByRole('progressbar')).toHaveAttribute('aria-valuenow', '55');
    });
    expect(screen.getByText('55%')).toBeInTheDocument();
  });

  // ── Completion banner ────────────────────────────────────────────────────────────

  it('shows "Audiobook ready" banner before transitioning to ready state', async () => {
    mockUpload.mockResolvedValue({
      id: 'doc-cb1', is_duplicate: false, processing_status: 'pending',
      can_reprocess: false, duplicate_message: null, preflight: basePreflight,
    });
    mockStart.mockResolvedValue({ job_id: 'job-cb1', status: 'queued' });
    mockGetJob.mockResolvedValue({ id: 'job-cb1', status: 'completed', progress: 100 });
    mockGetChapters.mockResolvedValue([]);
    mockGetDocument.mockResolvedValue({ id: 'doc-cb1', audiobook_url: null });

    render(<UploadZone />);
    dropFile(testPdf);
    await waitFor(() => screen.getByRole('button', { name: /start conversion/i }));
    fireEvent.click(screen.getByRole('button', { name: /start conversion/i }));

    // Banner appears first
    await waitFor(() => screen.getByText('Audiobook ready'));
    // Then transitions to the full ready state after the 1500 ms delay
    await waitFor(() => screen.getByText(/Your audiobook is ready/i), { timeout: 4000 });
  });

  // ── Failure with partial progress ─────────────────────────────────────────────────

  it('shows partial chapter count when generation fails mid-way', async () => {
    mockUpload.mockResolvedValue({
      id: 'doc-fp1', is_duplicate: false, processing_status: 'pending',
      can_reprocess: false, duplicate_message: null, preflight: basePreflight,
    });
    mockStart.mockResolvedValue({ job_id: 'job-fp1', status: 'queued' });
    mockGetJob.mockResolvedValue({
      id: 'job-fp1', status: 'failed',
      progress: 60, completed_chunks: 3, total_chunks: 4,
      error_message: 'TTS quota exceeded',
    });

    render(<UploadZone />);
    dropFile(testPdf);
    await waitFor(() => screen.getByRole('button', { name: /start conversion/i }));
    fireEvent.click(screen.getByRole('button', { name: /start conversion/i }));

    await waitFor(() => screen.getByRole('alert'));
    expect(screen.getByText(/couldn't finish/i)).toBeInTheDocument();
    expect(screen.getByText(/Completed 3 of 4 chapters/i)).toBeInTheDocument();
  });

  it('shows generic error when job fails before any chunks complete', async () => {
    mockUpload.mockResolvedValue({
      id: 'doc-fp2', is_duplicate: false, processing_status: 'pending',
      can_reprocess: false, duplicate_message: null, preflight: basePreflight,
    });
    mockStart.mockResolvedValue({ job_id: 'job-fp2', status: 'queued' });
    mockGetJob.mockResolvedValue({
      id: 'job-fp2', status: 'failed',
      progress: 10, completed_chunks: 0, total_chunks: 0,
      error_message: 'tts provider error',
    });

    render(<UploadZone />);
    dropFile(testPdf);
    await waitFor(() => screen.getByRole('button', { name: /start conversion/i }));
    fireEvent.click(screen.getByRole('button', { name: /start conversion/i }));

    await waitFor(() => screen.getByRole('alert'));
    expect(screen.getByText(/Audio generation failed/i)).toBeInTheDocument();
    expect(screen.queryByText(/Completed.*chapters/i)).not.toBeInTheDocument();
  });

  // ── ETA confidence copy ───────────────────────────────────────────────────

  describe('formatEtaConfident', () => {
    it('returns "Usually under 2 minutes" for ≤ 90 s', () => {
      expect(formatEtaConfident(60)).toBe('Usually under 2 minutes');
      expect(formatEtaConfident(90)).toBe('Usually under 2 minutes');
    });

    it('returns "Usually 2–5 minutes" for 91–300 s', () => {
      expect(formatEtaConfident(180)).toBe('Usually 2–5 minutes');
      expect(formatEtaConfident(300)).toBe('Usually 2–5 minutes');
    });

    it('returns "Usually 5–10 minutes" for 301–600 s', () => {
      expect(formatEtaConfident(360)).toBe('Usually 5–10 minutes');
    });

    it('returns "Usually over 10 minutes" for > 600 s', () => {
      expect(formatEtaConfident(700)).toBe('Usually over 10 minutes');
    });
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
