"""Services for Job Creation, Editing, Discovery Search, Saved Jobs, and Notifications."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import func, or_, select
from sqlalchemy.orm import selectinload

from app.extensions import db
from app.models.job import VALID_JOB_STATUSES, Job, SavedJob
from app.models.security_and_trust import AuditEvent, Notification
from app.models.user import EmployerProfile, User, utc_now
from app.services.job_transactions import AuthorizationError, DomainRuleError


@dataclass(frozen=True)
class JobSearchPage:
    """Paginated search result container for the Job Discovery page."""

    jobs: list[Job]
    total_count: int
    page: int
    per_page: int
    total_pages: int


def create_job_listing(
    *,
    employer_user: User,
    title: str,
    category: str,
    job_type: str,
    description: str,
    responsibilities: str,
    required_skills: str | None,
    experience_required: str | None,
    location: str,
    pincode: str,
    wage_amount: Decimal,
    wage_frequency: str,
    working_hours: str,
    vacancies: int,
    application_deadline: date,
    submit_action: str = "publish",
    ip_address: str | None = None,
) -> Job:
    """Atomically create a new Job listing (draft or published) for an Employer."""
    if not employer_user.is_employer or employer_user.employer_profile is None:
        msg = "Only Employer accounts with a business profile can create job listings."
        raise AuthorizationError(msg)

    initial_status = "published" if submit_action == "publish" else "draft"

    try:
        job = Job(
            employer_id=employer_user.employer_profile.id,
            title=title.strip(),
            category=category.strip(),
            job_type=job_type.strip().lower(),
            description=description.strip(),
            responsibilities=responsibilities.strip(),
            required_skills=required_skills.strip() if required_skills else None,
            experience_required=experience_required.strip() if experience_required else None,
            location=location.strip(),
            pincode=pincode.strip(),
            wage_amount=Decimal(str(wage_amount)),
            currency="INR",
            wage_frequency=wage_frequency.strip().lower(),
            working_hours=working_hours.strip(),
            vacancies=int(vacancies),
            application_deadline=application_deadline,
            status=initial_status,
        )
        if initial_status == "published":
            job.publish()

        db.session.add(job)
        db.session.flush()

        audit = AuditEvent.record(
            actor_id=employer_user.id,
            action="job.publish" if initial_status == "published" else "job.create_draft",
            resource_type="job",
            resource_id=job.id,
            metadata={"status": job.status, "category": job.category, "pincode": job.pincode},
            ip_address=ip_address,
        )
        db.session.add(audit)
        db.session.commit()
        return job
    except Exception:
        db.session.rollback()
        raise


def update_job_listing(
    *,
    employer_user: User,
    job_id: int,
    title: str,
    category: str,
    job_type: str,
    description: str,
    responsibilities: str,
    required_skills: str | None,
    experience_required: str | None,
    location: str,
    pincode: str,
    wage_amount: Decimal,
    wage_frequency: str,
    working_hours: str,
    vacancies: int,
    application_deadline: date,
    submit_action: str = "publish",
    ip_address: str | None = None,
) -> Job:
    """Atomically update an existing Job listing after verifying server-side ownership."""
    try:
        stmt = select(Job).where(Job.id == job_id).with_for_update()
        job = db.session.execute(stmt).scalar_one_or_none()
        if job is None:
            msg = "Job listing not found."
            raise DomainRuleError(msg)

        if not job.is_owned_by_user(employer_user):
            msg = "You do not have permission to edit this job listing."
            raise AuthorizationError(msg)

        job.title = title.strip()
        job.category = category.strip()
        job.job_type = job_type.strip().lower()
        job.description = description.strip()
        job.responsibilities = responsibilities.strip()
        job.required_skills = required_skills.strip() if required_skills else None
        job.experience_required = experience_required.strip() if experience_required else None
        job.location = location.strip()
        job.pincode = pincode.strip()
        job.wage_amount = Decimal(str(wage_amount))
        job.wage_frequency = wage_frequency.strip().lower()
        job.working_hours = working_hours.strip()
        job.vacancies = int(vacancies)
        job.application_deadline = application_deadline

        if submit_action == "publish":
            job.publish()
        elif submit_action in ("draft", "preview"):
            job.status = "draft"

        audit = AuditEvent.record(
            actor_id=employer_user.id,
            action="job.update",
            resource_type="job",
            resource_id=job.id,
            metadata={"status": job.status, "submit_action": submit_action},
            ip_address=ip_address,
        )
        db.session.add(audit)
        db.session.commit()
        return job
    except Exception:
        db.session.rollback()
        raise


def change_job_status(
    *,
    employer_user: User,
    job_id: int,
    target_status: str,
    ip_address: str | None = None,
) -> Job:
    """Atomically transition a Job between draft, published, closed, or archived."""
    cleaned_status = target_status.strip().lower()
    if cleaned_status not in VALID_JOB_STATUSES:
        msg = f"Invalid job status '{target_status}'."
        raise DomainRuleError(msg)

    try:
        stmt = select(Job).where(Job.id == job_id).with_for_update()
        job = db.session.execute(stmt).scalar_one_or_none()
        if job is None:
            msg = "Job listing not found."
            raise DomainRuleError(msg)

        if not job.is_owned_by_user(employer_user):
            msg = "You do not have permission to modify this job listing."
            raise AuthorizationError(msg)

        previous_status = job.status
        if cleaned_status == "published":
            if job.is_expired():
                msg = "Cannot publish a job whose application deadline is in the past."
                raise DomainRuleError(msg)
            job.publish()
        else:
            job.status = cleaned_status

        audit = AuditEvent.record(
            actor_id=employer_user.id,
            action="job.status_change",
            resource_type="job",
            resource_id=job.id,
            metadata={"from_status": previous_status, "to_status": job.status},
            ip_address=ip_address,
        )
        db.session.add(audit)
        db.session.commit()
        return job
    except Exception:
        db.session.rollback()
        raise


def search_published_jobs(
    *,
    q: str = "",
    location: str = "",
    category: str = "",
    job_type: str = "",
    wage_frequency: str = "",
    min_wage: Decimal | None = None,
    max_wage: Decimal | None = None,
    sort: str = "newest",
    page: int = 1,
    per_page: int = 10,
) -> JobSearchPage:
    """Execute a filtered, sorted, paginated query over active published Job records."""
    today = datetime.now(UTC).date()
    safe_page = max(1, int(page))
    safe_per_page = max(1, min(50, int(per_page)))

    filters = [
        Job.status == "published",
        Job.application_deadline >= today,
        Job.vacancies >= 1,
        EmployerProfile.id.is_not(None),
        User.role == "employer",
        User.account_status.in_(("active", "pending_verification")),
    ]

    if q.strip():
        pattern = f"%{q.strip()}%"
        filters.append(
            or_(
                Job.title.ilike(pattern),
                Job.description.ilike(pattern),
                Job.responsibilities.ilike(pattern),
                Job.required_skills.ilike(pattern),
            )
        )

    if location.strip():
        loc_pattern = f"%{location.strip()}%"
        filters.append(
            or_(
                Job.location.ilike(loc_pattern),
                Job.pincode.ilike(loc_pattern),
            )
        )

    if category.strip():
        filters.append(Job.category == category.strip())

    if job_type.strip():
        filters.append(Job.job_type == job_type.strip().lower())

    if wage_frequency.strip():
        filters.append(Job.wage_frequency == wage_frequency.strip().lower())

    if min_wage is not None:
        filters.append(Job.wage_amount >= min_wage)

    if max_wage is not None:
        filters.append(Job.wage_amount <= max_wage)

    count_stmt = (
        select(func.count(Job.id))
        .join(Job.employer)
        .join(EmployerProfile.user)
        .where(*filters)
    )
    total_count = int(db.session.execute(count_stmt).scalar_one() or 0)
    total_pages = max(1, math.ceil(total_count / safe_per_page))
    if safe_page > total_pages:
        safe_page = total_pages

    stmt = (
        select(Job)
        .join(Job.employer)
        .join(EmployerProfile.user)
        .options(selectinload(Job.employer))
        .where(*filters)
    )

    cleaned_sort = sort.strip().lower()
    if cleaned_sort == "wage_high":
        stmt = stmt.order_by(Job.wage_amount.desc(), Job.id.desc())
    elif cleaned_sort == "wage_low":
        stmt = stmt.order_by(Job.wage_amount.asc(), Job.id.desc())
    elif cleaned_sort == "deadline_soon":
        stmt = stmt.order_by(Job.application_deadline.asc(), Job.id.desc())
    else:
        stmt = stmt.order_by(Job.published_at.desc(), Job.id.desc())

    offset = (safe_page - 1) * safe_per_page
    stmt = stmt.offset(offset).limit(safe_per_page)
    jobs = list(db.session.execute(stmt).scalars().all())

    return JobSearchPage(
        jobs=jobs,
        total_count=total_count,
        page=safe_page,
        per_page=safe_per_page,
        total_pages=total_pages,
    )


def toggle_saved_job(*, worker_user: User, job_id: int) -> bool:
    """Bookmark a Job for a Worker, or remove the bookmark if already saved.

    Returns True when the job is now saved, or False when removed.
    """
    if not worker_user.is_worker or worker_user.worker_profile is None:
        msg = "Only Worker accounts can bookmark jobs."
        raise AuthorizationError(msg)

    worker_profile = worker_user.worker_profile
    job = db.session.get(Job, job_id)
    if job is None or job.status == "draft":
        msg = "Job listing not found."
        raise DomainRuleError(msg)

    try:
        existing_stmt = select(SavedJob).where(
            SavedJob.worker_id == worker_profile.id,
            SavedJob.job_id == job.id,
        )
        existing = db.session.execute(existing_stmt).scalar_one_or_none()
        if existing is not None:
            db.session.delete(existing)
            db.session.commit()
            return False

        saved = SavedJob(worker_id=worker_profile.id, job_id=job.id)
        db.session.add(saved)
        db.session.commit()
        return True
    except Exception:
        db.session.rollback()
        raise


def mark_notification_read(*, user: User, notification_id: int) -> Notification:
    """Mark a single notification as read after verifying ownership."""
    notif = db.session.get(Notification, notification_id)
    if notif is None:
        msg = "Notification not found."
        raise DomainRuleError(msg)
    if notif.user_id != user.id:
        msg = "You cannot modify another user's notification."
        raise AuthorizationError(msg)

    notif.mark_read()
    db.session.commit()
    return notif


def mark_all_notifications_read(*, user: User) -> int:
    """Mark all unread notifications for the given user as read."""
    now = utc_now()
    stmt = select(Notification).where(
        Notification.user_id == user.id,
        Notification.read_at.is_(None),
    )
    unread_items = list(db.session.execute(stmt).scalars().all())
    for item in unread_items:
        item.read_at = now
    db.session.commit()
    return len(unread_items)
