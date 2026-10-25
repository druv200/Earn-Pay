"""Flask Application Factory for Earn & Pay."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import click
from flask import Flask, Response, jsonify, render_template, request

from app.extensions import csrf, db, limiter, login_manager, migrate
from app.forms.auth_forms import LogoutForm
from app.models import User, verify_database_connection
from app.routes import register_blueprints
from app.services.seed_service import create_or_promote_admin_user, seed_demo_marketplace
from app.utils.security import apply_security_headers
from config import Config, get_config


def create_app(
    config_name: str | None = None,
    config_overrides: dict[str, Any] | None = None,
) -> Flask:
    """Create and configure an instance of the Earn & Pay Flask application."""
    app = Flask(__name__, instance_relative_config=True)

    config_cls: type[Config] = get_config(config_name)
    app.config.from_object(config_cls)
    if config_overrides:
        app.config.update(config_overrides)

    # Validate production safety invariants
    if app.config.get("ENV_NAME") == "production" and not config_overrides:
        config_cls.validate()

    # Ensure instance and upload folders exist safely
    Path(app.instance_path).mkdir(parents=True, exist_ok=True)
    upload_dir = Path(app.config["UPLOAD_FOLDER"])
    upload_dir.mkdir(parents=True, exist_ok=True)

    _configure_logging(app)
    _initialize_extensions(app)
    register_blueprints(app)
    _register_security_hooks(app)
    _register_error_handlers(app)
    _register_cli_commands(app)

    return app


def _configure_logging(app: Flask) -> None:
    """Configure structured, secret-safe application logging."""
    if not app.debug and not app.testing:
        app.logger.setLevel(logging.INFO)


def _initialize_extensions(app: Flask) -> None:
    """Bind SQLAlchemy, Alembic Migrate, Flask-Login, CSRFProtect, and Limiter."""
    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    csrf.init_app(app)
    limiter.init_app(app)

    @login_manager.user_loader
    def load_user(user_id: str) -> User | None:
        """Load active User instance from session user_id."""
        if not user_id or not user_id.isdigit():
            return None
        user = db.session.get(User, int(user_id))
        if user is None or not user.is_active:
            return None
        return user


def _register_security_hooks(app: Flask) -> None:
    """Attach HTTP security headers to all responses."""
    is_prod = app.config.get("ENV_NAME") == "production"

    @app.after_request
    def set_security_headers(response: Response) -> Response:
        return apply_security_headers(response, is_production=is_prod)

    @app.context_processor
    def inject_global_template_context() -> dict[str, Any]:
        return {
            "current_year": datetime.now(UTC).year,
            "logout_form": LogoutForm(),
        }


def _wants_json_response() -> bool:
    """Return True when the client explicitly prefers JSON over HTML."""
    best = request.accept_mimetypes.best_match(["application/json", "text/html"])
    return (
        best == "application/json"
        and request.accept_mimetypes[best] > request.accept_mimetypes["text/html"]
    )


def _register_error_handlers(app: Flask) -> None:
    """Register safe, accessible error handlers for 403, 404, 429, and 500."""

    @app.errorhandler(403)
    def forbidden_error(_error: Exception):
        if _wants_json_response():
            return jsonify({"error": "forbidden", "message": "Access restricted."}), 403
        return render_template("errors/403.html"), 403

    @app.errorhandler(404)
    def not_found_error(_error: Exception):
        if _wants_json_response():
            return jsonify({"error": "not_found", "message": "Resource not found."}), 404
        return render_template("errors/404.html"), 404

    @app.errorhandler(429)
    def too_many_requests_error(_error: Exception):
        if _wants_json_response():
            return (
                jsonify(
                    {
                        "error": "rate_limit_exceeded",
                        "message": "Too many requests. Please wait a moment and try again.",
                    }
                ),
                429,
            )
        return render_template("errors/429.html"), 429

    @app.errorhandler(500)
    def internal_server_error(_error: Exception):
        db.session.rollback()
        if _wants_json_response():
            return jsonify({"error": "internal_server_error", "message": "Unexpected error."}), 500
        return render_template("errors/500.html"), 500


def _register_cli_commands(app: Flask) -> None:
    """Register operational CLI utilities (`db-check`, `create-admin`, `seed-demo`)."""

    @app.cli.command("db-check")
    def db_check_command() -> None:
        """Verify database connection using `SELECT 1`."""
        ok, detail = verify_database_connection()
        if ok:
            click.echo(f"[OK] Database verified: {detail}")
        else:
            click.echo(f"[ERROR] {detail}", err=True)
            raise SystemExit(1)

    @app.cli.command("create-admin")
    @click.option("--email", required=True, help="Admin email address.")
    @click.option("--name", default="Platform Administrator", help="Admin full name.")
    @click.option("--password", required=True, help="Admin password (min 8 chars).")
    def create_admin_command(email: str, name: str, password: str) -> None:
        """Create or promote an administrator account."""
        admin = create_or_promote_admin_user(
            email=email,
            full_name=name,
            password=password,
        )
        click.echo(f"[OK] Admin user ready: id={admin.id} email={admin.normalized_email}")

    @app.cli.command("seed-demo")
    def seed_demo_command() -> None:
        """Disabled in normal development/production to prevent dummy marketplace listings."""
        summary = seed_demo_marketplace()
        click.echo(
            f"[OK] Dummy seeding disabled: employers={summary['employers']}, "
            f"workers={summary['workers']}, jobs={summary['jobs']}"
        )
