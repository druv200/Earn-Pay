"""Worker/Employer workspaces, profile management, privacy controls, and public employer views."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation

from flask import (
    Blueprint,
    abort,
    flash,
    g,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from flask_login import current_user, login_required, logout_user
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.extensions import db
from app.forms.profile_forms import (
    AccountDeletionRequestForm,
    EmployerProfileForm,
    WorkerProfileForm,
)
from app.models.job import Job, JobApplication, SavedJob
from app.models.security_and_trust import Notification
from app.models.user import EmployerProfile, WorkerProfile
from app.routes.public import DEFAULT_JOB_CATEGORIES
from app.services.job_transactions import AuthorizationError, DomainRuleError
from app.services.matching_service import get_recommended_jobs_for_worker
from app.services.moderation_service import export_user_personal_data
from app.services.profile_service import (
    can_employer_view_worker_profile,
    count_available_workers,
    request_account_deletion,
    search_available_workers,
    update_employer_profile,
    update_worker_profile,
)
from app.utils.security import role_required

profiles_bp = Blueprint("profiles", __name__)


def _parse_optional_decimal(raw_value: str | None) -> Decimal | None:
    if not raw_value or not raw_value.strip():
        return None
    try:
        dec = Decimal(raw_value.strip())
        return dec if dec >= 0 else None
    except InvalidOperation:
        return None


@profiles_bp.get("/worker/dashboard")
@role_required("worker")
def worker_dashboard():
    """Render personalized Worker workspace with status timeline and explainable job matches."""
    worker_profile = current_user.worker_profile
    if worker_profile is None:
        worker_profile = WorkerProfile(user_id=current_user.id)
        db.session.add(worker_profile)
        db.session.commit()

    apps_stmt = (
        select(JobApplication)
        .options(selectinload(JobApplication.job).selectinload(Job.employer))
        .where(JobApplication.worker_id == worker_profile.id)
        .order_by(JobApplication.updated_at.desc(), JobApplication.id.desc())
    )
    applications = list(db.session.execute(apps_stmt).scalars().all())

    upcoming_interviews = [
        app_rec
        for app_rec in applications
        if app_rec.status == "interview_scheduled" or app_rec.interview_scheduled_at is not None
    ]

    saved_stmt = (
        select(SavedJob)
        .options(selectinload(SavedJob.job).selectinload(Job.employer))
        .where(SavedJob.worker_id == worker_profile.id)
        .order_by(SavedJob.saved_at.desc())
    )
    saved_jobs = list(db.session.execute(saved_stmt).scalars().all())

    notif_stmt = (
        select(Notification)
        .where(Notification.user_id == current_user.id)
        .order_by(Notification.created_at.desc())
        .limit(5)
    )
    recent_notifications = list(db.session.execute(notif_stmt).scalars().all())

    recommended_matches = get_recommended_jobs_for_worker(worker_profile, limit=5)

    return render_template(
        "profiles/worker_dashboard.html",
        profile=worker_profile,
        applications=applications,
        upcoming_interviews=upcoming_interviews,
        saved_jobs=saved_jobs,
        recent_notifications=recent_notifications,
        recommended_matches=recommended_matches,
    )


@profiles_bp.route("/worker/profile", methods=["GET", "POST"])
@role_required("worker")
def edit_worker_profile():
    """Render and process the Worker profile and privacy controls editor."""
    profile = current_user.worker_profile
    if profile is None:
        profile = WorkerProfile(user_id=current_user.id)
        db.session.add(profile)
        db.session.commit()

    form = WorkerProfileForm()
    if request.method == "GET":
        form.full_name.data = current_user.full_name
        form.phone_number.data = profile.phone_number or ""
        form.skills.data = profile.skills or ""
        form.experience_summary.data = profile.experience_summary or ""
        form.preferred_categories.data = profile.preferred_categories or ""
        form.preferred_location.data = profile.preferred_location or ""
        form.pincode.data = profile.pincode or ""
        form.travel_radius_km.data = profile.travel_radius_km
        form.availability.data = profile.availability
        form.expected_daily_wage.data = profile.expected_daily_wage
        form.is_profile_public.data = profile.is_profile_public
        form.show_phone_to_employers.data = profile.show_phone_to_employers

    if form.validate_on_submit():
        try:
            expected_wage = (
                Decimal(str(form.expected_daily_wage.data))
                if form.expected_daily_wage.data is not None
                else None
            )
            update_worker_profile(
                user=current_user,
                full_name=form.full_name.data or current_user.full_name,
                phone_number=form.phone_number.data,
                skills=form.skills.data,
                experience_summary=form.experience_summary.data,
                preferred_categories=form.preferred_categories.data,
                preferred_location=form.preferred_location.data,
                pincode=form.pincode.data,
                travel_radius_km=form.travel_radius_km.data or 10,
                availability=form.availability.data or "flexible",
                expected_daily_wage=expected_wage,
                is_profile_public=bool(form.is_profile_public.data),
                show_phone_to_employers=bool(form.show_phone_to_employers.data),
                ip_address=request.remote_addr,
            )
            flash("Your worker profile and privacy preferences have been saved.", "success")
            return redirect(url_for("profiles.worker_dashboard"))
        except (DomainRuleError, AuthorizationError, ValueError) as exc:
            flash(str(exc), "danger")

    return render_template("profiles/worker_profile_edit.html", form=form, profile=profile)


@profiles_bp.get("/employer/dashboard")
@role_required("employer")
def employer_dashboard():
    """Render structured Employer Operations Workspace."""
    employer_profile = current_user.employer_profile
    if employer_profile is None:
        employer_profile = EmployerProfile(
            user_id=current_user.id,
            business_name=f"{current_user.full_name}'s Business",
        )
        db.session.add(employer_profile)
        db.session.commit()

    jobs_stmt = (
        select(Job)
        .options(selectinload(Job.applications))
        .where(Job.employer_id == employer_profile.id)
        .order_by(Job.created_at.desc(), Job.id.desc())
    )
    all_jobs = list(db.session.execute(jobs_stmt).scalars().all())

    active_jobs = [job for job in all_jobs if job.status == "published"]
    draft_jobs = [job for job in all_jobs if job.status == "draft"]
    closed_jobs = [job for job in all_jobs if job.status in ("closed", "archived")]

    recent_apps_stmt = (
        select(JobApplication)
        .join(JobApplication.job)
        .options(
            selectinload(JobApplication.job),
            selectinload(JobApplication.worker).selectinload(WorkerProfile.user),
        )
        .where(Job.employer_id == employer_profile.id)
        .order_by(JobApplication.applied_at.desc(), JobApplication.id.desc())
        .limit(10)
    )
    recent_applications = list(db.session.execute(recent_apps_stmt).scalars().all())

    total_applications = sum(len(job.applications) for job in all_jobs)
    pending_review_count = sum(
        1
        for job in all_jobs
        for app_rec in job.applications
        if app_rec.status in ("applied", "under_review")
    )

    selected_area = request.args.get("area", "").strip()
    available_worker_count = count_available_workers(location=selected_area)
    total_eligible_workers = count_available_workers()

    return render_template(
        "profiles/employer_dashboard.html",
        employer=employer_profile,
        active_jobs=active_jobs,
        draft_jobs=draft_jobs,
        closed_jobs=closed_jobs,
        recent_applications=recent_applications,
        total_applications=total_applications,
        pending_review_count=pending_review_count,
        available_worker_count=available_worker_count,
        total_eligible_workers=total_eligible_workers,
        selected_area=selected_area,
    )


@profiles_bp.get("/find-workers")
@role_required("employer")
def find_workers():
    """Render the dedicated Find Workers directory for authenticated Employers."""
    q = request.args.get("q", "").strip()
    location = request.args.get("location", "").strip()
    category = request.args.get("category", "").strip()
    availability = request.args.get("availability", "").strip()
    min_wage = _parse_optional_decimal(request.args.get("min_wage"))
    max_wage = _parse_optional_decimal(request.args.get("max_wage"))

    try:
        page = max(1, int(request.args.get("page", "1")))
    except ValueError:
        page = 1

    worker_page = search_available_workers(
        q=q,
        location=location,
        category=category,
        availability=availability,
        min_wage=min_wage,
        max_wage=max_wage,
        page=page,
        per_page=10,
    )
    available_worker_count = count_available_workers(location=location)
    total_eligible_workers = count_available_workers()

    return render_template(
        "profiles/find_workers.html",
        worker_page=worker_page,
        available_worker_count=available_worker_count,
        total_eligible_workers=total_eligible_workers,
        categories=DEFAULT_JOB_CATEGORIES,
        q=q,
        location=location,
        category=category,
        availability=availability,
        min_wage=request.args.get("min_wage", "").strip(),
        max_wage=request.args.get("max_wage", "").strip(),
    )


@profiles_bp.route("/employer/profile", methods=["GET", "POST"])
@role_required("employer")
def edit_employer_profile():
    """Render and process the Employer business profile editor."""
    employer = current_user.employer_profile
    if employer is None:
        employer = EmployerProfile(
            user_id=current_user.id,
            business_name=f"{current_user.full_name}'s Business",
        )
        db.session.add(employer)
        db.session.commit()

    form = EmployerProfileForm()
    if request.method == "GET":
        form.full_name.data = current_user.full_name
        form.business_name.data = employer.business_name
        form.business_type.data = employer.business_type
        form.description.data = employer.description or ""
        form.address.data = employer.address or ""
        form.location.data = employer.location or ""
        form.pincode.data = employer.pincode or ""
        form.contact_phone.data = employer.contact_phone or ""
        form.request_verification.data = employer.verification_status in ("pending", "verified")

    if form.validate_on_submit():
        try:
            update_employer_profile(
                user=current_user,
                full_name=form.full_name.data or current_user.full_name,
                business_name=form.business_name.data or employer.business_name,
                business_type=form.business_type.data or "shop",
                description=form.description.data,
                address=form.address.data,
                location=form.location.data,
                pincode=form.pincode.data,
                contact_phone=form.contact_phone.data,
                request_verification=bool(form.request_verification.data),
                ip_address=request.remote_addr,
            )
            flash("Your employer business profile has been updated.", "success")
            return redirect(url_for("profiles.employer_dashboard"))
        except (DomainRuleError, AuthorizationError, ValueError) as exc:
            flash(str(exc), "danger")

    return render_template("profiles/employer_profile_edit.html", form=form, employer=employer)


@profiles_bp.get("/employers/<int:employer_id>")
def public_employer_profile(employer_id: int):
    """Display public employer profile with truthful verification badge and live vacancies."""
    employer = db.session.get(EmployerProfile, employer_id)
    if employer is None or not employer.user.is_active:
        abort(404)

    today = datetime.now(UTC).date()
    jobs_stmt = (
        select(Job)
        .options(selectinload(Job.employer))
        .where(
            Job.employer_id == employer.id,
            Job.status == "published",
            Job.application_deadline >= today,
        )
        .order_by(Job.published_at.desc(), Job.id.desc())
    )
    open_jobs = list(db.session.execute(jobs_stmt).scalars().all())

    return render_template(
        "profiles/public_employer.html",
        employer=employer,
        open_jobs=open_jobs,
    )


@profiles_bp.get("/workers/<int:worker_id>")
@role_required("employer", "admin")
def view_worker_profile(worker_id: int):
    """Allow authorized employers or admins to view a worker profile while respecting privacy."""
    worker_profile = db.session.get(WorkerProfile, worker_id)
    if worker_profile is None or not worker_profile.user.is_active:
        abort(404)

    if not can_employer_view_worker_profile(current_user, worker_profile):
        abort(403)

    can_see_phone = bool(worker_profile.show_phone_to_employers or current_user.is_admin)
    return render_template(
        "profiles/worker_public_view.html",
        worker=worker_profile,
        can_see_phone=can_see_phone,
    )


@profiles_bp.route("/settings", methods=["GET", "POST"])
@login_required
def account_settings():
    """Render account settings, privacy summary, and documented account deletion workflow."""
    deletion_form = AccountDeletionRequestForm()
    if deletion_form.validate_on_submit():
        try:
            request_account_deletion(
                user=current_user,
                confirm_email=deletion_form.confirm_email.data or "",
                reason=deletion_form.reason.data,
                ip_address=request.remote_addr,
            )
            logout_user()
            session.clear()
            g.pop("csrf_token", None)
            flash(
                "Your account deletion request has been processed and your account is deactivated.",
                "success",
            )
            return redirect(url_for("public.index"))
        except DomainRuleError as exc:
            flash(str(exc), "danger")

    return render_template("profiles/account_settings.html", deletion_form=deletion_form)


@profiles_bp.get("/account/export-data")
@login_required
def export_account_data():
    """Download a portable JSON copy of the authenticated user's personal data."""
    payload = export_user_personal_data(current_user, ip_address=request.remote_addr)
    response = jsonify(payload)
    response.headers["Content-Disposition"] = (
        f"attachment; filename=earnandpay_data_export_user_{current_user.id}.json"
    )
    return response

