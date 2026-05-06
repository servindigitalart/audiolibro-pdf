"""
OAuth Base Classes
==================
Abstract base classes for OAuth providers (Google, GitHub, etc.).
Implementation will be done in future phases.
"""

from abc import ABC, abstractmethod
from typing import Dict, Optional


class OAuthProviderBase(ABC):
    """
    Abstract base class for OAuth providers.
    
    Future implementations will include:
    - GoogleOAuthProvider
    - GitHubOAuthProvider
    - MicrosoftOAuthProvider
    
    Each provider should implement:
    1. get_authorization_url() - Generate OAuth authorization URL
    2. exchange_code_for_token() - Exchange authorization code for access token
    3. get_user_info() - Fetch user information from provider
    """
    
    provider_name: str
    
    @abstractmethod
    async def get_authorization_url(self, state: str, redirect_uri: str) -> str:
        """
        Generate OAuth authorization URL.
        
        Args:
            state: CSRF protection state token
            redirect_uri: Callback URL after authorization
            
        Returns:
            Authorization URL string
        """
        pass
    
    @abstractmethod
    async def exchange_code_for_token(
        self, 
        code: str, 
        redirect_uri: str
    ) -> Dict[str, str]:
        """
        Exchange authorization code for access token.
        
        Args:
            code: Authorization code from OAuth provider
            redirect_uri: Callback URL (must match authorization request)
            
        Returns:
            Dictionary containing access_token, token_type, etc.
        """
        pass
    
    @abstractmethod
    async def get_user_info(self, access_token: str) -> Dict[str, Optional[str]]:
        """
        Fetch user information from OAuth provider.
        
        Args:
            access_token: Valid OAuth access token
            
        Returns:
            Dictionary with user info (email, name, provider_id, etc.)
        """
        pass
    
    @abstractmethod
    async def revoke_token(self, token: str) -> bool:
        """
        Revoke an OAuth access token.
        
        Args:
            token: Access token to revoke
            
        Returns:
            True if successfully revoked, False otherwise
        """
        pass


# Placeholder for future implementations
class GoogleOAuthProvider(OAuthProviderBase):
    """
    Google OAuth provider (to be implemented in future phase).
    """
    provider_name = "google"
    
    async def get_authorization_url(self, state: str, redirect_uri: str) -> str:
        raise NotImplementedError("Google OAuth not yet implemented")
    
    async def exchange_code_for_token(self, code: str, redirect_uri: str) -> Dict[str, str]:
        raise NotImplementedError("Google OAuth not yet implemented")
    
    async def get_user_info(self, access_token: str) -> Dict[str, Optional[str]]:
        raise NotImplementedError("Google OAuth not yet implemented")
    
    async def revoke_token(self, token: str) -> bool:
        raise NotImplementedError("Google OAuth not yet implemented")


class GitHubOAuthProvider(OAuthProviderBase):
    """
    GitHub OAuth provider (to be implemented in future phase).
    """
    provider_name = "github"
    
    async def get_authorization_url(self, state: str, redirect_uri: str) -> str:
        raise NotImplementedError("GitHub OAuth not yet implemented")
    
    async def exchange_code_for_token(self, code: str, redirect_uri: str) -> Dict[str, str]:
        raise NotImplementedError("GitHub OAuth not yet implemented")
    
    async def get_user_info(self, access_token: str) -> Dict[str, Optional[str]]:
        raise NotImplementedError("GitHub OAuth not yet implemented")
    
    async def revoke_token(self, token: str) -> bool:
        raise NotImplementedError("GitHub OAuth not yet implemented")
