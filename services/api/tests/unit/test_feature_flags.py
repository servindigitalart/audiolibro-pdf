"""
Unit tests for the feature flag registry.
"""

import pytest

from app.core.feature_flags import Flag, FeatureFlags, get_flags


@pytest.fixture(autouse=True)
def _reset_flags():
    """Ensure runtime overrides don't leak between tests."""
    get_flags().reset()
    yield
    get_flags().reset()


# ── Singleton ─────────────────────────────────────────────────────────────────

def test_get_flags_returns_singleton():
    assert get_flags() is get_flags()


# ── Default behaviour ─────────────────────────────────────────────────────────

def test_unknown_flag_defaults_false():
    flags = FeatureFlags()
    # Flag not in _SETTINGS_MAP (simulate by checking a real flag with no settings key)
    assert flags.is_enabled(Flag.EMAIL_VERIFICATION) is False


def test_flags_default_false_without_settings_override(monkeypatch):
    flags = FeatureFlags()
    # email_verification defaults to False in Settings
    assert flags.is_enabled(Flag.EMAIL_VERIFICATION) is False


# ── Runtime overrides ─────────────────────────────────────────────────────────

def test_enable_sets_flag_true():
    flags = get_flags()
    flags.enable(Flag.RATE_LIMITING)
    assert flags.is_enabled(Flag.RATE_LIMITING) is True


def test_disable_sets_flag_false():
    flags = get_flags()
    flags.enable(Flag.RATE_LIMITING)
    flags.disable(Flag.RATE_LIMITING)
    assert flags.is_enabled(Flag.RATE_LIMITING) is False


def test_disable_overrides_settings_default_true(monkeypatch):
    from app.core import feature_flags as ff_mod
    monkeypatch.setattr(ff_mod.settings, "feature_document_upload", True)
    flags = get_flags()
    assert flags.is_enabled(Flag.DOCUMENT_UPLOAD) is True
    flags.disable(Flag.DOCUMENT_UPLOAD)
    assert flags.is_enabled(Flag.DOCUMENT_UPLOAD) is False


def test_enable_overrides_settings_default_false(monkeypatch):
    from app.core import feature_flags as ff_mod
    monkeypatch.setattr(ff_mod.settings, "feature_rate_limiting", False)
    flags = get_flags()
    assert flags.is_enabled(Flag.RATE_LIMITING) is False
    flags.enable(Flag.RATE_LIMITING)
    assert flags.is_enabled(Flag.RATE_LIMITING) is True


# ── Reset ─────────────────────────────────────────────────────────────────────

def test_reset_single_flag():
    flags = get_flags()
    flags.enable(Flag.RATE_LIMITING)
    flags.enable(Flag.STRIPE_BILLING)
    flags.reset(Flag.RATE_LIMITING)
    assert flags.is_enabled(Flag.RATE_LIMITING) is False
    assert flags.is_enabled(Flag.STRIPE_BILLING) is True


def test_reset_all_flags():
    flags = get_flags()
    flags.enable(Flag.RATE_LIMITING)
    flags.enable(Flag.STRIPE_BILLING)
    flags.enable(Flag.REQUEST_TRACING)
    flags.reset()
    assert flags.is_enabled(Flag.RATE_LIMITING) is False
    assert flags.is_enabled(Flag.STRIPE_BILLING) is False
    assert flags.is_enabled(Flag.REQUEST_TRACING) is False


def test_reset_nonexistent_flag_is_noop():
    flags = get_flags()
    flags.reset(Flag.RATE_LIMITING)  # never enabled — should not raise


# ── Settings-backed defaults ──────────────────────────────────────────────────

def test_settings_field_true_makes_flag_enabled(monkeypatch):
    from app.core import feature_flags as ff_mod
    monkeypatch.setattr(ff_mod.settings, "feature_email_verification", True)
    flags = get_flags()
    assert flags.is_enabled(Flag.EMAIL_VERIFICATION) is True


def test_settings_field_false_makes_flag_disabled(monkeypatch):
    from app.core import feature_flags as ff_mod
    monkeypatch.setattr(ff_mod.settings, "feature_document_upload", False)
    flags = get_flags()
    assert flags.is_enabled(Flag.DOCUMENT_UPLOAD) is False


# ── Priority: override > settings ─────────────────────────────────────────────

def test_runtime_override_beats_settings_true(monkeypatch):
    from app.core import feature_flags as ff_mod
    monkeypatch.setattr(ff_mod.settings, "feature_rate_limiting", True)
    flags = get_flags()
    flags.disable(Flag.RATE_LIMITING)
    assert flags.is_enabled(Flag.RATE_LIMITING) is False


def test_runtime_override_beats_settings_false(monkeypatch):
    from app.core import feature_flags as ff_mod
    monkeypatch.setattr(ff_mod.settings, "feature_stripe_billing", False)
    flags = get_flags()
    flags.enable(Flag.STRIPE_BILLING)
    assert flags.is_enabled(Flag.STRIPE_BILLING) is True


# ── Containment sugar ─────────────────────────────────────────────────────────

def test_contains_syntax_enabled():
    flags = get_flags()
    flags.enable(Flag.ABUSE_DETECTION)
    assert Flag.ABUSE_DETECTION in flags


def test_contains_syntax_disabled():
    flags = get_flags()
    flags.disable(Flag.ABUSE_DETECTION)
    assert Flag.ABUSE_DETECTION not in flags


# ── Flag independence ─────────────────────────────────────────────────────────

def test_flags_are_independent():
    flags = get_flags()
    flags.enable(Flag.RATE_LIMITING)
    flags.disable(Flag.STRIPE_BILLING)
    assert flags.is_enabled(Flag.RATE_LIMITING) is True
    assert flags.is_enabled(Flag.STRIPE_BILLING) is False
    assert flags.is_enabled(Flag.EMAIL_VERIFICATION) is False


# ── Isolated instance ─────────────────────────────────────────────────────────

def test_isolated_instance_independent_of_singleton():
    singleton = get_flags()
    singleton.enable(Flag.RATE_LIMITING)

    isolated = FeatureFlags()
    assert isolated.is_enabled(Flag.RATE_LIMITING) is False
