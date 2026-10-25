"""Moderation, Admin Operations, Employer Verification, and Personal Data Export Service."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select

from app.extensions import db
from app.models.job import Job, JobApplication, SavedJob
from app.models.security_and_trust import AuditEvent, Notification, Report
from app.models.user import EmployerProfile, User, WorkerProfile, utc_now
from app.services.job_transactions import AuthorizationError, DomainRuleError


def _resolve_target_owner_user(target_type: str, target_id: int) -> tuple[Any, User | None]:
    """Return `(target_entity, owner_user)` for a moderation target or `(None, None)`."""
    cleaned_type = target_type.strip().lower()
    if cleaned_type == "job":
        job = db.session.get(Job, target_id)
        if job is None:
            return None, None
        owner_user = job.employer.user if job.employer else None
        return job, owner_user
    if cleaned_type == "employer":
        employer = db.session.get(EmployerProfile, target_id)
        if employer is None:
            return None, None
        return employer, employer.user
    if cleaned_type == "worker":
        worker = db.session.get(WorkerProfile, target_id)
        if worker is None:
            return None, None
        return worker, worker.user
    return None, None


def submit_moderation_report(
    *,
    reporter: User,
    target_type: str,
    target_id: int,
    reason: str,
    details: str,
    ip_address: str | None = None,
) -> Report:
    """Create a validated moderation report and record an audit event."""
    if not reporter.is_active:
        msg = "Active account required to submit a moderation report."
        raise AuthorizationError(msg)

    entity, _ = _resolve_target_owner_user(target_type, target_id)
    if entity is None:
        msg = f"The specified {target_type} (#{target_id}) could not be found."
        raise DomainRuleError(msg)

    cleaned_details = (details or "").strip()
    if len(cleaned_details) < 10:
        msg = "Please provide at least 10 characters describing the issue."
        raise DomainRuleError(msg)

    report = Report(
        reporter_id=reporter.id,
        target_type=target_type.strip().lower(),
        target_id=target_id,
        reason=reason.strip().lower(),
        details=cleaned_details,
        status="open",
        moderation_action="none",
    )
    db.session.add(report)
    db.session.flush()

    db.session.add(
        AuditEvent.record(
            actor_id=reporter.id,
            action="report.submitted",
            resource_type="report",
            resource_id=report.id,
            metadata={
                "target_type": report.target_type,
                "target_id": report.target_id,
                "reason": report.reason,
            },
            ip_address=ip_address,
        )
    )
    db.session.commit()
    return report


def resolve_moderation_report(
    *,
    admin_user: User,
    report_id: int,
    status: str,
    moderation_action: str,
    resolution_notes: str | None = None,
    ip_address: str | None = None,
) -> Report:
    """Process an admin moderation decision and execute any linked enforcement action."""
    if not admin_user.is_active or admin_user.role != "admin":
        msg = "Only administrators can review moderation reports."
        raise AuthorizationError(msg)

    report = db.session.get(Report, report_id)
    if report is None:
        msg = f"Report #{report_id} does not exist."
        raise DomainRuleError(msg)

    cleaned_status = status.strip().lower()
    cleaned_action = moderation_action.strip().lower()
    cleaned_notes = (resolution_notes or "").strip() or None

    if cleaned_status == "investigating":
        report.status = "investigating"
        report.reviewer_id = admin_user.id
        report.moderation_action = cleaned_action
        report.resolution_notes = cleaned_notes
    elif cleaned_status in ("resolved", "dismissed"):
        report.resolve(
            reviewer_id=admin_user.id,
            action=cleaned_action,
            status=cleaned_status,
            notes=cleaned_notes,
        )
    else:
        msg = f"Unsupported report status '{status}'."
        raise DomainRuleError(msg)

    entity, owner_user = _resolve_target_owner_user(report.target_type, report.target_id)

    # Execute atomic enforcement action on target entity when requested
    if cleaned_action == "listing_hidden" and report.target_type == "job" and entity is not None:
        job: Job = entity
        job.status = "archived"
        job.closed_at = utc_now()
        if owner_user is not None:
            db.session.add(
                Notification(
                    user_id=owner_user.id,
                    notification_type="moderation",
                    title=f"Job listing archived by Trust & Safety: {job.title}",
                    message=(
                        f"Your job listing '{job.title}' was archived following a "
                        f"Trust & Safety review ({report.reason})."
                    ),
                )
            )
    elif cleaned_action == "account_suspended" and owner_user is not None:
        if owner_user.role == "admin":
            msg = "Administrator accounts cannot be suspended via report resolution."
            raise DomainRuleError(msg)
        owner_user.account_status = "suspended"
    elif cleaned_action == "warning_issued" and owner_user is not None:
        db.session.add(
            Notification(
                user_id=owner_user.id,
                notification_type="moderation",
                title="Earn & Pay Trust & Safety Warning",
                message=(
                    cleaned_notes
                    or (
                        "Please review Earn & Pay marketplace safety guidelines. "
                        "Asking workers for fees or posting misleading terms is prohibited."
                    )
                ),
            )
        )

    # Notify reporter when report reaches a terminal resolution
    if report.reporter_id is not None and cleaned_status in ("resolved", "dismissed"):
        db.session.add(
            Notification(
                user_id=report.reporter_id,
                notification_type="moderation",
                title=f"Moderation update on Report #{report.id}",
                message=(
                    f"Our Trust & Safety team has {cleaned_status} your report "
                    f"regarding {report.target_type} #{report.target_id}."
                ),
            )
        )

    db.session.add(
        AuditEvent.record(
            actor_id=admin_user.id,
            action="admin.report_moderated",
            resource_type="report",
            resource_id=report.id,
            metadata={
                "status": report.status,
                "moderation_action": report.moderation_action,
                "target_type": report.target_type,
                "target_id": report.target_id,
            },
            ip_address=ip_address,
        )
    )
    db.session.commit()
    return report


def review_employer_verification(
    *,
    admin_user: User,
    employer_id: int,
    decision: str,
    verification_notes: str | None = None,
    ip_address: str | None = None,
) -> EmployerProfile:
    """Approve or revoke an employer's verified status with strict timestamp integrity."""
    if not admin_user.is_active or admin_user.role != "admin":
        msg = "Only administrators can verify employer profiles."
        raise AuthorizationError(msg)

    employer = db.session.get(EmployerProfile, employer_id)
    if employer is None:
        msg = f"Employer profile #{employer_id} not found."
        raise DomainRuleError(msg)

    cleaned_decision = decision.strip().lower()
    if cleaned_decision not in ("verified", "pending", "unverified"):
        msg = f"Invalid verification decision '{decision}'."
        raise DomainRuleError(msg)

    previous_status = employer.verification_status
    employer.verification_status = cleaned_decision
    employer.verification_notes = (verification_notes or "").strip() or None

    if cleaned_decision == "verified":
        employer.verified_at = utc_now()
        notif_title = f"Verified Employer Badge Approved: {employer.business_name}"
        notif_msg = (
            "Your business profile has been verified by Earn & Pay operations. "
            "Your listings now display the Verified Employer badge."
        )
    else:
        employer.verified_at = None
        notif_title = f"Verification status updated: {employer.business_name}"
        notif_msg = (
            f"Your employer verification status is now '{cleaned_decision}'. "
            f"{employer.verification_notes or ''}".strip()
        )

    db.session.add(
        Notification(
            user_id=employer.user_id,
            notification_type="moderation",
            title=notif_title,
            message=notif_msg,
        )
    )
    db.session.add(
        AuditEvent.record(
            actor_id=admin_user.id,
            action="admin.employer_verification_updated",
            resource_type="employer_profile",
            resource_id=employer.id,
            metadata={
                "previous_status": previous_status,
                "new_status": employer.verification_status,
                "is_genuinely_verified": employer.is_genuinely_verified,
            },
            ip_address=ip_address,
        )
    )
    db.session.commit()
    return employer


