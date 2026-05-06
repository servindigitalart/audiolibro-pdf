"""
Metrics Router
==============
Prometheus metrics endpoint.
"""

from fastapi import APIRouter, Response
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST

from app.monitoring.metrics import metrics_registry

router = APIRouter(tags=["metrics"])


@router.get(
    "/metrics",
    summary="Prometheus metrics",
    description="Prometheus-compatible metrics endpoint",
    response_class=Response,
)
async def metrics() -> Response:
    """
    Expose Prometheus metrics.
    
    This endpoint returns metrics in Prometheus text format.
    Configure Prometheus to scrape this endpoint.
    
    Example Prometheus configuration:
    ```yaml
    scrape_configs:
      - job_name: 'sonoro-api'
        static_configs:
          - targets: ['api:8000']
        metrics_path: '/metrics'
    ```
    """
    # Generate metrics in Prometheus format
    data = generate_latest(metrics_registry)
    
    return Response(
        content=data,
        media_type=CONTENT_TYPE_LATEST,
    )
