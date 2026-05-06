"""
Sonoro API - Main Application
==============================
FastAPI application for document-to-audiobook SaaS platform.
"""

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse

from app.core import settings, setup_logging, get_logger
from app.core.redis import init_redis, close_redis
from app.db import init_db, close_db, engine
from app.routers import health_router, auth_router
from app.monitoring.middleware import MetricsMiddleware
from app.monitoring.sentry import init_sentry
from app.monitoring.collector import MetricsCollector

# Setup logging first
setup_logging()
logger = get_logger(__name__)

# Initialize metrics collector
_metrics_collector: MetricsCollector = None


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator:
    """
    Application lifespan manager.
    Handles startup and shutdown events.
    """
    global _metrics_collector
    
    # Startup
    logger.info("Starting Sonoro API...")
    logger.info(f"Environment: {settings.app_env}")
    logger.info(f"Debug mode: {settings.debug}")

    try:
        # Initialize Sentry (error tracking)
        if settings.sentry_dsn:
            init_sentry(
                dsn=settings.sentry_dsn,
                environment=settings.app_env,
                release="0.9.0",  # BLOCK 7: Billing & Monetization Layer
                traces_sample_rate=settings.sentry_traces_sample_rate,
                profiles_sample_rate=settings.sentry_profiles_sample_rate,
            )
        
        # Initialize database
        await init_db()

        # Initialize Redis
        await init_redis()
        
        # Start metrics collector
        _metrics_collector = MetricsCollector(
            db_engine=engine,
            collection_interval=settings.metrics_collection_interval,
        )
        await _metrics_collector.start()

        logger.info("✅ All services initialized successfully")
        yield
    except Exception as e:
        logger.error(f"Failed to initialize services: {e}")
        raise
    finally:
        # Shutdown
        logger.info("Shutting down Sonoro API...")
        
        # Stop metrics collector
        if _metrics_collector:
            await _metrics_collector.stop()
        
        await close_redis()
        await close_db()
        logger.info("✅ Shutdown complete")


# Create FastAPI application
app = FastAPI(
    title="Sonoro API",
    description="Professional document-to-audiobook SaaS platform",
    version="0.9.0",  # BLOCK 7: Billing & Monetization Layer
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    lifespan=lifespan,
    debug=settings.debug,
)

# Add Metrics Middleware (first, to capture all requests)
app.add_middleware(MetricsMiddleware)

# CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# GZip Middleware for response compression
app.add_middleware(GZipMiddleware, minimum_size=1000)


# Exception Handlers
@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    """Global exception handler for unhandled errors."""
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    
    # Capture in Sentry if available
    try:
        from app.monitoring.sentry import capture_exception
        capture_exception(exc, level="error")
    except Exception:
        pass
    
    return JSONResponse(
        status_code=500,
        content={
            "detail": "Internal server error",
            "type": "internal_server_error",
        },
    )


# Include routers
from app.routers.metrics import router as metrics_router
from app.routers.admin import router as admin_router
from app.routers.admin_financial import router as admin_financial_router
from app.routers.account import router as account_router
from app.routers.documents import router as documents_router  # BLOCK 5A
from app.routers.processing import router as processing_router  # BLOCK 5B
from app.routers.billing import router as billing_router  # BLOCK 7

app.include_router(metrics_router)  # Prometheus metrics endpoint
app.include_router(health_router)
app.include_router(auth_router)
app.include_router(admin_router)  # Admin runtime introspection
app.include_router(admin_financial_router)  # Admin financial management
app.include_router(account_router)  # Account & user experience
app.include_router(documents_router)  # Document upload & storage
app.include_router(processing_router)  # Processing orchestration
app.include_router(billing_router)  # Billing & subscriptions


# Startup event log
@app.on_event("startup")
async def startup_event():
    """Log startup completion."""
    logger.info("🚀 Sonoro API is ready to accept requests")
    logger.info(f"📚 API Documentation: http://{settings.api_host}:{settings.api_port}/docs")


# Root endpoint (will be removed in production, handled by health router)
@app.get("/", include_in_schema=False)
async def redirect_to_docs():
    """Redirect root to documentation."""
    return {
        "message": "Welcome to Sonoro API",
        "docs": "/docs",
        "health": "/api/v1/health",
    }


