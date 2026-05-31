"""
Tests for app.tts.narration_profiles
======================================
PHASE 5H: Real Narration Profiles

Coverage:
  - All five profiles are present and valid
  - Profile parameters are within Google TTS safe ranges
  - get_profile() and get_profile_or_default() retrieval logic
  - Backward compatibility: unknown/None style → storytelling
  - NarrationProfile dataclass validation
  - voice_compatibility_score() and rank_voices()
  - prepare_text_for_profile() per profile — no content changes
  - Text preparation is deterministic and idempotent
  - Migration safety: NULL narration_style → default profile
"""

import pytest
from app.tts.narration_profiles import (
    NarrationProfile,
    PROFILES,
    DEFAULT_PROFILE_NAME,
    get_profile,
    get_profile_or_default,
    voice_compatibility_score,
    rank_voices,
    prepare_text_for_profile,
)

pytestmark = pytest.mark.unit

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

KNOWN_PROFILES = {"calm", "storytelling", "documentary", "podcast", "educational"}

SAMPLE_TEXT = (
    "Dr. Smith entered the room. She looked around carefully.\n\n"
    "The memo-\n"
    "ry of that day lingered — like a shadow that never quite left.\n\n"
    "1. First point\n"
    "2. Second point\n"
    "3. Third point"
)


# ===========================================================================
# Profile registry completeness
# ===========================================================================

class TestProfileRegistry:
    def test_all_five_profiles_present(self):
        assert KNOWN_PROFILES == set(PROFILES.keys())

    def test_default_profile_name_is_storytelling(self):
        assert DEFAULT_PROFILE_NAME == "storytelling"

    def test_all_profiles_are_narration_profile_instances(self):
        for name, profile in PROFILES.items():
            assert isinstance(profile, NarrationProfile), f"{name} is not NarrationProfile"

    def test_profile_names_match_registry_keys(self):
        for key, profile in PROFILES.items():
            assert profile.name == key, f"key={key} profile.name={profile.name}"

    def test_all_profiles_have_display_name(self):
        for name, profile in PROFILES.items():
            assert profile.display_name, f"{name} missing display_name"

    def test_all_profiles_have_description(self):
        for name, profile in PROFILES.items():
            assert profile.description, f"{name} missing description"


# ===========================================================================
# Google TTS safe ranges
# ===========================================================================

class TestSafeRanges:
    @pytest.mark.parametrize("name", list(KNOWN_PROFILES))
    def test_speaking_rate_in_range(self, name):
        p = PROFILES[name]
        assert 0.25 <= p.speaking_rate <= 4.0, f"{name} rate={p.speaking_rate}"

    @pytest.mark.parametrize("name", list(KNOWN_PROFILES))
    def test_pitch_in_range(self, name):
        p = PROFILES[name]
        assert -20.0 <= p.pitch <= 20.0, f"{name} pitch={p.pitch}"

    def test_out_of_range_speaking_rate_raises(self):
        with pytest.raises(ValueError, match="speaking_rate"):
            NarrationProfile(
                name="bad", display_name="Bad", description="Bad",
                speaking_rate=5.0, pitch=0.0,
                pause_multiplier=1.0,
                sentence_pause_multiplier=1.0,
                paragraph_pause_multiplier=1.0,
                voice_preference_tags=(),
                text_prep_hints=frozenset(),
            )

    def test_out_of_range_pitch_raises(self):
        with pytest.raises(ValueError, match="pitch"):
            NarrationProfile(
                name="bad", display_name="Bad", description="Bad",
                speaking_rate=1.0, pitch=25.0,
                pause_multiplier=1.0,
                sentence_pause_multiplier=1.0,
                paragraph_pause_multiplier=1.0,
                voice_preference_tags=(),
                text_prep_hints=frozenset(),
            )


# ===========================================================================
# Profile parameter contracts per profile
# ===========================================================================

