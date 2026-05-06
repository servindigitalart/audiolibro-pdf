"""
Sentry Integration
==================
Error tracking and performance monitoring with Sentry.
"""

import sys
from typing import Optional

from app.core import get_logger

logger = get_logger(__name__)


def init_sentry(
    dsn: Optional[str] = None,
    environment: str = "development",
    release: Optional[str] = None,
    traces_sample_rate: float = 0.1,
    profiles_sample_rate: float = 0.1,
) -> bool:
    """
    Initialize Sentry SDK for error tracking and performance monitoring.
    
    Args:
        dsn: Sentry DSN URL. If None or empty, Sentry is not initialized.
        environment: Environment name (development, production, etc.)
        release: Release version for tracking
        traces_sample_rate: Sampling rate for performance traces (0.0-1.0)
        profiles_sample_rate: Sampling rate for profiling (0.0-1.0)
    
    Returns:
        bool: True if initialized successfully, False otherwise
    """
    if not dsn:
        logger.info("Sentry DSN not provided, skipping Sentry initialization")
        return False
    
    try:
        import sentry_sdk
        from sentry_sdk.integrations.fastapi import FastApiIntegration
        from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration
        from sentry_sdk.integrations.redis import RedisIntegration
        
        sentry_sdk.init(
            dsn=dsn,
            environment=environment,
            release=release,
            traces_sample_rate=traces_sample_rate,
            profiles_sample_rate=profiles_sample_rate,
            integrations=[
                FastApiIntegration(
                    transaction_style="url",  # Use URL path as transaction name
                ),
                SqlalchemyIntegration(),
                RedisIntegration(),
            ],
            # Send default PII (Personally Identifiable Information)
            send_default_pii=False,
            
            # Add custom tags
            _experiments={
                "profiles_sample_rate": profiles_sample_rate,
            },
            
            # Before send hook for filtering
            before_send=_before_send_hook,
        )
        
        logger.info(
            f"✅ Sentry initialized successfully "
            f"(environment={environment}, traces_sample_rate={traces_sample_rate})"
        )
        return True
        
    except ImportError:
        logger.warning(
            "Sentry SDK not installed. Install with: pip install sentry-sdk[fastapi]"
        )
        return False
        
    except Exception as e:
        logger.error(f"Failed to initialize Sentry: {e}", exc_info=True)
        return False


def _before_send_hook(event, hint):
    """
    Filter and modify events before sending to Sentry.
    Can be used to scrub sensitive data or filter out certain errors.
    """
    # Example: Filter out specific exceptions
    if "exc_info" in hint:
        exc_type, exc_value, tb = hint["exc_info"]
        
        # Don't send HTTPExceptions to Sentry (these are expected errors)
        if exc_type.__name__ == "HTTPException":
            return None
    
    return event


def capture_exception(
    error: Exception,
    level: str = "error",
    extra: Optional[dict] = None,
) -> Optional[str]:
    """
    Manually capture an exception and send to Sentry.
    
    Args:
        error: Exception to capture
        level: Severity level (fatal, error, warning, info, debug)
        extra: Additional context data
    
    Returns:
        str: Event ID if sent, None otherwise
    """
    try:
        import sentry_sdk
        
        with sentry_sdk.push_scope() as scope:
            scope.level = level
            
            if extra:
                for key, value in extra.items():
                    scope.set_extra(key, value)
            
            event_id = sentry_sdk.capture_exception(error)
            logger.debug(f"Exception captured in Sentry: {event_id}")
            return event_id
            
    except ImportError:
        logger.debug("Sentry SDK not available, exception not captured")
        return None
    except Exception as e:
        logger.error(f"Failed to capture exception in Sentry: {e}")
        return None


def capture_message(
    message: str,
    level: str = "info",
    extra: Optional[dict] = None,
) -> Optional[str]:
    """
    Manually capture a message and send to Sentry.
    
    Args:
        message: Message to capture
        level: Severity level (fatal, error, warning, info, debug)
        extra: Additional context data
    
    Returns:
        str: Event ID if sent, None otherwise
    """
    try:
        import sentry_sdk
        
        with sentry_sdk.push_scope() as scope:
            scope.level = level
            
            if extra:
                for key, value in extra.items():
                    scope.set_extra(key, value)
            
            event_id = sentry_sdk.capture_message(message)
            logger.debug(f"Message captured in Sentry: {event_id}")
            return event_id
            
    except ImportError:
        logger.debug("Sentry SDK not available, message not captured")
        return None
    except Exception as e:
        logger.error(f"Failed to capture message in Sentry: {e}")
        return None


def set_user_context(user_id: str, email: Optional[str] = None) -> None:
    """
    Set user context for Sentry events.
    
    Args:
        user_id: User ID
        email: User email (optional)
    """
    try:
        import sentry_sdk
        
        sentry_sdk.set_user({
            "id": user_id,
            "email": email,
        })
        
    except ImportError:
        pass
    except Exception as e:
        logger.error(f"Failed to set user context in Sentry: {e}")


def add_breadcrumb(
    message: str,
    category: str = "custom",
    level: str = "info",
    data: Optional[dict] = None,
) -> None:
    """
    Add a breadcrumb for debugging context.
    
    Args:
        message: Breadcrumb message
        category: Category (auth, query, navigation, etc.)
        level: Severity level
        data: Additional data
    """
    try:
        import sentry_sdk
        
        sentry_sdk.add_breadcrumb(
            message=message,
            category=category,
            level=level,
            data=data or {},
        )
        
    except ImportError:
        pass
    except Exception as e:
        logger.error(f"Failed to add breadcrumb in Sentry: {e}")
