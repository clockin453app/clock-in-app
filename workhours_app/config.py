"""Configuration values re-exported from the shared core module.

This keeps the runtime behavior identical to the original app while providing
a dedicated import path for configuration consumers.
"""

from workhours_app.core import (
    APP_ENV,
    DEBUG_MODE,
    IS_PRODUCTION,
    DATABASE_URL,
    DATABASE_ENABLED,
    DB_DEBUG_EXPORTS_ENABLED,
    DESTRUCTIVE_ADMIN_CONFIRM_VALUE,
    MAX_CLOCK_LOCATION_ACCURACY_M,
    MAX_CLOCK_LOCATION_AGE_S,
    BASE_DIR,
    TZ,
)

__all__ = [
    "APP_ENV",
    "DEBUG_MODE",
    "IS_PRODUCTION",
    "DATABASE_URL",
    "DATABASE_ENABLED",
    "DB_DEBUG_EXPORTS_ENABLED",
    "DESTRUCTIVE_ADMIN_CONFIRM_VALUE",
    "MAX_CLOCK_LOCATION_ACCURACY_M",
    "MAX_CLOCK_LOCATION_AGE_S",
    "BASE_DIR",
    "TZ",
]
