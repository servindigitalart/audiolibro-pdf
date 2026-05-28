/**
 * AudioPlayer — completion state, playback controls, chapter list.
 * The <audio> element is left as jsdom stubs; we fire synthetic events
 * to drive state transitions.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import AudioPlayer from '@/components/dashboard/AudioPlayer';
import type { Chapter } from '@/lib/api/types';

// ── Stub HTMLAudioElement methods (jsdom doesn't implement media APIs) ─────
beforeEach(() => {
  // Stub play / pause so they don't throw
  vi.spyOn(window.HTMLAudioElement.prototype, 'play').mockResolvedValue(undefined);
  vi.spyOn(window.HTMLAudioElement.prototype, 'pause').mockImplementation(() => undefined);
  // Stub load so setting src doesn't throw
  vi.spyOn(window.HTMLAudioElement.prototype, 'load').mockImplementation(() => undefined);
  // jsdom doesn't implement scrollIntoView
  Element.prototype.scrollIntoView = vi.fn();
});

afterEach(() => {
  vi.restoreAllMocks();
  localStorage.clear();
});

// ── Helpers ───────────────────────────────────────────────────────────────────

function makeChapter(overrides: Partial<Chapter> = {}): Chapter {
  return {
    id:               'c1',
    document_id:      'doc-1',
    chapter_number:   1,
    title:            'Introduction',
    start_page:       1,
    end_page:         10,
    confidence_score: 0.95,
    audio_url:        'https://cdn.sonoro.com/audio/c1.mp3',
    duration_seconds: 300,
    status:           'completed',
    ...overrides,
  };
}

// ── Tests ─────────────────────────────────────────────────────────────────────

describe('AudioPlayer — basic rendering', () => {

  it('shows generating state when no completed chapters', () => {
    const chapter = makeChapter({ status: 'processing', audio_url: undefined });
    render(<AudioPlayer chapters={[chapter]} documentTitle="My Book" />);
    expect(screen.getByText(/Generating your audiobook/i)).toBeInTheDocument();
  });

  it('renders play button for completed chapters', () => {
    const chapter = makeChapter();
    render(<AudioPlayer chapters={[chapter]} documentTitle="My Book" />);
    expect(screen.getByRole('button', { name: /Play/i })).toBeInTheDocument();
  });

  it('shows document title in now-playing header', () => {
    const chapter = makeChapter();
    render(<AudioPlayer chapters={[chapter]} documentTitle="Atomic Habits" />);
    expect(screen.getAllByText('Atomic Habits').length).toBeGreaterThan(0);
  });

  it('shows chapter title in header', () => {
    const chapter = makeChapter({ title: 'The Beginning' });
    render(<AudioPlayer chapters={[chapter]} documentTitle="Book" />);
    expect(screen.getByText('The Beginning')).toBeInTheDocument();
  });

  it('renders chapter list section when multiple chapters exist', () => {
    const chapters = [
      makeChapter({ id: 'c1', chapter_number: 1, title: 'Intro' }),
      makeChapter({ id: 'c2', chapter_number: 2, title: 'Part One' }),
    ];
    render(<AudioPlayer chapters={chapters} documentTitle="Book" />);
    expect(screen.getByText('Chapters')).toBeInTheDocument();
    // Each title appears in both the header and the chapter list
    expect(screen.getAllByText('Intro').length).toBeGreaterThan(0);
    expect(screen.getAllByText('Part One').length).toBeGreaterThan(0);
  });

  it('omits chapter list section for a single chapter', () => {
    const chapter = makeChapter();
    render(<AudioPlayer chapters={[chapter]} documentTitle="Book" />);
    expect(screen.queryByText('Chapters')).not.toBeInTheDocument();
  });

  it('renders all five speed options', () => {
    const chapter = makeChapter();
    render(<AudioPlayer chapters={[chapter]} documentTitle="Book" />);
    for (const s of [0.75, 1, 1.25, 1.5, 2]) {
      expect(screen.getByRole('button', { name: `${s}× speed` })).toBeInTheDocument();
    }
  });

  it('shows immersive mode toggle button', () => {
    const chapter = makeChapter();
    render(<AudioPlayer chapters={[chapter]} documentTitle="Book" />);
    expect(screen.getByRole('button', { name: /immersive/i })).toBeInTheDocument();
  });

  it('shows sleep timer button', () => {
    const chapter = makeChapter();
    render(<AudioPlayer chapters={[chapter]} documentTitle="Book" />);
    expect(screen.getByRole('button', { name: /sleep timer/i })).toBeInTheDocument();
  });

  it('disables chapter list item that has no audio', () => {
    const chapters = [
      makeChapter({ id: 'c1', title: 'Ready' }),
      makeChapter({ id: 'c2', title: 'Not Ready', audio_url: undefined, status: 'pending' }),
    ];
    render(<AudioPlayer chapters={chapters} documentTitle="Book" />);
    // Accessible name includes chapter number prefix ("2 Not Ready"), so use regex
    expect(screen.getByRole('button', { name: /Not Ready/i })).toBeDisabled();
  });
});

// ── Immersive mode ────────────────────────────────────────────────────────────

describe('AudioPlayer — immersive mode', () => {

  it('opens the immersive dialog when button clicked', () => {
    const chapter = makeChapter();
    render(<AudioPlayer chapters={[chapter]} documentTitle="My Epic Book" />);
    fireEvent.click(screen.getByRole('button', { name: /immersive/i }));
    expect(screen.getByRole('dialog', { name: /immersive/i })).toBeInTheDocument();
  });

  it('closes immersive dialog with Escape', async () => {
    const chapter = makeChapter();
    render(<AudioPlayer chapters={[chapter]} documentTitle="Book" />);
    fireEvent.click(screen.getByRole('button', { name: /immersive/i }));
    expect(screen.getByRole('dialog')).toBeInTheDocument();

    fireEvent.keyDown(document, { key: 'Escape' });

    await waitFor(() => {
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    });
  });

  it('closes immersive dialog with close button', async () => {
    const chapter = makeChapter();
    render(<AudioPlayer chapters={[chapter]} documentTitle="Book" />);
    fireEvent.click(screen.getByRole('button', { name: /immersive/i }));

    fireEvent.click(screen.getByRole('button', { name: /exit immersive/i }));

    await waitFor(() => {
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    });
  });
});

// ── Completion state ──────────────────────────────────────────────────────────

describe('AudioPlayer — completion state', () => {

  it('shows completion overlay after the only chapter ends', async () => {
    const chapter = makeChapter({ id: 'c1' });
    const { container } = render(
      <AudioPlayer chapters={[chapter]} documentTitle="Atomic Habits" documentId="doc-1" />,
    );

    const audio = container.querySelector('audio')!;
    fireEvent.ended(audio);

    await waitFor(() => {
      expect(screen.getByText(/Finished listening/i)).toBeInTheDocument();
    });
  });

  it('completion overlay includes upload-next CTA', async () => {
    const chapter = makeChapter();
    const { container } = render(
      <AudioPlayer chapters={[chapter]} documentTitle="Sapiens" />,
    );

    fireEvent.ended(container.querySelector('audio')!);

    await waitFor(() => screen.getByText(/Finished listening/i));
    expect(screen.getByRole('link', { name: /upload next/i })).toBeInTheDocument();
  });

  it('listen again resets to player view', async () => {
    const chapter = makeChapter();
    const { container } = render(
      <AudioPlayer chapters={[chapter]} documentTitle="Book" />,
    );

    fireEvent.ended(container.querySelector('audio')!);
    await waitFor(() => screen.getByText(/Finished listening/i));

    fireEvent.click(screen.getByRole('button', { name: /listen again/i }));

    await waitFor(() => {
      expect(screen.queryByText(/Finished listening/i)).not.toBeInTheDocument();
      // goToChapter(0) sets isPlaying=true so button may show "Pause"
      expect(screen.getByRole('button', { name: /Play|Pause/i })).toBeInTheDocument();
    });
  });

  it('does NOT show completion when a next chapter exists', async () => {
    const chapters = [
      makeChapter({ id: 'c1', title: 'One' }),
      makeChapter({ id: 'c2', title: 'Two' }),
    ];
    const { container } = render(
      <AudioPlayer chapters={chapters} documentTitle="Book" />,
    );

    // Ending the audio fires onEnded but since c2 exists, no completion
    fireEvent.ended(container.querySelector('audio')!);

    await new Promise(r => setTimeout(r, 30));
    expect(screen.queryByText(/Finished listening/i)).not.toBeInTheDocument();
  });
});

// ── ContinueListening ─────────────────────────────────────────────────────────

describe('ContinueListening', () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it('shows nothing when no progress is saved', async () => {
    const { default: ContinueListening } = await import('@/components/dashboard/ContinueListening');
    const { container } = render(<ContinueListening />);
    // Give useEffect time to run
    await new Promise(r => setTimeout(r, 20));
    expect(container.firstChild).toBeNull();
  });

  it('shows document title when meaningful progress is saved', async () => {
    const { saveProgress } = await import('@/hooks/usePlaybackProgress');
    saveProgress({
      documentId:    'doc-z',
      documentTitle: 'Thinking Fast',
      chapterIdx:    0,
      chapterTitle:  'Opening',
      currentTime:   120,
      totalDuration: 600,
      timestamp:     Date.now(),
    });

    const { default: ContinueListening } = await import('@/components/dashboard/ContinueListening');
    render(<ContinueListening />);

    await waitFor(() => {
      expect(screen.getByText('Thinking Fast')).toBeInTheDocument();
    });
  });

  it('shows chapter title when available', async () => {
    const { saveProgress } = await import('@/hooks/usePlaybackProgress');
    saveProgress({
      documentId:    'doc-y',
      documentTitle: 'Deep Work',
      chapterIdx:    1,
      chapterTitle:  'Rule #1',
      currentTime:   200,
      totalDuration: 3000,
      timestamp:     Date.now(),
    });

    const { default: ContinueListening } = await import('@/components/dashboard/ContinueListening');
    render(<ContinueListening />);

    await waitFor(() => {
      expect(screen.getByText('Rule #1')).toBeInTheDocument();
    });
  });

  it('resume link has autoplay flag', async () => {
    const { saveProgress } = await import('@/hooks/usePlaybackProgress');
    saveProgress({
      documentId:    'doc-x',
      documentTitle: 'Flow',
      chapterIdx:    0,
      chapterTitle:  '',
      currentTime:   60,
      totalDuration: 1800,
      timestamp:     Date.now(),
    });

    const { default: ContinueListening } = await import('@/components/dashboard/ContinueListening');
    render(<ContinueListening />);

    await waitFor(() => screen.getByRole('link', { name: /Resume/i }));
    expect(screen.getByRole('link', { name: /Resume/i }))
      .toHaveAttribute('href', '/dashboard/documents/doc-x?autoplay=1');
  });
});
