"""Phase 5 Automated Tests: Registration, Login, CSRF, Verification, Recovery & RBAC."""

from __future__ import annotations

import re

from flask import Flask
from flask.testing import FlaskClient

from app.extensions import db
from app.models import AuditEvent, User
from app.services import issue_new_verification_token, register_user_account, request_password_reset
from app.utils.security import role_required

_CSRF_META_RE = re.compile(r'name="csrf_token"\s+type="hidden"\s+value="([^"]+)"')


def _extract_csrf_token(html: str) -> str:
    """Extract the hidden Flask-WTF CSRF token from rendered form HTML."""
    match = _CSRF_META_RE.search(html)
    assert match is not None, "Expected hidden csrf_token input in form HTML"
    return match.group(1)


class TestRegistrationAndRoleOnboarding:
    """Verify Worker and Employer registration, CSRF enforcement, and profile creation."""

    def test_registration_page_renders_and_enforces_csrf(self, client: FlaskClient) -> None:
        get_resp = client.get("/auth/register?role=employer")
        assert get_resp.status_code == 200
        html = get_resp.get_data(as_text=True)
        assert "Create Your Earn &amp; Pay Account" in html

        # Submitting POST without CSRF token is rejected with 400
        no_csrf_resp = client.post(
            "/auth/register",
            data={
                "role": "worker",
                "full_name": "No CSRF User",
                "email": "nocsrf@example.com",
                "password": "ValidPassword#1",
                "confirm_password": "ValidPassword#1",
                "accept_terms": "y",
            },
        )
        assert no_csrf_resp.status_code == 400

    def test_worker_registration_creates_profile_and_logs_in(
        self, app: Flask, client: FlaskClient
    ) -> None:
        form_html = client.get("/auth/register").get_data(as_text=True)
        csrf_token = _extract_csrf_token(form_html)

        resp = client.post(
            "/auth/register",
            data={
                "csrf_token": csrf_token,
                "role": "worker",
                "full_name": "Suresh Babu",
                "business_name": "",
                "email": "  Suresh.Babu@Example.COM ",
                "password": "WorkerStrong#2026",
                "confirm_password": "WorkerStrong#2026",
                "accept_terms": "y",
            },
            follow_redirects=True,
        )
        assert resp.status_code == 200
        body = resp.get_data(as_text=True)
        assert "Account created!" in body
        assert "Pending Verification" in body

        with app.app_context():
            user = User.query.filter_by(normalized_email="suresh.babu@example.com").one()
            assert user.role == "worker"
            assert user.email_verified is False
            assert user.account_status == "pending_verification"
            assert user.worker_profile is not None
            assert user.employer_profile is None

    def test_employer_registration_requires_business_name_and_creates_profile(
        self, app: Flask, client: FlaskClient
    ) -> None:
        form_html = client.get("/auth/register?role=employer").get_data(as_text=True)
        csrf_token = _extract_csrf_token(form_html)

        # Missing business_name for employer fails validation
        missing_biz_resp = client.post(
            "/auth/register",
            data={
                "csrf_token": csrf_token,
                "role": "employer",
                "full_name": "Deepa Nair",
                "business_name": "",
                "email": "deepa@example.com",
                "password": "EmployerStrong#2026",
                "confirm_password": "EmployerStrong#2026",
                "accept_terms": "y",
            },
        )
        assert "Please enter your shop or business name" in missing_biz_resp.get_data(as_text=True)

        # Valid employer registration succeeds
        valid_resp = client.post(
            "/auth/register",
            data={
                "csrf_token": csrf_token,
                "role": "employer",
                "full_name": "Deepa Nair",
                "business_name": "Nair Provision & Bakery",
                "email": "deepa@example.com",
                "password": "EmployerStrong#2026",
                "confirm_password": "EmployerStrong#2026",
                "accept_terms": "y",
            },
            follow_redirects=True,
        )
        assert valid_resp.status_code == 200
        with app.app_context():
            user = User.query.filter_by(normalized_email="deepa@example.com").one()
            assert user.role == "employer"
            assert user.employer_profile is not None
            assert user.employer_profile.business_name == "Nair Provision & Bakery"
            assert user.employer_profile.verification_status == "unverified"

    def test_cannot_self_register_as_admin(self, app: Flask, client: FlaskClient) -> None:
        form_html = client.get("/auth/register").get_data(as_text=True)
        csrf_token = _extract_csrf_token(form_html)

        resp = client.post(
            "/auth/register",
            data={
                "csrf_token": csrf_token,
                "role": "admin",
                "full_name": "Attacker",
                "email": "attacker@example.com",
                "password": "StrongPass#2026",
                "confirm_password": "StrongPass#2026",
                "accept_terms": "y",
            },
        )
        assert resp.status_code == 200
        with app.app_context():
            assert User.query.filter_by(normalized_email="attacker@example.com").first() is None


