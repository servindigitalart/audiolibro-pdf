"""
Celery Application Configuration
=================================
BLOCK 5B: Processing Orchestration Layer

Enterprise-grade Celery configuration for document processing pipeline.
Pure orchestration infrastructure - no TTS business logic.
"""

import logging
from celery import Celery
from celery.signals import task_prerun, task_postrun, task_failure
from kombu import Queue

from app.core.config import settings

logger = logging.getLogger(__name__)


# ============================================
# CELERY APP CONFIGURATION
# ============================================

logger.info("[celery_app] broker=%s", settings.celery_broker_url.split("@")[-1])

celery_app = Celery(
    "sonoro_worker",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=["app.tasks.processing"],
)

# Configure Celery
celery_app.conf.update(
    # Serialization
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    
    # Timezone
    timezone="UTC",
    enable_utc=True,
    
    # Result backend (plain Redis — not Sentinel; master_name removed)
    result_backend_transport_options={
        "socket_keepalive": True,
    },
    result_expires=3600,  # Results expire after 1 hour
    result_persistent=False,
    
    # Task execution
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    task_track_started=True,
    task_time_limit=3600,  # 1 hour hard limit
    task_soft_time_limit=3300,  # 55 minutes soft limit
    
    # Worker
    worker_prefetch_multiplier=1,  # Take one task at a time
    worker_max_tasks_per_child=1000,  # Recycle worker after 1000 tasks
    worker_disable_rate_limits=False,
    
    # Retry policy
    task_default_retry_delay=60,  # 1 minute
    task_max_retries=3,
    
    # Queues configuration (Redis transport — no AMQP exchanges needed)
    task_queues=(
        Queue("high_priority"),
        Queue("normal"),
        Queue("low_priority"),
    ),
    task_default_queue="normal",

    # Disable Redis priority sub-queues. Without this, any apply_async(priority=N)
    # with N>0 would write to a suffixed key (e.g. "normal\x06\x166") that the
    # worker never polls. We route by queue name instead (high_priority/normal/low_priority).
    broker_transport_options={"priority_steps": []},
    
    # Monitoring
    task_send_sent_event=True,
    worker_send_task_events=True,
    
    # Beat (for future scheduled tasks)
    beat_schedule={},
)


# ============================================
# TASK ROUTING
# ============================================

def route_task(name, args, kwargs, options, task=None, **kw):
    """Route tasks to priority queues. Priority 1-3=high, 4-7=normal, 8-10=low."""
    priority = options.get("priority", 5)
    if priority <= 3:
        return {"queue": "high_priority"}
    elif priority >= 8:
        return {"queue": "low_priority"}
    else:
        return {"queue": "normal"}


celery_app.conf.task_routes = (route_task,)


# ============================================
# CELERY SIGNALS
# ============================================

@task_prerun.connect
def task_prerun_handler(sender=None, task_id=None, task=None, args=None, kwargs=None, **extra):
    logger.info("[SONORO] worker_task_received task=%s task_id=%s args=%s", task.name, task_id, args)


@task_postrun.connect
def task_postrun_handler(sender=None, task_id=None, task=None, args=None, kwargs=None, retval=None, state=None, **extra):
    logger.info("[SONORO] worker_task_done task=%s task_id=%s state=%s", task.name, task_id, state)


@task_failure.connect
def task_failure_handler(sender=None, task_id=None, exception=None, args=None, kwargs=None, traceback=None, einfo=None, **extra):
    """Log task failure."""
    logger.error(
        f"Task failed: {sender.name}",
        extra={
            "task_id": task_id,
            "task_name": sender.name,
            "exception": str(exception),
            "args": args,
            "kwargs": kwargs
        },
        exc_info=einfo
    )


# ============================================
# HEALTH CHECK
# ============================================

@celery_app.task(name="health_check")
def health_check():
    """Simple health check task."""
    return {"status": "healthy", "message": "Celery worker is operational"}


# ============================================
# UTILITY FUNCTIONS
# ============================================

def get_queue_depth(queue_name: str = "normal") -> int:
    """
    Get the number of tasks in a queue.
    
    Args:
        queue_name: Name of the queue
        
    Returns:
        Number of tasks in queue
    """
    try:
        inspect = celery_app.control.inspect()
        reserved = inspect.reserved()
        active = inspect.active()
        
        if not reserved and not active:
            return 0
        
        queue_count = 0
        for worker, tasks in (reserved or {}).items():
            queue_count += len([t for t in tasks if t.get("delivery_info", {}).get("routing_key") == queue_name])
        
        for worker, tasks in (active or {}).items():
            queue_count += len([t for t in tasks if t.get("delivery_info", {}).get("routing_key") == queue_name])
        
        return queue_count
    except Exception as e:
        logger.error(f"Failed to get queue depth: {str(e)}")
        return 0


def revoke_task(task_id: str, terminate: bool = False) -> bool:
    """
    Revoke (cancel) a Celery task.
    
    Args:
        task_id: Celery task ID
        terminate: Whether to terminate if already executing
        
    Returns:
        True if revoke command was sent successfully
    """
    try:
        celery_app.control.revoke(task_id, terminate=terminate, signal="SIGTERM")
        logger.info(f"Task revoked: {task_id}")
        return True
    except Exception as e:
        logger.error(f"Failed to revoke task {task_id}: {str(e)}")
        return False
