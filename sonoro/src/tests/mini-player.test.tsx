/**
 * MiniPlayer component — localStorage-backed sticky bar.
 * localStorage is mocked via vitest's built-in jsdom support.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import MiniPlayer from '@/components/dashboard/MiniPlayer';
import { saveProgress } from '@/hooks/usePlaybackProgress';

// ── Helpers ──────────────────────────────────────────────────────────────────

function saveActiveProgress(overrides: Record<string, unknown> = {}) {
  saveProgress({
    documentId:    'doc-abc',
    documentTitle: 'Deep Work',
    chapterIdx:    2,
    chapterTitle:  'Chapter Three',
    currentTime:   900,
    totalDuration: 3600,
    timestamp:     Date.now(),
    ...overrides,
  } as any);
}

beforeEach(() => {
  localStorage.clear();
  // Set a known pathname so MiniPlayer doesn't hide itself on the document page
  Object.defineProperty(window, 'location', {
    value: { pathname: '/dashboard' },
    configurable: true,
    writable: true,
  });
});

afterEach(() => {
  vi.restoreAllMocks();
});

// ── Tests ────────────────────────────────────────────────────────────────────

describe('MiniPlayer', () => {

  it('renders nothing when localStorage is empty', () => {
    const { container } = render(<MiniPlayer />);
    expect(container.firstChild).toBeNull();
  });

  it('renders nothing when progress is < 30s', () => {
    saveActiveProgress({ currentTime: 10 });
    const { container } = render(<MiniPlayer />);
    expect(container.firstChild).toBeNull();
  });

  it('renders nothing when progress >= 95%', () => {
    saveActiveProgress({ currentTime: 3450, totalDuration: 3600 }); // 95.8%
    const { container } = render(<MiniPlayer />);
    expect(container.firstChild).toBeNull();
  });

  it('renders when meaningful progress is saved', async () => {
    saveActiveProgress();
    render(<MiniPlayer />);

    await waitFor(() => {
      expect(screen.getByText('Deep Work')).toBeInTheDocument();
    });
  });

  it('shows chapter title when available', async () => {
    saveActiveProgress();
    render(<MiniPlayer />);

    await waitFor(() => {
      expect(screen.getByText(/Chapter Three/)).toBeInTheDocument();
    });
  });

  it('falls back to "Chapter N" when chapterTitle is empty', async () => {
    saveActiveProgress({ chapterTitle: '' });
    render(<MiniPlayer />);

    await waitFor(() => {
      expect(screen.getByText(/Chapter 3/)).toBeInTheDocument();
    });
  });

  it('resume link points to correct document with autoplay flag', async () => {
    saveActiveProgress();
    render(<MiniPlayer />);

    await waitFor(() => screen.getByRole('link', { name: /Resume/i }));
    const link = screen.getByRole('link', { name: /Resume/i });
    expect(link).toHaveAttribute('href', '/dashboard/documents/doc-abc?autoplay=1');
  });

  it('dismiss button hides the player', async () => {
    saveActiveProgress();
    render(<MiniPlayer />);

    await waitFor(() => screen.getByText('Deep Work'));

    const dismissBtn = screen.getByRole('button', { name: /dismiss/i });
    fireEvent.click(dismissBtn);

    await waitFor(() => {
      expect(screen.queryByText('Deep Work')).not.toBeInTheDocument();
    });
  });

  it('does not render when on the document\'s own page', () => {
    Object.defineProperty(window, 'location', {
      value: { pathname: '/dashboard/documents/doc-abc' },
      configurable: true,
      writable: true,
    });
    saveActiveProgress();
    const { container } = render(<MiniPlayer />);
    expect(container.firstChild).toBeNull();
  });
});