def moderate_job_listing(
    *,
    admin_user: User,
    job_id: int,
    target_status: str,
    reason: str | None = None,
    ip_address: str | None = None,
) -> Job:
    """Allow an administrator to archive, close, or restore a job listing."""
    if not admin_user.is_active or admin_user.role != "admin":
        msg = "Only administrators can moderate job listings."
        raise AuthorizationError(msg)

    job = db.session.get(Job, job_id)
    if job is None:
        msg = f"Job #{job_id} does not exist."
        raise DomainRuleError(msg)

    cleaned_status = target_status.strip().lower()
    if cleaned_status not in ("published", "closed", "archived"):
        msg = f"Invalid moderation status '{target_status}'."
        raise DomainRuleError(msg)

    previous_status = job.status
    if cleaned_status == "published":
        job.publish()
    else:
        job.status = cleaned_status
        job.closed_at = utc_now()

    if job.employer and job.employer.user_id:
        db.session.add(
            Notification(
                user_id=job.employer.user_id,
                notification_type="moderation",
                title=f"Listing status updated by moderator: {job.title}",
                message=(
                    f"Your job listing '{job.title}' status was changed from "
                    f"'{previous_status}' to '{job.status}'. {reason or ''}".strip()
                ),
            )
        )

    db.session.add(
        AuditEvent.record(
            actor_id=admin_user.id,
            action="admin.job_status_moderated",
            resource_type="job",
            resource_id=job.id,
            metadata={
                "previous_status": previous_status,
                "new_status": job.status,
                "reason": (reason or "").strip() or None,
            },
            ip_address=ip_address,
        )
    )
    db.session.commit()
    return job


