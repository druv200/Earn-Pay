"""Phase 9 Routes: Suspicious Job/User Reporting and Admin Operations Console."""

from __future__ import annotations

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.extensions import db, limiter
from app.forms.moderation_forms import (
    AdminEmployerVerificationForm,
    AdminJobModerationForm,
    AdminReportResolutionForm,
    AdminUserStatusForm,
    ReportSubmissionForm,
)
from app.models.job import Job, JobApplication
from app.models.security_and_trust import AuditEvent, Report
from app.models.user import EmployerProfile, User, WorkerProfile
from app.services.job_transactions import AuthorizationError, DomainRuleError
from app.services.moderation_service import (
    moderate_job_listing,
    resolve_moderation_report,
    review_employer_verification,
    set_user_account_status,
    submit_moderation_report,
)
from app.utils.security import role_required

moderation_bp = Blueprint("moderation", __name__)


def _describe_report_target(target_type: str, target_id: int) -> dict[str, str | None]:
    """Return human-readable summary and inspection link for a moderation target."""
    if target_type == "job":
        job = db.session.get(Job, target_id)
        if job is not None:
            return {
                "label": f"Job #{job.id}: {job.title} ({job.status})",
                "url": url_for("jobs.job_detail", job_id=job.id),
            }
    elif target_type == "employer":
        emp = db.session.get(EmployerProfile, target_id)
        if emp is not None:
            return {
                "label": f"Employer #{emp.id}: {emp.business_name} ({emp.verification_status})",
                "url": url_for("profiles.public_employer_profile", employer_id=emp.id),
            }
    elif target_type == "worker":
        worker = db.session.get(WorkerProfile, target_id)
        if worker is not None:
            return {
                "label": f"Worker #{worker.id}: {worker.user.full_name}",
                "url": url_for("profiles.view_worker_profile", worker_id=worker.id),
            }
    return {"label": f"{target_type.capitalize()} #{target_id}", "url": None}


@moderation_bp.route("/reports/new", methods=["GET", "POST"])
@login_required
@limiter.limit("10 per hour")
def submit_report():
    """Render and process a suspicious job, employer, or worker moderation report."""
    form = ReportSubmissionForm()

    if request.method == "GET":
        q_type = (request.args.get("target_type") or "job").strip().lower()
        if q_type in ("job", "employer", "worker"):
            form.target_type.data = q_type
        q_id = request.args.get("target_id", type=int)
        if q_id and q_id > 0:
            form.target_id.data = q_id

    target_summary = None
    if form.target_type.data and form.target_id.data:
        target_summary = _describe_report_target(form.target_type.data, int(form.target_id.data))

    if form.validate_on_submit():
        try:
            report = submit_moderation_report(
                reporter=current_user,
                target_type=form.target_type.data or "job",
                target_id=int(form.target_id.data or 0),
                reason=form.reason.data or "other",
                details=form.details.data or "",
                ip_address=request.remote_addr,
            )
            flash(
                f"Thank you. Your report (#{report.id}) has been submitted to Trust & Safety.",
                "success",
            )
            if report.target_type == "job":
                return redirect(url_for("jobs.job_detail", job_id=report.target_id))
            if report.target_type == "employer":
                return redirect(
                    url_for("profiles.public_employer_profile", employer_id=report.target_id)
                )
            return redirect(url_for("public.index"))
        except (DomainRuleError, AuthorizationError, ValueError) as exc:
            flash(str(exc), "danger")

    return render_template(
        "moderation/report_form.html",
        form=form,
        target_summary=target_summary,
    )


