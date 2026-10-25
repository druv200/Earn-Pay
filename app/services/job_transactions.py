"""Atomic database transactions for job applications, status transitions, and race safety."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models.job import Job, JobApplication
from app.models.security_and_trust import AuditEvent, Notification
from app.models.user import User


class DomainRuleError(ValueError):
    """Raised when a business invariant or state transition rule is violated."""


class AuthorizationError(PermissionError):
    """Raised when an actor attempts to read or mutate a resource they do not own."""


def submit_job_application(
    *,
    worker_user: User,
    job_id: int,
    cover_note: str | None = None,
) -> JobApplication:
    """Atomically validate eligibility, create a JobApplication, notify employer, and log audit."""
    if not worker_user.is_worker or worker_user.worker_profile is None:
        msg = "Only registered workers with a completed profile can apply for jobs."
        raise AuthorizationError(msg)

    worker_profile = worker_user.worker_profile

    try:
        # Lock the target job row to prevent race conditions against concurrent close/archive
        stmt = select(Job).where(Job.id == job_id).with_for_update()
        job = db.session.execute(stmt).scalar_one_or_none()
        if job is None:
            msg = "The requested job listing does not exist."
            raise DomainRuleError(msg)

        if not job.is_accepting_applications():
            msg = "This job is closed, archived, or past its application deadline."
            raise DomainRuleError(msg)

        existing_stmt = select(JobApplication.id).where(
            JobApplication.job_id == job.id,
            JobApplication.worker_id == worker_profile.id,
        )
        if db.session.execute(existing_stmt).scalar_one_or_none() is not None:
            msg = "You have already applied for this job."
            raise DomainRuleError(msg)

        application = JobApplication(
            job_id=job.id,
            worker_id=worker_profile.id,
            status="applied",
            cover_note=cover_note.strip() if cover_note else None,
        )
        db.session.add(application)
        db.session.flush()

        # Notify owning employer without exposing private worker phone/email in notification text
        employer_user_id = job.employer.user_id
        notification = Notification(
            user_id=employer_user_id,
            notification_type="application_status",
            title=f"New application for {job.title}",
            message=f"A candidate has applied for '{job.title}' ({job.location}).",
            link_url=f"/employer/jobs/{job.id}/applicants",
        )
        audit = AuditEvent.record(
            actor_id=worker_user.id,
            action="application.submit",
            resource_type="job_application",
            resource_id=application.id,
            metadata={"job_id": job.id, "status": "applied"},
        )
        db.session.add_all([notification, audit])
        db.session.commit()
        return application

    except IntegrityError as exc:
        db.session.rollback()
        msg = "You have already applied for this job."
        raise DomainRuleError(msg) from exc
    except Exception:
        db.session.rollback()
        raise


def transition_application_status(
    *,
    actor_user: User,
    application_id: int,
    target_status: str,
    employer_notes: str | None = None,
    interview_scheduled_at: datetime | None = None,
    interview_details: str | None = None,
) -> JobApplication:
    """Atomically transition application status with row locking and vacancy enforcement."""
    cleaned_target = target_status.strip().lower()

    try:
        app_stmt = (
            select(JobApplication)
            .where(JobApplication.id == application_id)
            .with_for_update()
        )
        application = db.session.execute(app_stmt).scalar_one_or_none()
        if application is None:
            msg = "Application record not found."
            raise DomainRuleError(msg)

        # Lock parent job row to serialize vacancy checks and status mutations
        job_stmt = select(Job).where(Job.id == application.job_id).with_for_update()
        job = db.session.execute(job_stmt).scalar_one()

        # Enforce strict server-side ownership
        if cleaned_target == "withdrawn":
            if not actor_user.is_worker or application.worker.user_id != actor_user.id:
                msg = "Only the applicant who submitted this application may withdraw it."
                raise AuthorizationError(msg)
        else:
            if not job.is_owned_by_user(actor_user):
                msg = "Only the employer who owns this job listing may update candidate status."
                raise AuthorizationError(msg)

        previous_status = application.status
        if not application.can_transition_to(cleaned_target):
            msg = f"Cannot transition application from '{previous_status}' to '{cleaned_target}'."
            raise DomainRuleError(msg)

        # Race-safe vacancy enforcement when accepting a candidate
        if cleaned_target == "accepted":
            count_stmt = select(func.count(JobApplication.id)).where(
                JobApplication.job_id == job.id,
                JobApplication.status == "accepted",
            )
            accepted_count = int(db.session.execute(count_stmt).scalar_one() or 0)
            if accepted_count >= job.vacancies:
                msg = f"All {job.vacancies} vacancies for this job have already been filled."
                raise DomainRuleError(msg)

            # Automatically close the job when the final vacancy is filled
            if accepted_count + 1 >= job.vacancies and job.status == "published":
                job.status = "closed"

        application.status = cleaned_target
        if employer_notes is not None and job.is_owned_by_user(actor_user):
            application.employer_private_notes = employer_notes.strip()
        if interview_scheduled_at is not None:
            application.interview_scheduled_at = interview_scheduled_at
        if interview_details is not None:
            application.interview_details = interview_details.strip()

        # Notify the counter-party
        if cleaned_target == "withdrawn":
            recipient_id = job.employer.user_id
            notif_title = f"Application withdrawn for {job.title}"
            notif_msg = f"An applicant withdrew their application for '{job.title}'."
            notif_link = f"/employer/jobs/{job.id}/applicants"
        else:
            recipient_id = application.worker.user_id
            readable_status = cleaned_target.replace("_", " ")
            notif_title = f"Application update: {job.title}"
            notif_msg = (
                f"Your application for '{job.title}' at {job.employer.business_name} "
                f"is now marked as {readable_status}."
            )
            notif_link = "/worker/dashboard"

        notification = Notification(
            user_id=recipient_id,
            notification_type="application_status",
            title=notif_title,
            message=notif_msg,
            link_url=notif_link,
        )
        audit = AuditEvent.record(
            actor_id=actor_user.id,
            action="application.status_transition",
            resource_type="job_application",
            resource_id=application.id,
            metadata={
                "job_id": job.id,
                "from_status": previous_status,
                "to_status": cleaned_target,
            },
        )
        db.session.add_all([notification, audit])
        db.session.commit()
        return application

    except Exception:
        db.session.rollback()
        raise
