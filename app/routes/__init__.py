"""Route blueprints registration package."""

from __future__ import annotations

from flask import Flask

from app.routes.applications import applications_bp
from app.routes.auth import auth_bp
from app.routes.jobs import jobs_bp
from app.routes.moderation import moderation_bp
from app.routes.profiles import profiles_bp
from app.routes.public import public_bp
from app.routes.system import system_bp


def register_blueprints(app: Flask) -> None:
    """Register all application blueprints on the Flask instance."""
    app.register_blueprint(public_bp)
    app.register_blueprint(system_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(profiles_bp)
    app.register_blueprint(jobs_bp)
    app.register_blueprint(applications_bp)
    app.register_blueprint(moderation_bp)
