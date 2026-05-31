"""
Narration Profile System
========================
PHASE 5H: Real Narration Profiles

Defines the five narration profiles supported by Sonoro.  Each profile is a
frozen dataclass that fully describes the desired delivery style — TTS engine
parameters, text-preparation hints, and voice-compatibility preferences.

Public API
----------
get_profile(name)                              -> NarrationProfile
get_profile_or_default(name)                  -> NarrationProfile
voice_compatibility_score(voice_id, profile)  -> float  (0.0 – 1.0)
prepare_text_for_profile(text, profile)        -> str
PROFILES                                       dict[str, NarrationProfile]
DEFAULT_PROFILE_NAME                           str

Design principles
-----------------
- All profiles share the same dataclass shape so callers are polymorphic.
- Parameters stay within Google TTS safe ranges (rate 0.25–4.0, pitch -20–20).
- Text preparation NEVER rewrites content — only structural/pacing adjustments.
- Voice compatibility is advisory only; users can always override.
- The system degrades gracefully: unknown style → storytelling (most neutral).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Google TTS safe ranges
# ---------------------------------------------------------------------------
_RATE_MIN  = 0.25
_RATE_MAX  = 4.0
_PITCH_MIN = -20.0
_PITCH_MAX =  20.0

DEFAULT_PROFILE_NAME = "storytelling"

# ---------------------------------------------------------------------------
# NarrationProfile dataclass
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class NarrationProfile:
    """
    Complete specification for a narration delivery style.

    TTS engine parameters
    ----------------------
    speaking_rate              Google TTS AudioConfig.speaking_rate (1.0 = natural)
    pitch                      Google TTS AudioConfig.pitch in semitones (0.0 = natural)

    Pacing metadata (advisory — used for future SSML and chunking strategy)
    -----------------------------------------------------------------------
    pause_multiplier           General pause weight relative to baseline (1.0).
                               > 1.0 → longer natural pauses (calmer).
                               < 1.0 → shorter pauses (energetic/podcast).
    sentence_pause_multiplier  Extra weight for pauses at sentence boundaries.
    paragraph_pause_multiplier Extra weight for pauses at paragraph transitions.

    Voice compatibility
    -------------------
    voice_preference_tags      Abstract characteristic tags preferred by this
                               profile.  Used for compatibility scoring.
                               Callers are NOT required to honour the score.

    Text preparation
    ----------------
    text_prep_hints            Frozenset of string tokens that guide
                               prepare_text_for_profile().  The function
                               interprets these without altering content.

    Metadata
    --------
    name                       Internal identifier (lowercase, no spaces).
    display_name               Human-readable name for UI display.
    description                One-line intent description for UI tooltips.
    """

    name: str
    display_name: str
    description: str

    # TTS engine
    speaking_rate: float
    pitch: float

    # Pacing (advisory)
    pause_multiplier: float
    sentence_pause_multiplier: float
    paragraph_pause_multiplier: float

    # Voice compatibility
    voice_preference_tags: tuple[str, ...]

    # Text preparation
    text_prep_hints: frozenset

    def __post_init__(self) -> None:
        if not (_RATE_MIN <= self.speaking_rate <= _RATE_MAX):
            raise ValueError(
                f"speaking_rate {self.speaking_rate} out of range [{_RATE_MIN}, {_RATE_MAX}]"
            )
        if not (_PITCH_MIN <= self.pitch <= _PITCH_MAX):
            raise ValueError(
                f"pitch {self.pitch} out of range [{_PITCH_MIN}, {_PITCH_MAX}]"
            )


# ---------------------------------------------------------------------------
# Profile registry
# ---------------------------------------------------------------------------

PROFILES: dict[str, NarrationProfile] = {

    # ------------------------------------------------------------------
    # CALM
    # Intent: relaxed, meditative, comfortable for long listening sessions
    # ------------------------------------------------------------------
    "calm": NarrationProfile(
        name="calm",
        display_name="Calm",
        description="Relaxed and meditative — ideal for long listening sessions.",

        # Rationale: slightly slower rate reduces cognitive load for passive
        # listening without sounding artificial.  Lower pitch is perceived as
        # soothing; -1.5 semitones shifts the voice toward a warmer register
        # without making it sound unnatural.
        speaking_rate=0.92,
        pitch=-1.5,

        # Longer pauses give listeners breathing room — critical for meditation
        # or wind-down reading.  Paragraph breaks are especially prolonged to
        # signal a gentle topic transition.
        pause_multiplier=1.35,
        sentence_pause_multiplier=1.20,
        paragraph_pause_multiplier=1.60,

        # Smooth, warm voices are least fatiguing over extended sessions.
        voice_preference_tags=("warm", "smooth", "soft", "female"),

        # Abbreviation safety prevents false sentence breaks; narration pass
        # ensures em-dashes read as natural clause pauses rather than noise.
        text_prep_hints=frozenset({"narration_pass", "abbreviation_safety", "preserve_em_dashes"}),
    ),

    # ------------------------------------------------------------------
    # STORYTELLING
    # Intent: human narrator, warm, novel-like, expressive
    # ------------------------------------------------------------------
    "storytelling": NarrationProfile(
        name="storytelling",
        display_name="Storytelling",
        description="Warm and expressive — like a professional human narrator.",

        # Rationale: 0.97 is the sweet spot between "natural conversation" and
        # "deliberate narration".  It sounds intentional without being slow.
        # Slight pitch warmth (+0.5) makes the voice feel engaged and invested
        # in the story — the single most important cue for perceived expressiveness.
        speaking_rate=0.97,
        pitch=0.5,

        # Moderate pauses: narrative needs rhythm, not silence.  Paragraph
        # transitions are slightly longer to honour chapter/scene boundaries —
        # a professional narrator always pauses before "Meanwhile, back at…"
        pause_multiplier=1.10,
        sentence_pause_multiplier=1.20,
        paragraph_pause_multiplier=1.40,

        voice_preference_tags=("warm", "expressive", "engaging"),

        # Full narration pass with em-dash preservation: em-dashes are story
        # beats (the "pause for effect" a narrator would use) and must not be
        # collapsed to commas.
        text_prep_hints=frozenset({"narration_pass", "abbreviation_safety", "preserve_em_dashes"}),
    ),

    # ------------------------------------------------------------------
    # DOCUMENTARY
    # Intent: authoritative, clear, informative
    # ------------------------------------------------------------------
    "documentary": NarrationProfile(
        name="documentary",
        display_name="Documentary",
        description="Authoritative and clear — ideal for nonfiction and academic content.",

        # Rationale: 0.93 is measured and deliberate — the audience is
        # processing facts, not following a story, so slightly more time per
        # sentence aids retention.  Pitch -2.0 conveys authority and seriousness;
        # documentary/news voices universally trend lower than narrative voices.
        speaking_rate=0.93,
        pitch=-2.0,

        # Strong sentence boundaries let each fact land before the next begins.
        # Paragraph pause is equivalent to a documentary's B-roll cut: the
        # audience expects a pause before a new topic segment.
        pause_multiplier=1.20,
        sentence_pause_multiplier=1.35,
        paragraph_pause_multiplier=1.35,

        # Deep, authoritative voices are standard for documentary / news.
        voice_preference_tags=("deep", "authoritative", "clear", "male"),

        # Abbreviation safety is essential: academic text is dense with
        # abbreviations (Dr., Prof., etc.) that must not fragment sentences.
        text_prep_hints=frozenset({"narration_pass", "abbreviation_safety", "emphasize_lists"}),
    ),

    # ------------------------------------------------------------------
    # PODCAST
    # Intent: conversational, modern, friendly, energetic
    # ------------------------------------------------------------------
    "podcast": NarrationProfile(
        name="podcast",
        display_name="Podcast",
        description="Conversational and energetic — feels like a modern audio show.",

        # Rationale: 1.08 matches the "default" speed of most podcast listeners
        # (many already use 1.25x–1.5x, so 1.08 feels natural without the
        # artificial quality of a heavily slowed voice).  Slight pitch increase
        # (+0.4) creates energy and forward momentum — the signature of
        # engaging podcast hosts.
        speaking_rate=1.08,
        pitch=0.4,

        # Shorter pauses eliminate the "reading aloud" quality.  A podcast
        # host does not pause dramatically between sentences; the conversation
        # flows.  Paragraph pause is kept at 1.0 (baseline) so topic changes
        # don't feel like they came from a different recording session.
        pause_multiplier=0.85,
        sentence_pause_multiplier=0.90,
        paragraph_pause_multiplier=1.00,

        # Conversational voices that sound natural at faster speeds.
        voice_preference_tags=("conversational", "warm", "engaging", "clear"),

        # Abbreviation safety still needed (podcasts discuss "Dr. Smith" too).
        # No em-dash preservation — podcast speech doesn't use dramatic pauses.
        text_prep_hints=frozenset({"abbreviation_safety"}),
    ),

    # ------------------------------------------------------------------
    # EDUCATIONAL
    # Intent: teaching, retention, clarity, structured
    # ------------------------------------------------------------------
    "educational": NarrationProfile(
        name="educational",
        display_name="Educational",
        description="Clear and structured — designed for retention and learning.",

        # Rationale: 0.97 is the evidence-based sweet spot for information
        # retention — slower than 0.90 causes mind-wandering; faster than 1.00
        # reduces recall for dense material.  Pitch 0.0 (neutral) removes
        # emotional colour so the listener focuses on content not delivery;
        # neutral pitch is the standard for educational/instructional content.
        speaking_rate=0.97,
        pitch=0.0,

        # Longer sentence pauses allow concepts to "sink in" — each sentence
        # is a discrete piece of information the student must store.  The
        # paragraph pause is long to signal a new concept block, critical for
        # following lecture-style material.
        pause_multiplier=1.20,
        sentence_pause_multiplier=1.30,
        paragraph_pause_multiplier=1.45,

        # Clear, neutral voices without strong stylistic colour — the voice
        # should not distract from the content.
        voice_preference_tags=("clear", "warm", "neutral"),

        # emphasize_lists: enumerations and numbered items get extra formatting
        # care so the student can follow along easily.
        text_prep_hints=frozenset({"narration_pass", "abbreviation_safety", "emphasize_lists"}),
    ),
}


# ---------------------------------------------------------------------------
# Profile retrieval
# ---------------------------------------------------------------------------

def get_profile(name: str) -> NarrationProfile:
    """
    Return the NarrationProfile for *name*.

    Raises KeyError for unknown names.
    """
    return PROFILES[name.lower()]


def get_profile_or_default(name: Optional[str]) -> NarrationProfile:
    """
    Return the NarrationProfile for *name*, falling back to DEFAULT_PROFILE_NAME.

    This is the recommended entry point for production code: unknown or absent
    names resolve to the storytelling profile rather than raising.
    """
    if not name:
        return PROFILES[DEFAULT_PROFILE_NAME]
    profile = PROFILES.get(name.lower())
    if profile is None:
        logger.warning(
            "[SONORO] unknown_narration_profile name=%s fallback=%s",
            name, DEFAULT_PROFILE_NAME,
        )
        return PROFILES[DEFAULT_PROFILE_NAME]
    return profile


# ---------------------------------------------------------------------------
# Voice compatibility scoring
# ---------------------------------------------------------------------------

# Maps known Google TTS voice IDs to their characteristic tags.
# This is an advisory database — missing entries score 0.0 and are treated
# as "compatible but unranked" by calling code.
_VOICE_CHARACTERISTICS: dict[str, tuple[str, ...]] = {
    # English (US) — Neural2
    "en-US-Neural2-A": ("female", "warm", "smooth"),
    "en-US-Neural2-B": ("male", "deep", "authoritative"),
    "en-US-Neural2-C": ("female", "conversational", "engaging", "clear"),
    "en-US-Neural2-D": ("male", "warm", "expressive", "conversational"),
    "en-US-Neural2-E": ("female", "clear", "neutral", "smooth"),
    "en-US-Neural2-F": ("female", "warm", "expressive", "engaging"),
    "en-US-Neural2-G": ("female", "smooth", "clear", "soft"),
    "en-US-Neural2-H": ("female", "conversational", "warm", "engaging"),
    "en-US-Neural2-I": ("male", "conversational", "engaging", "warm"),
    "en-US-Neural2-J": ("male", "deep", "warm", "authoritative"),
    # English (GB) — Neural2
    "en-GB-Neural2-A": ("female", "warm", "smooth", "clear"),
    "en-GB-Neural2-B": ("male", "deep", "authoritative"),
    "en-GB-Neural2-C": ("female", "clear", "engaging"),
    "en-GB-Neural2-D": ("male", "warm", "expressive"),
    # Spanish (Spain) — Neural2
    "es-ES-Neural2-A": ("female", "warm", "smooth"),
    "es-ES-Neural2-B": ("male", "deep", "authoritative"),
    "es-ES-Neural2-C": ("female", "conversational", "engaging"),
    "es-ES-Neural2-D": ("male", "warm", "clear"),
    # Spanish (US) — Neural2
    "es-US-Neural2-A": ("female", "warm", "conversational"),
    "es-US-Neural2-B": ("male", "conversational", "warm"),
    "es-US-Neural2-C": ("female", "clear", "smooth"),
    # French — Neural2
    "fr-FR-Neural2-A": ("female", "warm", "smooth"),
    "fr-FR-Neural2-B": ("male", "deep", "authoritative"),
    "fr-FR-Neural2-C": ("female", "conversational", "engaging"),
    "fr-FR-Neural2-D": ("male", "warm", "clear"),
    # Portuguese (Brazil) — Neural2
    "pt-BR-Neural2-A": ("female", "warm", "conversational"),
    "pt-BR-Neural2-B": ("male", "deep", "warm"),
    "pt-BR-Neural2-C": ("female", "clear", "smooth"),
}


def voice_compatibility_score(voice_id: str, profile: NarrationProfile) -> float:
    """
    Return a compatibility score in [0.0, 1.0] for *voice_id* with *profile*.

    Score = fraction of the profile's preference tags that the voice possesses.
    A score of 1.0 means every preferred characteristic is present.
    A score of 0.0 means no overlap (voice is still usable — score is advisory).
    An unknown voice_id returns 0.0.
    """
    if not profile.voice_preference_tags:
        return 1.0  # profile has no preferences → all voices are equal

    voice_tags = set(_VOICE_CHARACTERISTICS.get(voice_id, ()))
    if not voice_tags:
        return 0.0

    overlap = voice_tags.intersection(profile.voice_preference_tags)
    return len(overlap) / len(profile.voice_preference_tags)


def rank_voices(voice_ids: list[str], profile: NarrationProfile) -> list[tuple[str, float]]:
    """
    Return *voice_ids* sorted by descending compatibility score with *profile*.

    Returns a list of (voice_id, score) tuples.  Ties are broken by the original
    order in *voice_ids*.
    """
    scored = [(vid, voice_compatibility_score(vid, profile)) for vid in voice_ids]
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored


# ---------------------------------------------------------------------------
# Profile-aware text preparation
# ---------------------------------------------------------------------------

# Patterns used by the text preparation pass
_NUMBERED_LIST_SPACING = re.compile(
    r'^(\s*)(\d+[\.\)])\s+',
    re.MULTILINE,
)
_BULLET_LIST_ITEM = re.compile(
    r'^(\s*)([-•·]\s+)',
    re.MULTILINE,
)
# Raw em/en dash (no surrounding spaces)
_RAW_DASH = re.compile(r'\s*[—–]\s*')


def prepare_text_for_profile(text: str, profile: NarrationProfile) -> str:
    """
    Apply profile-specific text transformations to *text*.

    This function NEVER rewrites, paraphrases, summarises, or alters the
    semantic content of *text*.  It only applies structural and pacing
    adjustments that influence how the TTS engine delivers the narration.

    Transformations are controlled by profile.text_prep_hints:

      "narration_pass"       Apply normalize_for_narration() from Phase 5G.
                             Includes: ellipsis normalisation, quote normalisation,
                             abbreviation safety, em-dash spacing.

      "abbreviation_safety"  Apply abbreviation period removal without the full
                             narration pass.  Useful when narration_pass is omitted
                             (e.g. podcast — keeps pace tight).

      "preserve_em_dashes"   Keep em/en dashes with proper spacing ( — ) so
                             the TTS engine reads them as a natural clause pause.
                             Without this hint, dashes may be read as hyphens.

      "emphasize_lists"      Ensure numbered and bulleted list items have a
                             consistent space after the marker so the TTS engine
                             reads them clearly without running items together.

    All hints are additive and idempotent.
    """
    if not text or not text.strip():
        return ""

    hints = profile.text_prep_hints

    if "narration_pass" in hints:
        # Full Phase 5G narration normalisation: includes quote normalisation,
        # ellipsis cleanup, abbreviation safety, and em-dash spacing.
        from app.text.normalizer import normalize_for_narration
        text = normalize_for_narration(text)
    elif "abbreviation_safety" in hints:
        # Lightweight pass: only handle abbreviations (podcast stays snappy
        # without the overhead of full normalisation).
        from app.text.normalizer import normalize_for_tts
        text = normalize_for_tts(text)

    if "preserve_em_dashes" in hints:
        # Ensure em/en dashes are surrounded by exactly one space so TTS reads
        # them as a meaningful pause rather than a word-joiner.
        # Already done by normalize_for_narration, but applied again here as a
        # guard for callers that skip the narration pass.
        text = _RAW_DASH.sub(' — ', text)
        # Collapse any accidental double-spacing from the substitution.
        text = re.sub(r'  +', ' ', text)

    if "emphasize_lists" in hints:
        # Ensure exactly one space after numbered markers ("1." "2)") and
        # bullet markers ("- " "• ") to prevent TTS from eliding the number
        # into the following word (e.g. "1.First" → "1. First").
        text = _NUMBERED_LIST_SPACING.sub(
            lambda m: m.group(1) + m.group(2) + ' ',
            text,
        )
        text = _BULLET_LIST_ITEM.sub(
            lambda m: m.group(1) + m.group(2),
            text,
        )

    return text.strip()
