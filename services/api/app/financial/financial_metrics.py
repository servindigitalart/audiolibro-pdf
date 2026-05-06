"""
Financial Metrics for Prometheus
================================
Cost and quota metrics for financial observability.
"""

from prometheus_client import Gauge, Counter, Histogram
from app.monitoring.metrics import metrics_registry

# ============================================
# COST METRICS
# ============================================

cost_total = Gauge(
    "sonoro_cost_total",
    "Total cost in USD by event type",
    ["event_type", "provider"],
    registry=metrics_registry,
)

cost_per_user = Gauge(
    "sonoro_cost_per_user",
    "Cost per user in USD",
    ["user_id"],
    registry=metrics_registry,
)

estimated_cost_total = Gauge(
    "sonoro_estimated_cost_total",
    "Estimated cost without tracking (for what-if scenarios)",
    ["event_type"],
    registry=metrics_registry,
)

cost_events_total = Counter(
    "sonoro_cost_events_total",
    "Total cost events tracked",
    ["event_type", "provider"],
    registry=metrics_registry,
)

monthly_cost_usd = Gauge(
    "sonoro_monthly_cost_usd",
    "Monthly cost breakdown by type",
    ["cost_type"],
    registry=metrics_registry,
)

# ============================================
# QUOTA METRICS
# ============================================

quota_remaining = Gauge(
    "sonoro_quota_remaining",
    "Remaining quota by user and action type",
    ["user_id", "action_type"],
    registry=metrics_registry,
)

quota_usage_percentage = Gauge(
    "sonoro_quota_usage_percentage",
    "Quota usage percentage by user and action type",
    ["user_id", "action_type"],
    registry=metrics_registry,
)

quota_exceeded_total = Counter(
    "sonoro_quota_exceeded_total",
    "Total quota exceeded events",
    ["user_id", "action_type"],
    registry=metrics_registry,
)

quota_resets_total = Counter(
    "sonoro_quota_resets_total",
    "Total quota period resets",
    ["user_id"],
    registry=metrics_registry,
)

# ============================================
# RATE LIMIT METRICS
# ============================================

rate_limit_exceeded_total = Counter(
    "sonoro_rate_limit_exceeded_total",
    "Total rate limit exceeded events",
    ["tier", "window"],
    registry=metrics_registry,
)

rate_limit_requests_total = Counter(
    "sonoro_rate_limit_requests_total",
    "Total rate limit checks performed",
    ["tier"],
    registry=metrics_registry,
)

# ============================================
# RUNTIME PROTECTION METRICS
# ============================================

cost_cap_exceeded_total = Counter(
    "sonoro_cost_cap_exceeded_total",
    "Total times cost cap was exceeded",
    ["cap_type"],
    registry=metrics_registry,
)

emergency_shutdown_triggered = Counter(
    "sonoro_emergency_shutdown_triggered_total",
    "Emergency shutdown trigger events",
    ["reason"],
    registry=metrics_registry,
)

# ============================================
# ACCOUNT DOMAIN METRICS
# ============================================

account_overview_requests_total = Counter(
    "sonoro_account_overview_requests_total",
    "Total account overview requests",
    ["plan_tier"],
    registry=metrics_registry,
)

usage_requests_total = Counter(
    "sonoro_usage_requests_total",
    "Total usage endpoint requests",
    ["plan_tier"],
    registry=metrics_registry,
)

activity_requests_total = Counter(
    "sonoro_activity_requests_total",
    "Total activity endpoint requests",
    registry=metrics_registry,
)

settings_updates_total = Counter(
    "sonoro_settings_updates_total",
    "Total settings update operations",
    registry=metrics_registry,
)

plan_simulations_total = Counter(
    "sonoro_plan_simulations_total",
    "Total plan upgrade simulations",
    ["current_tier", "target_tier"],
    registry=metrics_registry,
)

account_health_status = Gauge(
    "sonoro_account_health_status",
    "Account health status (1=healthy, 0=unhealthy)",
    ["user_id"],
    registry=metrics_registry,
)

# ============================================
# DOCUMENT STORAGE METRICS (BLOCK 5A)
# ============================================

