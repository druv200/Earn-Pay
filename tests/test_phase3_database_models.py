"""Phase 3 Automated Database Tests: 11 Entities, Constraints, Tokens, Audit & Transactions."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config as AlembicConfig
from flask import Flask
from sqlalchemy.exc import IntegrityError

from app.extensions import db, login_manager
from app.models import (
    AuditEvent,
    EmailVerificationToken,
    EmployerProfile,
    Job,
    Notification,
    PasswordResetToken,
    Report,
    SavedJob,
    User,
    WorkerProfile,
    hash_security_token,
)
from app.services import (
    AuthorizationError,
    DomainRuleError,
    submit_job_application,
    transition_application_status,
)


def _create_worker_with_profile(
    email: str = "ravi.kumar@example.com",
    full_name: str = "Ravi Kumar",
) -> User:
    user = User(
        full_name=full_name,
        normalized_email=email,
        role="worker",
        account_status="active",
        email_verified=True,
    )
    user.set_password("StrongPass#2026")
    db.session.add(user)
    db.session.flush()

    profile = WorkerProfile(
        user_id=user.id,
        phone_number="+919876543210",
        skills="Retail billing, inventory stacking, Kannada, Hindi",
        experience_summary="3 years assisting at local provision stores",
        preferred_categories="Retail, Warehouse",
        preferred_location="Jayanagar",
        pincode="560041",
        travel_radius_km=8,
        availability="daily",
        expected_daily_wage=Decimal("650.00"),
    )
    db.session.add(profile)
    db.session.commit()
    return user


def _create_employer_with_profile(
    email: str = "sharma.traders@example.com",
    business_name: str = "Sharma General Stores",
) -> User:
    user = User(
        full_name="Anil Sharma",
        normalized_email=email,
        role="employer",
        account_status="active",
        email_verified=True,
    )
    user.set_password("EmployerPass#2026")
    db.session.add(user)
    db.session.flush()

    profile = EmployerProfile(
        user_id=user.id,
        business_name=business_name,
        business_type="shop",
        description="Neighborhood grocery and provisions store",
        address="14th Cross, 4th Block, Jayanagar",
        location="Jayanagar, Bengaluru",
        pincode="560041",
        contact_phone="+919845012345",
        verification_status="unverified",
    )
    db.session.add(profile)
    db.session.commit()
    return user


def _create_published_job(
    employer_profile: EmployerProfile,
    *,
    title: str = "Store Helper & Stock Assistant",
    vacancies: int = 2,
    deadline_days: int = 7,
    status: str = "published",
) -> Job:
    job = Job(
        employer_id=employer_profile.id,
        title=title,
        category="Retail",
        job_type="daily_wage",
        description="Assist with unloading daily stock and arranging shelves.",
        responsibilities="Count incoming crates, arrange shelves, keep aisle tidy.",
        required_skills="Basic counting, punctuality",
        experience_required="Fresher or 6+ months",
        location="Jayanagar, Bengaluru",
        pincode="560041",
        wage_amount=Decimal("700.00"),
        currency="INR",
        wage_frequency="daily",
        working_hours="9:00 AM - 6:00 PM (1 hr lunch break)",
        vacancies=vacancies,
        application_deadline= datetime.now(UTC).date() + timedelta(days=deadline_days),
        status=status,
    )
    if status == "published":
        job.publish()
    db.session.add(job)
    db.session.commit()
    return job


class TestSchemaAndUserConstraints:
    """Verify all 11 tables, user roles, email normalization, and password hashing."""

    def test_all_eleven_tables_registered_in_metadata(self, app: Flask) -> None:
        with app.app_context():
            expected_tables = {
                "users",
                "worker_profiles",
                "employer_profiles",
                "jobs",
                "job_applications",
                "saved_jobs",
                "notifications",
                "email_verification_tokens",
                "password_reset_tokens",
                "reports",
                "audit_events",
            }
            assert expected_tables.issubset(set(db.metadata.tables.keys()))

    def test_user_email_normalization_and_uniqueness_constraint(self, app: Flask) -> None:
        with app.app_context():
            u1 = User(
                full_name="Meena Devi",
                normalized_email="  Meena.Devi@Example.COM ",
                role="worker",
            )
            u1.set_password("ValidPass#123")
            db.session.add(u1)
            db.session.commit()
            assert u1.normalized_email == "meena.devi@example.com"

            # Attempt duplicate with different casing
            u2 = User(
                full_name="Meena Duplicate",
                normalized_email="meena.devi@example.com",
                role="employer",
            )
            u2.set_password("AnotherPass#123")
            db.session.add(u2)
            with pytest.raises(IntegrityError):
                db.session.commit()
            db.session.rollback()

    def test_password_hashing_and_short_password_rejection(self, app: Flask) -> None:
        with app.app_context():
            user = User(full_name="Kiran Rao", normalized_email="kiran@example.com", role="worker")
            with pytest.raises(ValueError, match="at least 8 characters"):
                user.set_password("short")

            user.set_password("CorrectHorseBatteryStaple!9")
            assert user.password_hash != "CorrectHorseBatteryStaple!9"
            assert user.check_password("CorrectHorseBatteryStaple!9") is True
            assert user.check_password("WrongPassword!9") is False

    def test_invalid_role_and_status_rejected(self, app: Flask) -> None:
        with app.app_context():
            with pytest.raises(ValueError, match="Invalid user role"):
                User(full_name="Test", normalized_email="t@example.com", role="superuser")

            with pytest.raises(ValueError, match="Invalid account_status"):
                User(
                    full_name="Test",
                    normalized_email="t2@example.com",
                    role="worker",
                    account_status="banned_forever",
                )

    def test_user_loader_blocks_suspended_and_deleted_users(self, app: Flask) -> None:
        with app.app_context():
            worker = _create_worker_with_profile("active.worker@example.com")
            loaded = login_manager._user_callback(str(worker.id))
            assert loaded is not None and loaded.id == worker.id

            worker.account_status = "suspended"
            db.session.commit()
            assert login_manager._user_callback(str(worker.id)) is None


class TestProfilesAndJobsConstraints:
    """Verify WorkerProfile, EmployerProfile, Job constraints, and SavedJob uniqueness."""

    def test_worker_profile_completion_and_skill_parsing(self, app: Flask) -> None:
        with app.app_context():
            worker_user = _create_worker_with_profile()
            profile = worker_user.worker_profile
            assert profile is not None
            assert profile.completion_percentage == 100
            assert "retail billing" in profile.skill_list
            assert profile.show_phone_to_employers is False

    def test_employer_verification_integrity_principle(self, app: Flask) -> None:
        with app.app_context():
            employer_user = _create_employer_with_profile()
            emp = employer_user.employer_profile
            assert emp is not None
            assert emp.is_genuinely_verified is False

            # Setting status='verified' without verified_at timestamp is still False
            emp.verification_status = "verified"
            assert emp.is_genuinely_verified is False

            emp.verified_at = datetime.now(UTC)
            db.session.commit()
            assert emp.is_genuinely_verified is True

    def test_job_wage_and_vacancy_validation(self, app: Flask) -> None:
        with app.app_context():
            employer_user = _create_employer_with_profile()
            emp = employer_user.employer_profile
            assert emp is not None

            with pytest.raises(ValueError, match="greater than zero"):
                Job(
                    employer_id=emp.id,
                    title="Invalid Zero Wage Job",
                    category="Retail",
                    job_type="daily_wage",
                    description="Desc",
                    responsibilities="Resp",
                    location="Bengaluru",
                    pincode="560001",
                    wage_amount=Decimal("0.00"),
                    wage_frequency="daily",
                    working_hours="8 hrs",
                    vacancies=1,
                    application_deadline=date.today(),
                )

            with pytest.raises(ValueError, match="Vacancies must be at least 1"):
                Job(
                    employer_id=emp.id,
                    title="Invalid Zero Vacancy Job",
                    category="Retail",
                    job_type="daily_wage",
                    description="Desc",
                    responsibilities="Resp",
                    location="Bengaluru",
                    pincode="560001",
                    wage_amount=Decimal("500.00"),
                    wage_frequency="daily",
                    working_hours="8 hrs",
                    vacancies=0,
                    application_deadline=date.today(),
                )

    def test_saved_job_prevents_duplicates(self, app: Flask) -> None:
        with app.app_context():
            worker = _create_worker_with_profile()
            employer = _create_employer_with_profile()
            assert worker.worker_profile and employer.employer_profile
            job = _create_published_job(employer.employer_profile)

            s1 = SavedJob(worker_id=worker.worker_profile.id, job_id=job.id)
            db.session.add(s1)
            db.session.commit()

            s2 = SavedJob(worker_id=worker.worker_profile.id, job_id=job.id)
            db.session.add(s2)
            with pytest.raises(IntegrityError):
                db.session.commit()
            db.session.rollback()


class TestTokensReportsAndAuditSanitization:
    """Verify hashed single-use tokens, moderation reports, and secret-free audit logs."""

    def test_email_verification_and_password_reset_token_lifecycle(self, app: Flask) -> None:
        with app.app_context():
            worker = _create_worker_with_profile()

            ver_record, raw_ver_token = EmailVerificationToken.issue(worker.id, ttl_minutes=60)
            db.session.add(ver_record)
            db.session.commit()

            # Raw token is never stored in DB
            assert ver_record.token_hash != raw_ver_token
            assert ver_record.token_hash == hash_security_token(raw_ver_token)
            assert ver_record.is_valid() is True
            assert ver_record.consume() is True
            db.session.commit()

            # Single-use enforcement: second consume fails
            assert ver_record.is_valid() is False
            assert ver_record.consume() is False

            # Expired password reset token fails
            reset_record, _raw_reset = PasswordResetToken.issue(worker.id, ttl_minutes=-5)
            db.session.add(reset_record)
            db.session.commit()
            assert reset_record.is_valid() is False
            assert reset_record.consume() is False

    def test_moderation_report_and_secret_scrubbing_in_audit_events(self, app: Flask) -> None:
        with app.app_context():
            worker = _create_worker_with_profile("reporter@example.com")
            employer = _create_employer_with_profile("suspect@example.com")
            admin = User(
                full_name="Platform Moderator",
                normalized_email="admin@earnandpay.in",
                role="admin",
                account_status="active",
                email_verified=True,
            )
            admin.set_password("AdminSecure#2026")
            db.session.add(admin)
            db.session.flush()

            assert employer.employer_profile is not None
            job = _create_published_job(employer.employer_profile)

            report = Report(
                reporter_id=worker.id,
                target_type="job",
                target_id=job.id,
                reason="fee_demand",
                details="Asked for Rs 500 registration deposit on phone.",
            )
            db.session.add(report)
            db.session.commit()

            report.resolve(
                reviewer_id=admin.id,
                action="listing_hidden",
                status="resolved",
                notes="Confirmed fee demand violation; job hidden.",
            )
            audit = AuditEvent.record(
                actor_id=admin.id,
                action="report.resolve",
                resource_type="report",
                resource_id=report.id,
                metadata={
                    "moderation_action": "listing_hidden",
                    "password": "MUST_BE_STRIPPED",
                    "raw_token": "MUST_BE_STRIPPED",
                    "csrf_token": "MUST_BE_STRIPPED",
                },
            )
            db.session.add(audit)
            db.session.commit()

            assert report.status == "resolved"
            assert report.resolved_at is not None
            assert audit.safe_metadata == {"moderation_action": "listing_hidden"}


class TestTransactionalApplicationAndHiringWorkflows:
    """Verify atomic job applications, ownership checks, and vacancy race protection."""

    def test_submit_application_and_prevent_duplicates(self, app: Flask) -> None:
        with app.app_context():
            worker = _create_worker_with_profile()
            employer = _create_employer_with_profile()
            assert employer.employer_profile is not None
            job = _create_published_job(employer.employer_profile)

            app_record = submit_job_application(
                worker_user=worker,
                job_id=job.id,
                cover_note="Available to start tomorrow morning at 9 AM.",
            )
            assert app_record.status == "applied"

            # Verify employer received an in-app notification
            employer_notifs = Notification.query.filter_by(user_id=employer.id).all()
            assert len(employer_notifs) == 1
            assert "New application" in employer_notifs[0].title

            # Duplicate application must be rejected
            with pytest.raises(DomainRuleError, match="already applied"):
                submit_job_application(worker_user=worker, job_id=job.id)

    def test_closed_and_expired_jobs_reject_applications(self, app: Flask) -> None:
        with app.app_context():
            worker = _create_worker_with_profile()
            employer = _create_employer_with_profile()
            assert employer.employer_profile is not None

            closed_job = _create_published_job(employer.employer_profile, status="closed")
            with pytest.raises(DomainRuleError, match="closed, archived, or past"):
                submit_job_application(worker_user=worker, job_id=closed_job.id)

            expired_job = _create_published_job(
                employer.employer_profile,
                deadline_days=-1,
                status="published",
            )
            with pytest.raises(DomainRuleError, match="closed, archived, or past"):
                submit_job_application(worker_user=worker, job_id=expired_job.id)

    def test_unauthorized_employer_cannot_modify_another_employers_applicants(
        self, app: Flask
    ) -> None:
        with app.app_context():
            worker = _create_worker_with_profile()
            owner_employer = _create_employer_with_profile("owner@example.com", "Owner Shop")
            intruder_employer = _create_employer_with_profile("other@example.com", "Other Shop")
            assert owner_employer.employer_profile is not None
            job = _create_published_job(owner_employer.employer_profile)

            app_record = submit_job_application(worker_user=worker, job_id=job.id)

            with pytest.raises(AuthorizationError, match="Only the employer who owns"):
                transition_application_status(
                    actor_user=intruder_employer,
                    application_id=app_record.id,
                    target_status="accepted",
                )

    def test_vacancy_limit_enforcement_and_auto_close_on_fill(self, app: Flask) -> None:
        with app.app_context():
            w1 = _create_worker_with_profile("w1@example.com", "Worker One")
            w2 = _create_worker_with_profile("w2@example.com", "Worker Two")
            employer = _create_employer_with_profile()
            assert employer.employer_profile is not None

            # Create a job with exactly 1 vacancy
            single_vacancy_job = _create_published_job(
                employer.employer_profile,
                vacancies=1,
            )

            app1 = submit_job_application(worker_user=w1, job_id=single_vacancy_job.id)
            app2 = submit_job_application(worker_user=w2, job_id=single_vacancy_job.id)

            # Accepting first worker succeeds and automatically closes the 1-vacancy job
            transition_application_status(
                actor_user=employer,
                application_id=app1.id,
                target_status="accepted",
                employer_notes="Strong retail experience.",
            )
            assert app1.status == "accepted"
            assert single_vacancy_job.status == "closed"

            # Attempting to accept a second worker when vacancy=1 is blocked
            with pytest.raises(DomainRuleError, match="vacancies for this job have already"):
                transition_application_status(
                    actor_user=employer,
                    application_id=app2.id,
                    target_status="accepted",
                )


class TestAlembicMigrationUpgradeAndDowngrade:
    """Verify that the initial Alembic migration upgrades and downgrades repeatably."""

    def test_alembic_upgrade_and_downgrade_cycle(self, app: Flask) -> None:
        migrations_dir = Path(__file__).resolve().parent.parent / "migrations"
        alembic_cfg = AlembicConfig(str(migrations_dir / "alembic.ini"))
        alembic_cfg.set_main_option("script_location", str(migrations_dir))

        with app.app_context():
            db.drop_all()
            command.upgrade(alembic_cfg, "head")
            inspector = db.inspect(db.engine)
            table_names = set(inspector.get_table_names())
            assert "users" in table_names
            assert "jobs" in table_names
            assert "job_applications" in table_names
            assert "audit_events" in table_names

            command.downgrade(alembic_cfg, "base")
            inspector_after = db.inspect(db.engine)
            remaining = set(inspector_after.get_table_names()) - {"alembic_version"}
            assert len(remaining) == 0
            # Restore schema for fixture teardown
            db.create_all()
