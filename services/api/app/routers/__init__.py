"""
API Routers
===========
FastAPI route modules.
"""

from app.routers.health import router as health_router
from app.routers.auth import router as auth_router
from app.routers.metrics import router as metrics_router
from app.routers.admin import router as admin_router
from app.routers.billing import router as billing_router

__all__ = ["health_router", "auth_router", "metrics_router", "admin_router", "billing_router"]
