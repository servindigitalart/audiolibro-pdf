"""
Runtime Introspection Schemas
==============================
Pydantic schemas for runtime information.
"""

from typing import Dict, Optional

from pydantic import BaseModel, Field


class RuntimeInfo(BaseModel):
    """Runtime information for system introspection."""

    uptime_seconds: float = Field(
        ...,
        description="Application uptime in seconds",
        example=3600.5,
    )
    
    environment: str = Field(
        ...,
        description="Current environment (development, production, etc.)",
        example="production",
    )
    
    version: str = Field(
        ...,
        description="Application version",
        example="0.2.0",
    )
    
    total_requests: int = Field(
        ...,
        description="Total number of HTTP requests processed",
        example=12345,
    )
    
    active_requests: int = Field(
        ...,
        description="Number of currently active requests",
        example=5,
    )
    
    memory_usage_mb: float = Field(
        ...,
        description="Current memory usage in MB",
        example=256.7,
    )
    
    active_connections: Dict[str, int] = Field(
        ...,
        description="Active connections by service",
        example={
            "database": 5,
            "redis": 1,
        },
    )
    
    feature_flags: Dict[str, bool] = Field(
        default_factory=dict,
        description="Current feature flag states",
        example={
            "email_verification": False,
            "rate_limiting": True,
        },
    )


class HealthCheck(BaseModel):
    """Health check response with detailed status."""

    status: str = Field(
        ...,
        description="Overall health status",
        example="healthy",
    )
    
    services: Dict[str, str] = Field(
        ...,
        description="Individual service health statuses",
        example={
            "database": "healthy",
            "redis": "healthy",
            "sentry": "disabled",
        },
    )
    
    uptime_seconds: float = Field(
        ...,
        description="Application uptime in seconds",
        example=3600.5,
    )
    
    version: str = Field(
        ...,
        description="Application version",
        example="0.2.0",
    )