class TestProfileParameters:
    def test_calm_is_slower_than_podcast(self):
        assert PROFILES["calm"].speaking_rate < PROFILES["podcast"].speaking_rate

    def test_podcast_is_fastest(self):
        rates = {name: p.speaking_rate for name, p in PROFILES.items()}
        assert rates["podcast"] == max(rates.values())

    def test_calm_has_longest_pause_multiplier(self):
        multipliers = {name: p.pause_multiplier for name, p in PROFILES.items()}
        assert multipliers["calm"] == max(multipliers.values())

    def test_podcast_has_shortest_pause_multiplier(self):
        multipliers = {name: p.pause_multiplier for name, p in PROFILES.items()}
        assert multipliers["podcast"] == min(multipliers.values())

    def test_calm_pitch_is_lower_than_podcast(self):
        assert PROFILES["calm"].pitch < PROFILES["podcast"].pitch

    def test_documentary_has_lower_pitch_than_storytelling(self):
        assert PROFILES["documentary"].pitch < PROFILES["storytelling"].pitch

    def test_educational_pitch_is_neutral(self):
        assert PROFILES["educational"].pitch == pytest.approx(0.0)

    def test_all_profiles_have_voice_preference_tags(self):
        for name, profile in PROFILES.items():
            assert len(profile.voice_preference_tags) > 0, f"{name} has no voice tags"

    def test_all_profiles_have_text_prep_hints(self):
        for name, profile in PROFILES.items():
            assert isinstance(profile.text_prep_hints, frozenset)


# ===========================================================================
# Profile retrieval
# ===========================================================================

class TestProfileRetrieval:
    def test_get_profile_returns_correct_profile(self):
        for name in KNOWN_PROFILES:
            assert get_profile(name).name == name

    def test_get_profile_case_insensitive(self):
        assert get_profile("CALM").name == "calm"
        assert get_profile("Podcast").name == "podcast"
        assert get_profile("STORYTELLING").name == "storytelling"

    def test_get_profile_unknown_raises(self):
        with pytest.raises(KeyError):
            get_profile("asmr")

    def test_get_profile_or_default_returns_correct_profile(self):
        for name in KNOWN_PROFILES:
            assert get_profile_or_default(name).name == name

    def test_get_profile_or_default_none_returns_storytelling(self):
        assert get_profile_or_default(None).name == DEFAULT_PROFILE_NAME

    def test_get_profile_or_default_empty_string_returns_storytelling(self):
        assert get_profile_or_default("").name == DEFAULT_PROFILE_NAME

    def test_get_profile_or_default_unknown_returns_storytelling(self):
        assert get_profile_or_default("asmr").name == DEFAULT_PROFILE_NAME

    def test_get_profile_or_default_case_insensitive(self):
        assert get_profile_or_default("CALM").name == "calm"

    # Migration safety: existing rows with NULL narration_style
    def test_null_style_maps_to_storytelling(self):
        profile = get_profile_or_default(None)
        assert profile.name == "storytelling"
        # Storytelling should have near-natural rate (not dramatically altered)
        assert 0.90 <= profile.speaking_rate <= 1.05


# ===========================================================================
# Voice compatibility scoring
# ===========================================================================

