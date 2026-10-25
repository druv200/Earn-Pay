"""Phase 8 Routes: Applications, Withdrawals, Saved Jobs, Applicant Management & Notifications."""

from __future__ import annotations

from datetime import UTC, datetime

from flask import Blueprint, abort, flash, redirect, render_template, url_for
from flask_login import current_user, login_required
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.extensions import db
from app.forms.job_forms import (
    ApplicationWithdrawalForm,
    EmployerApplicantUpdateForm,
    JobApplicationForm,
    JobStatusActionForm,
    NotificationReadForm,
    SavedJobToggleForm,
)
from app.models.job import Job, JobApplication, SavedJob
from app.models.security_and_trust import Notification
from app.models.user import WorkerProfile
from app.services.job_service import (
    mark_all_notifications_read,
    mark_notification_read,
    toggle_saved_job,
)
from app.services.job_transactions import (
    AuthorizationError,
    DomainRuleError,
    submit_job_application,
    transition_application_status,
)
from app.services.matching_service import evaluate_job_match
from app.utils.security import role_required

applications_bp = Blueprint("applications", __name__)


def _parse_interview_datetime(raw_str: str | None) -> datetime | None:
    if not raw_str or not raw_str.strip():
        return None
    cleaned = raw_str.strip().replace("T", " ")
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            parsed = datetime.strptime(cleaned, fmt)
            return parsed.replace(tzinfo=UTC)
        except ValueError:
            continue
    return None


@applications_bp.post("/jobs/<int:job_id>/apply")
@role_required("worker")
def apply_to_job(job_id: int):
    """Submit a Worker's application to a published Job."""
    form = JobApplicationForm()
    if form.validate_on_submit():
        try:
            submit_job_application(
                worker_user=current_user,
                job_id=job_id,
                cover_note=form.cover_note.data,
            )
            flash(
                "Your application has been submitted! Track its progress in your Worker Dashboard.",
                "success",
            )
        except AuthorizationError:
            abort(403)
        except DomainRuleError as exc:
            flash(str(exc), "danger")
    else:
        for field_errors in form.errors.values():
            for err in field_errors:
                flash(str(err), "danger")

    return redirect(url_for("jobs.job_detail", job_id=job_id))


@applications_bp.post("/applications/<int:application_id>/withdraw")
@role_required("worker")
def withdraw_application(application_id: int):
    """Allow an applicant to withdraw their active job application."""
    form = ApplicationWithdrawalForm()
    app_record = db.session.get(JobApplication, application_id)
    if app_record is None:
        abort(404)

    if form.validate_on_submit():
        try:
            transition_application_status(
                actor_user=current_user,
                application_id=application_id,
                target_status="withdrawn",
            )
            flash("Your application has been withdrawn.", "warning")
        except AuthorizationError:
            abort(403)
        except DomainRuleError as exc:
            flash(str(exc), "danger")

    return redirect(url_for("jobs.job_detail", job_id=app_record.job_id))


@applications_bp.post("/jobs/<int:job_id>/save")
@role_required("worker")
def toggle_save_job_route(job_id: int):
    """Bookmark or unbookmark a Job for later review."""
    form = SavedJobToggleForm()
    if form.validate_on_submit():
        try:
            is_now_saved = toggle_saved_job(worker_user=current_user, job_id=job_id)
            if is_now_saved:
                flash("Job saved to your bookmarks.", "success")
            else:
                flash("Job removed from your saved jobs.", "warning")
        except AuthorizationError:
            abort(403)
        except DomainRuleError as exc:
            flash(str(exc), "danger")

    return redirect(url_for("jobs.job_detail", job_id=job_id))


@applications_bp.get("/worker/saved-jobs")
@role_required("worker")
def saved_jobs_page():
    """Render dedicated Saved Jobs page for a Worker."""
    worker_profile = current_user.worker_profile
    if worker_profile is None:
        saved_items: list[SavedJob] = []
    else:
        stmt = (
            select(SavedJob)
            .options(selectinload(SavedJob.job).selectinload(Job.employer))
            .where(SavedJob.worker_id == worker_profile.id)
            .order_by(SavedJob.saved_at.desc())
        )
        saved_items = list(db.session.execute(stmt).scalars().all())

    save_form = SavedJobToggleForm()
    return render_template(
        "applications/saved_jobs.html",
        saved_items=saved_items,
        save_form=save_form,
    )


