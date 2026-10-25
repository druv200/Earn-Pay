"""Phase 2 Automated Tests: Application Factory, Config, Security Headers & DB Connectivity."""

from __future__ import annotations

import pytest
from flask import Flask, abort
from flask.testing import FlaskClient, FlaskCliRunner

from app import create_app
from app.models import verify_database_connection
from app.utils.security import is_safe_redirect_url, normalize_email
from config import (
    INSECURE_DEFAULT_SECRET_KEY,
    ProductionConfig,
    get_config,
    normalize_database_uri,
)


class TestConfigurationAndUrls:
    """Verify environment configuration isolation and PostgreSQL URI normalization."""

    def test_psycopg3_url_normalization(self) -> None:
        assert (
            normalize_database_uri("postgres://user:pass@localhost:5432/db")
            == "postgresql+psycopg://user:pass@localhost:5432/db"
        )
        assert (
            normalize_database_uri("postgresql://user:pass@localhost:5432/db")
            == "postgresql+psycopg://user:pass@localhost:5432/db"
        )
        assert (
            normalize_database_uri("postgresql+psycopg://user:pass@localhost:5432/db")
            == "postgresql+psycopg://user:pass@localhost:5432/db"
        )

    def test_unknown_config_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="Unknown configuration"):
            get_config("nonexistent_env")

    def test_production_config_rejects_default_secret_key(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(ProductionConfig, "SECRET_KEY", INSECURE_DEFAULT_SECRET_KEY)
        monkeypatch.setattr(
            ProductionConfig,
            "SQLALCHEMY_DATABASE_URI",
            "postgresql+psycopg://user:pass@localhost:5432/prod_db",
        )
        with pytest.raises(RuntimeError, match="strong, unique SECRET_KEY"):
            ProductionConfig.validate()

    def test_production_config_rejects_short_secret_key(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(ProductionConfig, "SECRET_KEY", "too-short-secret")
        monkeypatch.setattr(
            ProductionConfig,
            "SQLALCHEMY_DATABASE_URI",
            "postgresql+psycopg://user:pass@localhost:5432/prod_db",
        )
        with pytest.raises(RuntimeError, match="at least 32 characters"):
            ProductionConfig.validate()


class TestHealthAndDatabaseConnectivity:
    """Verify system liveness, database `SELECT 1` probe, and CLI commands."""

    def test_index_route_returns_foundation_metadata(self, client: FlaskClient) -> None:
        response = client.get("/", headers={"Accept": "application/json"})
        assert response.status_code == 200
        payload = response.get_json()
        assert payload["product"] == "Earn & Pay"
        assert payload["tagline"] == "Find Work. Earn Money. Build Your Future."

    def test_health_endpoint_returns_200(self, client: FlaskClient) -> None:
        response = client.get("/health")
        assert response.status_code == 200
        payload = response.get_json()
        assert payload["status"] == "ok"
        assert payload["service"] == "earn-and-pay"
        assert payload["environment"] == "testing"

    def test_database_health_endpoint_executes_select_1(self, client: FlaskClient) -> None:
        response = client.get("/health/db")
        assert response.status_code == 200
        payload = response.get_json()
        assert payload["status"] == "ok"
        assert "Connected" in payload["database"]

    def test_verify_database_connection_helper(self, app: Flask) -> None:
        with app.app_context():
            ok, detail = verify_database_connection()
            assert ok is True
            assert "Connected" in detail

    def test_cli_db_check_command(self, cli_runner: FlaskCliRunner) -> None:
        result = cli_runner.invoke(args=["db-check"])
        assert result.exit_code == 0
        assert "[OK] Database verified:" in result.output


class TestSecurityHeadersAndErrorHandlers:
    """Verify defense-in-depth HTTP headers, safe redirects, and error templates."""

    def test_security_headers_attached_to_responses(self, client: FlaskClient) -> None:
        response = client.get("/health")
        assert response.headers["X-Content-Type-Options"] == "nosniff"
        assert response.headers["X-Frame-Options"] == "DENY"
        assert response.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"
        assert "default-src 'self'" in response.headers["Content-Security-Policy"]

    def test_hsts_header_enabled_in_production_mode(self) -> None:
        prod_app = create_app(
            "testing",
            config_overrides={
                "ENV_NAME": "production",
                "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
            },
        )
        prod_client = prod_app.test_client()
        response = prod_client.get("/health")
        assert "max-age=31536000" in response.headers.get("Strict-Transport-Security", "")

    def test_404_error_handler_html_and_json(self, client: FlaskClient) -> None:
        html_resp = client.get("/nonexistent-route-xyz")
        assert html_resp.status_code == 404
        assert b"ERROR 404" in html_resp.data

        json_resp = client.get(
            "/nonexistent-route-xyz",
            headers={"Accept": "application/json"},
        )
        assert json_resp.status_code == 404
        assert json_resp.get_json()["error"] == "not_found"

    def test_403_error_handler(self, app: Flask, client: FlaskClient) -> None:
        @app.get("/test-forbidden-endpoint")
        def trigger_403():
            abort(403)

        resp = client.get("/test-forbidden-endpoint")
        assert resp.status_code == 403
        assert b"ERROR 403" in resp.data

    def test_email_normalization_and_safe_redirect_helper(self, app: Flask) -> None:
        assert normalize_email("  Worker.One@Example.COM ") == "worker.one@example.com"
        with app.test_request_context("http://localhost:5000/login"):
            assert is_safe_redirect_url("/jobs") is True
            assert is_safe_redirect_url("http://localhost:5000/dashboard") is True
            assert is_safe_redirect_url("https://evil-phishing.example.com/steal") is False
            assert is_safe_redirect_url("javascript:alert(1)") is False
