"""Job discovery, job details, draft preview, and employer job creation/editing routes."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.extensions import db
from app.forms.job_forms import (
    ApplicationWithdrawalForm,
    JobApplicationForm,
    JobPostForm,
    JobStatusActionForm,
    SavedJobToggleForm,
)
from app.models.job import Job, JobApplication, SavedJob
from app.routes.public import DEFAULT_JOB_CATEGORIES
from app.services.job_service import (
    change_job_status,
    create_job_listing,
    search_published_jobs,
    update_job_listing,
)
from app.services.job_transactions import AuthorizationError, DomainRuleError
from app.utils.security import role_required

jobs_bp = Blueprint("jobs", __name__)


def _parse_optional_decimal(raw_value: str | None) -> Decimal | None:
    if not raw_value or not raw_value.strip():
        return None
    try:
        dec = Decimal(raw_value.strip())
        return dec if dec >= 0 else None
    except InvalidOperation:
        return None


@jobs_bp.get("/jobs")
def job_discovery():
    """Render the search-first Job Discovery interface for authenticated Workers."""
    if not current_user.is_authenticated:
        flash(
            "Please register or sign in with a Worker account to search and apply for local jobs.",
            "warning",
        )
        return redirect(url_for("auth.login", next=request.full_path.rstrip("?")))

    if current_user.is_employer:
        flash(
            "Job discovery is for Worker accounts. "
            "Use your Employer Dashboard or Find Workers to hire local staff.",
            "warning",
        )
        return redirect(url_for("profiles.employer_dashboard"))

    q = request.args.get("q", "").strip()
    location = request.args.get("location", "").strip()
    category = request.args.get("category", "").strip()
    job_type = request.args.get("job_type", "").strip()
    wage_frequency = request.args.get("wage_frequency", "").strip()
    min_wage = _parse_optional_decimal(request.args.get("min_wage"))
    max_wage = _parse_optional_decimal(request.args.get("max_wage"))
    sort = request.args.get("sort", "newest").strip()

    try:
        page = max(1, int(request.args.get("page", "1")))
    except ValueError:
        page = 1

    search_page = search_published_jobs(
        q=q,
        location=location,
        category=category,
        job_type=job_type,
        wage_frequency=wage_frequency,
        min_wage=min_wage,
        max_wage=max_wage,
        sort=sort,
        page=page,
        per_page=10,
    )

    return render_template(
        "jobs/discovery.html",
        search_page=search_page,
        categories=DEFAULT_JOB_CATEGORIES,
        q=q,
        location=location,
        category=category,
        job_type=job_type,
        wage_frequency=wage_frequency,
        min_wage=request.args.get("min_wage", "").strip(),
        max_wage=request.args.get("max_wage", "").strip(),
        sort=sort,
    )


@jobs_bp.get("/jobs/<int:job_id>")
def job_detail(job_id: int):
    """Render the structured Job Details fact-sheet and application/save controls."""
    stmt = (
        select(Job)
        .options(selectinload(Job.employer))
        .where(Job.id == job_id)
    )
    job = db.session.execute(stmt).scalar_one_or_none()
    if job is None:
        abort(404)

    # Draft or archived jobs are visible ONLY to their owning employer or an admin
    is_owner = current_user.is_authenticated and job.is_owned_by_user(current_user)
    is_admin = current_user.is_authenticated and current_user.is_admin
    if job.status in ("draft", "archived") and not (is_owner or is_admin):
        abort(404)

    if not current_user.is_authenticated:
        flash(
            "Please register or sign in with a Worker account to view job details and apply.",
            "warning",
        )
        return redirect(url_for("auth.login", next=request.full_path.rstrip("?")))

    if current_user.is_employer and not is_owner:
        flash(
            "Job search and third-party job listings are for Worker accounts. "
            "Redirected to your Employer Dashboard.",
            "warning",
        )
        return redirect(url_for("profiles.employer_dashboard"))

    existing_application: JobApplication | None = None
    is_saved: bool = False

    if (
        current_user.is_authenticated
        and current_user.is_worker
        and current_user.worker_profile is not None
    ):
        worker_id = current_user.worker_profile.id
        app_stmt = select(JobApplication).where(
            JobApplication.job_id == job.id,
            JobApplication.worker_id == worker_id,
        )
        existing_application = db.session.execute(app_stmt).scalar_one_or_none()

        save_stmt = select(SavedJob.id).where(
            SavedJob.job_id == job.id,
            SavedJob.worker_id == worker_id,
        )
        is_saved = db.session.execute(save_stmt).scalar_one_or_none() is not None

    apply_form = JobApplicationForm()
    withdraw_form = ApplicationWithdrawalForm()
    save_form = SavedJobToggleForm()
    status_form = JobStatusActionForm()

    return render_template(
        "jobs/detail.html",
        job=job,
        is_owner=is_owner,
        existing_application=existing_application,
        is_saved=is_saved,
        apply_form=apply_form,
        withdraw_form=withdraw_form,
        save_form=save_form,
        status_form=status_form,
    )


@jobs_bp.route("/employer/jobs/new", methods=["GET", "POST"])
@role_required("employer")
def create_job():
    """Render and process the Create Job page (supporting Draft, Preview, and Publish)."""
    form = JobPostForm()
    if form.validate_on_submit():
        try:
            action = form.submit_action.data or "publish"
            job = create_job_listing(
                employer_user=current_user,
                title=form.title.data or "",
                category=form.category.data or "Retail",
                job_type=form.job_type.data or "daily_wage",
                description=form.description.data or "",
                responsibilities=form.responsibilities.data or "",
                required_skills=form.required_skills.data,
                experience_required=form.experience_required.data,
                location=form.location.data or "",
                pincode=form.pincode.data or "",
                wage_amount=Decimal(str(form.wage_amount.data)),
                wage_frequency=form.wage_frequency.data or "daily",
                working_hours=form.working_hours.data or "",
                vacancies=form.vacancies.data or 1,
                application_deadline=form.application_deadline.data,
                submit_action=action,
                ip_address=request.remote_addr,
            )
            if action == "preview":
                flash(
                    "Draft saved! Review your job listing preview below before publishing.",
                    "warning",
                )
            elif action == "draft":
                flash("Job listing saved as a draft.", "success")
            else:
                flash("Your job listing is now published in the local marketplace!", "success")
            return redirect(url_for("jobs.job_detail", job_id=job.id))
        except (DomainRuleError, AuthorizationError, ValueError) as exc:
            flash(str(exc), "danger")

    return render_template("jobs/job_form.html", form=form, is_edit=False, job=None)


@jobs_bp.route("/employer/jobs/<int:job_id>/edit", methods=["GET", "POST"])
@role_required("employer")
def edit_job(job_id: int):
    """Render and process the Edit Job page with server-side ownership checks."""
    job = db.session.get(Job, job_id)
    if job is None:
        abort(404)
    if not job.is_owned_by_user(current_user):
        abort(403)

    form = JobPostForm()
    if request.method == "GET":
        form.title.data = job.title
        form.category.data = job.category
        form.job_type.data = job.job_type
        form.description.data = job.description
        form.responsibilities.data = job.responsibilities
        form.required_skills.data = job.required_skills or ""
        form.experience_required.data = job.experience_required or ""
        form.location.data = job.location
        form.pincode.data = job.pincode
        form.wage_amount.data = job.wage_amount
        form.wage_frequency.data = job.wage_frequency
        form.working_hours.data = job.working_hours
        form.vacancies.data = job.vacancies
        form.application_deadline.data = job.application_deadline
        form.submit_action.data = "publish" if job.status == "published" else "draft"

    if form.validate_on_submit():
        try:
            action = form.submit_action.data or "publish"
            updated = update_job_listing(
                employer_user=current_user,
                job_id=job.id,
                title=form.title.data or job.title,
                category=form.category.data or job.category,
                job_type=form.job_type.data or job.job_type,
                description=form.description.data or job.description,
                responsibilities=form.responsibilities.data or job.responsibilities,
                required_skills=form.required_skills.data,
                experience_required=form.experience_required.data,
                location=form.location.data or job.location,
                pincode=form.pincode.data or job.pincode,
                wage_amount=Decimal(str(form.wage_amount.data)),
                wage_frequency=form.wage_frequency.data or job.wage_frequency,
                working_hours=form.working_hours.data or job.working_hours,
                vacancies=form.vacancies.data or job.vacancies,
                application_deadline=form.application_deadline.data,
                submit_action=action,
                ip_address=request.remote_addr,
            )
            flash("Job listing updated.", "success")
            return redirect(url_for("jobs.job_detail", job_id=updated.id))
        except (DomainRuleError, AuthorizationError, ValueError) as exc:
            flash(str(exc), "danger")

    return render_template("jobs/job_form.html", form=form, is_edit=True, job=job)


@jobs_bp.post("/employer/jobs/<int:job_id>/status")
@role_required("employer")
def update_job_status_route(job_id: int):
    """Transition a Job between draft, published, closed, or archived."""
    form = JobStatusActionForm()
    if form.validate_on_submit():
        try:
            job = change_job_status(
                employer_user=current_user,
                job_id=job_id,
                target_status=form.target_status.data or "closed",
                ip_address=request.remote_addr,
            )
            flash(f"Job status updated to '{job.status}'.", "success")
        except AuthorizationError:
            abort(403)
        except DomainRuleError as exc:
            flash(str(exc), "danger")
    return redirect(url_for("jobs.job_detail", job_id=job_id))
