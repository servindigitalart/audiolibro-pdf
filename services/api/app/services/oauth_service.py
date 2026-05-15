"""
OAuth Service
=============
Google OAuth 2.0 code exchange and user provisioning.

All calls to Google are made server-to-server with httpx.
The browser never touches a raw OAuth token — only the Astro callback
endpoint mediates the exchange before handing Sonoro JWT cookies to the client.
"""

from typing import Dict, Optional, Tuple

import httpx
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging_config import get_logger
from app.db.models.user import User

logger = get_logger(__name__)

GOOGLE_TOKEN_URL    = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"


class OAuthService:

    @staticmethod
    async def exchange_google_code(code: str, redirect_uri: str) -> Dict[str, str]:
        """
        Exchange a Google authorization code for verified user profile data.

        Returns the raw Google userinfo dict (sub, email, name, picture,
        email_verified, …).  Raises HTTP 502 if Google responds with an error.
        """
        async with httpx.AsyncClient(timeout=10.0) as client:
            token_resp = await client.post(
                GOOGLE_TOKEN_URL,
                data={
                    "code":          code,
                    "client_id":     settings.google_client_id,
                    "client_secret": settings.google_client_secret,
                    "redirect_uri":  redirect_uri,
                    "grant_type":    "authorization_code",
                },
            )

        if token_resp.status_code != 200:
            logger.error(
                f"Google token exchange failed: {token_resp.status_code} {token_resp.text}"
            )
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Failed to exchange authorization code with Google",
            )

        token_data   = token_resp.json()
        access_token = token_data.get("access_token")

        if not access_token:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="No access token in Google response",
            )

        async with httpx.AsyncClient(timeout=10.0) as client:
            info_resp = await client.get(
                GOOGLE_USERINFO_URL,
                headers={"Authorization": f"Bearer {access_token}"},
            )

        if info_resp.status_code != 200:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Failed to fetch profile from Google",
            )

        user_info = info_resp.json()

        if not user_info.get("email_verified", False):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Google account email is not verified",
            )

        return user_info

    @staticmethod
    async def get_or_create_oauth_user(
        email:       str,
        provider_id: str,
        provider:    str,
        name:        Optional[str],
        db:          AsyncSession,
    ) -> Tuple[User, bool]:
        """
        Resolve OAuth identity to a Sonoro user record.

        Resolution order (safe against duplicate-email attacks):
        1. Existing row matching (provider, provider_id) → update profile, return
        2. Existing row matching email → link provider, mark verified, return
        3. No match → create new OAuth-only user (no password)

        Returns (user, is_new_user).
        """
        if not email:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email not provided by OAuth provider",
            )

        # 1. Exact provider match
        result = await db.execute(
            select(User).where(
                User.oauth_provider == provider,
                User.oauth_id       == provider_id,
            )
        )
        user = result.scalar_one_or_none()

        if user:
            if name and not user.full_name:
                user.full_name = name
            user.is_verified = True
            await db.commit()
            await db.refresh(user)
            logger.info(f"OAuth sign-in: {email} via {provider}")
            return user, False

        # 2. Email already exists (password account) → link the provider
        result = await db.execute(select(User).where(User.email == email))
        user   = result.scalar_one_or_none()

        if user:
            user.oauth_provider = provider
            user.oauth_id       = provider_id
            user.is_verified    = True
            if name and not user.full_name:
                user.full_name = name
            await db.commit()
            await db.refresh(user)
            logger.info(f"OAuth provider linked to existing account: {email}")
            return user, False

        # 3. Brand-new user
        new_user = User(
            email           = email,
            hashed_password = None,   # OAuth-only, no password
            full_name       = name,
            is_active       = True,
            is_verified     = True,   # Google has already verified the email
            oauth_provider  = provider,
            oauth_id        = provider_id,
            role            = "user",
            plan_tier       = "FREE",
        )
        db.add(new_user)
        await db.commit()
        await db.refresh(new_user)
        logger.info(f"New OAuth user created: {email} via {provider}")
        return new_user, True
