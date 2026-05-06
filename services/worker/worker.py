"""
Celery Worker Entrypoint
=========================
BLOCK 5B: Processing Orchestration Layer

Real Celery worker implementation.
No longer a placeholder - this is production-ready orchestration.
"""

import os
import sys
import logging

# Add parent directory to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'api'))

from app.celery_app import celery_app
from app.core.logging_config import setup_logging

# Setup logging
setup_logging()
logger = logging.getLogger(__name__)

logger.info("Celery worker starting...")
logger.info(f"Broker URL: {celery_app.conf.broker_url}")
logger.info(f"Result backend: {celery_app.conf.result_backend}")

# Import tasks to register them
from app.tasks import processing  # noqa

logger.info("Tasks imported and registered")

if __name__ == "__main__":
    # Start worker
    celery_app.start()
