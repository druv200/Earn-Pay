"""Phase 10 Automated Tests: Accessibility Landmarks, Seed Data CLI, Badges & Rate Limiting."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from flask import Flask
from flask.testing import FlaskClient
from werkzeug.exceptions import TooManyRequests

from app.extensions import db
from app.models import EmployerProfile, Job, Report, User
from app.services import register_user_account


class TestPhase10SeedAccessibilityAndResilience:
    """Verify idempotent seed-demo CLI, WCAG semantic HTML landmarks, and 429 handling."""

    def test_seed_demo_cli_no_longer_inserts_dummy_marketplace_data(self, app: Flask) -> None:
        runner = app.test_cli_runner()

        first_run = runner.invoke(args=["seed-demo"])
        assert first_run.exit_code == 0
        assert "Dummy seeding disabled" in first_run.output

        with app.app_context():
            assert User.query.count() == 0
            assert EmployerProfile.query.count() == 0
            assert Job.query.count() == 0
            assert Report.query.count() == 0

    def test_semantic_accessibility_landmarks_and_form_labels_across_core_pages(
        self, app: Flask, client: FlaskClient
    ) -> None:
        public_urls = [
            "/",
            "/safety",
            "/about",
            "/privacy",
            "/terms",
            "/help",
            "/auth/login",
            "/auth/register",
            "/auth/forgot-password",
        ]
        for url in public_urls:
            resp = client.get(url)
            assert resp.status_code == 200, f"Expected 200 OK on {url}"
            html = resp.get_data(as_text=True)

            # Skip-to-content keyboard link & <main id="main-content">
            assert 'href="#main-content"' in html, f"Missing skip link on {url}"
            assert 'id="main-content"' in html, f"Missing #main-content landmark on {url}"
            assert "<header" in html and "<footer" in html, f"Missing header/footer on {url}"
            assert 'aria-controls="primary-navigation"' in html

            # Every page must have exactly one primary <h1> heading
            h1_matches = re.findall(r"<h1\b", html)
            assert len(h1_matches) == 1, f"Expected 1 <h1> on {url}, found {len(h1_matches)}"

        # Job discovery is protected for unauthenticated visitors
        assert client.get("/jobs").status_code == 302

    def test_non_color_only_status_and_verification_badges(
        self, app: Flask, client: FlaskClient
    ) -> None:
        with app.app_context():
            for idx, verified in enumerate((True, False)):
                emp, _ = register_user_account(
                    full_name=f"Badge Employer {idx}",
                    email=f"badge.emp{idx}@example.com",
                    password="EmployerPass#2026",
                    role="employer",
                    business_name=f"Badge Shop {idx}",
                )
                assert emp.employer_profile is not None
                if verified:
                    emp.employer_profile.verification_status = "verified"
                    emp.employer_profile.verified_at = datetime.now(UTC)
                job = Job(
                    employer_id=emp.employer_profile.id,
                    title=f"Badge Test Role {idx}",
                    category="Retail",
                    job_type="daily_wage",
                    description="Counter help.",
                    responsibilities="Billing.",
                    location="Jayanagar, Bengaluru",
                    pincode="560041",
                    wage_amount=Decimal("700.00"),
                    currency="INR",
                    wage_frequency="daily",
                    working_hours="9 AM - 5 PM",
                    vacancies=1,
                    application_deadline=datetime.now(UTC).date() + timedelta(days=5),
                    status="published",
                )
                job.publish()
                db.session.add(job)
            register_user_account(
                full_name="Badge Worker",
                email="badge.worker@example.com",
                password="WorkerPass#2026",
                role="worker",
            )
            db.session.commit()

        login_html = client.get("/auth/login").get_data(as_text=True)
        csrf = re.search(r'name="csrf_token"\s+type="hidden"\s+value="([^"]+)"', login_html)
        assert csrf is not None
        client.post(
            "/auth/login",
            data={
                "csrf_token": csrf.group(1),
                "email": "badge.worker@example.com",
                "password": "WorkerPass#2026",
            },
        )

        discovery_html = client.get("/jobs").get_data(as_text=True)
        # Verified and Unverified badges include explicit text + symbol, never color alone
        assert "Verified Employer" in discovery_html
        assert "Unverified Listing" in discovery_html

    def test_429_rate_limit_error_handler_html_and_json(
        self, app: Flask, client: FlaskClient
    ) -> None:
        @app.route("/_test/trigger-429")
        def trigger_429():
            raise TooManyRequests()

        html_resp = client.get("/_test/trigger-429", headers={"Accept": "text/html"})
        assert html_resp.status_code == 429
        assert "Please Wait a Moment Before Trying Again" in html_resp.get_data(as_text=True)

        json_resp = client.get("/_test/trigger-429", headers={"Accept": "application/json"})
        assert json_resp.status_code == 429
        payload = json_resp.get_json()
        assert payload["error"] == "rate_limit_exceeded"
