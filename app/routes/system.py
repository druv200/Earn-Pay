"""System liveness and database readiness endpoints."""

from __future__ import annotations

from datetime import UTC, datetime

from flask import Blueprint, current_app, jsonify

from app.models import verify_database_connection

system_bp = Blueprint("system", __name__)


@system_bp.get("/health")
def health_check():
    """Application process liveness probe for load balancers and uptime monitors."""
    return (
        jsonify(
            {
                "status": "ok",
                "service": "earn-and-pay",
                "environment": current_app.config.get("ENV_NAME", "unknown"),
                "timestamp": datetime.now(UTC).isoformat(),
            }
        ),
        200,
    )


@system_bp.get("/health/db")
def database_health_check():
    """Database connectivity probe executing `SELECT 1` via SQLAlchemy."""
    is_healthy, detail = verify_database_connection()
    status_code = 200 if is_healthy else 503
    return (
        jsonify(
            {
                "status": "ok" if is_healthy else "degraded",
                "database": detail,
                "timestamp": datetime.now(UTC).isoformat(),
            }
        ),
        status_code,
    )
