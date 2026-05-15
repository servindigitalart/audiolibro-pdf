"""
OAuth Router
============
Google OAuth 2.0 endpoints.

Flow (browser never touches raw OAuth tokens):
  Browser → GET /api/auth/google (Astro)
          → Google consent screen
          → GET /api/auth/callback/google (Astro, verifies CSRF state)
          → POST /api/v1/auth/oauth/google/exchange  ← this file
          → Astro sets httpOnly cookies → redirect to dashboard
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging_config import get_logger
from app.db import get_db
from app.schemas.auth import OAuthExchangeRequest, OAuthTokenResponse
from app.services.auth_service import AuthService
from app.services.oauth_service import OAuthService

logger = get_logger(__name__)

router = APIRouter(prefix="/api/v1/auth/oauth", tags=["OAuth"])


@router.post(
    "/google/exchange",
    response_model=OAuthTokenResponse,
    summary="Exchange Google OAuth code for Sonoro JWT tokens",
    description=(
        "Server-to-server endpoint called by the Astro callback handler. "
        "Exchanges the authorization code, verifies the identity with Google, "
        "provisions or updates the user record, and returns Sonoro JWTs."
    ),
)
async def google_exchange(
    request: OAuthExchangeRequest,
    db: AsyncSession = Depends(get_db),
) -> OAuthTokenResponse:
    """
    1. Verify Google OAuth credentials are configured.
    2. Exchange the authorization code with Google (server-to-server).
    3. Verify the returned email is confirmed.
    4. Create or link the user record.
    5. Issue Sonoro access + refresh token pair (with Redis JTI registration).
    """
    if not settings.google_client_id or not settings.google_client_secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Google OAuth is not configured on this server",
        )

    try:
        # Step 1 — exchange code, get verified Google profile
        user_info = await OAuthService.exchange_google_code(
            code         = request.code,
            redirect_uri = request.redirect_uri,
        )

        # Step 2 — provision / link user
        user, is_new_user = await OAuthService.get_or_create_oauth_user(
            email       = user_info["email"],
            provider_id = user_info["sub"],
            provider    = "google",
            name        = user_info.get("name"),
            db          = db,
        )

        if not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="This account has been deactivated",
            )

        # Step 3 — issue Sonoro tokens (JTI stored in Redis for rotation)
        access_token, refresh_token, _ = await AuthService.create_tokens(user.id)

        logger.info(
            f"OAuth exchange complete: user={user.email} "
            f"new={is_new_user} provider=google"
        )

        return OAuthTokenResponse(
            access_token  = access_token,
            refresh_token = refresh_token,
            token_type    = "bearer",
            expires_in    = settings.access_token_expire_minutes * 60,
            is_new_user   = is_new_user,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Google OAuth exchange error: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="OAuth authentication failed — please try again",
        )