@applications_bp.get("/employer/applicants")
@role_required("employer")
def employer_applicants_overview():
    """Render an overview of all applicants across all jobs owned by the Employer."""
    employer_profile = current_user.employer_profile
    if employer_profile is None:
        all_applications: list[JobApplication] = []
    else:
        stmt = (
            select(JobApplication)
            .join(JobApplication.job)
            .options(
                selectinload(JobApplication.job),
                selectinload(JobApplication.worker).selectinload(WorkerProfile.user),
            )
            .where(Job.employer_id == employer_profile.id)
            .order_by(JobApplication.applied_at.desc(), JobApplication.id.desc())
        )
        all_applications = list(db.session.execute(stmt).scalars().all())

    return render_template(
        "applications/employer_all_applicants.html",
        applications=all_applications,
    )


@applications_bp.get("/employer/jobs/<int:job_id>/applicants")
@role_required("employer")
def manage_job_applicants(job_id: int):
    """Render the Employer's Applicant Management Workspace for a specific Job."""
    job = db.session.get(Job, job_id)
    if job is None:
        abort(404)
    if not job.is_owned_by_user(current_user):
        abort(403)

    stmt = (
        select(JobApplication)
        .options(selectinload(JobApplication.worker).selectinload(WorkerProfile.user))
        .where(JobApplication.job_id == job.id)
        .order_by(JobApplication.applied_at.desc(), JobApplication.id.desc())
    )
    applications = list(db.session.execute(stmt).scalars().all())

    # Pair each applicant with their explainable match evaluation against this job
    enriched_applicants = [
        {
            "application": app_rec,
            "worker": app_rec.worker,
            "user": app_rec.worker.user,
            "match": evaluate_job_match(app_rec.worker, job),
        }
        for app_rec in applications
    ]

    accepted_count = sum(1 for app_rec in applications if app_rec.status == "accepted")
    update_form = EmployerApplicantUpdateForm()
    status_form = JobStatusActionForm()

    return render_template(
        "applications/employer_applicants.html",
        job=job,
        enriched_applicants=enriched_applicants,
        accepted_count=accepted_count,
        update_form=update_form,
        status_form=status_form,
    )


@applications_bp.post("/employer/applications/<int:application_id>/update")
@role_required("employer")
def update_applicant_status(application_id: int):
    """Process an Employer's hiring action, interview schedule, and private notes."""
    app_record = db.session.get(JobApplication, application_id)
    if app_record is None:
        abort(404)

    form = EmployerApplicantUpdateForm()
    if form.validate_on_submit():
        try:
            interview_dt = _parse_interview_datetime(form.interview_date.data)
            updated = transition_application_status(
                actor_user=current_user,
                application_id=application_id,
                target_status=form.target_status.data or app_record.status,
                employer_notes=form.employer_private_notes.data,
                interview_scheduled_at=interview_dt,
                interview_details=form.interview_details.data,
            )
            readable = updated.status.replace("_", " ")
            flash(
                f"Candidate status updated to '{readable}'. The applicant has been notified.",
                "success",
            )
        except AuthorizationError:
            abort(403)
        except DomainRuleError as exc:
            flash(str(exc), "danger")
    else:
        for field_errors in form.errors.values():
            for err in field_errors:
                flash(str(err), "danger")

    return redirect(url_for("applications.manage_job_applicants", job_id=app_record.job_id))


@applications_bp.get("/notifications")
@login_required
def notifications_page():
    """Render the current user's in-app Notification Center."""
    stmt = (
        select(Notification)
        .where(Notification.user_id == current_user.id)
        .order_by(Notification.created_at.desc(), Notification.id.desc())
        .limit(50)
    )
    notifications = list(db.session.execute(stmt).scalars().all())
    unread_count = sum(1 for n in notifications if not n.is_read)
    read_form = NotificationReadForm()

    return render_template(
        "applications/notifications.html",
        notifications=notifications,
        unread_count=unread_count,
        read_form=read_form,
    )


@applications_bp.post("/notifications/<int:notification_id>/read")
@login_required
def mark_single_notification_read(notification_id: int):
    """Mark a single notification as read."""
    form = NotificationReadForm()
    if form.validate_on_submit():
        try:
            mark_notification_read(user=current_user, notification_id=notification_id)
        except AuthorizationError:
            abort(403)
        except DomainRuleError as exc:
            flash(str(exc), "danger")
    return redirect(url_for("applications.notifications_page"))


@applications_bp.post("/notifications/read-all")
@login_required
def mark_all_read():
    """Mark all unread notifications for the current user as read."""
    form = NotificationReadForm()
    if form.validate_on_submit():
        count = mark_all_notifications_read(user=current_user)
        if count > 0:
            flash(f"Marked {count} notifications as read.", "success")
    return redirect(url_for("applications.notifications_page"))
