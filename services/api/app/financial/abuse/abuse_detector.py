"""
Abuse Detection Service
======================
Pattern-based abuse detection with metric emission (log-only mode).
"""

from datetime import datetime, timedelta
from enum import Enum
from typing import Optional
from uuid import UUID

from prometheus_client import Counter
from redis.asyncio import Redis
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.financial.cost.cost_models import CostEvent
from app.monitoring.metrics import metrics_registry

logger = get_logger(__name__)


class AbuseSeverity(str, Enum):
    """Severity levels for abuse patterns."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class AbusePattern(str, Enum):
    """Types of abuse patterns to detect."""
    EXCESSIVE_FAILED_LOGINS = "excessive_failed_logins"
    EXCESSIVE_API_CALLS = "excessive_api_calls"
    USAGE_SPIKE = "usage_spike"
    COST_SPIKE = "cost_spike"
    SUSPICIOUS_STORAGE_GROWTH = "suspicious_storage_growth"
    RAPID_ACCOUNT_CREATION = "rapid_account_creation"
    CREDENTIAL_STUFFING = "credential_stuffing"


# Prometheus metrics for abuse detection
abuse_patterns_detected = Counter(
    "sonoro_abuse_patterns_detected_total",
    "Total abuse patterns detected by type and severity",
    ["pattern", "severity"],
    registry=metrics_registry,
)

abuse_checks_total = Counter(
    "sonoro_abuse_checks_total",
    "Total abuse detection checks performed",
    ["check_type"],
    registry=metrics_registry,
)


class AbuseDetector:
    """
    Abuse detection service for identifying suspicious patterns.
    
    Features:
    - Failed login detection
    - Excessive API call detection
    - Usage spike detection
    - Cost anomaly detection
    - Log-only mode (no automatic blocking)
    - Prometheus metric emission
    """

    def __init__(self, db: AsyncSession, redis: Redis):
        self.db = db
        self.redis = redis

    async def check_failed_logins(
        self,
        user_identifier: str,  # email or IP
        lookback_minutes: int = 15,
        threshold: int = 5,
    ) -> Optional[dict]:
        """
        Check for excessive failed login attempts.
        
        Args:
            user_identifier: Email or IP address
            lookback_minutes: Time window to check
            threshold: Number of failures to trigger alert
            
        Returns:
            Detection result if pattern found, None otherwise
        """
        abuse_checks_total.labels(check_type="failed_logins").inc()
        
        key = f"abuse:failed_login:{user_identifier}"
        
        # Get failed login count from Redis
        failed_count = await self.redis.get(key)
        
        if failed_count and int(failed_count) >= threshold:
            severity = self._calculate_severity(int(failed_count), threshold)
            
            result = {
                "pattern": AbusePattern.EXCESSIVE_FAILED_LOGINS,
                "severity": severity,
                "user_identifier": user_identifier,
                "failed_attempts": int(failed_count),
                "threshold": threshold,
                "window_minutes": lookback_minutes,
                "detected_at": datetime.utcnow().isoformat(),
            }
            
            abuse_patterns_detected.labels(
                pattern=AbusePattern.EXCESSIVE_FAILED_LOGINS,
                severity=severity,
            ).inc()
            
            logger.warning(
                "abuse_pattern_detected",
                **result,
            )
            
            return result
        
        return None

    async def track_failed_login(
        self,
        user_identifier: str,
        ttl_seconds: int = 900,  # 15 minutes
    ):
        """Track a failed login attempt."""
        key = f"abuse:failed_login:{user_identifier}"
        await self.redis.incr(key)
        await self.redis.expire(key, ttl_seconds)

    async def reset_failed_logins(self, user_identifier: str):
        """Reset failed login counter (after successful login)."""
        key = f"abuse:failed_login:{user_identifier}"
        await self.redis.delete(key)

    async def check_excessive_api_calls(
        self,
        user_id: UUID,
        lookback_minutes: int = 60,
        threshold: int = 1000,
    ) -> Optional[dict]:
        """
        Check for excessive API calls from a user.
        
        Args:
            user_id: User ID
            lookback_minutes: Time window to check
            threshold: Number of calls to trigger alert
            
        Returns:
            Detection result if pattern found, None otherwise
        """
        abuse_checks_total.labels(check_type="excessive_api_calls").inc()
        
        key = f"abuse:api_calls:{user_id}:{lookback_minutes}m"
        
        # Check Redis counter
        call_count = await self.redis.get(key)
        
        if call_count and int(call_count) >= threshold:
            severity = self._calculate_severity(int(call_count), threshold)
            
            result = {
                "pattern": AbusePattern.EXCESSIVE_API_CALLS,
                "severity": severity,
                "user_id": str(user_id),
                "api_calls": int(call_count),
                "threshold": threshold,
                "window_minutes": lookback_minutes,
                "detected_at": datetime.utcnow().isoformat(),
            }
            
            abuse_patterns_detected.labels(
                pattern=AbusePattern.EXCESSIVE_API_CALLS,
                severity=severity,
            ).inc()
            
            logger.warning(
                "abuse_pattern_detected",
                **result,
            )
            
            return result
        
        return None

    async def check_usage_spike(
        self,
        user_id: UUID,
        lookback_hours: int = 24,
        spike_multiplier: float = 5.0,
    ) -> Optional[dict]:
        """
        Check for unusual spike in usage compared to historical average.
        
        Args:
            user_id: User ID
            lookback_hours: Time window for comparison
            spike_multiplier: How many times average to trigger alert
            
        Returns:
            Detection result if pattern found, None otherwise
        """
        abuse_checks_total.labels(check_type="usage_spike").inc()
        
        now = datetime.utcnow()
        window_start = now - timedelta(hours=lookback_hours)
        history_start = now - timedelta(hours=lookback_hours * 7)  # 7x window for baseline
        
        # Get recent usage
        recent_query = select(func.count(CostEvent.id)).where(
            CostEvent.user_id == user_id,
            CostEvent.created_at >= window_start,
        )
        recent_result = await self.db.execute(recent_query)
        recent_count = recent_result.scalar() or 0
        
        # Get historical average
        history_query = select(func.count(CostEvent.id)).where(
            CostEvent.user_id == user_id,
            CostEvent.created_at >= history_start,
            CostEvent.created_at < window_start,
        )
        history_result = await self.db.execute(history_query)
        history_count = history_result.scalar() or 0
        
        if history_count == 0:
            return None  # Not enough data for comparison
        
        # Calculate average events per window
        num_windows = 7
        avg_per_window = history_count / num_windows
        
        if recent_count >= avg_per_window * spike_multiplier:
            spike_ratio = recent_count / avg_per_window if avg_per_window > 0 else 0
            severity = self._calculate_spike_severity(spike_ratio)
            
            result = {
                "pattern": AbusePattern.USAGE_SPIKE,
                "severity": severity,
                "user_id": str(user_id),
                "recent_events": recent_count,
                "historical_average": int(avg_per_window),
                "spike_ratio": round(spike_ratio, 2),
                "threshold_multiplier": spike_multiplier,
                "window_hours": lookback_hours,
                "detected_at": datetime.utcnow().isoformat(),
            }
            
            abuse_patterns_detected.labels(
                pattern=AbusePattern.USAGE_SPIKE,
                severity=severity,
            ).inc()
            
            logger.warning(
                "abuse_pattern_detected",
                **result,
            )
            
            return result
        
        return None

    async def check_cost_spike(
        self,
        user_id: UUID,
        lookback_hours: int = 24,
        spike_multiplier: float = 5.0,
    ) -> Optional[dict]:
        """
        Check for unusual spike in costs compared to historical average.
        
        Args:
            user_id: User ID
            lookback_hours: Time window for comparison
            spike_multiplier: How many times average to trigger alert
            
        Returns:
            Detection result if pattern found, None otherwise
        """
        abuse_checks_total.labels(check_type="cost_spike").inc()
        
        now = datetime.utcnow()
        window_start = now - timedelta(hours=lookback_hours)
        history_start = now - timedelta(hours=lookback_hours * 7)
        
        # Get recent costs
        recent_query = select(func.sum(CostEvent.total_cost)).where(
            CostEvent.user_id == user_id,
            CostEvent.created_at >= window_start,
        )
        recent_result = await self.db.execute(recent_query)
        recent_cost = recent_result.scalar() or 0.0
        
        # Get historical average
        history_query = select(func.sum(CostEvent.total_cost)).where(
            CostEvent.user_id == user_id,
            CostEvent.created_at >= history_start,
            CostEvent.created_at < window_start,
        )
        history_result = await self.db.execute(history_query)
        history_cost = history_result.scalar() or 0.0
        
        if history_cost == 0:
            return None
        
        num_windows = 7
        avg_per_window = history_cost / num_windows
        
        if recent_cost >= avg_per_window * spike_multiplier:
            spike_ratio = recent_cost / avg_per_window if avg_per_window > 0 else 0
            severity = self._calculate_spike_severity(spike_ratio)
            
            result = {
                "pattern": AbusePattern.COST_SPIKE,
                "severity": severity,
                "user_id": str(user_id),
                "recent_cost_usd": round(recent_cost, 2),
                "historical_average_usd": round(avg_per_window, 2),
                "spike_ratio": round(spike_ratio, 2),
                "threshold_multiplier": spike_multiplier,
                "window_hours": lookback_hours,
                "detected_at": datetime.utcnow().isoformat(),
            }
            
            abuse_patterns_detected.labels(
                pattern=AbusePattern.COST_SPIKE,
                severity=severity,
            ).inc()
            
            logger.warning(
                "abuse_pattern_detected",
                **result,
            )
            
            return result
        
        return None

    async def check_all_patterns(
        self,
        user_id: UUID,
        user_email: Optional[str] = None,
    ) -> list[dict]:
        """
        Run all abuse detection checks for a user.
        
        Returns:
            List of detected patterns
        """
        detections = []
        
        # Check failed logins (if email provided)
        if user_email:
            failed_login = await self.check_failed_logins(user_email)
            if failed_login:
                detections.append(failed_login)
        
        # Check excessive API calls
        api_calls = await self.check_excessive_api_calls(user_id)
        if api_calls:
            detections.append(api_calls)
        
        # Check usage spike
        usage_spike = await self.check_usage_spike(user_id)
        if usage_spike:
            detections.append(usage_spike)
        
        # Check cost spike
        cost_spike = await self.check_cost_spike(user_id)
        if cost_spike:
            detections.append(cost_spike)
        
        return detections

    def _calculate_severity(
        self,
        actual: int,
        threshold: int,
    ) -> AbuseSeverity:
        """Calculate severity based on how much threshold is exceeded."""
        ratio = actual / threshold if threshold > 0 else 0
        
        if ratio >= 10:
            return AbuseSeverity.CRITICAL
        elif ratio >= 5:
            return AbuseSeverity.HIGH
        elif ratio >= 2:
            return AbuseSeverity.MEDIUM
        else:
            return AbuseSeverity.LOW

    def _calculate_spike_severity(self, spike_ratio: float) -> AbuseSeverity:
        """Calculate severity based on spike ratio."""
        if spike_ratio >= 20:
            return AbuseSeverity.CRITICAL
        elif spike_ratio >= 10:
            return AbuseSeverity.HIGH
        elif spike_ratio >= 5:
            return AbuseSeverity.MEDIUM
        else:
            return AbuseSeverity.LOW
