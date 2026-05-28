/**
 * VoicePicker component — card rendering and selection behavior.
 * Voice preview API calls are mocked.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import VoicePicker, { _clearPreviewCache } from '@/components/upload/VoicePicker';
import * as clientApi from '@/lib/api/client';

vi.mock('@/lib/api/client', () => ({
  previewVoice: vi.fn(),
}));

const mockPreview = clientApi.previewVoice as ReturnType<typeof vi.fn>;

const voices = [
  { voice_id: 'v1', display_name: 'Rachel' },
  { voice_id: 'v2', display_name: 'Adam' },
  { voice_id: 'v3', display_name: 'Bella' },
];

function mockAudio(playImpl?: () => Promise<void>) {
  const mockPlay = vi.fn().mockImplementation(playImpl ?? (() => Promise.resolve()));
  const inst = { play: mockPlay, pause: vi.fn(), onended: null as (() => void) | null, onerror: null as (() => void) | null };
  vi.stubGlobal('Audio', vi.fn().mockImplementation(() => inst));
  return inst;
}

function renderPicker(overrides: Partial<Parameters<typeof VoicePicker>[0]> = {}) {
  const onSelect = vi.fn();
  render(
    <VoicePicker
      voices={voices}
      defaultVoiceId="v1"
      language="en-US"
      languageName="English"
      selected="v1"
      onSelect={onSelect}
      {...overrides}
    />,
  );
  return { onSelect };
}

describe('VoicePicker', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    _clearPreviewCache();
  });

  it('renders a card for each voice', () => {
    renderPicker();
    expect(screen.getByText('Rachel')).toBeInTheDocument();
    expect(screen.getByText('Adam')).toBeInTheDocument();
    expect(screen.getByText('Bella')).toBeInTheDocument();
  });

  it('shows Recommended badge on the default voice when it is not selected', () => {
    renderPicker({ selected: 'v2' });
    expect(screen.getByText('Recommended')).toBeInTheDocument();
  });

  it('does not show Recommended badge when the default voice is already selected', () => {
    renderPicker({ selected: 'v1' });
    expect(screen.queryByText('Recommended')).not.toBeInTheDocument();
  });

  it('marks the selected voice card as pressed', () => {
    renderPicker({ selected: 'v2' });
    expect(screen.getByRole('button', { name: /select adam/i })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByRole('button', { name: /select rachel/i })).toHaveAttribute('aria-pressed', 'false');
  });

  it('calls onSelect with the correct voice_id when a card is clicked', () => {
    const { onSelect } = renderPicker({ selected: 'v1' });
    fireEvent.click(screen.getByRole('button', { name: /select adam/i }));
    expect(onSelect).toHaveBeenCalledWith('v2');
  });

  it('renders known voice descriptors and tags', () => {
    renderPicker();
    expect(screen.getByText(/Warm · Calm · Storytelling/i)).toBeInTheDocument();
    expect(screen.getByText('Storytelling')).toBeInTheDocument();
  });

  it('shows language and voice count in the header', () => {
    renderPicker();
    expect(screen.getByText(/English · 3 voices/i)).toBeInTheDocument();
  });

  it('renders a Preview button for each voice', () => {
    renderPicker();
    const previewBtns = screen.getAllByRole('button', { name: /preview/i });
    expect(previewBtns.length).toBeGreaterThanOrEqual(3);
  });

  it('calls previewVoice with correct args when Preview is clicked', async () => {
    mockPreview.mockResolvedValue('blob:test');
    mockAudio();

    renderPicker();
    const previewBtn = screen.getAllByRole('button', { name: /preview rachel/i })[0];
    fireEvent.click(previewBtn);

    await waitFor(() => {
      expect(mockPreview).toHaveBeenCalledWith('v1', 'en-US');
    });
  });

  it('shows Generating… while preview is loading', async () => {
    mockPreview.mockReturnValue(new Promise(() => {})); // never resolves
    mockAudio();

    renderPicker();
    fireEvent.click(screen.getAllByRole('button', { name: /preview rachel/i })[0]);

    await waitFor(() => {
      expect(screen.getByText('Generating…')).toBeInTheDocument();
    });
  });

  it('shows Failed when preview API throws', async () => {
    mockPreview.mockRejectedValue(new Error('TTS unavailable'));
    mockAudio();

    renderPicker();
    fireEvent.click(screen.getAllByRole('button', { name: /preview rachel/i })[0]);

    await waitFor(() => {
      expect(screen.getByText('Failed')).toBeInTheDocument();
    });
  });

  it('preview button click does not trigger voice selection', async () => {
    mockPreview.mockReturnValue(new Promise(() => {}));
    mockAudio();

    const { onSelect } = renderPicker({ selected: 'v1' });
    fireEvent.click(screen.getAllByRole('button', { name: /preview adam/i })[0]);

    expect(onSelect).not.toHaveBeenCalled();
  });

  it('renders a single voice without a sibling', () => {
    renderPicker({ voices: [{ voice_id: 'v1', display_name: 'Rachel' }], selected: 'v1' });
    expect(screen.getByText('Rachel')).toBeInTheDocument();
    expect(screen.queryByText('Adam')).not.toBeInTheDocument();
  });
});
