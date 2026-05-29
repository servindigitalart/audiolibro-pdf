import { useState, useRef } from 'react';
import type { AvailableVoice } from '@/lib/api/types';
import { cn } from '@/lib/utils';
import { previewVoice } from '@/lib/api/client';

// Static voice metadata — keyed by lowercase display name (or fragment match)
const VOICE_CATALOG: Record<string, { descriptors: string; tags: string[] }> = {
  rachel:   { descriptors: 'Warm · Calm · Storytelling',       tags: ['Storytelling', 'Calm']         },
  adam:     { descriptors: 'Deep · Authoritative · Clear',     tags: ['Professional', 'Deep']         },
  bella:    { descriptors: 'Soft · Meditative · Soothing',     tags: ['Meditative', 'Calm']           },
  domi:     { descriptors: 'Clear · Precise · Educational',    tags: ['Educational', 'Natural']       },
  elli:     { descriptors: 'Bright · Friendly · Podcast',      tags: ['Podcast', 'Natural']           },
  josh:     { descriptors: 'Warm · Conversational · Natural',  tags: ['Casual', 'Natural']            },
  sam:      { descriptors: 'Dynamic · Energetic · Podcast',    tags: ['Podcast', 'Educational']       },
  charlie:  { descriptors: 'Crisp · Documentary · Assured',    tags: ['Documentary', 'Deep']          },
  emily:    { descriptors: 'Gentle · Story · Expressive',      tags: ['Storytelling', 'Natural']      },
  grace:    { descriptors: 'Clear · Measured · Professional',  tags: ['Professional', 'Calm']         },
  liam:     { descriptors: 'Strong · Deep · Resonant',         tags: ['Deep', 'Documentary']          },
  matilda:  { descriptors: 'Warm · Narrative · Rich',          tags: ['Storytelling', 'Warm']         },
  river:    { descriptors: 'Neutral · Balanced · Versatile',   tags: ['Natural', 'Educational']       },
  will:     { descriptors: 'Trustworthy · Clear · Steady',     tags: ['Educational', 'Professional']  },
  ethan:    { descriptors: 'Deep · Documentary · Engaged',     tags: ['Deep', 'Documentary']          },
  freja:    { descriptors: 'Clear · Nordic · Natural',         tags: ['Natural', 'Calm']              },
  lucia:    { descriptors: 'Warm · Calm · Storytelling',       tags: ['Storytelling', 'Warm']         },
  aria:     { descriptors: 'Expressive · Versatile · Warm',    tags: ['Natural', 'Warm']              },
  callum:   { descriptors: 'Composed · Deep · Professional',   tags: ['Professional', 'Deep']         },
  charlotte: { descriptors: 'Bright · Story · Engaging',      tags: ['Storytelling', 'Natural']      },
};

const FALLBACK_DESCRIPTORS = [
  { descriptors: 'Natural · Clear · Versatile',   tags: ['Natural']        },
  { descriptors: 'Warm · Expressive · Engaging',  tags: ['Warm']           },
  { descriptors: 'Deep · Measured · Professional', tags: ['Professional']  },
  { descriptors: 'Bright · Friendly · Clear',     tags: ['Natural']        },
];

const TAG_COLORS: Record<string, string> = {
  Storytelling:  'bg-amber-50 text-amber-700 border-amber-100',
  Calm:          'bg-sky-50 text-sky-700 border-sky-100',
  Professional:  'bg-slate-50 text-slate-600 border-slate-200',
  Podcast:       'bg-purple-50 text-purple-700 border-purple-100',
  Deep:          'bg-indigo-50 text-indigo-700 border-indigo-100',
  Meditative:    'bg-teal-50 text-teal-700 border-teal-100',
  Educational:   'bg-emerald-50 text-emerald-700 border-emerald-100',
  Natural:       'bg-green-50 text-green-600 border-green-100',
  Documentary:   'bg-stone-50 text-stone-600 border-stone-200',
  Casual:        'bg-orange-50 text-orange-700 border-orange-100',
  Warm:          'bg-rose-50 text-rose-700 border-rose-100',
};

const AVATAR_GRADIENTS = [
  'from-amber-400 to-orange-500',
  'from-blue-400 to-indigo-500',
  'from-emerald-400 to-teal-500',
  'from-rose-400 to-pink-500',
  'from-purple-400 to-violet-500',
  'from-sky-400 to-cyan-500',
  'from-lime-400 to-green-500',
  'from-fuchsia-400 to-purple-500',
];

function hashString(s: string): number {
  let h = 0;
  for (const c of s) h = (h * 31 + c.charCodeAt(0)) >>> 0;
  return h;
}