@moderation_bp.get("/admin/dashboard")
@role_required("admin")
def admin_dashboard():
    """Render the Admin & Trust Operations Console with marketplace metrics and queues."""
    metrics = {
        "total_users": db.session.scalar(select(func.count(User.id))) or 0,
        "active_workers": (
            db.session.scalar(
                select(func.count(User.id)).where(
                    User.role == "worker", User.account_status == "active"
                )
            )
            or 0
        ),
        "active_employers": (
            db.session.scalar(
                select(func.count(User.id)).where(
                    User.role == "employer", User.account_status == "active"
                )
            )
            or 0
        ),
        "published_jobs": (
            db.session.scalar(select(func.count(Job.id)).where(Job.status == "published")) or 0
        ),
        "archived_jobs": (
            db.session.scalar(select(func.count(Job.id)).where(Job.status == "archived")) or 0
        ),
        "total_applications": db.session.scalar(select(func.count(JobApplication.id))) or 0,
        "open_reports": (
            db.session.scalar(
                select(func.count(Report.id)).where(Report.status.in_(("open", "investigating")))
            )
            or 0
        ),
        "pending_verifications": (
            db.session.scalar(
                select(func.count(EmployerProfile.id)).where(
                    EmployerProfile.verification_status == "pending"
                )
            )
            or 0
        ),
    }

    open_reports = list(
        db.session.execute(
            select(Report)
            .options(selectinload(Report.reporter))
            .where(Report.status.in_(("open", "investigating")))
            .order_by(Report.created_at.desc())
            .limit(8)
        )
        .scalars()
        .all()
    )

    pending_employers = list(
        db.session.execute(
            select(EmployerProfile)
            .options(selectinload(EmployerProfile.user))
            .where(EmployerProfile.verification_status == "pending")
            .order_by(EmployerProfile.updated_at.desc())
            .limit(8)
        )
        .scalars()
        .all()
    )

    recent_users = list(
        db.session.execute(
            select(User)
            .where(User.account_status != "deleted")
            .order_by(User.created_at.desc())
            .limit(12)
        )
        .scalars()
        .all()
    )

    recent_audits = list(
        db.session.execute(
            select(AuditEvent)
            .options(selectinload(AuditEvent.actor))
            .order_by(AuditEvent.created_at.desc())
            .limit(15)
        )
        .scalars()
        .all()
    )

    user_status_form = AdminUserStatusForm()
    verify_form = AdminEmployerVerificationForm()

    return render_template(
        "moderation/admin_dashboard.html",
        metrics=metrics,
        open_reports=open_reports,
        pending_employers=pending_employers,
        recent_users=recent_users,
        recent_audits=recent_audits,
        user_status_form=user_status_form,
        verify_form=verify_form,
    )


@moderation_bp.get("/admin/reports")
@role_required("admin")
def admin_reports():
    """Render the full Moderation Reports queue with status filtering."""
    status_filter = (request.args.get("status") or "all").strip().lower()
    stmt = (
        select(Report)
        .options(selectinload(Report.reporter), selectinload(Report.reviewer))
        .order_by(Report.created_at.desc())
    )
    if status_filter in ("open", "investigating", "resolved", "dismissed"):
        stmt = stmt.where(Report.status == status_filter)

    reports = list(db.session.execute(stmt).scalars().all())
    target_summaries = {
        r.id: _describe_report_target(r.target_type, r.target_id) for r in reports
    }
    resolution_form = AdminReportResolutionForm()

    return render_template(
        "moderation/admin_reports.html",
        reports=reports,
        target_summaries=target_summaries,
        status_filter=status_filter,
        resolution_form=resolution_form,
    )


@moderation_bp.post("/admin/reports/<int:report_id>/resolve")
@role_required("admin")
def resolve_report_action(report_id: int):
    """Process an admin moderator's decision on a report."""
    form = AdminReportResolutionForm()
    if not form.validate_on_submit():
        flash("Please submit a valid moderation decision.", "danger")
        return redirect(url_for("moderation.admin_reports"))

    try:
        report = resolve_moderation_report(
            admin_user=current_user,
            report_id=report_id,
            status=form.status.data or "resolved",
            moderation_action=form.moderation_action.data or "none",
            resolution_notes=form.resolution_notes.data,
            ip_address=request.remote_addr,
        )
        flash(
            f"Report #{report.id} updated to '{report.status}' "
            f"(action: {report.moderation_action}).",
            "success",
        )
    except (DomainRuleError, AuthorizationError, ValueError) as exc:
        flash(str(exc), "danger")

    return redirect(url_for("moderation.admin_reports"))


