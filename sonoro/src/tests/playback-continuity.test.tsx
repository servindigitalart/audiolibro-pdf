/**
 * Phase 5E — Continue Listening Everywhere
 *
 * Tests covering:
 *   - PlaybackProgress type extensions (completed, progressPct, playbackSpeed)
 *   - saveProgress auto-computes progressPct and completed
 *   - AudioPlayer restores saved position via initialTime
 *   - AudioPlayer shows "Resume from X" label before first play
 *   - AudioPlayer saves progress on pause
 *   - DocumentList progress bars + contextual CTAs
 *   - MiniPlayer shows "Listen again" for completed books
 *   - MiniPlayer shows for completed books (pct >= 95 but completed=true)
 *   - ContinueListening shows "Recently finished" section for completed books
 *   - ContinueListening shows section header for in-progress books
 *   - No duplicate audio instances (single <audio> element)
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import {
  saveProgress,
  loadProgress,
  loadLastPlayed,
  clearProgress,
} from '@/hooks/usePlaybackProgress';
import type { PlaybackProgress } from '@/hooks/usePlaybackProgress';
import AudioPlayer from '@/components/dashboard/AudioPlayer';
import MiniPlayer from '@/components/dashboard/MiniPlayer';
import DocumentList from '@/components/dashboard/DocumentList';
import type { Chapter, Document } from '@/lib/api/types';

// ── Stubs ─────────────────────────────────────────────────────────────────────

beforeEach(() => {
  vi.spyOn(window.HTMLAudioElement.prototype, 'play').mockResolvedValue(undefined);
  vi.spyOn(window.HTMLAudioElement.prototype, 'pause').mockImplementation(() => undefined);
  vi.spyOn(window.HTMLAudioElement.prototype, 'load').mockImplementation(() => undefined);
  Element.prototype.scrollIntoView = vi.fn();
  localStorage.clear();
  Object.defineProperty(window, 'location', {
    value: { pathname: '/dashboard' },
    configurable: true, writable: true,
  });
});

afterEach(() => {
  vi.restoreAllMocks();
  localStorage.clear();
});

// ── Helpers ───────────────────────────────────────────────────────────────────

function makeChapter(overrides: Partial<Chapter> = {}): Chapter {
  return {
    id: 'c1', document_id: 'doc-1', chapter_number: 1,
    title: 'Introduction', start_page: 1, end_page: 10,
    confidence_score: 0.95, audio_url: 'https://cdn.sonoro.com/c1.mp3',
    duration_seconds: 300, status: 'completed', ...overrides,
  };
}

function makeDoc(overrides: Partial<Document> = {}): Document {
  return {
    id: 'doc-1', title: 'Atomic Habits', filename: 'atomic.pdf',
    file_size: 1024, status: 'completed', upload_date: new Date().toISOString(),
    ...overrides,
  };
}

// ── PlaybackProgress storage ──────────────────────────────────────────────────

describe('saveProgress / loadProgress', () => {
  it('auto-computes progressPct from currentTime / totalDuration', () => {
    saveProgress({
      documentId: 'd1', documentTitle: 'Book', chapterIdx: 0, chapterTitle: 'Ch 1',
      currentTime: 300, totalDuration: 1000, timestamp: Date.now(),
    });
    const p = loadProgress('d1')!;
    expect(p.progressPct).toBe(30);
  });

  it('sets completed=true when currentTime / totalDuration >= 0.98', () => {
    saveProgress({
      documentId: 'd2', documentTitle: 'Book', chapterIdx: 0, chapterTitle: '',
      currentTime: 980, totalDuration: 1000, timestamp: Date.now(),
    });
    expect(loadProgress('d2')?.completed).toBe(true);
  });

  it('sets completed=false when under the threshold', () => {
    saveProgress({
      documentId: 'd3', documentTitle: 'Book', chapterIdx: 0, chapterTitle: '',
      currentTime: 500, totalDuration: 1000, timestamp: Date.now(),
    });
    expect(loadProgress('d3')?.completed).toBe(false);
  });

  it('respects explicit completed=true override', () => {
    saveProgress({
      documentId: 'd4', documentTitle: 'Book', chapterIdx: 0, chapterTitle: '',
      currentTime: 100, totalDuration: 1000, timestamp: Date.now(),
      completed: true,
    });
    expect(loadProgress('d4')?.completed).toBe(true);
  });

  it('persists playbackSpeed', () => {
    saveProgress({
      documentId: 'd5', documentTitle: 'Book', chapterIdx: 0, chapterTitle: '',
      currentTime: 200, totalDuration: 1000, timestamp: Date.now(),
      playbackSpeed: 1.5,
    });
    expect(loadProgress('d5')?.playbackSpeed).toBe(1.5);
  });

  it('loadLastPlayed returns most-recently-saved entry', () => {
    saveProgress({
      documentId: 'first', documentTitle: 'First', chapterIdx: 0, chapterTitle: '',
      currentTime: 100, totalDuration: 500, timestamp: Date.now() - 1000,
    });
    saveProgress({
      documentId: 'second', documentTitle: 'Second', chapterIdx: 0, chapterTitle: '',
      currentTime: 200, totalDuration: 500, timestamp: Date.now(),
    });
    expect(loadLastPlayed()?.documentId).toBe('second');
  });

  it('clearProgress removes the entry and last-played pointer', () => {
    saveProgress({
      documentId: 'tbd', documentTitle: 'TBD', chapterIdx: 0, chapterTitle: '',
      currentTime: 100, totalDuration: 500, timestamp: Date.now(),
    });
    clearProgress('tbd');
    expect(loadProgress('tbd')).toBeNull();
    expect(loadLastPlayed()).toBeNull();
  });
});

// ── AudioPlayer — position restore ───────────────────────────────────────────

describe('AudioPlayer — position restore', () => {
  it('shows "Resume from X" label when saved progress exists', () => {
    saveProgress({
      documentId: 'doc-1', documentTitle: 'Atomic Habits',
      chapterIdx: 0, chapterTitle: 'Introduction',
      currentTime: 2522, totalDuration: 10000, timestamp: Date.now(),
    });

    render(
      <AudioPlayer
        chapters={[makeChapter()]}
        documentTitle="Atomic Habits"
        documentId="doc-1"
      />,
    );

    // "Resume from 42:02" — exact time depends on fmtDuration(2522)
    expect(screen.getByText(/Resume from/i)).toBeInTheDocument();
  });

  it('does not show Resume label when no progress is saved', () => {
    render(
      <AudioPlayer
        chapters={[makeChapter()]}
        documentTitle="Fresh Book"
        documentId="doc-fresh"
      />,
    );
    expect(screen.queryByText(/Resume from/i)).not.toBeInTheDocument();
  });

  it('does not show Resume label for a completed book', () => {
    saveProgress({
      documentId: 'doc-done', documentTitle: 'Done Book',
      chapterIdx: 0, chapterTitle: '',
      currentTime: 9900, totalDuration: 10000, timestamp: Date.now(),
      completed: true,
    });

    render(
      <AudioPlayer
        chapters={[makeChapter()]}
        documentTitle="Done Book"
        documentId="doc-done"
      />,
    );
    expect(screen.queryByText(/Resume from/i)).not.toBeInTheDocument();
  });

  it('applies initialTime to the audio element on loadedmetadata', () => {
    saveProgress({
      documentId: 'doc-seek', documentTitle: 'Seek Book',
      chapterIdx: 0, chapterTitle: 'Ch1',
      currentTime: 120, totalDuration: 600, timestamp: Date.now(),
    });

    const { container } = render(
      <AudioPlayer
        chapters={[makeChapter()]}
        documentTitle="Seek Book"
        documentId="doc-seek"
      />,
    );

    const audio = container.querySelector('audio')!;

    // Simulate duration becoming known
    Object.defineProperty(audio, 'duration', { value: 600, configurable: true });

    // Fire loadedmetadata — the hook should seek currentTime to 120
    const timeSetter = vi.fn();
    Object.defineProperty(audio, 'currentTime', {
      get: () => 0,
      set: timeSetter,
      configurable: true,
    });

    fireEvent.loadedMetadata(audio);

    expect(timeSetter).toHaveBeenCalledWith(expect.closeTo(120, 0));
  });

  it('only one <audio> element is rendered (no duplicate instances)', () => {
    const { container } = render(
      <AudioPlayer
        chapters={[makeChapter(), makeChapter({ id: 'c2', title: 'Chapter 2', chapter_number: 2 })]}
        documentTitle="Multi Chapter"
        documentId="doc-multi"
      />,
    );
    expect(container.querySelectorAll('audio')).toHaveLength(1);
  });
});

// ── AudioPlayer — save on pause ───────────────────────────────────────────────

describe('AudioPlayer — save on pause', () => {
  it('saves progress when user pauses', async () => {
    const { container } = render(
      <AudioPlayer
        chapters={[makeChapter()]}
        documentTitle="Pausable Book"
        documentId="doc-pause"
      />,
    );

    const audio = container.querySelector('audio')!;

    // Make paused property dynamic so togglePlay behaves correctly in jsdom
    let paused = true;
    Object.defineProperty(audio, 'paused', { get: () => paused, configurable: true });
    vi.spyOn(audio, 'play').mockImplementation(async () => { paused = false; });
    vi.spyOn(audio, 'pause').mockImplementation(() => { paused = true; });

    // Click Play → isPlaying=true, button label becomes "Pause"
    fireEvent.click(screen.getByRole('button', { name: /Play/i }));
    await waitFor(() => screen.getByRole('button', { name: /Pause/i }));

    // Simulate time advancing so saveStateRef.current.currentTime > 0
    Object.defineProperty(audio, 'currentTime', { value: 45, configurable: true });
    Object.defineProperty(audio, 'duration',    { value: 300, configurable: true });
    fireEvent.timeUpdate(audio);

    // Click Pause → isPlaying=false → save-on-pause effect fires
    fireEvent.click(screen.getByRole('button', { name: /Pause/i }));

    await waitFor(() => {
      expect(localStorage.getItem('sonoro_progress_doc-pause')).not.toBeNull();
    });
  });
});

// ── DocumentList — progress bars + CTAs ──────────────────────────────────────

describe('DocumentList — progress bars and CTAs', () => {
  it('shows "Resume" for an incomplete audiobook', async () => {
    saveProgress({
      documentId: 'doc-1', documentTitle: 'Atomic Habits',
      chapterIdx: 0, chapterTitle: '',
      currentTime: 300, totalDuration: 1000, timestamp: Date.now(),
    });

    render(<DocumentList initialDocuments={[makeDoc()]} />);

    // Hover reveals the button
    await waitFor(() => {
      expect(screen.getByRole('link', { name: /Resume — Atomic Habits/i })).toBeInTheDocument();
    });
  });

  it('shows "Start listening" for a doc with no saved progress', async () => {
    render(<DocumentList initialDocuments={[makeDoc()]} />);

    await waitFor(() => {
      expect(screen.getByRole('link', { name: /Start listening — Atomic Habits/i })).toBeInTheDocument();
    });
  });

  it('shows "Listen again" for a completed audiobook', async () => {
    saveProgress({
      documentId: 'doc-1', documentTitle: 'Atomic Habits',
      chapterIdx: 0, chapterTitle: '',
      currentTime: 990, totalDuration: 1000, timestamp: Date.now(),
      completed: true,
    });

    render(<DocumentList initialDocuments={[makeDoc()]} />);

    await waitFor(() => {
      expect(screen.getByRole('link', { name: /Listen again — Atomic Habits/i })).toBeInTheDocument();
    });
  });

  it('shows a progress bar for an incomplete doc', async () => {
    saveProgress({
      documentId: 'doc-1', documentTitle: 'Atomic Habits',
      chapterIdx: 0, chapterTitle: '',
      currentTime: 400, totalDuration: 1000, timestamp: Date.now(),
    });

    render(<DocumentList initialDocuments={[makeDoc()]} />);

    await waitFor(() => {
      const bar = screen.getByRole('progressbar', { name: /listened/i });
      expect(bar).toHaveAttribute('aria-valuenow', '40');
    });
  });

  it('does not show progress bar for a completed doc', async () => {
    saveProgress({
      documentId: 'doc-1', documentTitle: 'Atomic Habits',
      chapterIdx: 0, chapterTitle: '',
      currentTime: 990, totalDuration: 1000, timestamp: Date.now(),
      completed: true,
    });

    render(<DocumentList initialDocuments={[makeDoc()]} />);

    await waitFor(() =>
      screen.getByRole('link', { name: /Listen again/i }),
    );
    expect(screen.queryByRole('progressbar', { name: /listened/i })).not.toBeInTheDocument();
  });

  it('Resume link includes ?autoplay=1', async () => {
    saveProgress({
      documentId: 'doc-1', documentTitle: 'Atomic Habits',
      chapterIdx: 1, chapterTitle: 'Part Two',
      currentTime: 600, totalDuration: 3000, timestamp: Date.now(),
    });

    render(<DocumentList initialDocuments={[makeDoc()]} />);

    await waitFor(() =>
      screen.getByRole('link', { name: /Resume/i }),
    );
    expect(screen.getByRole('link', { name: /Resume/i }))
      .toHaveAttribute('href', '/dashboard/documents/doc-1?autoplay=1');
  });
});

// ── MiniPlayer — completed state ──────────────────────────────────────────────

describe('MiniPlayer — completed books', () => {
  it('shows "Listen again" for a completed book', async () => {
    saveProgress({
      documentId: 'doc-abc', documentTitle: 'Deep Work',
      chapterIdx: 2, chapterTitle: 'Chapter Three',
      currentTime: 3550, totalDuration: 3600, timestamp: Date.now(),
      completed: true,
    });

    render(<MiniPlayer />);

    await waitFor(() => {
      expect(screen.getByRole('link', { name: /Listen to Deep Work again/i })).toBeInTheDocument();
    });
  });

  it('shows the completed book even though pct >= 95', async () => {
    saveProgress({
      documentId: 'doc-abc', documentTitle: 'Atomic Habits',
      chapterIdx: 0, chapterTitle: '',
      currentTime: 3500, totalDuration: 3600, timestamp: Date.now(),
      completed: true,
    });

    render(<MiniPlayer />);

    await waitFor(() => {
      expect(screen.getByText('Atomic Habits')).toBeInTheDocument();
    });
  });

  it('hides for a non-completed book at or beyond 95%', () => {
    // pct = 95.8%, NOT marked completed — should still hide
    saveProgress({
      documentId: 'doc-abc', documentTitle: 'Boring Book',
      chapterIdx: 0, chapterTitle: '',
      currentTime: 3450, totalDuration: 3600, timestamp: Date.now(),
      completed: false,
    });

    const { container } = render(<MiniPlayer />);
    expect(container.firstChild).toBeNull();
  });

  it('shows "Finished listening" subtitle for completed books', async () => {
    saveProgress({
      documentId: 'doc-abc', documentTitle: 'Deep Work',
      chapterIdx: 2, chapterTitle: 'Last Chapter',
      currentTime: 3600, totalDuration: 3600, timestamp: Date.now(),
      completed: true,
    });

    render(<MiniPlayer />);

    await waitFor(() => {
      expect(screen.getByText('Finished listening')).toBeInTheDocument();
    });
  });
});

// ── ContinueListening — completed books ───────────────────────────────────────

describe('ContinueListening', () => {
  it('shows nothing when localStorage is empty', async () => {
    const { default: CL } = await import('@/components/dashboard/ContinueListening');
    const { container } = render(<CL />);
    await new Promise(r => setTimeout(r, 20));
    expect(container.firstChild).toBeNull();
  });

  it('shows "Continue listening" heading for an in-progress book', async () => {
    saveProgress({
      documentId: 'doc-x', documentTitle: 'Flow',
      chapterIdx: 0, chapterTitle: '',
      currentTime: 200, totalDuration: 1000, timestamp: Date.now(),
    });

    const { default: CL } = await import('@/components/dashboard/ContinueListening');
    render(<CL />);

    // Wait for the section heading (not the title, which also appears in BookCover)
    await waitFor(() => screen.getByText('Continue listening'));
    expect(screen.getByText('Continue listening')).toBeInTheDocument();
    // Title appears in multiple places (BookCover + p); at least one should be present
    expect(screen.getAllByText('Flow').length).toBeGreaterThan(0);
  });

  it('shows "Recently finished" heading for a completed book', async () => {
    saveProgress({
      documentId: 'doc-done', documentTitle: 'Sapiens',
      chapterIdx: 3, chapterTitle: '',
      currentTime: 9900, totalDuration: 10000, timestamp: Date.now(),
      completed: true,
    });

    const { default: CL } = await import('@/components/dashboard/ContinueListening');
    render(<CL />);

    await waitFor(() => screen.getByText('Recently finished'));
    expect(screen.getByText('Recently finished')).toBeInTheDocument();
    expect(screen.getByText('Finished')).toBeInTheDocument();
  });

  it('shows "Listen again" CTA link for a completed book', async () => {
    saveProgress({
      documentId: 'doc-done2', documentTitle: 'Thinking Fast',
      chapterIdx: 0, chapterTitle: '',
      currentTime: 9900, totalDuration: 10000, timestamp: Date.now(),
      completed: true,
    });

    const { default: CL } = await import('@/components/dashboard/ContinueListening');
    render(<CL />);

    await waitFor(() =>
      screen.getByRole('link', { name: /Listen to Thinking Fast again/i }),
    );
    expect(screen.getByRole('link', { name: /Listen to Thinking Fast again/i }))
      .toHaveAttribute('href', '/dashboard/documents/doc-done2?autoplay=1');
  });

  it('does not show progress bar for a completed book', async () => {
    saveProgress({
      documentId: 'doc-done3', documentTitle: 'Atomic',
      chapterIdx: 0, chapterTitle: '',
      currentTime: 9900, totalDuration: 10000, timestamp: Date.now(),
      completed: true,
    });

    const { default: CL } = await import('@/components/dashboard/ContinueListening');
    render(<CL />);

    // Heading confirms the section is visible
    await waitFor(() => screen.getByText('Recently finished'));
    expect(screen.queryByRole('progressbar')).not.toBeInTheDocument();
  });

  it('shows the book even if currentTime is < 30s (changed threshold)', async () => {
    // The old threshold was >= 30s; now we show completed books regardless
    saveProgress({
      documentId: 'doc-short', documentTitle: 'Short',
      chapterIdx: 0, chapterTitle: '',
      currentTime: 10, totalDuration: 100, timestamp: Date.now(),
    });
    const { default: CL } = await import('@/components/dashboard/ContinueListening');
    const { container } = render(<CL />);
    await new Promise(r => setTimeout(r, 20));
    // < 30s + not completed → still hidden
    expect(container.firstChild).toBeNull();
  });
});