function getVoiceMeta(displayName: string, index: number) {
  const key = displayName.toLowerCase().trim();
  if (VOICE_CATALOG[key]) return VOICE_CATALOG[key];
  // Partial match: "Rachel (English)" → "rachel"
  for (const [k, v] of Object.entries(VOICE_CATALOG)) {
    if (key.includes(k) || k.includes(key)) return v;
  }
  return FALLBACK_DESCRIPTORS[index % FALLBACK_DESCRIPTORS.length];
}

function initials(name: string): string {
  return name
    .split(/[\s()_-]+/)
    .filter(Boolean)
    .map(w => w[0]?.toUpperCase() ?? '')
    .join('')
    .slice(0, 2);
}

function avatarGradient(name: string): string {
  return AVATAR_GRADIENTS[hashString(name) % AVATAR_GRADIENTS.length];
}

// Module-level blob URL cache (lives for the browser session)
const _previewCache = new Map<string, string>();
export const _clearPreviewCache = () => _previewCache.clear();

interface Props {
  voices:          AvailableVoice[];
  defaultVoiceId:  string;
  language:        string;
  languageName:    string;
  selected:        string;
  onSelect:        (voiceId: string) => void;
  narrationStyle?: string;
}

type PreviewState = 'idle' | 'loading' | 'playing' | 'error';

