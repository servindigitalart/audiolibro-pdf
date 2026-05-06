"""
Account Schemas
===============
Pydantic schemas for account domain API.
"""

from datetime import datetime
from typing import Optional, List, Dict, Any
from uuid import UUID

from pydantic import BaseModel, Field, EmailStr


# ============================================
# ACCOUNT OVERVIEW SCHEMAS
# ============================================

class UserInfoSchema(BaseModel):
    """User basic information."""
    id: UUID
    email: EmailStr
    role: str
    plan_tier: str
    is_active: bool
    is_verified: bool
    created_at: datetime


class UsageSummarySchema(BaseModel):
    """Current period usage summary."""
    characters_used: int
    jobs_created: int
    storage_used_mb: float
    api_calls: int
    period_start: datetime
    period_end: datetime


class CostSummarySchema(BaseModel):
    """Cost summary for current period."""
    total_cost_usd: float
    by_event_type: Dict[str, float]
    by_provider: Dict[str, float]
    event_count: int


class QuotaRemainingSchema(BaseModel):
    """Remaining quota information."""
    characters: Dict[str, Any]  # {remaining, limit, used_percentage}
    jobs: Dict[str, Any]
    storage_mb: Dict[str, Any]
    api_calls: Dict[str, Any]


class AccountHealthSchema(BaseModel):
    """Account health indicators."""
    is_healthy: bool
    quota_warnings: List[str]
    cost_warnings: List[str]
    security_warnings: List[str]


class AccountOverviewResponse(BaseModel):
    """Complete account overview response."""
    user: UserInfoSchema
    plan: str
    usage: UsageSummarySchema
    costs: CostSummarySchema
    remaining_quota: QuotaRemainingSchema
    health: AccountHealthSchema
    
    model_config = {"from_attributes": True}


# ============================================
# USAGE SCHEMAS
# ============================================

class DailyUsagePoint(BaseModel):
    """Single day usage data point."""
    date: str
    characters: int
    jobs: int
    api_calls: int
    cost_usd: float


class UsageBreakdownSchema(BaseModel):
    """Detailed usage breakdown."""
    event_type: str
    count: int
    total_cost_usd: float
    percentage: float


class UsageResponse(BaseModel):
    """Usage endpoint response."""
    period: str
    monthly_usage: UsageSummarySchema
    cost_breakdown: List[UsageBreakdownSchema]
    daily_data: List[DailyUsagePoint]
    quota_remaining: QuotaRemainingSchema
    
    model_config = {"from_attributes": True}


# ============================================
# ACTIVITY SCHEMAS
# ============================================

class ActivityLogEntry(BaseModel):
    """Single activity log entry."""
    id: UUID
    activity_type: str
    description: str
    ip_address: Optional[str]
    user_agent: Optional[str]
    is_suspicious: bool
    created_at: datetime
    metadata: Optional[Dict[str, Any]]


class LoginHistoryEntry(BaseModel):
    """Login history entry."""
    timestamp: datetime
    ip_address: Optional[str]
    user_agent: Optional[str]
    success: bool
    location: Optional[str] = None


class ActivityResponse(BaseModel):
    """Activity endpoint response."""
    recent_activities: List[ActivityLogEntry]
    login_history: List[LoginHistoryEntry]
    suspicious_activity_count: int
    total_activities: int
    
    model_config = {"from_attributes": True}


# ============================================
# PREFERENCES SCHEMAS
# ============================================

class AccountPreferencesSchema(BaseModel):
    """Account preferences."""
    preferred_language: str = Field(default="en", max_length=10)
    preferred_voice: Optional[str] = Field(default=None, max_length=100)
    timezone: str = Field(default="UTC", max_length=50)
    currency: str = Field(default="USD", max_length=3)
    email_notifications: bool = Field(default=True)
    marketing_emails: bool = Field(default=False)
    usage_alerts: bool = Field(default=True)


