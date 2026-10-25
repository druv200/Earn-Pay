"""Role-Based Access, Job Visibility, Find Workers Directory & Worker Count Tests."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from flask import Flask
from flask.testing import FlaskClient
from sqlalchemy import text

from app.extensions import db
from app.models import Job, User, normalize_user_role
from app.services import count_available_workers, register_user_account

_CSRF_RE = re.compile(r'name="csrf_token"\s+type="hidden"\s+value="([^"]+)"')


def _csrf(html: str) -> str:
    match = _CSRF_RE.search(html)
    assert match is not None
    return match.group(1)


def _login(client: FlaskClient, email: str, password: str) -> None:
    csrf = _csrf(client.get("/auth/login").get_data(as_text=True))
    resp = client.post(
        "/auth/login",
        data={"csrf_token": csrf, "email": email, "password": password},
    )
    assert resp.status_code == 302


def _logout(client: FlaskClient) -> None:
    csrf = _csrf(client.get("/").get_data(as_text=True))
    client.post("/auth/logout", data={"csrf_token": csrf})


def _make_worker(
    email: str,
    *,
    complete: bool = True,
    public: bool = True,
    status: str = "active",
    pincode: str = "560041",
) -> User:
    user, _ = register_user_account(
        full_name=f"Worker {email.split('@')[0]}",
        email=email,
        password="WorkerPass#2026",
        role="worker",
    )
    profile = user.worker_profile
    assert profile is not None
    if complete:
        profile.skills = "Billing, Packing"
        profile.preferred_location = "Jayanagar, Bengaluru"
        profile.pincode = pincode
        profile.preferred_categories = "Retail"
        profile.availability = "daily"
        profile.expected_daily_wage = Decimal("700.00")
        profile.phone_number = "+919811122233"
    profile.is_profile_public = public
    user.account_status = status
    db.session.commit()
    return user


def _make_employer_with_job(email: str = "boss@example.com") -> tuple[User, int]:
    user, _ = register_user_account(
        full_name="Shop Owner",
        email=email,
        password="EmployerPass#2026",
        role="employer",
        business_name="Real Corner Store",
    )
    assert user.employer_profile is not None
    job = Job(
        employer_id=user.employer_profile.id,
        title="Real Database Counter Role",
        category="Retail",
        job_type="daily_wage",
        description="Counter billing.",
        responsibilities="Billing and packing.",
        location="Jayanagar, Bengaluru",
        pincode="560041",
        wage_amount=Decimal("650.00"),
        currency="INR",
        wage_frequency="daily",
        working_hours="9 AM - 5 PM",
        vacancies=1,
        application_deadline=datetime.now(UTC).date() + timedelta(days=7),
        status="published",
    )
    job.publish()
    db.session.add(job)
    db.session.commit()
    return user, job.id


class TestRegistrationRoles:
    def test_registration_offers_worker_and_employer_without_employee_label(
        self, client: FlaskClient
    ) -> None:
        html = client.get("/auth/register").get_data(as_text=True)
        assert 'value="worker"' in html
        assert 'value="employer"' in html
        assert "Worker — For people looking for work." in html
        assert "Employer — For people or businesses looking to hire workers." in html
        assert "Employee" not in html

    def test_legacy_employee_role_maps_to_worker(self, app: Flask) -> None:
        assert normalize_user_role("Employee") == "worker"
        with app.app_context():
            user, _ = register_user_account(
                full_name="Legacy Person",
                email="legacy@example.com",
                password="LegacyPass#2026",
                role="employee",
            )
            assert user.role == "worker"
            assert user.worker_profile is not None

    def test_role_migration_preserves_existing_users(self, app: Flask) -> None:
        with app.app_context():
            worker = _make_worker("keep.worker@example.com")
            emp, job_id = _make_employer_with_job()
            worker_id, emp_id = worker.id, emp.id
            # Re-run migration's data step; valid records must be unchanged
            db.session.execute(
                text(
                    "UPDATE users SET role = 'worker' "
                    "WHERE lower(trim(role)) IN ('employee', 'job_seeker', 'jobseeker')"
                )
            )
            db.session.commit()
            assert db.session.get(User, worker_id).role == "worker"
            assert db.session.get(User, emp_id).role == "employer"
            assert db.session.get(Job, job_id) is not None


class TestRoleNavigationAndAccess:
    def test_worker_navigation(self, app: Flask, client: FlaskClient) -> None:
        with app.app_context():
            _make_worker("nav.worker@example.com")
        _login(client, "nav.worker@example.com", "WorkerPass#2026")
        for _ in range(2):  # survives refresh
            html = client.get("/").get_data(as_text=True)
            assert "Find Local Jobs" in html
            assert "My Applications" in html
            assert "Saved Jobs" in html
            assert "Profile and Settings" in html
            assert "Post a Job" not in html
            assert "Find Workers" not in html
            assert "Employer Dashboard" not in html

    def test_employer_navigation_hides_job_seeker_actions(
        self, app: Flask, client: FlaskClient
    ) -> None:
        with app.app_context():
            _make_employer_with_job()
        _login(client, "boss@example.com", "EmployerPass#2026")
        for _ in range(2):
            html = client.get("/").get_data(as_text=True)
            assert "Employer Dashboard" in html
            assert "Post a Job" in html
            assert "Manage My Jobs" in html
            assert "Find Workers" in html
            assert "Applicants" in html
            assert "Find Local Jobs" not in html
            assert "Find Local Work" not in html
            assert "My Applications" not in html

    def test_navigation_switches_correctly_across_sessions(
        self, app: Flask, client: FlaskClient
    ) -> None:
        with app.app_context():
            _make_worker("switch.worker@example.com")
            _make_employer_with_job()
        _login(client, "boss@example.com", "EmployerPass#2026")
        assert "Find Workers" in client.get("/").get_data(as_text=True)
        _logout(client)
        visitor_html = client.get("/").get_data(as_text=True)
        assert "Find Workers" not in visitor_html
        assert "Sign In" in visitor_html
        _login(client, "switch.worker@example.com", "WorkerPass#2026")
        worker_html = client.get("/").get_data(as_text=True)
        assert "Find Local Jobs" in worker_html
        assert "Find Workers" not in worker_html

    def test_visitor_redirected_from_protected_pages(
        self, app: Flask, client: FlaskClient
    ) -> None:
        with app.app_context():
            _, job_id = _make_employer_with_job()
        for url in ("/jobs", f"/jobs/{job_id}", "/find-workers", "/worker/dashboard",
                    "/employer/dashboard", "/?find_work=1"):
            resp = client.get(url, follow_redirects=False)
            assert resp.status_code == 302, url
            assert "/auth/login" in resp.headers["Location"], url

    def test_worker_can_access_job_search_and_apply(
        self, app: Flask, client: FlaskClient
    ) -> None:
        with app.app_context():
            _, job_id = _make_employer_with_job()
            _make_worker("apply.worker@example.com")
        _login(client, "apply.worker@example.com", "WorkerPass#2026")
        resp = client.get("/jobs")
        assert resp.status_code == 200
        assert "Real Database Counter Role" in resp.get_data(as_text=True)
        detail = client.get(f"/jobs/{job_id}").get_data(as_text=True)
        assert "Apply for This Job" in detail

    def test_employer_cannot_search_or_apply_for_jobs(
        self, app: Flask, client: FlaskClient
    ) -> None:
        with app.app_context():
            _, job_id = _make_employer_with_job()
            other, other_job_id = _make_employer_with_job("other.boss@example.com")
        _login(client, "boss@example.com", "EmployerPass#2026")

        resp = client.get("/jobs", follow_redirects=False)
        assert resp.status_code == 302
        assert "/employer/dashboard" in resp.headers["Location"]

        # Another employer's job page redirects instead of showing apply actions
        resp = client.get(f"/jobs/{other_job_id}", follow_redirects=False)
        assert resp.status_code == 302

        csrf = _csrf(client.get("/employer/dashboard").get_data(as_text=True))
        assert client.post(
            f"/jobs/{other_job_id}/apply", data={"csrf_token": csrf}
        ).status_code == 403
        assert client.post(
            f"/jobs/{other_job_id}/save", data={"csrf_token": csrf}
        ).status_code == 403
        assert client.get("/worker/dashboard").status_code == 403
        assert client.get("/worker/saved-jobs").status_code == 403

        # Owner can still view own listing without apply actions
        own = client.get(f"/jobs/{job_id}").get_data(as_text=True)
        assert "Apply for This Job" not in own

    def test_worker_cannot_access_employer_routes(
        self, app: Flask, client: FlaskClient
    ) -> None:
        with app.app_context():
            _, job_id = _make_employer_with_job()
            _make_worker("blocked.worker@example.com")
        _login(client, "blocked.worker@example.com", "WorkerPass#2026")
        for url in ("/employer/dashboard", "/employer/jobs/new", "/find-workers",
                    "/employer/applicants", f"/employer/jobs/{job_id}/applicants",
                    f"/employer/jobs/{job_id}/edit"):
            assert client.get(url).status_code == 403, url
        detail = client.get(f"/jobs/{job_id}").get_data(as_text=True)
        assert "Edit Job Details" not in detail
        assert "Manage Applicants" not in detail


class TestWorkerCountAndDirectory:
    def test_worker_count_only_includes_eligible_records(self, app: Flask) -> None:
        with app.app_context():
            assert count_available_workers() == 0
            _make_worker("eligible1@example.com")
            _make_worker("eligible2@example.com", pincode="560038")
            _make_worker("private@example.com", public=False)
            _make_worker("suspended@example.com", status="suspended")
            _make_worker("deleted@example.com", status="deleted")
            _make_worker("incomplete@example.com", complete=False)
            _make_employer_with_job()

            assert count_available_workers() == 2
            assert count_available_workers(location="560038") == 1
            assert count_available_workers(location="999999") == 0

    def test_employer_dashboard_shows_real_count_and_empty_message(
        self, app: Flask, client: FlaskClient
    ) -> None:
        with app.app_context():
            _make_employer_with_job()
        _login(client, "boss@example.com", "EmployerPass#2026")
        html = client.get("/employer/dashboard").get_data(as_text=True)
        assert "No workers are currently available. Check back as more people join" in html

        with app.app_context():
            _make_worker("count1@example.com")
            _make_worker("count2@example.com")
            _make_worker("hidden@example.com", public=False)
        html = client.get("/employer/dashboard").get_data(as_text=True)
        assert "2 workers available in your area" in html
        area_html = client.get("/employer/dashboard?area=560041").get_data(as_text=True)
        assert "2 workers available in your area (560041)" in area_html

    def test_find_workers_directory_privacy_filters_and_empty_state(
        self, app: Flask, client: FlaskClient
    ) -> None:
        with app.app_context():
            _make_employer_with_job()
            _make_worker("visible@example.com")
            _make_worker("private.one@example.com", public=False)
        _login(client, "boss@example.com", "EmployerPass#2026")

        html = client.get("/find-workers").get_data(as_text=True)
        assert "Worker visible" in html
        assert "Worker private.one" not in html
        assert "visible@example.com" not in html
        assert "+919811122233" not in html
        assert "1 worker available in your area" in html

        empty = client.get("/find-workers?q=Forklift").get_data(as_text=True)
        assert (
            "No workers are currently available for these filters. "
            "Try changing your search criteria or check again later."
        ) in empty


class TestJobVisibility:
    def test_empty_database_shows_job_empty_state_and_no_demo_listings(
        self, app: Flask, client: FlaskClient
    ) -> None:
        with app.app_context():
            _make_worker("empty.worker@example.com")
        _login(client, "empty.worker@example.com", "WorkerPass#2026")
        html = client.get("/jobs").get_data(as_text=True)
        assert "No local jobs available yet." in html
        assert "New opportunities will appear here when employers publish" in html
        for demo_title in (
            "Local Neighbourhood Parcel Sorting",
            "Evening Grocery Billing",
            "Morning Breakfast Counter",
        ):
            assert demo_title not in html

    def test_job_results_come_from_database_and_exclude_ineligible(
        self, app: Flask, client: FlaskClient
    ) -> None:
        with app.app_context():
            emp, job_id = _make_employer_with_job()
            assert emp.employer_profile is not None
            expired = Job(
                employer_id=emp.employer_profile.id,
                title="Expired Listing Role",
                category="Retail",
                job_type="daily_wage",
                description="x",
                responsibilities="x",
                location="Jayanagar",
                pincode="560041",
                wage_amount=Decimal("500"),
                currency="INR",
                wage_frequency="daily",
                working_hours="9-5",
                vacancies=1,
                application_deadline=datetime.now(UTC).date() - timedelta(days=1),
                status="published",
            )
            db.session.add(expired)
            suspended_emp, _ = _make_employer_with_job("suspended.boss@example.com")
            suspended_emp.account_status = "suspended"
            db.session.commit()
            _make_worker("db.worker@example.com")

        _login(client, "db.worker@example.com", "WorkerPass#2026")
        html = client.get("/jobs").get_data(as_text=True)
        assert "Open Local Job Listings (1)" in html
        assert "Real Database Counter Role" in html
        assert "Expired Listing Role" not in html