export default function VoicePicker({
  voices, defaultVoiceId, language, languageName, selected, onSelect, narrationStyle,
}: Props) {
  const [previewState, setPreviewState] = useState<Record<string, PreviewState>>({});
  const [activeVoice,  setActiveVoice]  = useState<string | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);

  function stopCurrent() {
    if (audioRef.current) {
      audioRef.current.pause();
      audioRef.current = null;
    }
  }

  async function handlePreview(e: React.MouseEvent, voice: AvailableVoice) {
    e.stopPropagation();
    const vid = voice.voice_id;

    // Toggle: stop if already playing this voice
    if (activeVoice === vid && previewState[vid] === 'playing') {
      stopCurrent();
      setActiveVoice(null);
      setPreviewState(s => ({ ...s, [vid]: 'idle' }));
      return;
    }

    stopCurrent();
    setActiveVoice(vid);
    setPreviewState(s => ({ ...s, [vid]: 'loading' }));

    const cacheKey = `${vid}:${narrationStyle ?? ''}`;
    const cached = _previewCache.get(cacheKey);
    if (cached) {
      playBlob(vid, cached);
      return;
    }

    try {
      console.log('[SONORO] voice_preview_requested', vid, 'style=', narrationStyle ?? 'default');
      const blobUrl = await previewVoice(vid, language, narrationStyle);
      _previewCache.set(cacheKey, blobUrl);
      console.log('[SONORO] voice_preview_style_applied', vid, 'style=', narrationStyle ?? 'default');
      playBlob(vid, blobUrl);
    } catch {
      console.warn('[SONORO] voice_preview_failed', vid);
      setPreviewState(s => ({ ...s, [vid]: 'error' }));
      setActiveVoice(null);
      setTimeout(() => setPreviewState(s => ({ ...s, [vid]: 'idle' })), 2000);
    }
  }

  function playBlob(vid: string, blobUrl: string) {
    const audio = new Audio(blobUrl);
    audioRef.current = audio;
    audio.onended = () => {
      setPreviewState(s => ({ ...s, [vid]: 'idle' }));
      setActiveVoice(null);
    };
    audio.onerror = () => {
      setPreviewState(s => ({ ...s, [vid]: 'error' }));
      setActiveVoice(null);
      setTimeout(() => setPreviewState(s => ({ ...s, [vid]: 'idle' })), 2000);
    };
    audio.play()
      .then(() => setPreviewState(s => ({ ...s, [vid]: 'playing' })))
      .catch(() => {
        setPreviewState(s => ({ ...s, [vid]: 'error' }));
        setActiveVoice(null);
      });
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-3">
        <p className="text-[10px] font-semibold text-sonoro-400 uppercase tracking-wider">
          Narration voice
        </p>
        <span className="text-[10px] text-sonoro-400">
          {languageName} · {voices.length} voice{voices.length !== 1 ? 's' : ''}
        </span>
      </div>

      <div className={cn(
        'grid gap-3',
        voices.length === 1 ? 'grid-cols-1' : 'grid-cols-1 sm:grid-cols-2',
      )}>
        {voices.map((voice, i) => {
          const meta      = getVoiceMeta(voice.display_name, i);
          const isSelected = voice.voice_id === selected;
          const isDefault  = voice.voice_id === defaultVoiceId;
          const pState    = previewState[voice.voice_id] ?? 'idle';
          const gradient  = avatarGradient(voice.display_name);

          return (
            <div
              key={voice.voice_id}
              role="button"
              tabIndex={0}
              onClick={() => onSelect(voice.voice_id)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                  e.preventDefault();
                  onSelect(voice.voice_id);
                }
              }}
              className={cn(
                'relative text-left rounded-2xl border p-4 transition-all duration-200 cursor-pointer select-none',
                'hover:shadow-md hover:-translate-y-px focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sonoro-amber/50',
                isSelected
                  ? 'border-sonoro-amber bg-sonoro-amber-light shadow-sm ring-1 ring-sonoro-amber/20'
                  : 'border-sonoro-border bg-white hover:border-sonoro-amber/40',
              )}
              aria-pressed={isSelected}
              aria-label={`Select ${voice.display_name} voice`}
            >
              {isDefault && !isSelected && (
                <span className="absolute -top-2 left-4 inline-flex items-center rounded-full bg-sonoro-amber px-2 py-0.5 text-[9px] font-bold text-sonoro-black">
                  Recommended
                </span>
              )}

              <div className="flex items-start gap-3">
                {/* Avatar */}
                <div className={cn(
                  'flex h-10 w-10 shrink-0 items-center justify-center rounded-xl text-white text-sm font-bold bg-gradient-to-br shadow-sm',
                  gradient,
                )}>
                  {initials(voice.display_name)}
                </div>

                <div className="flex-1 min-w-0">
                  <div className="flex items-center justify-between gap-2 mb-0.5">
                    <p className="text-sm font-semibold text-sonoro-900 leading-tight truncate">
                      {voice.display_name}
                    </p>
                    {isSelected && (
                      <svg className="w-4 h-4 text-sonoro-amber shrink-0" viewBox="0 0 20 20" fill="currentColor" aria-hidden="true">
                        <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.857-9.809a.75.75 0 00-1.214-.882l-3.483 4.79-1.88-1.88a.75.75 0 10-1.06 1.061l2.5 2.5a.75.75 0 001.137-.089l4-5.5z" clipRule="evenodd"/>
                      </svg>
                    )}
                  </div>

                  <p className="text-[11px] text-sonoro-muted leading-snug mb-2">
                    {meta.descriptors}
                  </p>

                  <div className="flex items-center justify-between gap-2">
                    {/* Tags */}
                    <div className="flex items-center gap-1 flex-wrap">
                      {meta.tags.slice(0, 2).map(tag => (
                        <span
                          key={tag}
                          className={cn(
                            'text-[10px] font-medium px-1.5 py-0.5 rounded-full border',
                            TAG_COLORS[tag] ?? 'bg-sonoro-surface text-sonoro-400 border-sonoro-border',
                          )}
                        >
                          {tag}
                        </span>
                      ))}
                    </div>

                    {/* Preview button */}
                    <button
                      type="button"
                      onClick={e => handlePreview(e, voice)}
                      disabled={pState === 'loading'}
                      className={cn(
                        'flex items-center gap-1 shrink-0 text-[10px] font-semibold px-2 py-1 rounded-full border transition-all',
                        pState === 'playing'
                          ? 'bg-sonoro-amber border-sonoro-amber text-sonoro-black'
                          : pState === 'error'
                          ? 'bg-red-50 border-red-200 text-red-600'
                          : 'bg-sonoro-surface border-sonoro-border text-sonoro-500 hover:border-sonoro-amber/50 hover:text-sonoro-amber-dark',
                        pState === 'loading' && 'opacity-60 cursor-not-allowed',
                      )}
                      aria-label={
                        pState === 'playing'
                          ? `Stop ${voice.display_name} preview`
                          : `Preview ${voice.display_name}`
                      }
                    >
                      {pState === 'loading' ? (
                        <>
                          <svg className="w-3 h-3 animate-spin" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                            <circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="3" strokeOpacity=".3"/>
                            <path d="M12 2a10 10 0 0 1 10 10" stroke="currentColor" strokeWidth="3" strokeLinecap="round"/>
                          </svg>
                          Generating…
                        </>
                      ) : pState === 'playing' ? (
                        <>
                          <svg className="w-2.5 h-2.5" viewBox="0 0 10 10" fill="currentColor" aria-hidden="true">
                            <rect x="1" y="1" width="3" height="8" rx="1"/>
                            <rect x="6" y="1" width="3" height="8" rx="1"/>
                          </svg>
                          Stop
                        </>
                      ) : pState === 'error' ? (
                        'Failed'
                      ) : (
                        <>
                          <svg className="w-2.5 h-2.5" viewBox="0 0 10 10" fill="currentColor" aria-hidden="true">
                            <path d="M2 1.5l6 3.5-6 3.5V1.5z"/>
                          </svg>
                          Preview
                        </>
                      )}
                    </button>
                  </div>
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