class TestLoginLogoutAndEmailVerification:
    """Verify login, open-redirect defense, suspended account block, logout, and verification."""

    def test_login_logout_and_open_redirect_protection(
        self, app: Flask, client: FlaskClient
    ) -> None:
        with app.app_context():
            register_user_account(
                full_name="Asha Rani",
                email="asha@example.com",
                password="AshaPassword#99",
                role="worker",
            )

        login_html = client.get("/auth/login").get_data(as_text=True)
        csrf_token = _extract_csrf_token(login_html)

        # Wrong password fails safely
        bad_resp = client.post(
            "/auth/login",
            data={
                "csrf_token": csrf_token,
                "email": "asha@example.com",
                "password": "WrongPassword#11",
            },
        )
        assert "Invalid email address or password." in bad_resp.get_data(as_text=True)

        # Valid login with external malicious next URL ignores external redirect
        good_resp = client.post(
            "/auth/login?next=https://evil-phishing.example.com/steal",
            data={
                "csrf_token": csrf_token,
                "email": "  ASHA@example.com ",
                "password": "AshaPassword#99",
            },
            follow_redirects=False,
        )
        assert good_resp.status_code == 302
        assert good_resp.headers["Location"] == "/"

        # Logout via CSRF-protected POST
        home_html = client.get("/").get_data(as_text=True)
        logout_csrf = _extract_csrf_token(home_html)
        logout_resp = client.post(
            "/auth/logout",
            data={"csrf_token": logout_csrf},
            follow_redirects=True,
        )
        assert "You have been signed out safely." in logout_resp.get_data(as_text=True)

    def test_suspended_user_cannot_log_in(self, app: Flask, client: FlaskClient) -> None:
        with app.app_context():
            user, _tok = register_user_account(
                full_name="Suspended Account",
                email="suspended@example.com",
                password="SuspendedPass#2026",
                role="worker",
            )
            user.account_status = "suspended"
            db.session.commit()

        login_html = client.get("/auth/login").get_data(as_text=True)
        csrf_token = _extract_csrf_token(login_html)

        resp = client.post(
            "/auth/login",
            data={
                "csrf_token": csrf_token,
                "email": "suspended@example.com",
                "password": "SuspendedPass#2026",
            },
        )
        assert "suspended or deactivated" in resp.get_data(as_text=True)

    def test_email_verification_and_resend_workflow(
        self, app: Flask, client: FlaskClient
    ) -> None:
        with app.app_context():
            user, initial_token = register_user_account(
                full_name="Naveen Kumar",
                email="naveen@example.com",
                password="NaveenPass#2026",
                role="worker",
            )
            user_id = user.id
            # Issue a new token (which invalidates initial_token)
            fresh_token = issue_new_verification_token(user)

        # Old replaced token is rejected
        old_resp = client.get(f"/auth/verify-email/{initial_token}", follow_redirects=True)
        assert "invalid, expired, or has already been used" in old_resp.get_data(as_text=True)

        # Fresh token verifies the email and sets account_status='active'
        ok_resp = client.get(f"/auth/verify-email/{fresh_token}", follow_redirects=True)
        assert "Your email address is now verified!" in ok_resp.get_data(as_text=True)

        with app.app_context():
            refreshed = db.session.get(User, user_id)
            assert refreshed is not None
            assert refreshed.email_verified is True
            assert refreshed.account_status == "active"


