"""
Account Service
===============
Business logic for account domain operations.
"""

from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from uuid import UUID

from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.db.models.user import User
from app.db.models.account import AccountPreferences, UserActivityLog
from app.financial.cost.cost_models import CostEvent, UsageQuota
from app.financial.cost.cost_enums import CostEventType
from app.financial.quota.quota_limits import PlanTier, PLAN_QUOTAS
from app.schemas.account import (
    UserInfoSchema,
    UsageSummarySchema,
    CostSummarySchema,
    QuotaRemainingSchema,
    AccountHealthSchema,
    AccountOverviewResponse,
    DailyUsagePoint,
    UsageBreakdownSchema,
    ActivityLogEntry,
    LoginHistoryEntry,
    AccountPreferencesSchema,
    PlanLimitsSchema,
    PlanFeaturesSchema,
    PlanSchema,
    UpgradePossibilitySchema,
)

logger = get_logger(__name__)


class AccountService:
    """
    Service layer for account domain operations.
    
    Provides business logic for:
    - Account overview
    - Usage tracking
    - Activity logs
    - Preferences management
    - Plan information
    """
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    # ============================================
    # ACCOUNT OVERVIEW
    # ============================================
    
    async def get_account_overview(self, user_id: UUID) -> AccountOverviewResponse:
        """
        Get complete account overview.
        
        Args:
            user_id: User ID
            
        Returns:
            Complete account overview with usage, costs, quota, and health
        """
        # Get user
        user = await self._get_user(user_id)
        
        # Get usage summary
        usage = await self._get_usage_summary(user_id)
        
        # Get cost summary
        costs = await self._get_cost_summary(user_id)
        
        # Get remaining quota
        remaining = await self._get_remaining_quota(user_id, user.plan_tier)
        
        # Calculate health
        health = await self._calculate_account_health(
            user_id, user.plan_tier, usage, costs, remaining
        )
        
        # Build response
        user_info = UserInfoSchema(
            id=user.id,
            email=user.email,
            role=user.role,
            plan_tier=user.plan_tier,
            is_active=user.is_active,
            is_verified=user.is_verified,
            created_at=user.created_at,
        )
        
        return AccountOverviewResponse(
            user=user_info,
            plan=user.plan_tier,
            usage=usage,
            costs=costs,
            remaining_quota=remaining,
            health=health,
        )
    
    # ============================================
    # USAGE TRACKING
    # ============================================
    
    async def get_usage_details(
        self,
        user_id: UUID,
        days: int = 30,
    ) -> Dict[str, Any]:
        """
        Get detailed usage information.
        
        Args:
            user_id: User ID
            days: Number of days for daily data
            
        Returns:
            Usage details with breakdown and daily data
        """
        user = await self._get_user(user_id)
        
        # Get monthly usage
        usage = await self._get_usage_summary(user_id)
        
        # Get cost breakdown by event type
        breakdown = await self._get_cost_breakdown(user_id)
        
        # Get daily data
        daily_data = await self._get_daily_usage(user_id, days)
        
        # Get remaining quota
        remaining = await self._get_remaining_quota(user_id, user.plan_tier)
        
        return {
            "period": "current_month",
            "monthly_usage": usage,
            "cost_breakdown": breakdown,
            "daily_data": daily_data,
            "quota_remaining": remaining,
        }
    
    # ============================================
    # ACTIVITY LOGS
    # ============================================
    
    async def get_activity_history(
        self,
        user_id: UUID,
        limit: int = 50,
    ) -> Dict[str, Any]:
        """
        Get user activity history.
        
        Args:
            user_id: User ID
            limit: Maximum number of activities to return
            
        Returns:
            Activity history with login history and suspicious activity count
        """
        # Get recent activities
        activities_query = (
            select(UserActivityLog)
            .where(UserActivityLog.user_id == user_id)
            .order_by(UserActivityLog.created_at.desc())
            .limit(limit)
        )
        result = await self.db.execute(activities_query)
        activities = result.scalars().all()
        
        # Get login history (last 20 logins)
        login_query = (
            select(UserActivityLog)
            .where(
                and_(
                    UserActivityLog.user_id == user_id,
                    UserActivityLog.activity_type.in_(["login_success", "login_failed"])
                )
            )
            .order_by(UserActivityLog.created_at.desc())
            .limit(20)
        )
        result = await self.db.execute(login_query)
        logins = result.scalars().all()
        
        # Count suspicious activities
        suspicious_query = select(func.count(UserActivityLog.id)).where(
            and_(
                UserActivityLog.user_id == user_id,
                UserActivityLog.is_suspicious == True
            )
        )
        result = await self.db.execute(suspicious_query)
        suspicious_count = result.scalar() or 0
        
        # Count total activities
        total_query = select(func.count(UserActivityLog.id)).where(
            UserActivityLog.user_id == user_id
        )
        result = await self.db.execute(total_query)
        total_count = result.scalar() or 0
        
        # Build response
        recent_activities = [
            ActivityLogEntry(
                id=a.id,
                activity_type=a.activity_type,
                description=a.description,
                ip_address=a.ip_address,
                user_agent=a.user_agent,
                is_suspicious=a.is_suspicious,
                created_at=a.created_at,
                metadata=a.metadata,
            )
            for a in activities
        ]
        
        login_history = [
            LoginHistoryEntry(
                timestamp=l.created_at,
                ip_address=l.ip_address,
                user_agent=l.user_agent,
                success=l.activity_type == "login_success",
                location=l.metadata.get("location") if l.metadata else None,
            )
            for l in logins
        ]
        
        return {
            "recent_activities": recent_activities,
            "login_history": login_history,
            "suspicious_activity_count": suspicious_count,
            "total_activities": total_count,
        }
    
    async def log_activity(
        self,
        user_id: UUID,
        activity_type: str,
        description: str,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        is_suspicious: bool = False,
    ) -> None:
        """
        Log a user activity.
        
        Args:
            user_id: User ID
            activity_type: Type of activity (login_success, api_call, etc.)
            description: Human-readable description
            ip_address: Client IP address
            user_agent: Client user agent
            metadata: Additional context
            is_suspicious: Whether activity is suspicious
        """
        activity = UserActivityLog(
            user_id=user_id,
            activity_type=activity_type,
            description=description,
            ip_address=ip_address,
            user_agent=user_agent,
            metadata=metadata,
            is_suspicious=is_suspicious,
        )
        
        self.db.add(activity)
        await self.db.commit()
        
        logger.info(
            "activity_logged",
            user_id=str(user_id),
            activity_type=activity_type,
            is_suspicious=is_suspicious,
        )
    
    # ============================================
    # PREFERENCES
    # ============================================
    
    async def get_preferences(self, user_id: UUID) -> Dict[str, Any]:
        """
        Get user account preferences.
        
        Args:
            user_id: User ID
            
        Returns:
            Preferences with timestamps
        """
        query = select(AccountPreferences).where(
            AccountPreferences.user_id == user_id
        )
        result = await self.db.execute(query)
        prefs = result.scalar_one_or_none()
        
        if not prefs:
            # Create default preferences
            prefs = AccountPreferences(user_id=user_id)
            self.db.add(prefs)
            await self.db.commit()
            await self.db.refresh(prefs)
        
        return {
            "preferences": AccountPreferencesSchema(
                preferred_language=prefs.preferred_language,
                preferred_voice=prefs.preferred_voice,
                timezone=prefs.timezone,
                currency=prefs.currency,
                email_notifications=prefs.email_notifications,
                marketing_emails=prefs.marketing_emails,
                usage_alerts=prefs.usage_alerts,
            ),
            "created_at": prefs.created_at,
            "updated_at": prefs.updated_at,
        }
    
    async def update_preferences(
        self,
        user_id: UUID,
        updates: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Update user account preferences.
        
        Args:
            user_id: User ID
            updates: Dictionary of fields to update
            
        Returns:
            Updated preferences
        """
        query = select(AccountPreferences).where(
            AccountPreferences.user_id == user_id
        )
        result = await self.db.execute(query)
        prefs = result.scalar_one_or_none()
        
        if not prefs:
            # Create with updates
            prefs = AccountPreferences(user_id=user_id, **updates)
            self.db.add(prefs)
        else:
            # Update existing
            for key, value in updates.items():
                if value is not None and hasattr(prefs, key):
                    setattr(prefs, key, value)
        
        await self.db.commit()
        await self.db.refresh(prefs)
        
        logger.info(
            "preferences_updated",
            user_id=str(user_id),
            updated_fields=list(updates.keys()),
        )
        
        return await self.get_preferences(user_id)
    
    # ============================================
    # PLAN INFORMATION
    # ============================================
    
    async def get_plan_info(self, user_id: UUID) -> Dict[str, Any]:
        """
        Get plan information and upgrade options.
        
        Args:
            user_id: User ID
            
        Returns:
            Current plan, upgrade options, and feature matrix
        """
        user = await self._get_user(user_id)
        current_tier = PlanTier(user.plan_tier)
        current_limits = PLAN_QUOTAS[current_tier]
        
        # Build current plan
        current_plan = PlanSchema(
            tier=current_tier,
            name=self._get_plan_name(current_tier),
            limits=self._limits_to_schema(current_limits),
            features=self._features_to_schema(current_limits),
        )
        
        # Build upgrade options
        upgrade_options = []
        tier_order = [PlanTier.FREE, PlanTier.BASIC, PlanTier.PRO, PlanTier.ENTERPRISE]
        current_index = tier_order.index(current_tier)
        
        for tier in tier_order[current_index + 1:]:
            limits = PLAN_QUOTAS[tier]
            upgrade_options.append(
                UpgradePossibilitySchema(
                    target_tier=tier,
                    name=self._get_plan_name(tier),
                    monthly_price_usd=self._get_plan_price(tier),
                    limits=self._limits_to_schema(limits),
                    features=self._features_to_schema(limits),
                )
            )
        
        # Build feature matrix
        feature_matrix = self._build_feature_matrix()
        
        return {
            "current_plan": current_plan,
            "upgrade_options": upgrade_options,
            "feature_matrix": feature_matrix,
        }
    
    async def simulate_upgrade(
        self,
        user_id: UUID,
        target_tier: str,
    ) -> Dict[str, Any]:
        """
        Simulate plan upgrade.
        
        Args:
            user_id: User ID
            target_tier: Target plan tier
            
        Returns:
            Simulation results with new limits and projected costs
        """
        user = await self._get_user(user_id)
        current_tier = PlanTier(user.plan_tier)
        target = PlanTier(target_tier)
        
        # Validate upgrade path
        tier_order = [PlanTier.FREE, PlanTier.BASIC, PlanTier.PRO, PlanTier.ENTERPRISE]
        if tier_order.index(target) <= tier_order.index(current_tier):
            raise ValueError("Can only simulate upgrades, not downgrades")
        
        # Get limits
        new_limits = PLAN_QUOTAS[target]
        
        # Calculate cost increase (simulated)
        current_price = self._get_plan_price(current_tier)
        target_price = self._get_plan_price(target)
        cost_increase = target_price - current_price
        
        # Build benefits list
        benefits = self._calculate_upgrade_benefits(current_tier, target)
        
        return {
            "target_tier": target,
            "current_tier": current_tier,
            "new_limits": self._limits_to_schema(new_limits),
            "new_features": self._features_to_schema(new_limits),
            "projected_cost_increase_usd": cost_increase,
            "projected_quota": {
                "characters": new_limits.monthly_char_limit,
                "jobs": new_limits.monthly_job_limit,
                "storage_mb": new_limits.storage_limit_mb,
                "api_calls_per_day": new_limits.api_calls_per_day,
            },
            "benefits": benefits,
            "note": "This is a simulation. No payment has been processed.",
        }
    
    # ============================================
    # PRIVATE HELPER METHODS
    # ============================================
    
    async def _get_user(self, user_id: UUID) -> User:
        """Get user by ID."""
        query = select(User).where(User.id == user_id)
        result = await self.db.execute(query)
        user = result.scalar_one_or_none()
        
        if not user:
            raise ValueError(f"User not found: {user_id}")
        
        return user
    
    async def _get_usage_summary(self, user_id: UUID) -> UsageSummarySchema:
        """Get usage summary from usage_quotas."""
        query = select(UsageQuota).where(UsageQuota.user_id == user_id)
        result = await self.db.execute(query)
        quota = result.scalar_one_or_none()
        
        if not quota:
            # No quota yet, return zeros
            now = datetime.utcnow()
            return UsageSummarySchema(
                characters_used=0,
                jobs_created=0,
                storage_used_mb=0.0,
                api_calls=0,
                period_start=now,
                period_end=now + timedelta(days=30),
            )
        
        return UsageSummarySchema(
            characters_used=quota.characters_used,
            jobs_created=quota.jobs_created,
            storage_used_mb=quota.storage_used_mb,
            api_calls=quota.api_calls,
            period_start=quota.period_start,
            period_end=quota.period_end,
        )
    
    async def _get_cost_summary(self, user_id: UUID) -> CostSummarySchema:
        """Get cost summary from cost_events."""
        now = datetime.utcnow()
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        
        # Get total cost
        total_query = select(func.sum(CostEvent.total_cost)).where(
            and_(
                CostEvent.user_id == user_id,
                CostEvent.created_at >= month_start,
            )
        )
        result = await self.db.execute(total_query)
        total_cost = result.scalar() or 0.0
        
        # Get cost by event type
        by_type_query = (
            select(
                CostEvent.event_type,
                func.sum(CostEvent.total_cost).label("cost")
            )
            .where(
                and_(
                    CostEvent.user_id == user_id,
                    CostEvent.created_at >= month_start,
                )
            )
            .group_by(CostEvent.event_type)
        )
        result = await self.db.execute(by_type_query)
        by_type = {str(row[0]): float(row[1]) for row in result}
        
        # Get cost by provider
        by_provider_query = (
            select(
                CostEvent.provider,
                func.sum(CostEvent.total_cost).label("cost")
            )
            .where(
                and_(
                    CostEvent.user_id == user_id,
                    CostEvent.created_at >= month_start,
                )
            )
            .group_by(CostEvent.provider)
        )
        result = await self.db.execute(by_provider_query)
        by_provider = {str(row[0]): float(row[1]) for row in result}
        
        # Get event count
        count_query = select(func.count(CostEvent.id)).where(
            and_(
                CostEvent.user_id == user_id,
                CostEvent.created_at >= month_start,
            )
        )
        result = await self.db.execute(count_query)
        event_count = result.scalar() or 0
        
        return CostSummarySchema(
            total_cost_usd=total_cost,
            by_event_type=by_type,
            by_provider=by_provider,
            event_count=event_count,
        )
    
    async def _get_remaining_quota(
        self,
        user_id: UUID,
        plan_tier: str,
    ) -> QuotaRemainingSchema:
        """Calculate remaining quota."""
        tier = PlanTier(plan_tier)
        limits = PLAN_QUOTAS[tier]
        
        # Get current usage
        usage = await self._get_usage_summary(user_id)
        
        # Calculate remaining
        char_remaining = max(0, limits.monthly_char_limit - usage.characters_used)
        char_percentage = (usage.characters_used / limits.monthly_char_limit * 100) if limits.monthly_char_limit > 0 else 0
        
        jobs_remaining = max(0, limits.monthly_job_limit - usage.jobs_created)
        jobs_percentage = (usage.jobs_created / limits.monthly_job_limit * 100) if limits.monthly_job_limit > 0 else 0
        
        storage_remaining = max(0, limits.storage_limit_mb - usage.storage_used_mb)
        storage_percentage = (usage.storage_used_mb / limits.storage_limit_mb * 100) if limits.storage_limit_mb > 0 else 0
        
        # API calls is daily, not total
        api_remaining = limits.api_calls_per_day
        api_percentage = 0.0
        
        return QuotaRemainingSchema(
            characters={
                "remaining": char_remaining,
                "limit": limits.monthly_char_limit,
                "used_percentage": round(char_percentage, 2),
            },
            jobs={
                "remaining": jobs_remaining,
                "limit": limits.monthly_job_limit,
                "used_percentage": round(jobs_percentage, 2),
            },
            storage_mb={
                "remaining": round(storage_remaining, 2),
                "limit": limits.storage_limit_mb,
                "used_percentage": round(storage_percentage, 2),
            },
            api_calls={
                "remaining": api_remaining,
                "limit": limits.api_calls_per_day,
                "used_percentage": round(api_percentage, 2),
            },
        )
    
    async def _calculate_account_health(
        self,
        user_id: UUID,
        plan_tier: str,
        usage: UsageSummarySchema,
        costs: CostSummarySchema,
        remaining: QuotaRemainingSchema,
    ) -> AccountHealthSchema:
        """Calculate account health indicators."""
        warnings_quota = []
        warnings_cost = []
        warnings_security = []
        
        # Check quota warnings
        if remaining.characters["used_percentage"] > 90:
            warnings_quota.append("Character quota above 90%")
        if remaining.jobs["used_percentage"] > 90:
            warnings_quota.append("Job quota above 90%")
        if remaining.storage_mb["used_percentage"] > 90:
            warnings_quota.append("Storage quota above 90%")
        
        # Check cost warnings (placeholder - would use actual thresholds)
        tier = PlanTier(plan_tier)
        if tier == PlanTier.FREE and costs.total_cost_usd > 1.0:
            warnings_cost.append("FREE tier exceeding expected cost")
        
        # Check security warnings
        suspicious_query = select(func.count(UserActivityLog.id)).where(
            and_(
                UserActivityLog.user_id == user_id,
                UserActivityLog.is_suspicious == True,
                UserActivityLog.created_at >= datetime.utcnow() - timedelta(days=7),
            )
        )
        result = await self.db.execute(suspicious_query)
        suspicious_count = result.scalar() or 0
        
        if suspicious_count > 0:
            warnings_security.append(f"{suspicious_count} suspicious activities in last 7 days")
        
        is_healthy = (
            len(warnings_quota) == 0 and
            len(warnings_cost) == 0 and
            len(warnings_security) == 0
        )
        
        return AccountHealthSchema(
            is_healthy=is_healthy,
            quota_warnings=warnings_quota,
            cost_warnings=warnings_cost,
            security_warnings=warnings_security,
        )
    
    async def _get_cost_breakdown(self, user_id: UUID) -> List[UsageBreakdownSchema]:
        """Get cost breakdown by event type."""
        now = datetime.utcnow()
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        
        query = (
            select(
                CostEvent.event_type,
                func.count(CostEvent.id).label("count"),
                func.sum(CostEvent.total_cost).label("total_cost")
            )
            .where(
                and_(
                    CostEvent.user_id == user_id,
                    CostEvent.created_at >= month_start,
                )
            )
            .group_by(CostEvent.event_type)
        )
        
        result = await self.db.execute(query)
        rows = result.all()
        
        total_cost = sum(row[2] for row in rows)
        
        breakdown = []
        for event_type, count, cost in rows:
            percentage = (cost / total_cost * 100) if total_cost > 0 else 0
            breakdown.append(
                UsageBreakdownSchema(
                    event_type=str(event_type),
                    count=count,
                    total_cost_usd=cost,
                    percentage=round(percentage, 2),
                )
            )
        
        return breakdown
    
    async def _get_daily_usage(
        self,
        user_id: UUID,
        days: int,
    ) -> List[DailyUsagePoint]:
        """Get daily usage data for charting."""
        end_date = datetime.utcnow()
        start_date = end_date - timedelta(days=days)
        
        # Query daily aggregates
        query = (
            select(
                func.date_trunc('day', CostEvent.created_at).label('day'),
                func.sum(CostEvent.quantity).label('quantity'),
                func.count(CostEvent.id).label('count'),
                func.sum(CostEvent.total_cost).label('cost'),
            )
            .where(
                and_(
                    CostEvent.user_id == user_id,
                    CostEvent.created_at >= start_date,
                )
            )
            .group_by(func.date_trunc('day', CostEvent.created_at))
            .order_by(func.date_trunc('day', CostEvent.created_at))
        )
        
        result = await self.db.execute(query)
        rows = result.all()
        
        daily_data = []
        for day, quantity, count, cost in rows:
            daily_data.append(
                DailyUsagePoint(
                    date=day.strftime("%Y-%m-%d"),
                    characters=int(quantity),
                    jobs=count,
                    api_calls=count,  # Simplified
                    cost_usd=float(cost),
                )
            )
        
        return daily_data
    
    def _limits_to_schema(self, limits) -> PlanLimitsSchema:
        """Convert QuotaLimits to schema."""
        return PlanLimitsSchema(
            monthly_char_limit=limits.monthly_char_limit,
            monthly_job_limit=limits.monthly_job_limit,
            concurrent_job_limit=limits.concurrent_job_limit,
            storage_limit_mb=limits.storage_limit_mb,
            api_calls_per_minute=limits.api_calls_per_minute,
            api_calls_per_day=limits.api_calls_per_day,
        )
    
    def _features_to_schema(self, limits) -> PlanFeaturesSchema:
        """Convert QuotaLimits to features schema."""
        return PlanFeaturesSchema(
            priority_processing=limits.priority_processing,
            custom_voices=limits.custom_voices,
            api_access=limits.api_access,
            team_members=limits.team_members,
        )
    
    def _get_plan_name(self, tier: PlanTier) -> str:
        """Get human-readable plan name."""
        names = {
            PlanTier.FREE: "Free",
            PlanTier.BASIC: "Basic",
            PlanTier.PRO: "Professional",
            PlanTier.ENTERPRISE: "Enterprise",
        }
        return names.get(tier, str(tier))
    
    def _get_plan_price(self, tier: PlanTier) -> float:
        """Get simulated monthly price (no Stripe yet)."""
        prices = {
            PlanTier.FREE: 0.0,
            PlanTier.BASIC: 19.0,
            PlanTier.PRO: 49.0,
            PlanTier.ENTERPRISE: 199.0,
        }
        return prices.get(tier, 0.0)
    
    def _build_feature_matrix(self) -> Dict[str, Dict[str, Any]]:
        """Build feature comparison matrix."""
        return {
            "characters": {
                "FREE": "10,000/month",
                "BASIC": "100,000/month",
                "PRO": "500,000/month",
                "ENTERPRISE": "5,000,000/month",
            },
            "jobs": {
                "FREE": "5/month",
                "BASIC": "50/month",
                "PRO": "200/month",
                "ENTERPRISE": "2,000/month",
            },
            "storage": {
                "FREE": "100MB",
                "BASIC": "1GB",
                "PRO": "10GB",
                "ENTERPRISE": "100GB",
            },
            "api_access": {
                "FREE": False,
                "BASIC": True,
                "PRO": True,
                "ENTERPRISE": True,
            },
            "priority_processing": {
                "FREE": False,
                "BASIC": False,
                "PRO": True,
                "ENTERPRISE": True,
            },
            "custom_voices": {
                "FREE": False,
                "BASIC": False,
                "PRO": True,
                "ENTERPRISE": True,
            },
            "team_members": {
                "FREE": 1,
                "BASIC": 1,
                "PRO": 5,
                "ENTERPRISE": 50,
            },
        }
    
    def _calculate_upgrade_benefits(
        self,
        current: PlanTier,
        target: PlanTier,
    ) -> List[str]:
        """Calculate benefits of upgrading."""
        current_limits = PLAN_QUOTAS[current]
        target_limits = PLAN_QUOTAS[target]
        
        benefits = []
        
        # Character limit
        char_increase = target_limits.monthly_char_limit - current_limits.monthly_char_limit
        if char_increase > 0:
            benefits.append(f"+{char_increase:,} characters/month")
        
        # Job limit
        job_increase = target_limits.monthly_job_limit - current_limits.monthly_job_limit
        if job_increase > 0:
            benefits.append(f"+{job_increase} jobs/month")
        
        # Storage
        storage_increase = target_limits.storage_limit_mb - current_limits.storage_limit_mb
        if storage_increase > 0:
            benefits.append(f"+{storage_increase}MB storage")
        
        # Features
        if target_limits.api_access and not current_limits.api_access:
            benefits.append("API access enabled")
        
        if target_limits.priority_processing and not current_limits.priority_processing:
            benefits.append("Priority processing")
        
        if target_limits.custom_voices and not current_limits.custom_voices:
            benefits.append("Custom voice support")
        
        team_increase = target_limits.team_members - current_limits.team_members
        if team_increase > 0:
            benefits.append(f"+{team_increase} team members")
        
        return benefits