@moderation_bp.get("/admin/employers")
@role_required("admin")
def admin_employers():
    """Render the Employer Verification Queue for administrators."""
    status_filter = (request.args.get("status") or "all").strip().lower()
    stmt = (
        select(EmployerProfile)
        .options(selectinload(EmployerProfile.user), selectinload(EmployerProfile.jobs))
        .order_by(EmployerProfile.updated_at.desc(), EmployerProfile.id.desc())
    )
    if status_filter in ("pending", "verified", "unverified"):
        stmt = stmt.where(EmployerProfile.verification_status == status_filter)

    employers = list(db.session.execute(stmt).scalars().all())
    verify_form = AdminEmployerVerificationForm()

    return render_template(
        "moderation/admin_employers.html",
        employers=employers,
        status_filter=status_filter,
        verify_form=verify_form,
    )


@moderation_bp.post("/admin/employers/<int:employer_id>/verify")
@role_required("admin")
def verify_employer_action(employer_id: int):
    """Approve or revoke an employer's verified badge."""
    form = AdminEmployerVerificationForm()
    if not form.validate_on_submit():
        flash("Invalid verification submission.", "danger")
        return redirect(url_for("moderation.admin_employers"))

    try:
        employer = review_employer_verification(
            admin_user=current_user,
            employer_id=employer_id,
            decision=form.decision.data or "unverified",
            verification_notes=form.verification_notes.data,
            ip_address=request.remote_addr,
        )
        flash(
            f"Verification status for '{employer.business_name}' set to "
            f"'{employer.verification_status}'.",
            "success",
        )
    except (DomainRuleError, AuthorizationError, ValueError) as exc:
        flash(str(exc), "danger")

    return redirect(url_for("moderation.admin_employers"))


@moderation_bp.post("/admin/jobs/<int:job_id>/moderate")
@role_required("admin")
def moderate_job_action(job_id: int):
    """Allow an administrator to archive, close, or restore a job listing."""
    form = AdminJobModerationForm()
    if not form.validate_on_submit():
        flash("Invalid job moderation request.", "danger")
        return redirect(url_for("jobs.job_detail", job_id=job_id))

    try:
        job = moderate_job_listing(
            admin_user=current_user,
            job_id=job_id,
            target_status=form.target_status.data or "archived",
            reason=form.reason.data,
            ip_address=request.remote_addr,
        )
        flash(f"Job #{job.id} ('{job.title}') status updated to '{job.status}'.", "success")
    except (DomainRuleError, AuthorizationError, ValueError) as exc:
        flash(str(exc), "danger")

    return redirect(url_for("jobs.job_detail", job_id=job_id))


@moderation_bp.post("/admin/users/<int:user_id>/status")
@role_required("admin")
def update_user_status_action(user_id: int):
    """Suspend or reactivate a user account from the Admin Console."""
    form = AdminUserStatusForm()
    if not form.validate_on_submit():
        flash("Invalid user status form submission.", "danger")
        return redirect(url_for("moderation.admin_dashboard"))

    try:
        user = set_user_account_status(
            admin_user=current_user,
            target_user_id=user_id,
            target_status=form.target_status.data or "active",
            reason=form.reason.data,
            ip_address=request.remote_addr,
        )
        flash(
            f"Account status for '{user.full_name}' ({user.normalized_email}) "
            f"updated to '{user.account_status}'.",
            "success",
        )
    except (DomainRuleError, AuthorizationError, ValueError) as exc:
        flash(str(exc), "danger")

    return redirect(url_for("moderation.admin_dashboard"))
