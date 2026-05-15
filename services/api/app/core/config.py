"""
Sonoro API Configuration
========================
Type-safe configuration management using Pydantic Settings.
"""

from functools import lru_cache
from typing import List

from pydantic import Field, PostgresDsn, RedisDsn, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Application
    app_env: str = Field(default="development", description="Application environment")
    debug: bool = Field(default=False, description="Debug mode")
    api_host: str = Field(default="0.0.0.0", description="API host")
    api_port: int = Field(default=8000, description="API port")
    api_cors_origins: list[str] = Field(
        default=["http://localhost:3000", "http://localhost:8000"],
        description="Comma-separated CORS origins",
    )

    # Security
    secret_key: str = Field(..., description="Secret key for JWT and other crypto")
    
    # JWT Settings
    jwt_algorithm: str = Field(default="HS256", description="JWT signing algorithm")
    access_token_expire_minutes: int = Field(
        default=15, description="Access token expiration in minutes"
    )
    refresh_token_expire_days: int = Field(
        default=7, description="Refresh token expiration in days"
    )

    # Database
    database_url: PostgresDsn = Field(..., description="PostgreSQL connection URL")
    database_async_url: str = Field(..., description="Async PostgreSQL connection URL")
    db_pool_size: int = Field(default=10, description="Database connection pool size")
    db_max_overflow: int = Field(default=20, description="Database max overflow connections")
    db_pool_timeout: int = Field(default=30, description="Database pool timeout in seconds")
    db_pool_recycle: int = Field(default=3600, description="Database pool recycle time in seconds")

    # Redis
    redis_url: RedisDsn = Field(..., description="Redis connection URL")

    # Celery (for future use)
    celery_broker_url: str = Field(..., description="Celery broker URL")
    celery_result_backend: str = Field(..., description="Celery result backend URL")

    # Logging
    log_level: str = Field(default="INFO", description="Logging level")
    log_format: str = Field(default="json", description="Log format: json or text")

    # Rate Limiting
    rate_limit_enabled: bool = Field(default=True, description="Enable rate limiting")
    rate_limit_per_minute: int = Field(
        default=60, description="Rate limit requests per minute"
    )

    # Feature Flags
    feature_email_verification: bool = Field(
        default=False, description="Enable email verification"
    )
    feature_rate_limiting: bool = Field(default=False, description="Enable rate limiting")
    feature_document_upload: bool = Field(default=False, description="Enable document upload")
    feature_tts_processing: bool = Field(default=False, description="Enable TTS processing")
    feature_stripe_billing: bool = Field(default=False, description="Enable Stripe billing")
    feature_abuse_detection: bool = Field(default=False, description="Enable abuse detection")
    feature_request_tracing: bool = Field(default=False, description="Enable request ID tracing")
    feature_billing_enforcement: bool = Field(default=False, description="Enable billing quota enforcement middleware")

    # Cost Governance & Runtime Protection
    hard_cost_limit_enabled: bool = Field(
        default=False, description="Enable hard cost limits (will block when exceeded)"
    )
    global_monthly_cost_cap: float = Field(
        default=10000.0, description="Global monthly cost cap in USD"
    )
    user_monthly_cost_cap: float = Field(
        default=1000.0, description="Per-user monthly cost cap in USD"
    )
    emergency_shutdown_mode: bool = Field(
        default=False, description="Emergency shutdown mode (blocks all non-admin requests)"
    )
    cost_alert_threshold_percentage: float = Field(
        default=80.0, description="Send alerts when cost reaches this % of cap"
    )
    
    # Abuse Detection
    abuse_detection_enabled: bool = Field(
        default=True, description="Enable abuse pattern detection"
    )
    abuse_check_interval_minutes: int = Field(
        default=15, description="How often to run abuse checks"
    )

    # Monitoring & Observability
    sentry_dsn: str = Field(
        default="", description="Sentry DSN for error tracking"
    )
    sentry_traces_sample_rate: float = Field(
        default=0.1, description="Sentry traces sample rate (0.0-1.0)"
    )
    sentry_profiles_sample_rate: float = Field(
        default=0.1, description="Sentry profiles sample rate (0.0-1.0)"
    )
    metrics_collection_interval: int = Field(
        default=15, description="Metrics collection interval in seconds"
    )

    # Document Storage (DigitalOcean Spaces / S3-compatible)
    spaces_region: str = Field(
        default="nyc3", description="DigitalOcean Spaces region"
    )
    spaces_bucket: str = Field(
        default="sonoro-documents", description="Storage bucket name"
    )
    spaces_endpoint: str = Field(
        default="", description="Custom S3-compatible endpoint (auto-generated if empty)"
    )
    spaces_access_key: str = Field(
        default="", description="Spaces access key"
    )
    spaces_secret_key: str = Field(
        default="", description="Spaces secret key"
    )
    max_upload_size_mb: int = Field(
        default=50, description="Maximum file upload size in megabytes"
    )

    # Google Cloud TTS (BLOCK 6A)
    google_tts_credentials_json: str = Field(
        default="", description="Path to Google Cloud service account JSON file"
    )
    google_tts_api_key: str = Field(
        default="", description="Google Cloud API key (alternative to service account)"
    )
    google_tts_project_id: str = Field(
        default="", description="Google Cloud project ID"
    )
    google_tts_default_voice: str = Field(
        default="en-US-Neural2-A", description="Default Google TTS voice ID"
    )
    google_tts_default_language: str = Field(
        default="en-US", description="Default language code"
    )

    # Stripe Billing (BLOCK 7)
    stripe_mode: str = Field(
        default="mock",
        description="Stripe provider mode: 'mock' (tests/dev) or 'real' (production)",
    )
    stripe_secret_key: str = Field(
        default="", description="Stripe secret API key"
    )
    stripe_publishable_key: str = Field(
        default="", description="Stripe publishable key (for frontend)"
    )
    stripe_webhook_secret: str = Field(
        default="", description="Stripe webhook signing secret"
    )
    stripe_price_basic_monthly: str = Field(
        default="", description="Stripe price ID for BASIC plan (monthly)"
    )
    stripe_price_basic_yearly: str = Field(
        default="", description="Stripe price ID for BASIC plan (yearly)"
    )
    stripe_price_pro_monthly: str = Field(
        default="", description="Stripe price ID for PRO plan (monthly)"
    )
    stripe_price_pro_yearly: str = Field(
        default="", description="Stripe price ID for PRO plan (yearly)"
    )
    stripe_price_enterprise_monthly: str = Field(
        default="", description="Stripe price ID for ENTERPRISE plan (monthly)"
    )
    stripe_price_enterprise_yearly: str = Field(
        default="", description="Stripe price ID for ENTERPRISE plan (yearly)"
    )
    billing_return_url: str = Field(
        default="http://localhost:3000/billing", description="Billing portal return URL"
    )

    # OAuth — Google
    google_client_id: str = Field(
        default="", description="Google OAuth 2.0 client ID"
    )
    google_client_secret: str = Field(
        default="", description="Google OAuth 2.0 client secret"
    )
    frontend_url: str = Field(
        default="http://localhost:3000",
        description="Frontend base URL — used to construct OAuth redirect URIs",
    )


    @property
    def is_development(self) -> bool:
        """Check if running in development mode."""
        return self.app_env == "development"

    @property
    def is_production(self) -> bool:
        """Check if running in production mode."""
        return self.app_env == "production"

    @property
    def cors_origins_list(self) -> List[str]:
        """Get CORS origins as a list."""
        if isinstance(self.api_cors_origins, str):
            return [origin.strip() for origin in self.api_cors_origins.split(",")]
        return self.api_cors_origins


@lru_cache
def get_settings() -> Settings:
    """
    Get cached settings instance.
    Using lru_cache ensures we only load settings once.
    """
    return Settings()


# Global settings instance
settings = get_settings()