class AccountPreferencesResponse(BaseModel):
    """Preferences response with timestamps."""
    preferences: AccountPreferencesSchema
    created_at: datetime
    updated_at: datetime
    
    model_config = {"from_attributes": True}


class UpdateAccountPreferencesRequest(BaseModel):
    """Request to update preferences (partial update)."""
    preferred_language: Optional[str] = Field(default=None, max_length=10)
    preferred_voice: Optional[str] = Field(default=None, max_length=100)
    timezone: Optional[str] = Field(default=None, max_length=50)
    currency: Optional[str] = Field(default=None, max_length=3)
    email_notifications: Optional[bool] = None
    marketing_emails: Optional[bool] = None
    usage_alerts: Optional[bool] = None


# ============================================
# PLAN SCHEMAS
# ============================================

class PlanLimitsSchema(BaseModel):
    """Plan limits."""
    monthly_char_limit: int
    monthly_job_limit: int
    concurrent_job_limit: int
    storage_limit_mb: int
    api_calls_per_minute: int
    api_calls_per_day: int


class PlanFeaturesSchema(BaseModel):
    """Plan features."""
    priority_processing: bool
    custom_voices: bool
    api_access: bool
    team_members: int


class PlanSchema(BaseModel):
    """Complete plan information."""
    tier: str
    name: str
    limits: PlanLimitsSchema
    features: PlanFeaturesSchema


class UpgradePossibilitySchema(BaseModel):
    """Possible upgrade option."""
    target_tier: str
    name: str
    monthly_price_usd: Optional[float]
    limits: PlanLimitsSchema
    features: PlanFeaturesSchema


class PlanResponse(BaseModel):
    """Plan visualization response."""
    current_plan: PlanSchema
    upgrade_options: List[UpgradePossibilitySchema]
    feature_matrix: Dict[str, Dict[str, Any]]


# ============================================
# PLAN SIMULATION SCHEMAS
# ============================================

class SimulateUpgradeRequest(BaseModel):
    """Request to simulate plan upgrade."""
    target_tier: str = Field(..., description="Target plan tier (BASIC, PRO, ENTERPRISE)")


class ProjectedQuotaSchema(BaseModel):
    """Projected quota after upgrade."""
    characters: int
    jobs: int
    storage_mb: int
    api_calls_per_day: int


class SimulateUpgradeResponse(BaseModel):
    """Simulated upgrade response."""
    target_tier: str
    current_tier: str
    new_limits: PlanLimitsSchema
    new_features: PlanFeaturesSchema
    projected_cost_increase_usd: float
    projected_quota: ProjectedQuotaSchema
    benefits: List[str]
    note: str = "This is a simulation. No payment has been processed."


# ============================================
# ACCOUNT MANAGEMENT SCHEMAS (BLOCK 8E)
# ============================================

class ProfileUpdateRequest(BaseModel):
    """Request to update user profile."""
    full_name: Optional[str] = Field(default=None, max_length=255)


class ProfileResponse(BaseModel):
    """User profile response."""
    email: EmailStr
    full_name: Optional[str]
    is_active: bool
    is_verified: bool
    role: str
    created_at: datetime
    updated_at: datetime
    
    model_config = {"from_attributes": True}


class DeleteAccountRequest(BaseModel):
    """Request to delete account."""
    password: str = Field(..., description="Current password for verification")
    confirmation: str = Field(..., description="Must be exactly 'DELETE' to proceed")


class APIKeyResponse(BaseModel):
    """API key response."""
    key: str = Field(..., description="API key (only shown once after generation)")
    key_id: UUID = Field(..., description="API key ID for revocation")
    created_at: datetime


class APIKeyListItem(BaseModel):
    """API key list item (masked)."""
    key_id: UUID
    key_preview: str = Field(..., description="Last 4 characters of key")
    created_at: datetime
    last_used_at: Optional[datetime]


class APIKeysListResponse(BaseModel):
    """List of user's API keys."""
    keys: List[APIKeyListItem]
    total: int


class MessageResponse(BaseModel):
    """Simple message response."""
    message: str
