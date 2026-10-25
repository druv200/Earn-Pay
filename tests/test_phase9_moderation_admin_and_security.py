"""Phase 9 Automated Tests: Suspicious Job Reporting, Admin Console, Verification & Data Export."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from flask import Flask
from flask.testing import FlaskClient

from app.extensions import db
from app.models import AuditEvent, EmployerProfile, Job, Notification, Report, User
from app.services import (
    DomainRuleError,
    create_or_promote_admin_user,
    register_user_account,
    set_user_account_status,
)

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


class TestModerationReportingAndAdminResolution:
    """Verify suspicious job reporting, admin resolution, and atomic listing hiding."""

    def test_worker_submits_suspicious_job_report_and_admin_resolves_with_archive(
        self, app: Flask, client: FlaskClient
    ) -> None:
        with app.app_context():
            create_or_promote_admin_user(
                email="moderator@earnandpay.in",
                full_name="Lead Moderator",
                password="AdminPass#2026",
            )
            emp, _ = register_user_account(
                full_name="Suspicious Employer",
                email="suspect@example.com",
                password="EmployerPass#2026",
                role="employer",
                business_name="Quick Cash Agency",
            )
            register_user_account(
                full_name="Alert Worker",
                email="alert.worker@example.com",
                password="WorkerPass#2026",
                role="worker",
            )
            assert emp.employer_profile is not None
            job = Job(
                employer_id=emp.employer_profile.id,
                title="Data Entry Counter Helper",
                category="Office & Billing",
                job_type="daily_wage",
                description="Simple counter billing role.",
                responsibilities="Billing and filing.",
                location="Majestic, Bengaluru",
                pincode="560009",
                wage_amount=Decimal("900.00"),
                currency="INR",
                wage_frequency="daily",
                working_hours="9:00 AM - 5:00 PM",
                vacancies=2,
                application_deadline=datetime.now(UTC).date() + timedelta(days=10),
                status="published",
            )
            job.publish()
            db.session.add(job)
            db.session.commit()
            job_id = job.id

        # 1. Worker logs in and submits a report flagging an illegal fee demand
        _login(client, "alert.worker@example.com", "WorkerPass#2026")
        report_form_html = client.get(
            f"/reports/new?target_type=job&target_id={job_id}"
        ).get_data(as_text=True)
        assert "Data Entry Counter Helper" in report_form_html
        csrf_token = _get_csrf(report_form_html)

        submit_resp = client.post(
            "/reports/new",
            data={
                "csrf_token": csrf_token,
                "target_type": "job",
                "target_id": str(job_id),
                "reason": "fee_demand",
                "details": "Caller demanded a Rs 500 ID card registration fee before joining.",
            },
            follow_redirects=True,
        )
        assert submit_resp.status_code == 200
        assert "has been submitted to Trust &amp; Safety" in submit_resp.get_data(as_text=True)

        with app.app_context():
            report = Report.query.filter_by(target_type="job", target_id=job_id).one()
            report_id = report.id
            assert report.status == "open"

        # 2. Admin logs in, inspects report queue, resolves report & hides listing
        _logout(client)
        _login(client, "moderator@earnandpay.in", "AdminPass#2026")

        dash_resp = client.get("/admin/dashboard")
        assert dash_resp.status_code == 200
        assert "Data Entry Counter Helper" in client.get("/admin/reports").get_data(as_text=True)

        reports_html = client.get("/admin/reports").get_data(as_text=True)
        admin_csrf = _get_csrf(reports_html)

        resolve_resp = client.post(
            f"/admin/reports/{report_id}/resolve",
            data={
                "csrf_token": admin_csrf,
                "status": "resolved",
                "moderation_action": "listing_hidden",
                "resolution_notes": "Confirmed illegal fee demand; listing archived.",
            },
            follow_redirects=True,
        )
        assert resolve_resp.status_code == 200
        assert f"Report #{report_id} updated to &#39;resolved&#39;" in resolve_resp.get_data(
            as_text=True
        )

        # 3. Verify job is now archived and both employer & reporter received notifications
        with app.app_context():
            updated_job = db.session.get(Job, job_id)
            assert updated_job is not None
            assert updated_job.status == "archived"

            updated_report = db.session.get(Report, report_id)
            assert updated_report is not None
            assert updated_report.status == "resolved"
            assert updated_report.moderation_action == "listing_hidden"

            notifs = Notification.query.all()
            assert len(notifs) >= 2


class TestAdminRBACVerificationAndGovernance:
    """Verify strict admin RBAC, employer badge truth rules, user suspension, and data export."""

    def test_admin_rbac_protects_all_admin_routes_from_workers_and_employers(
        self, app: Flask, client: FlaskClient
    ) -> None:
        with app.app_context():
            register_user_account(
                full_name="Normal Worker",
                email="normal.w@example.com",
                password="WorkerPass#2026",
                role="worker",
            )
            register_user_account(
                full_name="Normal Employer",
                email="normal.e@example.com",
                password="EmployerPass#2026",
                role="employer",
                business_name="Normal Shop",
            )

        _login(client, "normal.w@example.com", "WorkerPass#2026")
        assert client.get("/admin/dashboard").status_code == 403
        assert client.get("/admin/reports").status_code == 403
        assert client.get("/admin/employers").status_code == 403
        _logout(client)

        _login(client, "normal.e@example.com", "EmployerPass#2026")
        assert client.get("/admin/dashboard").status_code == 403
        assert client.get("/admin/reports").status_code == 403
        assert client.get("/admin/employers").status_code == 403

    def test_admin_employer_verification_approval_and_revocation(
        self, app: Flask, client: FlaskClient
    ) -> None:
        with app.app_context():
            create_or_promote_admin_user(
                email="admin.verify@earnandpay.in",
                full_name="Verification Admin",
                password="AdminPass#2026",
            )
            emp_user, _ = register_user_account(
                full_name="Anand Bakery Owner",
                email="anand.bakery@example.com",
                password="EmployerPass#2026",
                role="employer",
                business_name="Anand Iyengar Bakery",
            )
            assert emp_user.employer_profile is not None
            emp_user.employer_profile.verification_status = "pending"
            db.session.commit()
            emp_id = emp_user.employer_profile.id

        _login(client, "admin.verify@earnandpay.in", "AdminPass#2026")
        emp_queue_html = client.get("/admin/employers?status=pending").get_data(as_text=True)
        assert "Anand Iyengar Bakery" in emp_queue_html
        csrf_token = _get_csrf(emp_queue_html)

        # Approve verification
        approve_resp = client.post(
            f"/admin/employers/{emp_id}/verify",
            data={
                "csrf_token": csrf_token,
                "decision": "verified",
                "verification_notes": "Verified GST & trade licence in Malleshwaram.",
            },
            follow_redirects=True,
        )
        assert approve_resp.status_code == 200

        with app.app_context():
            emp_prof = db.session.get(EmployerProfile, emp_id)
            assert emp_prof is not None
            assert emp_prof.verification_status == "verified"
            assert emp_prof.verified_at is not None
            assert emp_prof.is_genuinely_verified is True

        # Revoke verification -> must clear verified_at
        revoke_csrf = _get_csrf(client.get("/admin/employers").get_data(as_text=True))
        client.post(
            f"/admin/employers/{emp_id}/verify",
            data={
                "csrf_token": revoke_csrf,
                "decision": "unverified",
                "verification_notes": "Licence expired.",
            },
            follow_redirects=True,
        )

        with app.app_context():
            emp_prof = db.session.get(EmployerProfile, emp_id)
            assert emp_prof is not None
            assert emp_prof.verification_status == "unverified"
            assert emp_prof.verified_at is None
            assert emp_prof.is_genuinely_verified is False

    def test_admin_user_suspension_and_self_suspension_protection(
        self, app: Flask, client: FlaskClient
    ) -> None:
        with app.app_context():
            admin = create_or_promote_admin_user(
                email="root.admin@earnandpay.in",
                full_name="Root Admin",
                password="AdminPass#2026",
            )
            bad_user, _ = register_user_account(
                full_name="Spam Account",
                email="spam@example.com",
                password="WorkerPass#2026",
                role="worker",
            )
            admin_id = admin.id
            bad_user_id = bad_user.id

            # Admin cannot self-suspend
            with pytest.raises(DomainRuleError, match="cannot suspend or modify their own"):
                set_user_account_status(
                    admin_user=admin,
                    target_user_id=admin_id,
                    target_status="suspended",
                )

        _login(client, "root.admin@earnandpay.in", "AdminPass#2026")
        dash_html = client.get("/admin/dashboard").get_data(as_text=True)
        csrf_token = _get_csrf(dash_html)

        resp = client.post(
            f"/admin/users/{bad_user_id}/status",
            data={
                "csrf_token": csrf_token,
                "target_status": "suspended",
                "reason": "Repeated spam listings",
            },
            follow_redirects=True,
        )
        assert resp.status_code == 200

        with app.app_context():
            target = db.session.get(User, bad_user_id)
            assert target is not None
            assert target.account_status == "suspended"

    def test_personal_data_json_export_and_create_admin_cli(
        self, app: Flask, client: FlaskClient
    ) -> None:
        runner = app.test_cli_runner()
        cli_result = runner.invoke(
            args=[
                "create-admin",
                "--email",
                "cli.admin@earnandpay.in",
                "--name",
                "CLI Admin",
                "--password",
                "AdminPass#2026",
            ]
        )
        assert cli_result.exit_code == 0
        assert "[OK] Admin user ready" in cli_result.output

        with app.app_context():
            register_user_account(
                full_name="Data Export Worker",
                email="export.worker@example.com",
                password="WorkerPass#2026",
                role="worker",
            )

        _login(client, "export.worker@example.com", "WorkerPass#2026")
        export_resp = client.get("/account/export-data")
        assert export_resp.status_code == 200
        assert export_resp.mimetype == "application/json"
        assert "attachment; filename=earnandpay_data_export_user_" in export_resp.headers.get(
            "Content-Disposition", ""
        )
        payload = export_resp.get_json()
        assert payload["platform"] == "Earn & Pay"
        assert payload["account"]["email"] == "export.worker@example.com"
        assert "password" not in str(payload).lower()

        with app.app_context():
            export_audit = AuditEvent.query.filter_by(action="user.data_exported").first()
            assert export_audit is not None
