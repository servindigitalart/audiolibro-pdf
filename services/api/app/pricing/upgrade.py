"""
Upgrade Trigger Engine — Task 3
=================================
Evaluates whether a user should see a paywall or upgrade CTA based on
their current usage snapshot against their tier's limits.

Two-stage paywall model:
  SOFT (warn_usage_pct) — show upgrade CTA, request is allowed through
  HARD (block_usage_pct) — block the request, return HTTP 402/429

Trigger types:
  QUOTA_CHARS_WARNING     — char quota at warn threshold
  QUOTA_CHARS_EXHAUSTED   — char quota at hard block threshold
  QUOTA_JOBS_WARNING      — job quota at warn threshold
  QUOTA_JOBS_EXHAUSTED    — job quota at hard block threshold
  QUOTA_STORAGE_WARNING   — storage at warn threshold
  QUOTA_STORAGE_EXHAUSTED — storage at hard block threshold
  DAILY_API_WARNING       — daily API calls at warn threshold
  DAILY_API_EXHAUSTED     — daily API calls exhausted
  COST_CAP_WARNING        — daily cost approaching max_daily_cost_usd
  COST_CAP_EXCEEDED       — daily cost exceeded
  FEATURE_GATE_HIT        — user attempted to use a feature above their tier
  RATE_LIMIT_HIT          — repeated rate limit violations

Design:
  - UpgradeEvaluator is stateless: given a UsageSnapshot → list[UpgradeCTA]
  - CTAs carry blocking=False (soft) or blocking=True (hard)
  - Callers decide what HTTP code to return; this module has no HTTP dependency
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from app.pricing.tiers import PlanTier, TierConfig, TierFeature, TIER_CATALOG, get_next_tier


# ── Trigger types ─────────────────────────────────────────────────────────────

class UpgradeTrigger(str, Enum):
    QUOTA_CHARS_WARNING       = "quota_chars_warning"
    QUOTA_CHARS_EXHAUSTED     = "quota_chars_exhausted"
    QUOTA_JOBS_WARNING        = "quota_jobs_warning"
    QUOTA_JOBS_EXHAUSTED      = "quota_jobs_exhausted"
    QUOTA_STORAGE_WARNING     = "quota_storage_warning"
    QUOTA_STORAGE_EXHAUSTED   = "quota_storage_exhausted"
    DAILY_API_WARNING         = "daily_api_warning"
    DAILY_API_EXHAUSTED       = "daily_api_exhausted"
    COST_CAP_WARNING          = "cost_cap_warning"
    COST_CAP_EXCEEDED         = "cost_cap_exceeded"
    FEATURE_GATE_HIT          = "feature_gate_hit"
    RATE_LIMIT_HIT            = "rate_limit_hit"


# ── Upgrade CTA ───────────────────────────────────────────────────────────────

@dataclass
class UpgradeCTA:
    """
    Actionable upgrade signal returned by the evaluator.

    blocking=True  → request must be rejected (hard paywall)
    blocking=False → request is allowed, but UI should show the CTA
    """
    trigger: UpgradeTrigger
    current_tier: PlanTier
    suggested_tier: Optional[PlanTier]     # None when already on top tier
    resource_type: str                     # human-readable: "characters", "jobs", etc.
    current_value: float
    limit_value: float
    usage_pct: float                       # 0.0 – 1.0+
    blocking: bool
    message: str

    def as_dict(self) -> dict:
        return {
            "trigger": self.trigger.value,
            "current_tier": self.current_tier.value,
            "suggested_tier": self.suggested_tier.value if self.suggested_tier else None,
            "resource_type": self.resource_type,
            "current_value": self.current_value,
            "limit_value": self.limit_value,
            "usage_pct": round(self.usage_pct, 4),
            "blocking": self.blocking,
            "message": self.message,
        }


# ── Usage snapshot ────────────────────────────────────────────────────────────

@dataclass
class UsageSnapshot:
    """
    Point-in-time usage metrics for one user.

    All values represent the CURRENT billing period unless noted.
    """
    user_id: str
    tier: PlanTier

    # Resource usage
    chars_used: int = 0
    jobs_created: int = 0
    storage_mb: float = 0.0
    daily_api_calls: int = 0
    daily_cost_usd: float = 0.0
    monthly_cost_usd: float = 0.0

    # Recent behaviour signals
    rate_limit_hits_24h: int = 0          # how many 429s in last 24h
    feature_gate_hits_24h: int = 0        # attempted gated feature accesses

    # Feature access attempt (for feature-gate triggers)
    attempted_feature: Optional[TierFeature] = None


# ── Evaluator ─────────────────────────────────────────────────────────────────

class UpgradeEvaluator:
    """
    Stateless evaluator: UsageSnapshot → list[UpgradeCTA].

    Returns ALL active triggers, not just the first one.  Callers should
    pick the highest-priority trigger to present.
    """

    # Repeated rate-limit hits before showing a CTA
    RATE_LIMIT_HIT_THRESHOLD = 3

    def evaluate(self, snapshot: UsageSnapshot) -> list[UpgradeCTA]:
        """Return all active upgrade triggers for the given usage snapshot."""
        config = TIER_CATALOG[snapshot.tier]
        next_tier_config = get_next_tier(snapshot.tier)
        next_tier = next_tier_config.tier if next_tier_config else None
        ctas: list[UpgradeCTA] = []

        ctas.extend(self._check_chars(snapshot, config, next_tier))
        ctas.extend(self._check_jobs(snapshot, config, next_tier))
        ctas.extend(self._check_storage(snapshot, config, next_tier))
        ctas.extend(self._check_daily_api(snapshot, config, next_tier))
        ctas.extend(self._check_cost_cap(snapshot, config, next_tier))
        ctas.extend(self._check_feature_gate(snapshot, config, next_tier))
        ctas.extend(self._check_rate_limit(snapshot, next_tier))

        return ctas

    def has_blocking_trigger(self, snapshot: UsageSnapshot) -> bool:
        """True if any trigger would block the current request."""
        return any(c.blocking for c in self.evaluate(snapshot))

    def highest_priority(self, snapshot: UsageSnapshot) -> Optional[UpgradeCTA]:
        """Return the single most critical trigger (blocking first, then by usage_pct)."""
        ctas = self.evaluate(snapshot)
        if not ctas:
            return None
        blocking = [c for c in ctas if c.blocking]
        if blocking:
            return max(blocking, key=lambda c: c.usage_pct)
        return max(ctas, key=lambda c: c.usage_pct)

    # ── Internal checks ───────────────────────────────────────────────────────

    def _check_chars(
        self, s: UsageSnapshot, cfg: TierConfig, next_tier: Optional[PlanTier]
    ) -> list[UpgradeCTA]:
        return self._quota_check(
            current=s.chars_used,
            limit=cfg.monthly_chars,
            tier=s.tier,
            next_tier=next_tier,
            resource="characters",
            warn_trigger=UpgradeTrigger.QUOTA_CHARS_WARNING,
            block_trigger=UpgradeTrigger.QUOTA_CHARS_EXHAUSTED,
            cfg=cfg,
            warn_msg_template="You've used {pct:.0%} of your monthly character quota. Upgrade to process more.",
            block_msg_template="Monthly character quota exhausted ({used:,}/{limit:,}). Upgrade to continue.",
        )

    def _check_jobs(
        self, s: UsageSnapshot, cfg: TierConfig, next_tier: Optional[PlanTier]
    ) -> list[UpgradeCTA]:
        return self._quota_check(
            current=s.jobs_created,
            limit=cfg.monthly_jobs,
            tier=s.tier,
            next_tier=next_tier,
            resource="jobs",
            warn_trigger=UpgradeTrigger.QUOTA_JOBS_WARNING,
            block_trigger=UpgradeTrigger.QUOTA_JOBS_EXHAUSTED,
            cfg=cfg,
            warn_msg_template="You've used {pct:.0%} of your monthly job quota.",
            block_msg_template="Monthly job limit reached ({used}/{limit}). Upgrade to create more.",
        )

    def _check_storage(
        self, s: UsageSnapshot, cfg: TierConfig, next_tier: Optional[PlanTier]
    ) -> list[UpgradeCTA]:
        return self._quota_check(
            current=s.storage_mb,
            limit=cfg.storage_mb,
            tier=s.tier,
            next_tier=next_tier,
            resource="storage_mb",
            warn_trigger=UpgradeTrigger.QUOTA_STORAGE_WARNING,
            block_trigger=UpgradeTrigger.QUOTA_STORAGE_EXHAUSTED,
            cfg=cfg,
            warn_msg_template="Storage at {pct:.0%} capacity. Upgrade for more space.",
            block_msg_template="Storage limit reached ({used:.0f}/{limit:.0f} MB). Upgrade to upload more.",
        )

    def _check_daily_api(
        self, s: UsageSnapshot, cfg: TierConfig, next_tier: Optional[PlanTier]
    ) -> list[UpgradeCTA]:
        if cfg.daily_api_calls == -1:
            return []  # unlimited tier
        return self._quota_check(
            current=s.daily_api_calls,
            limit=cfg.daily_api_calls,
            tier=s.tier,
            next_tier=next_tier,
            resource="api_calls_today",
            warn_trigger=UpgradeTrigger.DAILY_API_WARNING,
            block_trigger=UpgradeTrigger.DAILY_API_EXHAUSTED,
            cfg=cfg,
            warn_msg_template="Approaching daily API limit ({pct:.0%} used). Upgrade for higher limits.",
            block_msg_template="Daily API limit reached ({used}/{limit} calls). Resets at midnight UTC.",
        )

    def _check_cost_cap(
        self, s: UsageSnapshot, cfg: TierConfig, next_tier: Optional[PlanTier]
    ) -> list[UpgradeCTA]:
        ctas: list[UpgradeCTA] = []
        limit = cfg.max_daily_cost_usd
        if limit <= 0:
            return ctas
        pct = s.daily_cost_usd / limit
        if pct >= cfg.block_usage_pct:
            ctas.append(UpgradeCTA(
                trigger=UpgradeTrigger.COST_CAP_EXCEEDED,
                current_tier=s.tier,
                suggested_tier=next_tier,
                resource_type="daily_cost_usd",
                current_value=s.daily_cost_usd,
                limit_value=limit,
                usage_pct=pct,
                blocking=True,
                message=(
                    f"Daily cost cap of ${limit:.2f} exceeded. "
                    "Request blocked to protect your account. Resets at midnight UTC."
                ),
            ))
        elif pct >= cfg.warn_usage_pct:
            ctas.append(UpgradeCTA(
                trigger=UpgradeTrigger.COST_CAP_WARNING,
                current_tier=s.tier,
                suggested_tier=next_tier,
                resource_type="daily_cost_usd",
                current_value=s.daily_cost_usd,
                limit_value=limit,
                usage_pct=pct,
                blocking=False,
                message=f"Daily cost cap {pct:.0%} consumed. Upgrade to increase your limit.",
            ))
        return ctas

    def _check_feature_gate(
        self, s: UsageSnapshot, cfg: TierConfig, next_tier: Optional[PlanTier]
    ) -> list[UpgradeCTA]:
        if s.attempted_feature is None:
            return []
        if s.attempted_feature in cfg.features:
            return []
        return [UpgradeCTA(
            trigger=UpgradeTrigger.FEATURE_GATE_HIT,
            current_tier=s.tier,
            suggested_tier=next_tier,
            resource_type="feature",
            current_value=0,
            limit_value=0,
            usage_pct=1.0,
            blocking=True,
            message=(
                f"Feature '{s.attempted_feature.value}' is not available on the "
                f"{s.tier.value} plan. Upgrade to unlock it."
            ),
        )]

    def _check_rate_limit(
        self, s: UsageSnapshot, next_tier: Optional[PlanTier]
    ) -> list[UpgradeCTA]:
        if s.rate_limit_hits_24h < self.RATE_LIMIT_HIT_THRESHOLD:
            return []
        return [UpgradeCTA(
            trigger=UpgradeTrigger.RATE_LIMIT_HIT,
            current_tier=s.tier,
            suggested_tier=next_tier,
            resource_type="rate_limit",
            current_value=s.rate_limit_hits_24h,
            limit_value=self.RATE_LIMIT_HIT_THRESHOLD,
            usage_pct=s.rate_limit_hits_24h / self.RATE_LIMIT_HIT_THRESHOLD,
            blocking=False,
            message=(
                f"You've hit the rate limit {s.rate_limit_hits_24h} times today. "
                "Upgrade for higher request rates."
            ),
        )]

    # ── Generic quota check helper ────────────────────────────────────────────

    def _quota_check(
        self,
        current: float,
        limit: float,
        tier: PlanTier,
        next_tier: Optional[PlanTier],
        resource: str,
        warn_trigger: UpgradeTrigger,
        block_trigger: UpgradeTrigger,
        cfg: TierConfig,
        warn_msg_template: str,
        block_msg_template: str,
    ) -> list[UpgradeCTA]:
        if limit <= 0:
            return []
        pct = current / limit
        if pct >= cfg.block_usage_pct:
            return [UpgradeCTA(
                trigger=block_trigger,
                current_tier=tier,
                suggested_tier=next_tier,
                resource_type=resource,
                current_value=current,
                limit_value=limit,
                usage_pct=pct,
                blocking=True,
                message=block_msg_template.format(used=current, limit=limit, pct=pct),
            )]
        if pct >= cfg.warn_usage_pct:
            return [UpgradeCTA(
                trigger=warn_trigger,
                current_tier=tier,
                suggested_tier=next_tier,
                resource_type=resource,
                current_value=current,
                limit_value=limit,
                usage_pct=pct,
                blocking=False,
                message=warn_msg_template.format(used=current, limit=limit, pct=pct),
            )]
        return []
