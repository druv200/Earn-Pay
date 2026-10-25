"""Phase 6 Automated Tests: Worker/Employer Profiles, Dashboards, Matching & Privacy Controls."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from flask import Flask
from flask.testing import FlaskClient

from app.extensions import db
from app.models import Job, User
from app.services import register_user_account, submit_job_application

_CSRF_RE = re.compile(r'name="csrf_token"\s+type="hidden"\s+value="([^"]+)"')


def _get_csrf(html: str) -> str:
    match = _CSRF_RE.search(html)
    assert match is not None, "Expected hidden csrf_token in form"
    return match.group(1)


def _login_client(client: FlaskClient, email: str, password: str) -> None:
    login_html = client.get("/auth/login").get_data(as_text=True)
    csrf_token = _get_csrf(login_html)
    resp = client.post(
        "/auth/login",
        data={"csrf_token": csrf_token, "email": email, "password": password},
    )
    assert resp.status_code == 302


class TestWorkerProfileDashboardAndMatching:
    """Verify worker profile updates, rule-based job matching, and dashboard timeline."""

    def test_worker_profile_update_and_pincode_validation(
        self, app: Flask, client: FlaskClient
    ) -> None:
        with app.app_context():
            register_user_account(
                full_name="Ganesh Hegde",
                email="ganesh@example.com",
                password="GaneshPass#2026",
                role="worker",
            )
        _login_client(client, "ganesh@example.com", "GaneshPass#2026")

        edit_html = client.get("/worker/profile").get_data(as_text=True)
        csrf_token = _get_csrf(edit_html)

        # Invalid 5-digit pincode is rejected
        bad_pin_resp = client.post(
            "/worker/profile",
            data={
                "csrf_token": csrf_token,
                "full_name": "Ganesh Hegde",
                "pincode": "56004",
                "travel_radius_km": "10",
                "availability": "daily",
            },
        )
        assert "valid 6-digit Indian pincode" in bad_pin_resp.get_data(as_text=True)

        # Valid full update brings completion to 100%
        ok_resp = client.post(
            "/worker/profile",
            data={
                "csrf_token": csrf_token,
                "full_name": "Ganesh Hegde",
                "phone_number": "+919900112233",
                "skills": "Billing, Stock counting, Kannada",
                "experience_summary": "4 years in retail stores across Jayanagar",
                "preferred_categories": "Retail, Warehouse & Stock",
                "preferred_location": "Jayanagar",
                "pincode": "560041",
                "travel_radius_km": "12",
                "availability": "daily",
                "expected_daily_wage": "650.00",
                "is_profile_public": "y",
            },
            follow_redirects=True,
        )
        assert ok_resp.status_code == 200
        dash_html = ok_resp.get_data(as_text=True)
        assert "100%" in dash_html
        assert "Your worker profile and privacy preferences have been saved." in dash_html

    def test_worker_dashboard_displays_explainable_matches_and_application_timeline(
        self, app: Flask, client: FlaskClient
    ) -> None:
        with app.app_context():
            worker, _ = register_user_account(
                full_name="Kavitha R",
                email="kavitha@example.com",
                password="KavithaPass#2026",
                role="worker",
            )
            assert worker.worker_profile is not None
            worker.worker_profile.skills = "billing, counter service"
            worker.worker_profile.preferred_categories = "Retail"
            worker.worker_profile.preferred_location = "Jayanagar"
            worker.worker_profile.pincode = "560041"
            worker.worker_profile.availability = "daily"
            worker.worker_profile.expected_daily_wage = Decimal("600.00")

            employer, _ = register_user_account(
                full_name="Ramesh Pai",
                email="ramesh.pai@example.com",
                password="EmployerPass#2026",
                role="employer",
                business_name="Pai Supermart",
            )
            assert employer.employer_profile is not None
            job = Job(
                employer_id=employer.employer_profile.id,
                title="Retail Billing & Counter Helper",
                category="Retail",
                job_type="daily_wage",
                description="Operate billing desk and assist shoppers.",
                responsibilities="Billing, packing.",
                required_skills="billing, basic math",
                location="Jayanagar, Bengaluru",
                pincode="560041",
                wage_amount=Decimal("700.00"),
                currency="INR",
                wage_frequency="daily",
                working_hours="9 AM - 6 PM",
                vacancies=2,
                application_deadline=datetime.now(UTC).date() + timedelta(days=5),
                status="published",
            )
            job.publish()
            db.session.add(job)
            db.session.commit()

            submit_job_application(worker_user=worker, job_id=job.id)

        _login_client(client, "kavitha@example.com", "KavithaPass#2026")
        resp = client.get("/worker/dashboard")
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)

        # Verify explainable match reasons and application timeline
        assert "Same pincode (560041)" in html
        assert "Category match (Retail)" in html
        assert "Skills match (billing)" in html
        assert "Meets expected daily wage (₹700)" in html
        assert "STATUS: APPLIED" in html


class TestEmployerWorkspaceAndPrivacyControls:
    """Verify Employer dashboard, verification request, and worker privacy enforcement."""

    def test_employer_profile_update_and_verification_request(
        self, app: Flask, client: FlaskClient
    ) -> None:
        with app.app_context():
            register_user_account(
                full_name="Vikram Rao",
                email="vikram@example.com",
                password="VikramPass#2026",
                role="employer",
                business_name="Rao Hardware & Tools",
            )
        _login_client(client, "vikram@example.com", "VikramPass#2026")

        edit_html = client.get("/employer/profile").get_data(as_text=True)
        csrf_token = _get_csrf(edit_html)

        resp = client.post(
            "/employer/profile",
            data={
                "csrf_token": csrf_token,
                "full_name": "Vikram Rao",
                "business_name": "Rao Hardware & Electricals",
                "business_type": "shop",
                "description": "Retail hardware and plumbing supplies store.",
                "address": "12th Main, Malleshwaram",
                "location": "Malleshwaram, Bengaluru",
                "pincode": "560003",
                "contact_phone": "+919845099887",
                "request_verification": "y",
            },
            follow_redirects=True,
        )
        assert resp.status_code == 200
        dash_html = resp.get_data(as_text=True)
        assert "Rao Hardware &amp; Electricals" in dash_html
        assert "Verification State: <strong>Pending</strong>" in dash_html
        # Still shows Unverified Listing badge until an admin completes verification
        assert "Unverified Listing" in dash_html

    def test_worker_privacy_controls_enforced_on_server(
        self, app: Flask, client: FlaskClient
    ) -> None:
        with app.app_context():
            worker, _ = register_user_account(
                full_name="Private Worker",
                email="private.worker@example.com",
                password="WorkerPass#2026",
                role="worker",
            )
            assert worker.worker_profile is not None
            worker.worker_profile.phone_number = "+919988776655"
            worker.worker_profile.show_phone_to_employers = False
            worker.worker_profile.is_profile_public = True
            worker_profile_id = worker.worker_profile.id

            emp1, _ = register_user_account(
                full_name="Employer One",
                email="emp1@example.com",
                password="EmployerPass#2026",
                role="employer",
                business_name="Shop One",
            )
            emp2, _ = register_user_account(
                full_name="Employer Two",
                email="emp2@example.com",
                password="EmployerPass#2026",
                role="employer",
                business_name="Shop Two",
            )
            assert emp1.employer_profile is not None
            job = Job(
                employer_id=emp1.employer_profile.id,
                title="Evening Helper",
                category="Retail",
                job_type="part_time",
                description="Evening counter help.",
                responsibilities="Packing.",
                location="Bengaluru",
                pincode="560001",
                wage_amount=Decimal("400.00"),
                currency="INR",
                wage_frequency="daily",
                working_hours="5 PM - 9 PM",
                vacancies=1,
                application_deadline=datetime.now(UTC).date() + timedelta(days=3),
                status="published",
            )
            job.publish()
            db.session.add(job)
            db.session.commit()

            submit_job_application(worker_user=worker, job_id=job.id)

        # 1. Employer 1 views public profile with show_phone_to_employers=False: phone hidden
        _login_client(client, "emp1@example.com", "EmployerPass#2026")
        view_resp = client.get(f"/workers/{worker_profile_id}")
        assert view_resp.status_code == 200
        view_html = view_resp.get_data(as_text=True)
        assert "Hidden by Worker Privacy Setting" in view_html
        assert "+919988776655" not in view_html

        # 2. Worker marks profile private (is_profile_public=False)
        with app.app_context():
            w_user = User.query.filter_by(normalized_email="private.worker@example.com").one()
            assert w_user.worker_profile is not None
            w_user.worker_profile.is_profile_public = False
            db.session.commit()

        # Employer 1 (to whom the worker applied) can STILL view the candidate summary
        assert client.get(f"/workers/{worker_profile_id}").status_code == 200

        # Employer 2 (unrelated employer) gets 403 Forbidden on the private worker profile
        client.get("/")
        home_csrf = _get_csrf(client.get("/").get_data(as_text=True))
        client.post("/auth/logout", data={"csrf_token": home_csrf})
        _login_client(client, "emp2@example.com", "EmployerPass#2026")
        assert client.get(f"/workers/{worker_profile_id}").status_code == 403


class TestPublicEmployerAndAccountDeletion:
    """Verify public employer profile page and documented account deletion workflow."""

    def test_public_employer_profile_and_account_deletion(
        self, app: Flask, client: FlaskClient
    ) -> None:
        with app.app_context():
            emp_user, _ = register_user_account(
                full_name="Mohan Das",
                email="mohan@example.com",
                password="MohanPass#2026",
                role="employer",
                business_name="Das Tea & Snacks",
            )
            assert emp_user.employer_profile is not None
            employer_id = emp_user.employer_profile.id

        # Public employer page is accessible to anyone
        pub_resp = client.get(f"/employers/{employer_id}")
        assert pub_resp.status_code == 200
        assert "Das Tea &amp; Snacks" in pub_resp.get_data(as_text=True)

        # Log in as employer and execute account deletion
        _login_client(client, "mohan@example.com", "MohanPass#2026")
        settings_html = client.get("/settings").get_data(as_text=True)
        csrf_token = _get_csrf(settings_html)

        del_resp = client.post(
            "/settings",
            data={
                "csrf_token": csrf_token,
                "confirm_email": "mohan@example.com",
                "reason": "Closing shop temporarily.",
            },
            follow_redirects=True,
        )
        assert del_resp.status_code == 200
        assert "account deletion request has been processed" in del_resp.get_data(as_text=True)

        # Deactivated employer profile is no longer publicly listed (returns 404)
        assert client.get(f"/employers/{employer_id}").status_code == 404