documents_uploaded_total = Counter(
    "sonoro_documents_uploaded_total",
    "Total documents successfully uploaded",
    ["user_plan_tier"],
    registry=metrics_registry,
)

documents_failed_total = Counter(
    "sonoro_documents_failed_total",
    "Total document upload failures",
    ["failure_reason"],
    registry=metrics_registry,
)

documents_bytes_uploaded = Counter(
    "sonoro_documents_bytes_uploaded",
    "Total bytes uploaded to storage",
    ["user_plan_tier"],
    registry=metrics_registry,
)

documents_processing_status_total = Gauge(
    "sonoro_documents_processing_status_total",
    "Document count by processing status",
    ["processing_status"],
    registry=metrics_registry,
)

upload_latency_seconds = Histogram(
    "sonoro_upload_latency_seconds",
    "Document upload latency in seconds",
    ["operation"],
    buckets=[0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0],
    registry=metrics_registry,
)

documents_deleted_total = Counter(
    "sonoro_documents_deleted_total",
    "Total documents deleted",
    ["user_plan_tier"],
    registry=metrics_registry,
)

download_url_generated_total = Counter(
    "sonoro_download_url_generated_total",
    "Total download URLs generated",
    registry=metrics_registry,
)

# ============================================
# PROCESSING ORCHESTRATION METRICS (BLOCK 5B)
# ============================================

processing_jobs_total = Counter(
    "sonoro_processing_jobs_total",
    "Total processing jobs by status",
    ["status"],
    registry=metrics_registry,
)

processing_failures_total = Counter(
    "sonoro_processing_failures_total",
    "Total processing job failures",
    ["failure_reason"],
    registry=metrics_registry,
)

processing_job_duration_seconds = Histogram(
    "sonoro_processing_job_duration_seconds",
    "Processing job duration in seconds",
    ["job_type"],
    buckets=[10, 30, 60, 120, 300, 600, 1800, 3600],
    registry=metrics_registry,
)

processing_queue_depth = Gauge(
    "sonoro_processing_queue_depth",
    "Number of jobs in processing queue",
    registry=metrics_registry,
)

processing_active_jobs = Gauge(
    "sonoro_processing_active_jobs",
    "Number of currently active processing jobs",
    registry=metrics_registry,
)

processing_retry_count = Counter(
    "sonoro_processing_retry_count",
    "Total processing job retries",
    ["job_type"],
    registry=metrics_registry,
)

# ============================================
# CHAPTER DETECTION METRICS (BLOCK 6B)
# ============================================

chapters_detected_total = Counter(
    "sonoro_chapters_detected_total",
    "Total chapters detected",
    ["detection_method"],
    registry=metrics_registry,
)

chapter_detection_confidence = Histogram(
    "sonoro_chapter_detection_confidence",
    "Chapter detection confidence scores",
    ["detection_method"],
    buckets=[0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 0.95, 1.0],
    registry=metrics_registry,
)

text_chunks_generated_total = Counter(
    "sonoro_text_chunks_generated_total",
    "Total text chunks generated for TTS",
    registry=metrics_registry,
)

segmentation_latency_seconds = Histogram(
    "sonoro_segmentation_latency_seconds",
    "Text segmentation latency in seconds",
    buckets=[0.1, 0.5, 1.0, 2.0, 5.0, 10.0],
    registry=metrics_registry,
)

document_structure_analysis_duration = Histogram(
    "sonoro_document_structure_analysis_duration_seconds",
    "Document structure analysis duration",
    buckets=[1, 5, 10, 30, 60, 120, 300],
    registry=metrics_registry,
)

# ============================================
# AUDIO ASSEMBLY METRICS (BLOCK 6C)
# ============================================

audio_assembly_duration_seconds = Histogram(
    "sonoro_audio_assembly_seconds",
    "Audio assembly (concatenation) duration in seconds",
    buckets=[1, 5, 10, 30, 60, 120, 300, 600],
    registry=metrics_registry,
)