def set_user_account_status(
    *,
    admin_user: User,
    target_user_id: int,
    target_status: str,
    reason: str | None = None,
    ip_address: str | None = None,
) -> User:
    """Allow an administrator to suspend or reactivate a non-self user account."""
    if not admin_user.is_active or admin_user.role != "admin":
        msg = "Only administrators can change user account status."
        raise AuthorizationError(msg)

    if admin_user.id == target_user_id:
        msg = "Administrators cannot suspend or modify their own account status."
        raise DomainRuleError(msg)

    target_user = db.session.get(User, target_user_id)
    if target_user is None:
        msg = f"User #{target_user_id} does not exist."
        raise DomainRuleError(msg)

    cleaned_status = target_status.strip().lower()
    if cleaned_status not in ("active", "suspended"):
        msg = f"Invalid user status '{target_status}'."
        raise DomainRuleError(msg)

    previous_status = target_user.account_status
    target_user.account_status = cleaned_status

    db.session.add(
        AuditEvent.record(
            actor_id=admin_user.id,
            action="admin.user_status_changed",
            resource_type="user",
            resource_id=target_user.id,
            metadata={
                "previous_status": previous_status,
                "new_status": target_user.account_status,
                "reason": (reason or "").strip() or None,
            },
            ip_address=ip_address,
        )
    )
    db.session.commit()
    return target_user


def export_user_personal_data(user: User, ip_address: str | None = None) -> dict[str, Any]:
    """Assemble a portable, secret-free JSON export of a user's personal data."""
    payload: dict[str, Any] = {
        "exported_at": utc_now().isoformat(),
        "platform": "Earn & Pay",
        "account": {
            "id": user.id,
            "full_name": user.full_name,
            "email": user.normalized_email,
            "role": user.role,
            "account_status": user.account_status,
            "email_verified": user.email_verified,
            "created_at": user.created_at.isoformat() if user.created_at else None,
        },
        "worker_profile": None,
        "employer_profile": None,
        "applications": [],
        "saved_jobs": [],
        "notifications": [],
        "reports_submitted": [],
    }

    if user.worker_profile is not None:
        wp = user.worker_profile
        payload["worker_profile"] = {
            "phone_number": wp.phone_number,
            "skills": wp.skills,
            "experience_summary": wp.experience_summary,
            "preferred_categories": wp.preferred_categories,
            "preferred_location": wp.preferred_location,
            "pincode": wp.pincode,
            "travel_radius_km": wp.travel_radius_km,
            "availability": wp.availability,
            "expected_daily_wage": (
                str(wp.expected_daily_wage) if wp.expected_daily_wage is not None else None
            ),
            "privacy": {
                "show_phone_to_employers": wp.show_phone_to_employers,
                "is_profile_public": wp.is_profile_public,
            },
        }
        apps = (
            db.session.execute(
                select(JobApplication)
                .where(JobApplication.worker_id == wp.id)
                .order_by(JobApplication.applied_at.desc())
            )
            .scalars()
            .all()
        )
        payload["applications"] = [
            {
                "id": app_rec.id,
                "job_id": app_rec.job_id,
                "status": app_rec.status,
                "cover_note": app_rec.cover_note,
                "applied_at": app_rec.applied_at.isoformat() if app_rec.applied_at else None,
            }
            for app_rec in apps
        ]
        saved = (
            db.session.execute(
                select(SavedJob)
                .where(SavedJob.worker_id == wp.id)
                .order_by(SavedJob.saved_at.desc())
            )
            .scalars()
            .all()
        )
        payload["saved_jobs"] = [
            {
                "job_id": s.job_id,
                "saved_at": s.saved_at.isoformat() if s.saved_at else None,
            }
            for s in saved
        ]

    if user.employer_profile is not None:
        ep = user.employer_profile
        payload["employer_profile"] = {
            "business_name": ep.business_name,
            "business_type": ep.business_type,
            "description": ep.description,
            "address": ep.address,
            "location": ep.location,
            "pincode": ep.pincode,
            "contact_phone": ep.contact_phone,
            "verification_status": ep.verification_status,
            "is_genuinely_verified": ep.is_genuinely_verified,
        }

    notifs = (
        db.session.execute(
            select(Notification)
            .where(Notification.user_id == user.id)
            .order_by(Notification.created_at.desc())
            .limit(100)
        )
        .scalars()
        .all()
    )
    payload["notifications"] = [
        {
            "id": n.id,
            "type": n.notification_type,
            "title": n.title,
            "message": n.message,
            "read": n.is_read,
            "created_at": n.created_at.isoformat() if n.created_at else None,
        }
        for n in notifs
    ]

    reports = (
        db.session.execute(
            select(Report)
            .where(Report.reporter_id == user.id)
            .order_by(Report.created_at.desc())
        )
        .scalars()
        .all()
    )
    payload["reports_submitted"] = [
        {
            "id": r.id,
            "target_type": r.target_type,
            "target_id": r.target_id,
            "reason": r.reason,
            "status": r.status,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in reports
    ]

    db.session.add(
        AuditEvent.record(
            actor_id=user.id,
            action="user.data_exported",
            resource_type="user",
            resource_id=user.id,
            metadata={"role": user.role},
            ip_address=ip_address,
        )
    )
    db.session.commit()
    return payload