class TestVoiceCompatibility:
    def test_warm_voice_scores_well_with_calm(self):
        # en-US-Neural2-A is tagged ("female", "warm", "smooth")
        # calm prefers ("warm", "smooth", "soft", "female")
        score = voice_compatibility_score("en-US-Neural2-A", PROFILES["calm"])
        assert score > 0.5

    def test_deep_voice_scores_well_with_documentary(self):
        # en-US-Neural2-B is ("male", "deep", "authoritative")
        # documentary prefers ("deep", "authoritative", "clear", "male")
        score = voice_compatibility_score("en-US-Neural2-B", PROFILES["documentary"])
        assert score > 0.5

    def test_conversational_voice_scores_well_with_podcast(self):
        # en-US-Neural2-C is ("female", "conversational", "engaging", "clear")
        # podcast prefers ("conversational", "warm", "engaging", "clear")
        score = voice_compatibility_score("en-US-Neural2-C", PROFILES["podcast"])
        assert score > 0.5

    def test_unknown_voice_scores_zero(self):
        assert voice_compatibility_score("xx-XX-Unknown-Z", PROFILES["calm"]) == 0.0

    def test_score_is_between_zero_and_one(self):
        voices = ["en-US-Neural2-A", "en-US-Neural2-B", "en-US-Neural2-J"]
        for vid in voices:
            for profile in PROFILES.values():
                score = voice_compatibility_score(vid, profile)
                assert 0.0 <= score <= 1.0, f"{vid}/{profile.name} score={score}"

    def test_perfect_tag_match_scores_one(self):
        # If we construct a profile whose only tag is "warm" and use a voice
        # that has "warm" as a tag, score must be 1.0
        profile = NarrationProfile(
            name="test", display_name="Test", description="Test",
            speaking_rate=1.0, pitch=0.0,
            pause_multiplier=1.0,
            sentence_pause_multiplier=1.0,
            paragraph_pause_multiplier=1.0,
            voice_preference_tags=("warm",),  # single tag
            text_prep_hints=frozenset(),
        )
        # en-US-Neural2-A has "warm" in its tags
        assert voice_compatibility_score("en-US-Neural2-A", profile) == pytest.approx(1.0)

    def test_rank_voices_sorted_descending(self):
        voices = ["en-US-Neural2-B", "en-US-Neural2-A", "en-US-Neural2-J"]
        ranked = rank_voices(voices, PROFILES["documentary"])
        scores = [s for _, s in ranked]
        assert scores == sorted(scores, reverse=True)

    def test_rank_voices_returns_all_voices(self):
        voices = ["en-US-Neural2-A", "en-US-Neural2-B", "en-US-Neural2-C"]
        ranked = rank_voices(voices, PROFILES["calm"])
        assert {v for v, _ in ranked} == set(voices)

    def test_rank_voices_empty_input(self):
        assert rank_voices([], PROFILES["calm"]) == []

    def test_documentary_best_voice_is_deep(self):
        male_deep = ["en-US-Neural2-B", "en-US-Neural2-J"]
        warm_female = ["en-US-Neural2-A", "en-US-Neural2-F"]
        all_voices = male_deep + warm_female
        ranked = rank_voices(all_voices, PROFILES["documentary"])
        top_two = {v for v, _ in ranked[:2]}
        assert len(top_two.intersection(male_deep)) >= 1


# ===========================================================================
# prepare_text_for_profile — no content changes
# ===========================================================================