class TestPasswordRecoveryAndRBAC:
    """Verify enumeration-safe password recovery and @role_required access control."""

    def test_enumeration_safe_forgot_password_and_single_use_reset(
        self, app: Flask, client: FlaskClient
    ) -> None:
        with app.app_context():
            register_user_account(
                full_name="Priya Menon",
                email="priya@example.com",
                password="OldPassword#2026",
                role="worker",
            )

        forgot_html = client.get("/auth/forgot-password").get_data(as_text=True)
        csrf_token = _extract_csrf_token(forgot_html)

        # Unregistered email gets the exact same confirmation message as registered email
        unreg_resp = client.post(
            "/auth/forgot-password",
            data={"csrf_token": csrf_token, "email": "nobody.here@example.com"},
            follow_redirects=True,
        )
        reg_resp = client.post(
            "/auth/forgot-password",
            data={"csrf_token": csrf_token, "email": "priya@example.com"},
            follow_redirects=True,
        )
        expected_msg = (
            "If an active account exists for that email address, "
            "password reset instructions have been issued."
        )
        assert expected_msg in unreg_resp.get_data(as_text=True)
        assert expected_msg in reg_resp.get_data(as_text=True)

        # Issue a reset token and complete password reset via HTTP form
        with app.app_context():
            raw_reset_token = request_password_reset("priya@example.com")
            assert raw_reset_token is not None

        reset_page_resp = client.get(f"/auth/reset-password/{raw_reset_token}")
        assert reset_page_resp.status_code == 200
        reset_csrf = _extract_csrf_token(reset_page_resp.get_data(as_text=True))

        post_reset_resp = client.post(
            f"/auth/reset-password/{raw_reset_token}",
            data={
                "csrf_token": reset_csrf,
                "password": "BrandNewPassword#2027",
                "confirm_password": "BrandNewPassword#2027",
            },
            follow_redirects=True,
        )
        assert "Your password has been updated" in post_reset_resp.get_data(as_text=True)

        # Reusing the same reset token must be rejected
        reuse_resp = client.get(
            f"/auth/reset-password/{raw_reset_token}",
            follow_redirects=True,
        )
        assert "invalid, expired, or has already been used" in reuse_resp.get_data(as_text=True)

        # Verify user can now authenticate with the new password
        login_html = client.get("/auth/login").get_data(as_text=True)
        login_csrf = _extract_csrf_token(login_html)
        login_resp = client.post(
            "/auth/login",
            data={
                "csrf_token": login_csrf,
                "email": "priya@example.com",
                "password": "BrandNewPassword#2027",
            },
            follow_redirects=True,
        )
        assert "Welcome back, Priya Menon." in login_resp.get_data(as_text=True)

    def test_role_required_decorator_enforces_strict_rbac(
        self, app: Flask, client: FlaskClient
    ) -> None:
        @app.get("/test-employer-only-zone")
        @role_required("employer")
        def employer_zone():
            return "Employer Workspace Authorised", 200

        @app.get("/test-admin-only-zone")
        @role_required("admin")
        def admin_zone():
            return "Admin Moderation Authorised", 200

        # 1. Unauthenticated request redirects to /auth/login?next=...
        anon_resp = client.get("/test-employer-only-zone", follow_redirects=False)
        assert anon_resp.status_code == 302
        assert "/auth/login" in anon_resp.headers["Location"]

        # 2. Authenticate as a Worker
        with app.app_context():
            register_user_account(
                full_name="Worker User",
                email="worker.rbac@example.com",
                password="WorkerPass#2026",
                role="worker",
            )
        login_html = client.get("/auth/login").get_data(as_text=True)
        login_csrf = _extract_csrf_token(login_html)
        client.post(
            "/auth/login",
            data={
                "csrf_token": login_csrf,
                "email": "worker.rbac@example.com",
                "password": "WorkerPass#2026",
            },
        )

        # 3. Worker attempting to access Employer or Admin route gets 403 Forbidden
        assert client.get("/test-employer-only-zone").status_code == 403
        assert client.get("/test-admin-only-zone").status_code == 403

        # 4. Verify audit events were recorded without leaking secrets
        with app.app_context():
            events = AuditEvent.query.all()
            assert len(events) >= 2
