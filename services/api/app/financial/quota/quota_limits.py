"""
Quota Limits Configuration
===========================
Plan tiers and quota limits.
"""

from dataclasses import dataclass
from enum import Enum


class PlanTier(str, Enum):
    """
    Subscription plan tiers.
    """
    
    FREE = "free"
    BASIC = "basic"
    PRO = "pro"
    ENTERPRISE = "enterprise"


@dataclass
class QuotaLimits:
    """
    Quota limits for a plan tier.
    """
    
    # TTS Limits
    monthly_char_limit: int
    monthly_job_limit: int
    concurrent_job_limit: int
    
    # Storage Limits
    storage_limit_mb: int
    
    # API Limits
    api_calls_per_minute: int
    api_calls_per_day: int
    
    # Features
    priority_processing: bool = False
    custom_voices: bool = False
    api_access: bool = False
    team_members: int = 1


# Plan Tier Configurations
PLAN_QUOTAS = {
    PlanTier.FREE: QuotaLimits(
        monthly_char_limit=10_000,  # ~5 pages
        monthly_job_limit=5,
        concurrent_job_limit=1,
        storage_limit_mb=100,  # 100MB
        api_calls_per_minute=10,
        api_calls_per_day=100,
        priority_processing=False,
        custom_voices=False,
        api_access=False,
        team_members=1,
    ),
    
    PlanTier.BASIC: QuotaLimits(
        monthly_char_limit=100_000,  # ~50 pages
        monthly_job_limit=50,
        concurrent_job_limit=2,
        storage_limit_mb=1_000,  # 1GB
        api_calls_per_minute=30,
        api_calls_per_day=1_000,
        priority_processing=False,
        custom_voices=False,
        api_access=True,
        team_members=1,
    ),
    
    PlanTier.PRO: QuotaLimits(
        monthly_char_limit=500_000,  # ~250 pages
        monthly_job_limit=200,
        concurrent_job_limit=5,
        storage_limit_mb=10_000,  # 10GB
        api_calls_per_minute=100,
        api_calls_per_day=10_000,
        priority_processing=True,
        custom_voices=True,
        api_access=True,
        team_members=5,
    ),
    
    PlanTier.ENTERPRISE: QuotaLimits(
        monthly_char_limit=5_000_000,  # ~2500 pages
        monthly_job_limit=2_000,
        concurrent_job_limit=20,
        storage_limit_mb=100_000,  # 100GB
        api_calls_per_minute=500,
        api_calls_per_day=100_000,
        priority_processing=True,
        custom_voices=True,
        api_access=True,
        team_members=50,
    ),
}


def get_plan_limits(plan_tier: PlanTier) -> QuotaLimits:
    """
    Get quota limits for a plan tier.
    
    Args:
        plan_tier: Plan tier
    
    Returns:
        QuotaLimits for the tier
    """
    return PLAN_QUOTAS[plan_tier]