audio_file_size_bytes = Histogram(
    "sonoro_audio_file_size_bytes",
    "Final audiobook file size in bytes",
    buckets=[1_000_000, 5_000_000, 10_000_000, 50_000_000, 100_000_000, 500_000_000, 1_000_000_000],
    registry=metrics_registry,
)

full_audiobook_generated_total = Counter(
    "sonoro_full_audiobook_generated_total",
    "Total full audiobooks generated successfully",
    registry=metrics_registry,
)

audio_normalization_duration_seconds = Histogram(
    "sonoro_audio_normalization_seconds",
    "Audio normalization duration in seconds",
    buckets=[1, 5, 10, 30, 60, 120, 300],
    registry=metrics_registry,
)

audio_metadata_write_duration_seconds = Histogram(
    "sonoro_audio_metadata_write_seconds",
    "Audio metadata writing duration in seconds",
    buckets=[0.1, 0.5, 1.0, 2.0, 5.0, 10.0],
    registry=metrics_registry,
)

# ============================================
# BILLING & REVENUE METRICS (BLOCK 7)
# ============================================

revenue_total = Counter(
    "sonoro_revenue_total",
    "Total revenue collected in USD",
    ["plan_tier", "interval"],
    registry=metrics_registry,
)

active_subscriptions_total = Gauge(
    "sonoro_active_subscriptions_total",
    "Total active subscriptions by plan tier",
    ["plan_tier"],
    registry=metrics_registry,
)

mrr = Gauge(
    "sonoro_mrr",
    "Monthly Recurring Revenue in USD by plan tier",
    ["plan_tier"],
    registry=metrics_registry,
)

subscription_events_total = Counter(
    "sonoro_subscription_events_total",
    "Total subscription events",
    ["event_type"],
    registry=metrics_registry,
)

payment_failures_total = Counter(
    "sonoro_payment_failures_total",
    "Total payment failures",
    ["failure_reason"],
    registry=metrics_registry,
)

subscription_churn_total = Counter(
    "sonoro_subscription_churn_total",
    "Total subscription cancellations",
    ["plan_tier", "reason"],
    registry=metrics_registry,
)

checkout_sessions_created = Counter(
    "sonoro_checkout_sessions_created_total",
    "Total checkout sessions created",
    ["plan_tier"],
    registry=metrics_registry,
)

checkout_sessions_completed = Counter(
    "sonoro_checkout_sessions_completed_total",
    "Total checkout sessions completed",
    ["plan_tier"],
    registry=metrics_registry,
)

subscription_upgrades_total = Counter(
    "sonoro_subscription_upgrades_total",
    "Total subscription upgrades",
    ["from_tier", "to_tier"],
    registry=metrics_registry,
)

subscription_downgrades_total = Counter(
    "sonoro_subscription_downgrades_total",
    "Total subscription downgrades",
    ["from_tier", "to_tier"],
    registry=metrics_registry,
)

trial_conversions_total = Counter(
    "sonoro_trial_conversions_total",
    "Total trial to paid conversions",
    ["plan_tier"],
    registry=metrics_registry,
)

customer_lifetime_value = Histogram(
    "sonoro_customer_lifetime_value_usd",
    "Customer lifetime value in USD",
    ["plan_tier"],
    buckets=[10, 50, 100, 250, 500, 1000, 2500, 5000, 10000],
    registry=metrics_registry,
)

# ============================================
# BLOCK 8E: User Settings & Account Management Metrics
# ============================================

password_changes_total = Counter(
    "sonoro_password_changes_total",
    "Total password change operations",
    registry=metrics_registry,
)

account_deletions_total = Counter(
    "sonoro_account_deletions_total",
    "Total account deletions (soft delete)",
    registry=metrics_registry,
)

api_keys_generated_total = Counter(
    "sonoro_api_keys_generated_total",
    "Total API keys generated",
    registry=metrics_registry,
)

api_keys_revoked_total = Counter(
    "sonoro_api_keys_revoked_total",
    "Total API keys revoked",
    registry=metrics_registry,
)

profile_updates_total = Counter(
    "sonoro_profile_updates_total",
    "Total profile update operations",
    registry=metrics_registry,
)

# ============================================
