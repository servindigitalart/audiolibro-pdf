"""
Authentication Router
=====================
API endpoints for user authentication.
"""

from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth_dependencies import get_current_active_user
from app.core.config import settings
from app.core.logging_config import get_logger
from app.db import get_db
from app.db.models.user import User
from app.schemas.auth import (
    RegisterRequest,
    LoginRequest,
    TokenResponse,
    RefreshTokenRequest,
    UserResponse,
    PasswordChangeRequest,
    MessageResponse,
)
from app.services.auth_service import AuthService
from app.monitoring.business_metrics import (
    increment_login_attempt,
    increment_login_failure,
    increment_user_registration,
    increment_token_refresh,
)

logger = get_logger(__name__)

router = APIRouter(prefix="/api/v1/auth", tags=["Authentication"])


# Rate limiting helper (simplified - full implementation in future)
async def check_rate_limit(request: Request, limit_type: str) -> None:
    """
    Check rate limit for authentication endpoints.
    
    Note: This is a placeholder. Full rate limiting with Redis
    will be implemented in future phases.
    """
    if not settings.feature_rate_limiting:
        return
    
    # TODO: Implement Redis-based rate limiting
    # For now, just log the attempt
    client_ip = request.client.host if request.client else "unknown"
    logger.debug(f"Rate limit check ({limit_type}): {client_ip}")


@router.post(
    "/register",
    response_model=TokenResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new user",
    description="Create a new user account with email and password",
)
async def register(
    request: Request,
    data: RegisterRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Register a new user account.
    
    - **email**: Valid email address (must be unique)
    - **password**: Minimum 8 characters with uppercase, lowercase, and digit
    
    Returns JWT access and refresh tokens upon successful registration.
    """
    await check_rate_limit(request, "register")
    
    try:
        # Register user
        user = await AuthService.register_user(
            email=data.email,
            password=data.password,
            db=db,
        )
        
        # Track successful registration
        increment_user_registration(success=True)
        
        # Create tokens
        access_token, refresh_token, _ = await AuthService.create_tokens(user.id)
        
        return TokenResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            token_type="bearer",
            expires_in=settings.access_token_expire_minutes * 60,
        )
    except Exception as e:
        # Track failed registration
        increment_user_registration(success=False)
        raise


@router.post(
    "/login",
    response_model=TokenResponse,
    summary="User login",
    description="Authenticate with email and password",
)
async def login(
    request: Request,
    data: LoginRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Authenticate a user and return JWT tokens.
    
    - **email**: User email address
    - **password**: User password
    
    Returns JWT access and refresh tokens upon successful authentication.
    """
    await check_rate_limit(request, "login")
    
    # Authenticate user
    user = await AuthService.authenticate_user(
        email=data.email,
        password=data.password,
        db=db,
    )
    
    if not user:
        # Track failed login
        increment_login_attempt(success=False)
        increment_login_failure(reason="invalid_credentials")
        
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
        )
    
    # Check if user is active
    if not user.is_active:
        # Track failed login
        increment_login_attempt(success=False)
        increment_login_failure(reason="account_inactive")
        
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is inactive",
        )
    
    # Track successful login
    increment_login_attempt(success=True)
    
    # Create tokens
    access_token, refresh_token, _ = await AuthService.create_tokens(user.id)
    
    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer",
        expires_in=settings.access_token_expire_minutes * 60,
    )


@router.post(
    "/refresh",
    response_model=TokenResponse,
    summary="Refresh access token",
    description="Get a new access token using a refresh token",
)
async def refresh(
    data: RefreshTokenRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Refresh access token using a valid refresh token.
    
    Implements token rotation: the old refresh token is invalidated
    and a new pair of tokens is returned.
    
    - **refresh_token**: Valid JWT refresh token
    
    Returns new JWT access and refresh tokens.
    """
    try:
        # Refresh tokens (with rotation)
        new_access_token, new_refresh_token = await AuthService.refresh_tokens(
            refresh_token=data.refresh_token,
            db=db,
        )
        
        # Track successful token refresh
        increment_token_refresh(success=True)
        
        return TokenResponse(
            access_token=new_access_token,
            refresh_token=new_refresh_token,
            token_type="bearer",
            expires_in=settings.access_token_expire_minutes * 60,
        )
    except Exception as e:
        # Track failed token refresh
        increment_token_refresh(success=False)
        raise


@router.post(
    "/logout",
    response_model=MessageResponse,
    summary="User logout",
    description="Logout and invalidate refresh token",
)
async def logout(data: RefreshTokenRequest):
    """
    Logout a user by invalidating their refresh token.
    
    - **refresh_token**: JWT refresh token to invalidate
    
    Note: Access tokens cannot be invalidated (stateless JWT design).
    They will expire after 15 minutes.
    """
    await AuthService.logout_user(refresh_token=data.refresh_token)
    
    return MessageResponse(message="Successfully logged out")


@router.get(
    "/me",
    response_model=UserResponse,
    summary="Get current user",
    description="Get information about the currently authenticated user",
)
async def get_me(current_user: User = Depends(get_current_active_user)):
    """
    Get current user information.
    
    Requires valid JWT access token in Authorization header:
    `Authorization: Bearer <access_token>`
    
    Returns user profile information.
    """
    return UserResponse.model_validate(current_user)


@router.post(
    "/change-password",
    response_model=MessageResponse,
    summary="Change password",
    description="Change user password",
)
async def change_password(
    data: PasswordChangeRequest,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Change user password.
    
    Requires valid JWT access token.
    
    - **current_password**: Current password for verification
    - **new_password**: New password (min 8 characters with uppercase, lowercase, digit)
    
    Note: OAuth users cannot change password.
    """
    await AuthService.change_password(
        user=current_user,
        current_password=data.current_password,
        new_password=data.new_password,
        db=db,
    )
    
    return MessageResponse(message="Password changed successfully")
