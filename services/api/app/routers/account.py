"""
Account Router
==============
Account domain API endpoints.
"""

from uuid import UUID
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth_dependencies import get_current_user
from app.core.logging import get_logger
from app.db.models.user import User
from app.db.session import get_db
from app.services.account_service import AccountService
from app.schemas.account import (
    AccountOverviewResponse,
    UsageResponse,
    ActivityResponse,
    AccountPreferencesResponse,
    UpdateAccountPreferencesRequest,
    PlanResponse,
    SimulateUpgradeRequest,
    SimulateUpgradeResponse,
    ProfileResponse,
    ProfileUpdateRequest,
    DeleteAccountRequest,
    APIKeyResponse,
    APIKeyListItem,
    APIKeysListResponse,
    MessageResponse,
)
from app.financial.financial_metrics import (
    account_overview_requests_total,
    usage_requests_total,
    activity_requests_total,
    settings_updates_total,
    plan_simulations_total,
    account_health_status,
    password_changes_total,
    account_deletions_total,
    api_keys_generated_total,
    api_keys_revoked_total,
    profile_updates_total,
)

logger = get_logger(__name__)

router = APIRouter(prefix="/api/v1/account", tags=["account"])


@router.get("/overview", response_model=AccountOverviewResponse)
async def get_account_overview(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Get complete account overview.
    
    Returns:
    - User information
    - Current plan tier
    - Usage summary (characters, jobs, storage, API calls)
    - Cost summary (total, by event type, by provider)
    - Remaining quota
    - Account health indicators
    
    **Requires authentication**
    """
    service = AccountService(db)
    overview = await service.get_account_overview(current_user.id)
    
    # Emit metrics
    account_overview_requests_total.labels(plan_tier=current_user.plan_tier).inc()
    account_health_status.labels(user_id=str(current_user.id)).set(
        1 if overview.health.is_healthy else 0
    )
    
    # Log activity
    await service.log_activity(
        user_id=current_user.id,
        activity_type="account_overview",
        description="Viewed account overview",
    )
    
    logger.info(
        "account_overview_accessed",
        user_id=str(current_user.id),
        plan_tier=current_user.plan_tier,
    )
    
    return overview


@router.get("/usage", response_model=UsageResponse)
async def get_usage(
    days: int = Query(default=30, ge=1, le=90, description="Number of days for daily data"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Get detailed usage information.
    
    Returns:
    - Monthly usage summary
    - Cost breakdown by event type
    - Daily usage data (chart-ready)
    - Remaining quota
    
    **Requires authentication**
    """
    service = AccountService(db)
    usage = await service.get_usage_details(current_user.id, days=days)
    
    # Emit metrics
    usage_requests_total.labels(plan_tier=current_user.plan_tier).inc()
    
    logger.info(
        "usage_accessed",
        user_id=str(current_user.id),
        days=days,
    )
    
    return usage


@router.get("/activity", response_model=ActivityResponse)
async def get_activity(
    limit: int = Query(default=50, ge=1, le=100, description="Maximum activities to return"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Get user activity history.
    
    Returns:
    - Recent activities (last N actions)
    - Login history
    - Suspicious activity markers
    - Total activity count
    
    **Requires authentication**
    """
    service = AccountService(db)
    activity = await service.get_activity_history(current_user.id, limit=limit)
    
    # Emit metrics
    activity_requests_total.inc()
    
    logger.info(
        "activity_accessed",
        user_id=str(current_user.id),
        limit=limit,
    )
    
    return activity


@router.get("/settings", response_model=AccountPreferencesResponse)
async def get_settings(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Get account settings and preferences.
    
    Returns:
    - Preferred language
    - Preferred voice
    - Timezone
    - Currency
    - Notification preferences
    
    **Requires authentication**
    """
    service = AccountService(db)
    preferences = await service.get_preferences(current_user.id)
    
    logger.info(
        "settings_accessed",
        user_id=str(current_user.id),
    )
    
    return preferences


@router.patch("/settings", response_model=AccountPreferencesResponse)
async def update_settings(
    updates: UpdateAccountPreferencesRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Update account settings and preferences.
    
    Supports partial updates - only send fields you want to change.
    
    **Requires authentication**
    """
    service = AccountService(db)
    
    # Convert to dict, excluding None values
    update_dict = updates.model_dump(exclude_none=True)
    
    preferences = await service.update_preferences(current_user.id, update_dict)
    
    # Emit metrics
    settings_updates_total.inc()
    
    # Log activity
    await service.log_activity(
        user_id=current_user.id,
        activity_type="settings_update",
        description="Updated account settings",
        metadata={"updated_fields": list(update_dict.keys())},
    )
    
    logger.info(
        "settings_updated",
        user_id=str(current_user.id),
        updated_fields=list(update_dict.keys()),
    )
    
    return preferences


@router.get("/plan", response_model=PlanResponse)
async def get_plan(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Get plan information and upgrade options.
    
    Returns:
    - Current plan details (tier, limits, features)
    - Available upgrade options
    - Feature comparison matrix
    
    **Requires authentication**
    """
    service = AccountService(db)
    plan_info = await service.get_plan_info(current_user.id)
    
    logger.info(
        "plan_info_accessed",
        user_id=str(current_user.id),
        current_tier=current_user.plan_tier,
    )
    
    return plan_info


@router.post("/plan/simulate-upgrade", response_model=SimulateUpgradeResponse)
async def simulate_upgrade(
    request: SimulateUpgradeRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Simulate plan upgrade.
    
    **NO PAYMENT IS PROCESSED - THIS IS A SIMULATION ONLY**
    
    Returns:
    - New plan limits
    - New plan features
    - Projected cost increase
    - Projected quota increase
    - Benefits of upgrading
    
    **Requires authentication**
    """
    service = AccountService(db)
    
    try:
        simulation = await service.simulate_upgrade(
            current_user.id,
            request.target_tier,
        )
        
        # Emit metrics
        plan_simulations_total.labels(
            current_tier=current_user.plan_tier,
            target_tier=request.target_tier
        ).inc()
        
        # Log activity
        await service.log_activity(
            user_id=current_user.id,
            activity_type="upgrade_simulation",
            description=f"Simulated upgrade to {request.target_tier}",
            metadata={"target_tier": request.target_tier},
        )
        
        logger.info(
            "upgrade_simulated",
            user_id=str(current_user.id),
            current_tier=current_user.plan_tier,
            target_tier=request.target_tier,
        )
        
        return simulation
    
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ============================================
# BLOCK 8E: PROFILE & ACCOUNT MANAGEMENT
# ============================================

@router.get("/profile", response_model=ProfileResponse)
async def get_profile(
    current_user: User = Depends(get_current_user),
):
    """
    Get user profile information.
    
    Returns:
    - Email (read-only)
    - Full name
    - Account status
    - Role
    - Timestamps
    
    **Requires authentication**
    """
    return ProfileResponse(
        email=current_user.email,
        full_name=current_user.full_name,
        is_active=current_user.is_active,
        is_verified=current_user.is_verified,
        role=current_user.role,
        created_at=current_user.created_at,
        updated_at=current_user.updated_at,
    )


@router.patch("/profile", response_model=ProfileResponse)
async def update_profile(
    updates: ProfileUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Update user profile.
    
    Supports partial updates - only send fields you want to change.
    
    **Requires authentication**
    """
    service = AccountService(db)
    
    # Update full_name if provided
    if updates.full_name is not None:
        current_user.full_name = updates.full_name
        await db.commit()
        await db.refresh(current_user)
    
    # Log activity
    await service.log_activity(
        user_id=current_user.id,
        activity_type="profile_update",
        description="Updated profile information",
        metadata={"fields": ["full_name"] if updates.full_name is not None else []},
    )
    
    # Emit metric
    profile_updates_total.inc()
    
    logger.info(
        "profile_updated",
        user_id=str(current_user.id),
    )
    
    return ProfileResponse(
        email=current_user.email,
        full_name=current_user.full_name,
        is_active=current_user.is_active,
        is_verified=current_user.is_verified,
        role=current_user.role,
        created_at=current_user.created_at,
        updated_at=current_user.updated_at,
    )


@router.delete("/delete-account", response_model=MessageResponse)
async def delete_account(
    request: DeleteAccountRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Delete user account (soft delete).
    
    Requires:
    - Current password for verification
    - Confirmation string "DELETE"
    
    This performs a soft delete by setting is_active=False.
    All user data is retained for auditing but account cannot be used.
    
    **Requires authentication**
    **This action cannot be undone**
    """
    from app.services.auth_service import AuthService
    
    # Verify confirmation
    if request.confirmation != "DELETE":
        raise HTTPException(
            status_code=400,
            detail="Confirmation must be exactly 'DELETE'"
        )
    
    # OAuth users cannot verify password
    if current_user.oauth_provider:
        raise HTTPException(
            status_code=400,
            detail="OAuth users must delete account through OAuth provider"
        )
    
    # Verify password
    if not AuthService.verify_password(request.password, current_user.hashed_password):
        raise HTTPException(
            status_code=401,
            detail="Invalid password"
        )
    
    # Soft delete - set is_active to False
    current_user.is_active = False
    await db.commit()
    
    # Log activity
    service = AccountService(db)
    await service.log_activity(
        user_id=current_user.id,
        activity_type="account_deletion",
        description="Account deleted by user",
        metadata={"method": "self-service"},
    )
    
    # Emit metric
    from app.financial.financial_metrics import account_deletions_total
    account_deletions_total.inc()
    
    logger.warning(
        "account_deleted",
        user_id=str(current_user.id),
        email=current_user.email,
    )
    
    return MessageResponse(message="Account deleted successfully")


@router.post("/api-key", response_model=APIKeyResponse)
async def generate_api_key(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Generate a new API key.
    
    Returns the full key only once. Store it securely.
    Maximum 5 active keys per user.
    
    **Requires authentication**
    """
    import secrets
    from app.services.auth_service import AuthService
    from app.db.models.api_key import APIKey
    from sqlalchemy import select, func
    
    # Check existing active keys count
    stmt = select(func.count()).select_from(APIKey).where(
        APIKey.user_id == current_user.id,
        APIKey.is_active == True
    )
    result = await db.execute(stmt)
    active_count = result.scalar()
    
    if active_count >= 5:
        raise HTTPException(
            status_code=400,
            detail="Maximum 5 active API keys allowed. Please revoke an existing key first."
        )
    
    # Generate secure random key (32 bytes = 64 hex chars)
    api_key = f"sk_live_{secrets.token_hex(32)}"
    key_hash = AuthService.hash_password(api_key)
    key_preview = f"...{api_key[-4:]}"
    
    # Create API key
    new_key = APIKey(
        user_id=current_user.id,
        key_hash=key_hash,
        key_preview=key_preview,
        is_active=True,
    )
    db.add(new_key)
    await db.commit()
    await db.refresh(new_key)
    
    # Log activity
    service = AccountService(db)
    await service.log_activity(
        user_id=current_user.id,
        activity_type="api_key_generated",
        description="Generated new API key",
        metadata={"key_id": str(new_key.id), "key_preview": key_preview},
    )
    
    # Emit metric
    from app.financial.financial_metrics import api_keys_generated_total
    api_keys_generated_total.inc()
    
    logger.info(
        "api_key_generated",
        user_id=str(current_user.id),
        key_id=str(new_key.id),
    )
    
    return APIKeyResponse(
        key=api_key,  # Only shown once!
        key_id=new_key.id,
        created_at=new_key.created_at,
    )


@router.get("/api-keys", response_model=APIKeysListResponse)
async def list_api_keys(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    List all user's API keys (active and inactive).
    
    Keys are masked for security. Only last 4 characters are shown.
    
    **Requires authentication**
    """
    from app.db.models.api_key import APIKey
    from sqlalchemy import select
    
    stmt = select(APIKey).where(
        APIKey.user_id == current_user.id
    ).order_by(APIKey.created_at.desc())
    
    result = await db.execute(stmt)
    keys = result.scalars().all()
    
    return APIKeysListResponse(
        keys=[
            APIKeyListItem(
                key_id=key.id,
                key_preview=key.key_preview,
                created_at=key.created_at,
                last_used_at=key.last_used_at,
            )
            for key in keys if key.is_active
        ],
        total=len([k for k in keys if k.is_active]),
    )


@router.delete("/api-key/{key_id}", response_model=MessageResponse)
async def revoke_api_key(
    key_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Revoke (delete) an API key.
    
    This is permanent and cannot be undone.
    The key will immediately stop working.
    
    **Requires authentication**
    """
    from app.db.models.api_key import APIKey
    from sqlalchemy import select
    
    # Find key
    stmt = select(APIKey).where(
        APIKey.id == key_id,
        APIKey.user_id == current_user.id
    )
    result = await db.execute(stmt)
    api_key = result.scalar_one_or_none()
    
    if not api_key:
        raise HTTPException(
            status_code=404,
            detail="API key not found"
        )
    
    # Soft delete - set is_active to False
    api_key.is_active = False
    await db.commit()
    
    # Log activity
    service = AccountService(db)
    await service.log_activity(
        user_id=current_user.id,
        activity_type="api_key_revoked",
        description="Revoked API key",
        metadata={"key_id": str(key_id), "key_preview": api_key.key_preview},
    )
    
    logger.info(
        "api_key_revoked",
        user_id=str(current_user.id),
        key_id=str(key_id),
    )
    
    return MessageResponse(message="API key revoked successfully")
