"""
Root conftest — runs BEFORE tests/conftest.py imports any app module.

Why this file exists
--------------------
app.core.config executes `settings = get_settings()` at module level.
get_settings() calls Settings() which validates all required fields
immediately.  Without this file, importing any app module in tests
crashes with a pydantic ValidationError because no .env file or
environment variables exist in the local test environment.

Strategy: set every required field in os.environ using setdefault()
BEFORE tests/conftest.py triggers the first app import.  setdefault()
does NOT override values that CI or a developer has already exported,
so this file is safe to commit and causes zero production side-effects.
"""

import os

_DEFAULTS: dict[str, str] = {
    # Minimum required by pydantic Settings (all Field(...) fields)
    "SECRET_KEY": "test-only-secret-key-do-not-use-in-production-32chars!",
    "DATABASE_URL": (
        "postgresql://sonoro:sonoro_dev_password@localhost:5432/sonoro_test"
    ),
    "DATABASE_ASYNC_URL": (
        "postgresql+asyncpg://sonoro:sonoro_dev_password@localhost:5432/sonoro_test"
    ),
    "REDIS_URL": "redis://localhost:6379/0",
    "CELERY_BROKER_URL": "redis://localhost:6379/0",
    "CELERY_RESULT_BACKEND": "redis://localhost:6379/0",
    # Informational — lets the app know it's running under pytest
    "APP_ENV": "test",
    "DEBUG": "false",
}

for _key, _value in _DEFAULTS.items():
    os.environ.setdefault(_key, _value)
