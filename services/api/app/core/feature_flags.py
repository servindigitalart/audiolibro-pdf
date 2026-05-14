"""
Feature Flags
=============
Environment-aware feature flag registry with runtime override support.

Priority (highest to lowest):
  1. Runtime override (enable/disable called in code or tests)
  2. Settings field (environment variable)
  3. Default: False
"""

from enum import Enum
from typing import Optional

from app.core.config import settings


class Flag(str, Enum):
    EMAIL_VERIFICATION = "email_verification"
    RATE_LIMITING = "rate_limiting"
    DOCUMENT_UPLOAD = "document_upload"
    TTS_PROCESSING = "tts_processing"
    STRIPE_BILLING = "stripe_billing"
    ABUSE_DETECTION = "abuse_detection"
    REQUEST_TRACING = "request_tracing"
    BILLING_ENFORCEMENT = "billing_enforcement"


_SETTINGS_MAP: dict[str, str] = {
    Flag.EMAIL_VERIFICATION: "feature_email_verification",
    Flag.RATE_LIMITING: "feature_rate_limiting",
    Flag.DOCUMENT_UPLOAD: "feature_document_upload",
    Flag.TTS_PROCESSING: "feature_tts_processing",
    Flag.STRIPE_BILLING: "feature_stripe_billing",
    Flag.ABUSE_DETECTION: "feature_abuse_detection",
    Flag.REQUEST_TRACING: "feature_request_tracing",
    Flag.BILLING_ENFORCEMENT: "feature_billing_enforcement",
}


class FeatureFlags:
    """
    Registry for feature flags with runtime override support.

    Typical usage in tests:
        flags = get_flags()
        flags.enable(Flag.RATE_LIMITING)
        ...
        flags.reset()
    """

    def __init__(self) -> None:
        self._overrides: dict[Flag, bool] = {}

    def enable(self, flag: Flag) -> None:
        self._overrides[flag] = True

    def disable(self, flag: Flag) -> None:
        self._overrides[flag] = False

    def reset(self, flag: Optional[Flag] = None) -> None:
        """Clear runtime overrides. Pass no arg to clear all."""
        if flag is None:
            self._overrides.clear()
        else:
            self._overrides.pop(flag, None)

    def is_enabled(self, flag: Flag) -> bool:
        if flag in self._overrides:
            return self._overrides[flag]
        attr = _SETTINGS_MAP.get(flag)
        if attr:
            return bool(getattr(settings, attr, False))
        return False

    def __contains__(self, flag: Flag) -> bool:
        return self.is_enabled(flag)


_instance: Optional[FeatureFlags] = None


def get_flags() -> FeatureFlags:
    """Return the singleton FeatureFlags registry."""
    global _instance
    if _instance is None:
        _instance = FeatureFlags()
    return _instance
