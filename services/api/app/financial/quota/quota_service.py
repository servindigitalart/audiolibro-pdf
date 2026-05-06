"""
Quota Service
=============
Service for checking and enforcing usage quotas.
"""

from datetime import datetime, timedelta
from typing import Dict, Optional
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import get_logger
from app.db.models import User
from app.financial.cost.cost_models import UsageQuota
from app.financial.cost.cost_enums import ActionType
from app.financial.quota.quota_limits import PlanTier, get_plan_limits, QuotaLimits

logger = get_logger(__name__)


class QuotaExceeded(HTTPException):
    """Exception raised when quota is exceeded."""
    
    def __init__(self, message: str, quota_type: str):
        super().__init__(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "error": "quota_exceeded",
                "message": message,
                "quota_type": quota_type,
            },
        )


class QuotaService:
    """
    Service for managing user quotas and usage limits.
    
    Enforces:
    - Monthly character limits
    - Monthly job limits
    - Concurrent job limits
    - Storage limits
    - API rate limits
    """
    
    @staticmethod
    async def get_or_create_quota(
        db: AsyncSession,
        user_id: UUID,
    ) -> UsageQuota:
        """
        Get or create usage quota for a user.
        
        Args:
            db: Database session
            user_id: User ID
        
        Returns:
            UsageQuota instance
        """
        # Try to get existing quota
        result = await db.execute(
            db.query(UsageQuota).filter(UsageQuota.user_id == user_id)
        )
        quota = result.scalar_one_or_none()
        
        if quota:
            # Check if period has expired
            if datetime.utcnow() >= quota.period_end:
                # Reset quota for new period
                quota.period_start = datetime.utcnow()
                quota.period_end = quota.period_start + timedelta(days=30)
                quota.characters_used = 0
                quota.jobs_created = 0
                quota.api_calls = 0
                # Note: storage_used_mb persists across periods
                
                await db.commit()
                await db.refresh(quota)
                
                logger.info(f"Reset quota for user {user_id}")
        else:
            # Create new quota
            quota = UsageQuota(
                user_id=user_id,
                period_start=datetime.utcnow(),
                period_end=datetime.utcnow() + timedelta(days=30),
            )
            db.add(quota)
            await db.commit()
            await db.refresh(quota)
            
            logger.info(f"Created quota for user {user_id}")
        
        return quota
    
    @staticmethod
    async def check_quota(
        db: AsyncSession,
        user_id: UUID,
        action_type: ActionType,
        amount: int = 1,
    ) -> bool:
        """
        Check if user has quota remaining for an action.
        
        Args:
            db: Database session
            user_id: User ID
            action_type: Type of action
            amount: Amount of quota needed
        
        Returns:
            True if quota available
        
        Raises:
            QuotaExceeded: If quota exceeded
        """
        # Get user and their plan
        user = await db.get(User, user_id)
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found",
            )
        
        # Get plan limits (default to FREE if not set)
        plan_tier = PlanTier(user.plan_tier) if hasattr(user, 'plan_tier') else PlanTier.FREE
        limits = get_plan_limits(plan_tier)
        
        # Get current usage
        quota = await QuotaService.get_or_create_quota(db, user_id)
        
        # Check quota based on action type
        if action_type == ActionType.TTS_CHARACTER_USE:
            if quota.characters_used + amount > limits.monthly_char_limit:
                raise QuotaExceeded(
                    f"Monthly character limit exceeded. "
                    f"Used: {quota.characters_used}, "
                    f"Limit: {limits.monthly_char_limit}",
                    "monthly_characters",
                )
        
        elif action_type == ActionType.TTS_JOB_CREATE:
            if quota.jobs_created + amount > limits.monthly_job_limit:
                raise QuotaExceeded(
                    f"Monthly job limit exceeded. "
                    f"Used: {quota.jobs_created}, "
                    f"Limit: {limits.monthly_job_limit}",
                    "monthly_jobs",
                )
        
        elif action_type == ActionType.STORAGE_USE:
            if quota.storage_used_mb + amount > limits.storage_limit_mb:
                raise QuotaExceeded(
                    f"Storage limit exceeded. "
                    f"Used: {quota.storage_used_mb}MB, "
                    f"Limit: {limits.storage_limit_mb}MB",
                    "storage",
                )
        
        elif action_type == ActionType.API_CALL:
            # API calls checked via rate limiter
            pass
        
        return True
    
    @staticmethod
    async def increment_usage(
        db: AsyncSession,
        user_id: UUID,
        action_type: ActionType,
        amount: int = 1,
    ) -> UsageQuota:
        """
        Increment usage counter.
        
        Args:
            db: Database session
            user_id: User ID
            action_type: Type of action
            amount: Amount to increment
        
        Returns:
            Updated UsageQuota
        """
        quota = await QuotaService.get_or_create_quota(db, user_id)
        
        if action_type == ActionType.TTS_CHARACTER_USE:
            quota.characters_used += amount
        elif action_type == ActionType.TTS_JOB_CREATE:
            quota.jobs_created += amount
        elif action_type == ActionType.STORAGE_USE:
            quota.storage_used_mb += amount
        elif action_type == ActionType.API_CALL:
            quota.api_calls += amount
        
        await db.commit()
        await db.refresh(quota)
        
        logger.debug(
            f"Incremented usage: user={user_id}, "
            f"action={action_type}, "
            f"amount={amount}"
        )
        
        return quota
    
    @staticmethod
    async def get_remaining_quota(
        db: AsyncSession,
        user_id: UUID,
    ) -> Dict:
        """
        Get remaining quota for a user.
        
        Args:
            db: Database session
            user_id: User ID
        
        Returns:
            Dict with remaining quota by type
        """
        # Get user and their plan
        user = await db.get(User, user_id)
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found",
            )
        
        # Get plan limits
        plan_tier = PlanTier(user.plan_tier) if hasattr(user, 'plan_tier') else PlanTier.FREE
        limits = get_plan_limits(plan_tier)
        
        # Get current usage
        quota = await QuotaService.get_or_create_quota(db, user_id)
        
        return {
            "plan_tier": plan_tier.value,
            "period_start": quota.period_start.isoformat(),
            "period_end": quota.period_end.isoformat(),
            "characters": {
                "used": quota.characters_used,
                "limit": limits.monthly_char_limit,
                "remaining": max(0, limits.monthly_char_limit - quota.characters_used),
                "percentage": (quota.characters_used / limits.monthly_char_limit * 100)
                if limits.monthly_char_limit > 0 else 0,
            },
            "jobs": {
                "used": quota.jobs_created,
                "limit": limits.monthly_job_limit,
                "remaining": max(0, limits.monthly_job_limit - quota.jobs_created),
                "percentage": (quota.jobs_created / limits.monthly_job_limit * 100)
                if limits.monthly_job_limit > 0 else 0,
            },
            "storage": {
                "used_mb": quota.storage_used_mb,
                "limit_mb": limits.storage_limit_mb,
                "remaining_mb": max(0, limits.storage_limit_mb - quota.storage_used_mb),
                "percentage": (quota.storage_used_mb / limits.storage_limit_mb * 100)
                if limits.storage_limit_mb > 0 else 0,
            },
            "api_calls": {
                "used": quota.api_calls,
                "limit_per_day": limits.api_calls_per_day,
            },
        }
