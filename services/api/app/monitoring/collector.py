"""
Background Metrics Collector
=============================
Periodic collection of infrastructure metrics (DB, Redis, etc.)
"""

import asyncio
import time
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncEngine

from app.core import get_logger
from app.core.redis import get_redis
from app.monitoring.metrics import (
    db_connection_pool_size,
    db_connection_pool_overflow,
    db_connection_pool_checked_out,
    redis_connection_status,
    redis_latency_seconds,
)

logger = get_logger(__name__)


class MetricsCollector:
    """
    Background task to collect infrastructure metrics periodically.
    """

    def __init__(
        self,
        db_engine: Optional[AsyncEngine] = None,
        collection_interval: int = 15,  # seconds
    ):
        """
        Initialize metrics collector.
        
        Args:
            db_engine: SQLAlchemy async engine for DB metrics
            collection_interval: How often to collect metrics (seconds)
        """
        self.db_engine = db_engine
        self.collection_interval = collection_interval
        self._task: Optional[asyncio.Task] = None
        self._running = False

    async def start(self) -> None:
        """Start the background metrics collection task."""
        if self._running:
            logger.warning("Metrics collector already running")
            return

        self._running = True
        self._task = asyncio.create_task(self._collect_loop())
        logger.info(
            f"✅ Metrics collector started (interval={self.collection_interval}s)"
        )

    async def stop(self) -> None:
        """Stop the background metrics collection task."""
        if not self._running:
            return

        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

        logger.info("Metrics collector stopped")

    async def _collect_loop(self) -> None:
        """Main collection loop."""
        while self._running:
            try:
                await self._collect_metrics()
            except Exception as e:
                logger.error(f"Error collecting metrics: {e}", exc_info=True)

            # Wait for next collection interval
            await asyncio.sleep(self.collection_interval)

    async def _collect_metrics(self) -> None:
        """Collect all metrics."""
        # Collect DB metrics
        if self.db_engine:
            await self._collect_db_metrics()

        # Collect Redis metrics
        await self._collect_redis_metrics()

    async def _collect_db_metrics(self) -> None:
        """Collect database connection pool metrics."""
        try:
            if not self.db_engine:
                return

            pool = self.db_engine.pool

            # Pool size metrics
            db_connection_pool_size.set(pool.size())
            db_connection_pool_overflow.set(pool.overflow())
            db_connection_pool_checked_out.set(pool.checkedout())

            logger.debug(
                f"DB pool metrics: size={pool.size()}, "
                f"overflow={pool.overflow()}, "
                f"checked_out={pool.checkedout()}"
            )

        except Exception as e:
            logger.error(f"Failed to collect DB metrics: {e}")

    async def _collect_redis_metrics(self) -> None:
        """Collect Redis connection and latency metrics."""
        try:
            if not await get_redis():
                redis_connection_status.set(0)
                return

            # Measure Redis latency with PING
            start_time = time.time()
            await (await get_redis()).ping()
            latency = time.time() - start_time

            redis_connection_status.set(1)  # Connected
            redis_latency_seconds.set(latency)

            logger.debug(f"Redis metrics: latency={latency:.4f}s, status=connected")

        except Exception as e:
            logger.error(f"Failed to collect Redis metrics: {e}")
            redis_connection_status.set(0)  # Disconnected
