"""Pytest fixtures for Earn & Pay automated test suite."""

from __future__ import annotations

import os
from collections.abc import Generator

import pytest
from flask import Flask
from flask.testing import FlaskClient, FlaskCliRunner
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError

from app import create_app
from app.extensions import db
from config import normalize_database_uri


def _resolve_test_database_uri() -> str:
    """Use TEST_DATABASE_URL if PostgreSQL is reachable; otherwise use isolated in-memory DB."""
    candidate = normalize_database_uri(
        os.getenv(
            "TEST_DATABASE_URL",
            "postgresql+psycopg://postgres:postgres@localhost:5432/earn_and_pay_test",
        )
    )
    try:
        engine = create_engine(candidate, connect_args={"connect_timeout": 2})
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        engine.dispose()
        return candidate
    except (SQLAlchemyError, ImportError, OSError):
        return "sqlite:///:memory:"


@pytest.fixture()
def app() -> Generator[Flask, None, None]:
    """Create an isolated Flask application instance for testing."""
    db_uri = _resolve_test_database_uri()
    test_app = create_app(
        "testing",
        config_overrides={
            "SQLALCHEMY_DATABASE_URI": db_uri,
            "WTF_CSRF_ENABLED": True,
        },
    )
    with test_app.app_context():
        db.create_all()
        yield test_app
        db.session.remove()
        db.drop_all()


@pytest.fixture()
def client(app: Flask) -> FlaskClient:
    """Return a Flask test client."""
    return app.test_client()


@pytest.fixture()
def cli_runner(app: Flask) -> FlaskCliRunner:
    """Return a Flask CLI test runner."""
    return app.test_cli_runner()
