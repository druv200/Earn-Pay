"""Environment-separated configuration for Earn & Pay."""

from __future__ import annotations

import os
from datetime import timedelta
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

INSECURE_DEFAULT_SECRET_KEY = "dev-only-unsafe-secret-key-change-before-production"  # noqa: S105


def normalize_database_uri(uri: str) -> str:
    """Ensure PostgreSQL connection strings explicitly use the Psycopg 3 driver."""
    cleaned = uri.strip()
    if cleaned.startswith("postgres://"):
        return cleaned.replace("postgres://", "postgresql+psycopg://", 1)
    if cleaned.startswith("postgresql://"):
        return cleaned.replace("postgresql://", "postgresql+psycopg://", 1)
    return cleaned


class Config:
    """Base configuration shared across environments."""

    APP_NAME: str = "Earn & Pay"
    LAUNCH_CITY: str = os.getenv("LAUNCH_CITY", "Bengaluru")
    LAUNCH_COUNTRY: str = os.getenv("LAUNCH_COUNTRY", "India")
    DEFAULT_CURRENCY: str = os.getenv("DEFAULT_CURRENCY", "INR")

    SECRET_KEY: str = os.getenv("SECRET_KEY", INSECURE_DEFAULT_SECRET_KEY)

    SQLALCHEMY_TRACK_MODIFICATIONS: bool = False
    SQLALCHEMY_ENGINE_OPTIONS: dict[str, object] = {
        "pool_pre_ping": True,
        "pool_recycle": 300,
    }

    # Session & Cookie Security
    SESSION_COOKIE_HTTPONLY: bool = True
    SESSION_COOKIE_SAMESITE: str = os.getenv("SESSION_COOKIE_SAMESITE", "Lax")
    SESSION_COOKIE_SECURE: bool = os.getenv("SESSION_COOKIE_SECURE", "false").lower() == "true"
    REMEMBER_COOKIE_HTTPONLY: bool = True
    REMEMBER_COOKIE_SAMESITE: str = "Lax"
    PERMANENT_SESSION_LIFETIME: timedelta = timedelta(
        minutes=int(os.getenv("PERMANENT_SESSION_LIFETIME_MINUTES", "120"))
    )

    # CSRF Protection
    WTF_CSRF_ENABLED: bool = True
    WTF_CSRF_TIME_LIMIT: int = 3600

    # File Upload Restrictions
    MAX_CONTENT_LENGTH: int = int(os.getenv("MAX_CONTENT_LENGTH", str(5 * 1024 * 1024)))
    UPLOAD_FOLDER: str = str(BASE_DIR / os.getenv("UPLOAD_FOLDER", "instance/uploads"))
    ALLOWED_UPLOAD_EXTENSIONS: frozenset[str] = frozenset({"png", "jpg", "jpeg", "webp", "pdf"})

    # Rate Limiting
    RATELIMIT_ENABLED: bool = os.getenv("RATELIMIT_ENABLED", "true").lower() == "true"
    RATELIMIT_STORAGE_URI: str = os.getenv("RATELIMIT_STORAGE_URI", "memory://")

    @classmethod
    def validate(cls) -> None:
        """Perform environment-specific sanity checks on startup."""


class DevelopmentConfig(Config):
    """Local development configuration."""

    ENV_NAME: str = "development"
    DEBUG: bool = True
    TESTING: bool = False
    SQLALCHEMY_DATABASE_URI: str = normalize_database_uri(
        os.getenv(
            "DATABASE_URL",
            "postgresql+psycopg://postgres:postgres@localhost:5432/earn_and_pay_dev",
        )
    )


class TestingConfig(Config):
    """Isolated automated test configuration."""

    ENV_NAME: str = "testing"
    DEBUG: bool = False
    TESTING: bool = True
    WTF_CSRF_ENABLED: bool = True
    RATELIMIT_ENABLED: bool = False
    SESSION_COOKIE_SECURE: bool = False
    SQLALCHEMY_DATABASE_URI: str = normalize_database_uri(
        os.getenv(
            "TEST_DATABASE_URL",
            "postgresql+psycopg://postgres:postgres@localhost:5432/earn_and_pay_test",
        )
    )


class ProductionConfig(Config):
    """Hardened production configuration."""

    ENV_NAME: str = "production"
    DEBUG: bool = False
    TESTING: bool = False
    SESSION_COOKIE_SECURE: bool = True
    REMEMBER_COOKIE_SECURE: bool = True
    SQLALCHEMY_DATABASE_URI: str = normalize_database_uri(os.getenv("DATABASE_URL", ""))

    @classmethod
    def validate(cls) -> None:
        """Fail fast if production secrets or database settings are unsafe."""
        if not cls.SECRET_KEY or cls.SECRET_KEY in {
            INSECURE_DEFAULT_SECRET_KEY,
            "replace-with-a-64-char-cryptographically-random-hex-string",
        }:
            msg = "ProductionConfig requires a strong, unique SECRET_KEY environment variable."
            raise RuntimeError(msg)
        if len(cls.SECRET_KEY) < 32:
            msg = "Production SECRET_KEY must be at least 32 characters long."
            raise RuntimeError(msg)
        if not cls.SQLALCHEMY_DATABASE_URI.startswith("postgresql+psycopg://"):
            msg = "ProductionConfig requires a valid PostgreSQL DATABASE_URL."
            raise RuntimeError(msg)


CONFIG_BY_NAME: dict[str, type[Config]] = {
    "development": DevelopmentConfig,
    "testing": TestingConfig,
    "production": ProductionConfig,
}


def get_config(config_name: str | None = None) -> type[Config]:
    """Resolve configuration class by explicit name or FLASK_ENV."""
    resolved = (config_name or os.getenv("FLASK_ENV", "development")).strip().lower()
    if resolved not in CONFIG_BY_NAME:
        valid = ", ".join(sorted(CONFIG_BY_NAME))
        msg = f"Unknown configuration '{resolved}'. Expected one of: {valid}"
        raise ValueError(msg)
    return CONFIG_BY_NAME[resolved]
