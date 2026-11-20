"""Environment-separated configuration for Earn & Pay."""

from __future__ import annotations

import os
from collections.abc import Mapping
from datetime import timedelta
from pathlib import Path
from urllib.parse import urlparse

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


def _comma_separated_values(value: str) -> list[str] | None:
    """Return a cleaned list for a comma-separated environment variable."""
    values = [item.strip() for item in value.split(",") if item.strip()]
    return values or None


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

    # Reverse proxy and host validation. Keep these off for local development,
    # but make the production requirements explicit below.
    TRUST_PROXY_COUNT: int = int(os.getenv("TRUST_PROXY_COUNT", "0"))
    TRUSTED_HOSTS: list[str] | None = _comma_separated_values(os.getenv("TRUSTED_HOSTS", ""))
    PREFERRED_URL_SCHEME: str = os.getenv("PREFERRED_URL_SCHEME", "http")

    # Transactional email is delivered through Resend's HTTPS API. This avoids
    # SMTP ports, which many free hosting plans block.
    EMAIL_BACKEND: str = os.getenv("EMAIL_BACKEND", "console").strip().lower()
    EMAIL_FROM: str = os.getenv("EMAIL_FROM", "")
    RESEND_API_KEY: str = os.getenv("RESEND_API_KEY", "")
    PUBLIC_BASE_URL: str = os.getenv("PUBLIC_BASE_URL", "http://localhost:5000").rstrip("/")

    @classmethod
    def validate(cls, values: Mapping[str, object] | None = None) -> None:
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
    PREFERRED_URL_SCHEME: str = "https"
    SESSION_COOKIE_SECURE: bool = True
    REMEMBER_COOKIE_SECURE: bool = True
    SQLALCHEMY_DATABASE_URI: str = normalize_database_uri(os.getenv("DATABASE_URL", ""))

    @classmethod
    def validate(cls, values: Mapping[str, object] | None = None) -> None:
        """Fail fast if production secrets or database settings are unsafe."""
        source = values if values is not None else cls.__dict__

        def value(name: str, default: object = "") -> object:
            return source.get(name, getattr(cls, name, default))

        secret_key = value("SECRET_KEY")
        database_uri = value("SQLALCHEMY_DATABASE_URI")
        email_backend = value("EMAIL_BACKEND")
        email_from = value("EMAIL_FROM")
        resend_api_key = value("RESEND_API_KEY")
        public_base_url = value("PUBLIC_BASE_URL")
        trusted_hosts = value("TRUSTED_HOSTS")
        proxy_count = value("TRUST_PROXY_COUNT", 0)
        rate_limit_storage = value("RATELIMIT_STORAGE_URI")

        if not isinstance(secret_key, str) or not secret_key or secret_key in {
            INSECURE_DEFAULT_SECRET_KEY,
            "replace-with-a-64-char-cryptographically-random-hex-string",
        }:
            msg = "ProductionConfig requires a strong, unique SECRET_KEY environment variable."
            raise RuntimeError(msg)
        if len(secret_key) < 32:
            msg = "Production SECRET_KEY must be at least 32 characters long."
            raise RuntimeError(msg)
        if not isinstance(database_uri, str) or not database_uri.startswith("postgresql+psycopg://"):
            msg = "ProductionConfig requires a valid PostgreSQL DATABASE_URL."
            raise RuntimeError(msg)
        if email_backend != "resend":
            msg = "ProductionConfig requires EMAIL_BACKEND=resend."
            raise RuntimeError(msg)
        if not isinstance(email_from, str) or "@" not in email_from:
            msg = "ProductionConfig requires a valid EMAIL_FROM address."
            raise RuntimeError(msg)
        if not isinstance(resend_api_key, str) or not resend_api_key.strip():
            msg = "ProductionConfig requires RESEND_API_KEY."
            raise RuntimeError(msg)
        if not isinstance(public_base_url, str):
            msg = "ProductionConfig requires an HTTPS PUBLIC_BASE_URL."
            raise RuntimeError(msg)
        parsed_base_url = urlparse(public_base_url)
        if parsed_base_url.scheme != "https" or not parsed_base_url.netloc:
            msg = "ProductionConfig requires an HTTPS PUBLIC_BASE_URL."
            raise RuntimeError(msg)
        if not isinstance(trusted_hosts, list | tuple) or not trusted_hosts:
            msg = "ProductionConfig requires at least one TRUSTED_HOSTS entry."
            raise RuntimeError(msg)
        if not isinstance(proxy_count, int) or proxy_count < 1:
            msg = "ProductionConfig requires TRUST_PROXY_COUNT to be at least 1."
            raise RuntimeError(msg)
        if not isinstance(rate_limit_storage, str) or rate_limit_storage.startswith("memory://"):
            msg = "ProductionConfig requires a shared RATELIMIT_STORAGE_URI."
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
