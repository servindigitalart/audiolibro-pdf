"""
Cost Enumerations
=================
Enums for cost tracking and financial operations.
"""

from enum import Enum


class CostEventType(str, Enum):
    """
    Types of cost events that can be tracked.
    """
    
    # TTS Operations (future)
    TTS_CHARACTERS = "tts_characters"
    TTS_JOB = "tts_job"
    
    # Storage Operations (future)
    STORAGE_GB_MONTH = "storage_gb_month"
    STORAGE_UPLOAD = "storage_upload"
    STORAGE_DOWNLOAD = "storage_download"
    
    # API Operations
    API_CALL = "api_call"
    API_CALL_PREMIUM = "api_call_premium"
    
    # Infrastructure
    COMPUTE_HOUR = "compute_hour"
    BANDWIDTH_GB = "bandwidth_gb"
    
    # Email Operations (future)
    EMAIL_SENT = "email_sent"
    
    # External Services (future)
    OPENAI_TTS = "openai_tts"
    OPENAI_WHISPER = "openai_whisper"
    ANTHROPIC_API = "anthropic_api"
    
    # Credits/Refunds
    CREDIT_MANUAL = "credit_manual"
    REFUND = "refund"


class CostProvider(str, Enum):
    """
    External providers that generate costs.
    """
    
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    GOOGLE = "google"  # BLOCK 6A: Google Cloud TTS
    DIGITALOCEAN = "digitalocean"
    AWS_S3 = "aws_s3"
    SENDGRID = "sendgrid"
    INTERNAL = "internal"
    NONE = "none"


class ActionType(str, Enum):
    """
    Types of actions for quota checking.
    """
    
    # TTS Actions (future)
    TTS_JOB_CREATE = "tts_job_create"
    TTS_CHARACTER_USE = "tts_character_use"
    
    # Storage Actions (future)
    STORAGE_UPLOAD = "storage_upload"
    STORAGE_USE = "storage_use"
    
    # API Actions
    API_CALL = "api_call"
    CONCURRENT_JOB = "concurrent_job"
