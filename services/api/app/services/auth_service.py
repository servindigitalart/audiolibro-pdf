"""
Authentication Service
======================
Business logic for user authentication and token management.
"""

from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging_config import get_logger
from app.core.redis import redis_client
from app.core.security import (
    hash_password,
    verify_password,
    create_access_token,
    create_refresh_token,
    verify_token,
)
from app.db.models.user import User

logger = get_logger(__name__)


class AuthService:
    """Authentication service for user management."""
    
    @staticmethod
    async def register_user(
        email: str, 
        password: str, 
        db: AsyncSession
    ) -> User:
        """
        Register a new user.
        
        Args:
            email: User email address
            password: Plain text password
            db: Database session
            
        Returns:
            Created User object
            
        Raises:
            HTTPException: If email already exists
        """
        # Check if user already exists
        result = await db.execute(select(User).where(User.email == email))
        existing_user = result.scalar_one_or_none()
        
        if existing_user:
            logger.warning(f"Registration attempt with existing email: {email}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email already registered",
            )
        
        # Create new user
        hashed_pw = hash_password(password)
        new_user = User(
            email=email,
            hashed_password=hashed_pw,
            is_active=True,
            is_verified=False,  # Email verification required
            role="user",
        )
        
        db.add(new_user)
        await db.commit()
        await db.refresh(new_user)
        
        logger.info(f"User registered successfully: {email}")
        return new_user
    
    @staticmethod
    async def authenticate_user(
        email: str, 
        password: str, 
        db: AsyncSession
    ) -> Optional[User]:
        """
        Authenticate a user with email and password.
        
        Args:
            email: User email address
            password: Plain text password
            db: Database session
            
        Returns:
            User object if authentication successful, None otherwise
        """
        # Fetch user by email
        result = await db.execute(select(User).where(User.email == email))
        user = result.scalar_one_or_none()
        
        if not user:
            logger.warning(f"Login attempt with non-existent email: {email}")
            return None
        
        # Check if user has a password (OAuth users don't)
        if not user.hashed_password:
            logger.warning(f"Login attempt for OAuth-only user: {email}")
            return None
        
        # Verify password
        if not verify_password(password, user.hashed_password):
            logger.warning(f"Failed login attempt for user: {email}")
            return None
        
        logger.info(f"User authenticated successfully: {email}")
        return user
    
    @staticmethod
    async def create_tokens(user_id: UUID) -> Tuple[str, str, str]:
        """
        Create access and refresh tokens for a user.
        
        Args:
            user_id: User UUID
            
        Returns:
            Tuple of (access_token, refresh_token, jti)
        """
        user_id_str = str(user_id)
        
        # Create tokens
        access_token = create_access_token(subject=user_id_str)
        refresh_token, jti = create_refresh_token(subject=user_id_str)
        
        # Store refresh token JTI in Redis
        # Key format: refresh_token:{jti}
        # Value: user_id
        # Expiration: Same as refresh token (7 days)
        redis_key = f"refresh_token:{jti}"
        expire_seconds = settings.refresh_token_expire_days * 24 * 60 * 60
        
        await redis_client.setex(
            redis_key,
            expire_seconds,
            user_id_str
        )
        
        logger.debug(f"Tokens created for user: {user_id}")
        return access_token, refresh_token, jti
    
    @staticmethod
    async def refresh_tokens(refresh_token: str, db: AsyncSession) -> Tuple[str, str]:
        """
        Refresh access and refresh tokens using a refresh token.
        Implements token rotation for security.
        
        Args:
            refresh_token: Current refresh token
            db: Database session
            
        Returns:
            Tuple of (new_access_token, new_refresh_token)
            
        Raises:
            HTTPException: If refresh token is invalid or blacklisted
        """
        # Verify refresh token
        payload = verify_token(refresh_token, token_type="refresh")
        if not payload:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid refresh token",
            )
        
        user_id_str = payload.get("sub")
        jti = payload.get("jti")
        
        if not user_id_str or not jti:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token payload",
            )
        
        # Check if refresh token is blacklisted (exists in Redis)
        redis_key = f"refresh_token:{jti}"
        stored_user_id = await redis_client.get(redis_key)
        
        if not stored_user_id:
            # Token has been used, revoked, or expired
            logger.warning(f"Refresh token reuse attempt detected: {jti}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Refresh token has been revoked or expired",
            )
        
        if stored_user_id != user_id_str:
            logger.error(f"Refresh token user mismatch: {jti}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token",
            )
        
        # Verify user still exists and is active
        try:
            user_id = UUID(user_id_str)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid user ID",
            )
        
        result = await db.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        
        if not user or not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User not found or inactive",
            )
        
        # Invalidate old refresh token (token rotation)
        await redis_client.delete(redis_key)
        
        # Create new tokens
        new_access_token, new_refresh_token, new_jti = await AuthService.create_tokens(user_id)
        
        logger.info(f"Tokens refreshed for user: {user_id}")
        return new_access_token, new_refresh_token
    
    @staticmethod
    async def logout_user(refresh_token: str) -> None:
        """
        Logout a user by invalidating their refresh token.
        
        Args:
            refresh_token: User's refresh token
            
        Raises:
            HTTPException: If refresh token is invalid
        """
        # Verify refresh token
        payload = verify_token(refresh_token, token_type="refresh")
        if not payload:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid refresh token",
            )
        
        jti = payload.get("jti")
        if not jti:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token payload",
            )
        
        # Remove refresh token from Redis
        redis_key = f"refresh_token:{jti}"
        deleted = await redis_client.delete(redis_key)
        
        if deleted:
            logger.info(f"User logged out, token invalidated: {jti}")
        else:
            logger.warning(f"Logout attempted with already invalid token: {jti}")
    
    @staticmethod
    async def change_password(
        user: User,
        current_password: str,
        new_password: str,
        db: AsyncSession,
    ) -> None:
        """
        Change user password.
        
        Args:
            user: User object
            current_password: Current password
            new_password: New password
            db: Database session
            
        Raises:
            HTTPException: If current password is incorrect or user has no password
        """
        # OAuth users cannot change password
        if not user.hashed_password:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot change password for OAuth users",
            )
        
        # Verify current password
        if not verify_password(current_password, user.hashed_password):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Current password is incorrect",
            )
        
        # Hash and update password
        user.hashed_password = hash_password(new_password)
        user.updated_at = datetime.now(timezone.utc)
        
        await db.commit()
        await db.refresh(user)
        
        logger.info(f"Password changed for user: {user.email}")
