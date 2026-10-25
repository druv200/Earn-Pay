"""Phase 7 & 8 Automated Tests: Job Creation, Discovery, Applications, Saved Jobs & Hiring."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from flask import Flask
from flask.testing import FlaskClient

from app.extensions import db
from app.models import Job, JobApplication
from app.services import register_user_account

_CSRF_RE = re.compile(r'name="csrf_token"\s+type="hidden"\s+value="([^"]+)"')


def _get_csrf(html: str) -> str:
    match = _CSRF_RE.search(html)
    assert match is not None, "Expected hidden csrf_token in form"
    return match.group(1)


def _login(client: FlaskClient, email: str, password: str) -> None:
    login_html = client.get("/auth/login").get_data(as_text=True)
    csrf_token = _get_csrf(login_html)
    resp = client.post(
        "/auth/login",
        data={"csrf_token": csrf_token, "email": email, "password": password},
    )
    assert resp.status_code == 302


def _logout(client: FlaskClient) -> None:
    home_html = client.get("/").get_data(as_text=True)
    csrf_token = _get_csrf(home_html)
    client.post("/auth/logout", data={"csrf_token": csrf_token})


class TestPhase7JobCreationDraftPreviewAndDiscovery:
    """Verify job creation, draft preview visibility, ownership editing, and discovery filters."""

    def test_employer_creates_draft_previews_edits_and_publishes_job(
        self, app: Flask, client: FlaskClient
    ) -> None:
        with app.app_context():
            register_user_account(
                full_name="Srinivas Murthy",
                email="srinivas@example.com",
                password="EmployerPass#2026",
                role="employer",
                business_name="Murthy Medicals & General",
            )
            register_user_account(
                full_name="Other Employer",
                email="other.emp@example.com",
                password="EmployerPass#2026",
                role="employer",
                business_name="Other Shop",
            )

        _login(client, "srinivas@example.com", "EmployerPass#2026")
        form_html = client.get("/employer/jobs/new").get_data(as_text=True)
        csrf_token = _get_csrf(form_html)
        deadline_str = (datetime.now(UTC).date() + timedelta(days=10)).strftime("%Y-%m-%d")

        # 1. Create as Draft Preview
        create_resp = client.post(
            "/employer/jobs/new",
            data={
                "csrf_token": csrf_token,
                "title": "Pharmacy Counter & Delivery Assistant",
                "category": "Retail",
                "job_type": "daily_wage",
                "description": "Assist customers at the pharmacy counter and deliver local orders.",
                "responsibilities": "Pack medicines checked by pharmacist, local delivery.",
                "required_skills": "Billing, Two-wheeler",
                "experience_required": "6 months retail",
                "location": "Basavanagudi, Bengaluru",
                "pincode": "560004",
                "wage_amount": "800.00",
                "wage_frequency": "daily",
                "working_hours": "9:00 AM - 6:00 PM",
                "vacancies": "2",
                "application_deadline": deadline_str,
                "submit_action": "preview",
            },
            follow_redirects=True,
        )
        assert create_resp.status_code == 200
        preview_html = create_resp.get_data(as_text=True)
        assert "Draft Preview — Only visible to you until published" in preview_html

        with app.app_context():
            job = Job.query.filter_by(title="Pharmacy Counter & Delivery Assistant").one()
            job_id = job.id
            assert job.status == "draft"

        # 2. Anonymous visitor or another employer cannot view draft (404) or edit it (403)
        _logout(client)
        assert client.get(f"/jobs/{job_id}").status_code == 404

        _login(client, "other.emp@example.com", "EmployerPass#2026")
        assert client.get(f"/jobs/{job_id}").status_code == 404
        assert client.get(f"/employer/jobs/{job_id}/edit").status_code == 403
        _logout(client)

        # 3. Owning employer edits wage to 850 and publishes
        _login(client, "srinivas@example.com", "EmployerPass#2026")
        edit_html = client.get(f"/employer/jobs/{job_id}/edit").get_data(as_text=True)
        edit_csrf = _get_csrf(edit_html)
        edit_resp = client.post(
            f"/employer/jobs/{job_id}/edit",
            data={
                "csrf_token": edit_csrf,
                "title": "Pharmacy Counter & Delivery Assistant",
                "category": "Retail",
                "job_type": "daily_wage",
                "description": "Assist customers at the pharmacy counter and deliver local orders.",
                "responsibilities": "Pack medicines checked by pharmacist, local delivery.",
                "required_skills": "Billing, Two-wheeler",
                "experience_required": "6 months retail",
                "location": "Basavanagudi, Bengaluru",
                "pincode": "560004",
                "wage_amount": "850.00",
                "wage_frequency": "daily",
                "working_hours": "9:00 AM - 6:00 PM",
                "vacancies": "2",
                "application_deadline": deadline_str,
                "submit_action": "publish",
            },
            follow_redirects=True,
        )
        assert edit_resp.status_code == 200
        assert "₹850 / daily" in edit_resp.get_data(as_text=True)

        # 4. Employers cannot use worker job discovery
        assert client.get("/jobs").status_code == 302
        _logout(client)

        # 5. Verify Job Discovery search, wage filter, and sorting as a Worker
        with app.app_context():
            register_user_account(
                full_name="Discovery Worker",
                email="discovery.worker@example.com",
                password="WorkerPass#2026",
                role="worker",
            )
        _login(client, "discovery.worker@example.com", "WorkerPass#2026")
        disc_resp = client.get(
            "/jobs?q=Pharmacy&location=560004&category=Retail&job_type=daily_wage&min_wage=800&sort=wage_high"
        )
        assert disc_resp.status_code == 200
        assert "Pharmacy Counter &amp; Delivery Assistant" in disc_resp.get_data(as_text=True)

        no_match = client.get("/jobs?min_wage=5000")
        assert "No local jobs available yet." in no_match.get_data(as_text=True)


class TestPhase8ApplicationsSavedJobsHiringAndNotifications:
    """Verify applying, saving jobs, applicant management, private notes, and notifications."""

    def test_end_to_end_apply_save_schedule_interview_accept_and_notify(
        self, app: Flask, client: FlaskClient
    ) -> None:
        with app.app_context():
            emp, _ = register_user_account(
                full_name="Harish Gowda",
                email="harish@example.com",
                password="EmployerPass#2026",
                role="employer",
                business_name="Gowda Fresh Mart",
            )
            worker, _ = register_user_account(
                full_name="Manjunath K",
                email="manju@example.com",
                password="WorkerPass#2026",
                role="worker",
            )
            assert emp.employer_profile is not None
            job = Job(
                employer_id=emp.employer_profile.id,
                title="Vegetable & Fruit Counter Helper",
                category="Retail",
                job_type="daily_wage",
                description="Sort fresh produce and weigh customer baskets.",
                responsibilities="Weighing, stacking crates.",
                required_skills="Digital scale, Kannada",
                location="Vijayanagar, Bengaluru",
                pincode="560040",
                wage_amount=Decimal("720.00"),
                currency="INR",
                wage_frequency="daily",
                working_hours="7:00 AM - 3:00 PM",
                vacancies=2,
                application_deadline=datetime.now(UTC).date() + timedelta(days=7),
                status="published",
            )
            job.publish()
            db.session.add(job)
            db.session.commit()
            job_id = job.id

        # 1. Worker logs in, bookmarks job, and submits an application
        _login(client, "manju@example.com", "WorkerPass#2026")
        detail_html = client.get(f"/jobs/{job_id}").get_data(as_text=True)
        csrf_token = _get_csrf(detail_html)

        save_resp = client.post(
            f"/jobs/{job_id}/save",
            data={"csrf_token": csrf_token},
            follow_redirects=True,
        )
        assert "Job saved to your bookmarks." in save_resp.get_data(as_text=True)

        saved_page = client.get("/worker/saved-jobs")
        assert "Vegetable &amp; Fruit Counter Helper" in saved_page.get_data(as_text=True)

        apply_csrf = _get_csrf(client.get(f"/jobs/{job_id}").get_data(as_text=True))
        apply_resp = client.post(
            f"/jobs/{job_id}/apply",
            data={
                "csrf_token": apply_csrf,
                "cover_note": "I have 2 years experience with digital weighing scales.",
            },
            follow_redirects=True,
        )
        assert "Your application has been submitted!" in apply_resp.get_data(as_text=True)

        with app.app_context():
            app_rec = JobApplication.query.filter_by(job_id=job_id).one()
            app_id = app_rec.id

        # 2. Employer logs in, opens Applicant Management, schedules interview & writes private note
        _logout(client)
        _login(client, "harish@example.com", "EmployerPass#2026")

        applicants_resp = client.get(f"/employer/jobs/{job_id}/applicants")
        assert applicants_resp.status_code == 200
        applicants_html = applicants_resp.get_data(as_text=True)
        assert "Manjunath K" in applicants_html
        assert "digital weighing scales" in applicants_html

        mgr_csrf = _get_csrf(applicants_html)
        update_resp = client.post(
            f"/employer/applications/{app_id}/update",
            data={
                "csrf_token": mgr_csrf,
                "target_status": "interview_scheduled",
                "interview_date": "2026-11-05 10:00",
                "interview_details": "Ask for Harish at Shop #4, Vijayanagar Main Road.",
                "employer_private_notes": "CONFIDENTIAL_EMPLOYER_NOTE_DO_NOT_SHOW_WORKER",
            },
            follow_redirects=True,
        )
        assert update_resp.status_code == 200
        assert "CONFIDENTIAL_EMPLOYER_NOTE_DO_NOT_SHOW_WORKER" in update_resp.get_data(
            as_text=True
        )

        # 3. Worker checks dashboard & notifications: sees interview details, not private note
        _logout(client)
        _login(client, "manju@example.com", "WorkerPass#2026")

        worker_dash_html = client.get("/worker/dashboard").get_data(as_text=True)
        assert "Ask for Harish at Shop #4, Vijayanagar Main Road." in worker_dash_html
        assert "CONFIDENTIAL_EMPLOYER_NOTE_DO_NOT_SHOW_WORKER" not in worker_dash_html

        notif_resp = client.get("/notifications")
        assert notif_resp.status_code == 200
        notif_html = notif_resp.get_data(as_text=True)
        assert "Application update: Vegetable &amp; Fruit Counter Helper" in notif_html

        # Mark all notifications read
        notif_csrf = _get_csrf(notif_html)
        mark_resp = client.post(
            "/notifications/read-all",
            data={"csrf_token": notif_csrf},
            follow_redirects=True,
        )
        assert "Notifications (0 Unread)" in mark_resp.get_data(as_text=True)

        # 4. Worker withdraws application
        job_page_html = client.get(f"/jobs/{job_id}").get_data(as_text=True)
        withdraw_csrf = _get_csrf(job_page_html)
        withdraw_resp = client.post(
            f"/applications/{app_id}/withdraw",
            data={"csrf_token": withdraw_csrf},
            follow_redirects=True,
        )
        assert "Your application has been withdrawn." in withdraw_resp.get_data(as_text=True)