class TestPrepareTextForProfile:
    def test_returns_non_empty_string(self):
        for profile in PROFILES.values():
            result = prepare_text_for_profile("Hello world.", profile)
            assert isinstance(result, str)
            assert result.strip()

    def test_empty_input_returns_empty(self):
        for profile in PROFILES.values():
            assert prepare_text_for_profile("", profile) == ""

    def test_whitespace_only_returns_empty(self):
        for profile in PROFILES.values():
            result = prepare_text_for_profile("   \n\n  ", profile)
            assert result == ""

    def test_words_preserved_across_all_profiles(self):
        text = "The quick brown fox jumps over the lazy dog."
        for profile in PROFILES.values():
            result = prepare_text_for_profile(text, profile)
            assert "quick brown fox" in result, f"{profile.name} lost content"
            assert "lazy dog" in result, f"{profile.name} lost content"

    def test_dr_abbreviation_handled(self):
        text = "Dr. Smith was present."
        result = prepare_text_for_profile(text, PROFILES["calm"])
        assert "Smith" in result
        # Period after Dr should be removed (abbreviation safety)
        assert "Dr " in result

    def test_calm_preserves_em_dash(self):
        text = "He spoke — very quietly — to the crowd."
        result = prepare_text_for_profile(text, PROFILES["calm"])
        assert " — " in result
        assert "quietly" in result

    def test_storytelling_preserves_em_dash(self):
        text = "She waited — her heart pounding."
        result = prepare_text_for_profile(text, PROFILES["storytelling"])
        assert " — " in result

    def test_documentary_handles_lists(self):
        text = "The key findings:\n1.First finding\n2.Second finding"
        result = prepare_text_for_profile(text, PROFILES["documentary"])
        # emphasize_lists ensures spacing after list markers
        assert "1. First" in result or "1.First" in result  # marker preserved
        assert "Second" in result

    def test_educational_handles_lists(self):
        text = "Steps:\n1.Install\n2.Configure\n3.Run"
        result = prepare_text_for_profile(text, PROFILES["educational"])
        assert "Install" in result
        assert "Configure" in result
        assert "Run" in result

    def test_podcast_does_not_destroy_content(self):
        text = "Welcome back, everyone! Today we're discussing Phase 5H."
        result = prepare_text_for_profile(text, PROFILES["podcast"])
        assert "Phase 5H" in result
        assert "everyone" in result

    def test_ellipsis_normalized(self):
        text = "He paused… and then spoke."
        for profile in PROFILES.values():
            result = prepare_text_for_profile(text, profile)
            assert "…" not in result, f"{profile.name} left unicode ellipsis"
            assert "paused" in result

    def test_paragraph_breaks_preserved(self):
        text = "First paragraph here.\n\nSecond paragraph here."
        for profile in PROFILES.values():
            result = prepare_text_for_profile(text, profile)
            assert "\n\n" in result, f"{profile.name} lost paragraph break"

    def test_hyphenated_word_repaired(self):
        text = "The memo-\nry was vivid."
        for profile in PROFILES.values():
            result = prepare_text_for_profile(text, profile)
            assert "memory" in result, f"{profile.name} did not repair hyphen"


# ===========================================================================
# Determinism and idempotency
# ===========================================================================

class TestDeterminism:
    def test_same_output_on_repeated_calls(self):
        for profile in PROFILES.values():
            r1 = prepare_text_for_profile(SAMPLE_TEXT, profile)
            r2 = prepare_text_for_profile(SAMPLE_TEXT, profile)
            r3 = prepare_text_for_profile(SAMPLE_TEXT, profile)
            assert r1 == r2 == r3, f"{profile.name} is not deterministic"

    def test_idempotent_on_all_profiles(self):
        for profile in PROFILES.values():
            once  = prepare_text_for_profile(SAMPLE_TEXT, profile)
            twice = prepare_text_for_profile(once, profile)
            assert once == twice, f"{profile.name} is not idempotent"

    def test_profile_dataclass_is_frozen(self):
        profile = PROFILES["calm"]
        with pytest.raises((AttributeError, TypeError)):
            profile.speaking_rate = 0.5  # type: ignore[misc]


# ===========================================================================
# Backward compatibility for existing jobs
# ===========================================================================

class TestBackwardCompatibility:
    def test_none_resolves_to_storytelling(self):
        p = get_profile_or_default(None)
        assert p.name == "storytelling"

    def test_storytelling_is_most_neutral_rate(self):
        # Storytelling should have a near-natural rate (not aggressively modified)
        p = PROFILES["storytelling"]
        assert 0.93 <= p.speaking_rate <= 1.02

    def test_all_profiles_serializable(self):
        import dataclasses, json
        for name, profile in PROFILES.items():
            d = dataclasses.asdict(profile)
            # frozenset is not directly JSON serializable; convert for test
            d["text_prep_hints"] = sorted(d["text_prep_hints"])
            json.dumps(d)  # must not raise

    def test_profile_str_representation(self):
        # NarrationProfile is a frozen dataclass; str() should not raise
        for profile in PROFILES.values():
            s = str(profile)
            assert profile.name in s
