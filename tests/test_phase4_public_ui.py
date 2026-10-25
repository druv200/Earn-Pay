"""Phase 4 Automated Tests: Responsive Public Pages, Job Ledger, Badges & Accessibility."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from flask import Flask
from flask.testing import FlaskClient

from app.extensions import db
from app.models import EmployerProfile, Job, User
from app.services import register_user_account


def _seed_employer_and_jobs(
    *,
    verified: bool = False,
) -> tuple[EmployerProfile, Job, Job]:
    user = User(
        full_name="Lakshmi Narayan",
        normalized_email=f"lakshmi.{'ver' if verified else 'unver'}@example.com",
        role="employer",
        account_status="active",
        email_verified=True,
    )
    user.set_password("EmployerSafe#2026")
    db.session.add(user)
    db.session.flush()

    employer = EmployerProfile(
        user_id=user.id,
        business_name="Udupi Darshini Tiffins" if verified else "Local Corner Bakery",
        business_type="restaurant",
        location="Indiranagar, Bengaluru",
        pincode="560038",
        verification_status="verified" if verified else "unverified",
        verified_at=datetime.now(UTC) if verified else None,
    )
    db.session.add(employer)
    db.session.flush()

    today = datetime.now(UTC).date()
    published_job = Job(
        employer_id=employer.id,
        title="Morning Kitchen & Counter Assistant",
        category="Restaurant & Food",
        job_type="daily_wage",
        description="Assist with morning tiffin counter and dish organization.",
        responsibilities="Serve plates, keep counter clean, assist head cook.",
        required_skills="Cleanliness, basic Kannada",
        location="Indiranagar, Bengaluru",
        pincode="560038",
        wage_amount=Decimal("750.00"),
        currency="INR",
        wage_frequency="daily",
        working_hours="6:30 AM - 2:30 PM",
        vacancies=3,
        application_deadline=today + timedelta(days=5),
        status="published",
    )
    published_job.publish()

    draft_job = Job(
        employer_id=employer.id,
        title="Unpublished Draft Inventory Role",
        category="Retail",
        job_type="part_time",
        description="Internal draft not for public display.",
        responsibilities="Count stock.",
        location="Jayanagar, Bengaluru",
        pincode="560041",
        wage_amount=Decimal("500.00"),
        currency="INR",
        wage_frequency="daily",
        working_hours="4 hours",
        vacancies=1,
        application_deadline=today + timedelta(days=5),
        status="draft",
    )

    db.session.add_all([published_job, draft_job])
    db.session.commit()
    return employer, published_job, draft_job


def _login_new_worker(client: FlaskClient) -> None:
    register_user_account(
        full_name="Landing Worker",
        email="landing.worker@example.com",
        password="WorkerPass#2026",
        role="worker",
    )
    login_html = client.get("/auth/login").get_data(as_text=True)
    match = re.search(r'name="csrf_token"\s+type="hidden"\s+value="([^"]+)"', login_html)
    assert match is not None
    resp = client.post(
        "/auth/login",
        data={
            "csrf_token": match.group(1),
            "email": "landing.worker@example.com",
            "password": "WorkerPass#2026",
        },
    )
    assert resp.status_code == 302


class TestLandingPageAndEditorialDesign:
    """Verify landing page requirements, role-aware actions, and database job feed."""

    def test_landing_page_renders_hero_ctas_and_accessibility_landmarks(
        self, client: FlaskClient
    ) -> None:
        resp = client.get("/")
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)

        # Required hero heading & sections
        assert "Find Work. Earn Money. Build Your Future." in html
        assert "Find Local Work" in html
        assert "Hire Workers" in html
        assert "How Earn &amp; Pay Works" in html
        assert "Frequently Asked Questions" in html
        assert "Never Pay Money to Get a Job" in html

        # Accessibility landmarks & skip link
        assert 'class="skip-link"' in html
        assert 'id="main-content"' in html

    def test_visitor_landing_page_never_exposes_live_jobs(
        self, app: Flask, client: FlaskClient
    ) -> None:
        with app.app_context():
            _seed_employer_and_jobs(verified=False)

        html = client.get("/").get_data(as_text=True)
        assert "Morning Kitchen &amp; Counter Assistant" not in html
        assert "Register or Sign In to Discover Local Jobs" in html

    def test_worker_landing_page_displays_only_published_non_expired_jobs(
        self, app: Flask, client: FlaskClient
    ) -> None:
        with app.app_context():
            _seed_employer_and_jobs(verified=False)
            _login_new_worker(client)

        resp = client.get("/")
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)

        assert "Morning Kitchen &amp; Counter Assistant" in html
        assert "₹750 / daily" in html
        assert "Indiranagar, Bengaluru (560038)" in html
        assert "Unpublished Draft Inventory Role" not in html
        assert "Unverified Listing" in html
        assert '<span aria-hidden="true">✓</span> Verified Employer' not in html

    def test_landing_page_renders_verified_badge_only_when_genuinely_verified(
        self, app: Flask, client: FlaskClient
    ) -> None:
        with app.app_context():
            _seed_employer_and_jobs(verified=True)
            _login_new_worker(client)

        resp = client.get("/")
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        assert "Udupi Darshini Tiffins" in html
        assert "Verified Employer" in html

    def test_visitor_search_on_landing_redirects_to_sign_in(
        self, app: Flask, client: FlaskClient
    ) -> None:
        with app.app_context():
            _seed_employer_and_jobs(verified=True)

        resp = client.get("/?q=Kitchen&location=560038", follow_redirects=False)
        assert resp.status_code == 302
        assert "/auth/login" in resp.headers["Location"]
        assert "next=" in resp.headers["Location"]


class TestPublicPolicyAndSupportPages:
    """Verify About, Safety Guidelines, Privacy Policy, Terms of Service, and Help pages."""

    def test_about_page_renders(self, client: FlaskClient) -> None:
        resp = client.get("/about")
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        assert "About Earn &amp; Pay" in html
        assert "Upfront Wage &amp; Schedule Transparency" in html

    def test_safety_guidelines_page_renders(self, client: FlaskClient) -> None:
        resp = client.get("/safety")
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        assert "Community &amp; Job Safety Guidelines" in html
        assert "Never Pay Any Fee to Apply, Interview, or Start Work" in html

    def test_privacy_policy_page_renders(self, client: FlaskClient) -> None:
        resp = client.get("/privacy")
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        assert "Privacy Policy" in html
        assert "Worker Privacy Controls" in html
        assert "Account Deletion Rights" in html

    def test_terms_of_service_page_renders(self, client: FlaskClient) -> None:
        resp = client.get("/terms")
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        assert "Terms of Service" in html
        assert "Payments &amp; No Internal Wallet" in html

    def test_help_and_contact_page_renders(self, client: FlaskClient) -> None:
        resp = client.get("/help")
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        assert "Help, Support &amp; Suspicious Listing Reports" in html
        assert "safety@earnandpay.in" in html

    def test_design_system_static_assets_served(self, client: FlaskClient) -> None:
        tokens_resp = client.get("/static/css/tokens.css")
        main_css_resp = client.get("/static/css/main.css")
        main_js_resp = client.get("/static/js/main.js")
        assert tokens_resp.status_code == 200
        assert main_css_resp.status_code == 200
        assert main_js_resp.status_code == 200
        assert "--color-bg-canvas: #F7F4EC" in tokens_resp.get_data(as_text=True)
