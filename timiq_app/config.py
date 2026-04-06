import os
from pathlib import Path


def env_flag(name: str, default: bool = False) -> bool:
    val = os.environ.get(name)
    if val is None:
        return default
    return str(val).strip().lower() in {"1", "true", "yes", "on"}


def is_sqlite_url(url: str) -> bool:
    return str(url or "").strip().lower().startswith("sqlite:")


def normalize_database_url(url: str) -> str:
    url = (url or "").strip()
    if url.startswith("postgres://"):
        return "postgresql://" + url[len("postgres://"):]
    return url


class Settings:
    BASE_DIR = Path(__file__).resolve().parent.parent

    APP_ENV = os.environ.get("APP_ENV", os.environ.get("FLASK_ENV", "production")).strip().lower() or "production"
    DEBUG_MODE = env_flag("FLASK_DEBUG", default=False) or env_flag("APP_DEBUG", default=False)
    IS_PRODUCTION = APP_ENV == "production" and not DEBUG_MODE

    SECRET_KEY = os.environ.get("SECRET_KEY", "").strip()
    if not SECRET_KEY:
        raise RuntimeError("SECRET_KEY environment variable must be set (do not use a default in production).")

    MAX_CONTENT_LENGTH = int(os.environ.get("MAX_UPLOAD_MB", "15")) * 1024 * 1024
    PREFERRED_URL_SCHEME = "https" if IS_PRODUCTION else "http"

    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = env_flag("SESSION_COOKIE_SECURE", default=IS_PRODUCTION)

    DATABASE_URL = normalize_database_url(os.environ.get("DATABASE_URL", ""))
    DATABASE_ENABLED = (
        env_flag("DATABASE")
        or env_flag("USE_DATABASE")
        or env_flag("DB_MIGRATION_MODE")
    )
    USE_DATABASE = DATABASE_ENABLED
    DB_MIGRATION_MODE = DATABASE_ENABLED

    if DATABASE_ENABLED and not DATABASE_URL:
        raise RuntimeError(
            "DATABASE_ENABLED is on but DATABASE_URL is not set. Refusing to fall back to in-memory SQLite."
        )

    SQLALCHEMY_DATABASE_URI = DATABASE_URL if DATABASE_URL else "sqlite:///:memory:"
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    if DATABASE_URL and not is_sqlite_url(DATABASE_URL):
        SQLALCHEMY_ENGINE_OPTIONS = {
            "pool_pre_ping": True,
            "pool_recycle": int(os.environ.get("DB_POOL_RECYCLE", "1800")),
            "pool_size": int(os.environ.get("DB_POOL_SIZE", "5")),
            "max_overflow": int(os.environ.get("DB_MAX_OVERFLOW", "10")),
        }

    TZ_NAME = os.environ.get("APP_TZ", "Europe/London")
    DB_DEBUG_EXPORTS_ENABLED = env_flag("DB_DEBUG_EXPORTS_ENABLED", default=not IS_PRODUCTION)
    DESTRUCTIVE_ADMIN_CONFIRM_VALUE = os.environ.get("DESTRUCTIVE_ADMIN_CONFIRM_VALUE", "CONFIRM").strip() or "CONFIRM"
    MAX_CLOCK_LOCATION_ACCURACY_M = float(
        os.environ.get("MAX_CLOCK_LOCATION_ACCURACY_M", os.environ.get("CLOCK_GEO_MAX_ACCURACY_METERS", "250")) or "250"
    )
    MAX_CLOCK_LOCATION_AGE_S = int(
        os.environ.get("MAX_CLOCK_LOCATION_AGE_S", os.environ.get("CLOCK_GEO_MAX_AGE_SECONDS", "180")) or "180"
    )
    ALLOWED_EMPLOYEE_ROLES = {"employee", "admin"}
