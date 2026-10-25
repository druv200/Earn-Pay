"""Transactional services for updating Worker/Employer profiles and Account Deletion."""

from __future__ import annotations

import math
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import selectinload

from app.extensions import db
from app.models.job import JobApplication
from app.models.security_and_trust import AuditEvent
from app.models.user import (
    VALID_WORKER_AVAILABILITY,
    EmployerProfile,
    User,
    WorkerProfile,
    utc_now,
)
from app.services.job_transactions import AuthorizationError, DomainRuleError
from app.utils.security import normalize_email


@dataclass(frozen=True)
class WorkerSearchPage:
    """Paginated result container for the Employer Find Workers directory."""

    workers: list[WorkerProfile]
    total_count: int
    page: int
    per_page: int
    total_pages: int


def _eligible_worker_filters() -> list[Any]:
    """Return SQLAlchemy filter predicates for an eligible, discoverable available worker."""
    return [
        User.role == "worker",
        User.account_status.in_(("active", "pending_verification")),
        WorkerProfile.is_profile_public.is_(True),
        WorkerProfile.availability.in_(VALID_WORKER_AVAILABILITY),
        WorkerProfile.skills.is_not(None),
        func.length(func.trim(WorkerProfile.skills)) > 0,
        or_(
            and_(
                WorkerProfile.pincode.is_not(None),
                func.length(func.trim(WorkerProfile.pincode)) > 0,
            ),
            and_(
                WorkerProfile.preferred_location.is_not(None),
                func.length(func.trim(WorkerProfile.preferred_location)) > 0,
            ),
        ),
    ]


def count_available_workers(*, location: str = "") -> int:
    """Calculate the number of eligible available workers from the database."""
    filters = _eligible_worker_filters()
    if location.strip():
        loc_pattern = f"%{location.strip()}%"
        filters.append(
            or_(
                WorkerProfile.preferred_location.ilike(loc_pattern),
                WorkerProfile.pincode.ilike(loc_pattern),
            )
        )
    stmt = (
        select(func.count(func.distinct(WorkerProfile.id)))
        .join(WorkerProfile.user)
        .where(*filters)
    )
    return int(db.session.execute(stmt).scalar_one() or 0)


def search_available_workers(
    *,
    q: str = "",
    location: str = "",
    category: str = "",
    availability: str = "",
    min_wage: Decimal | None = None,
    max_wage: Decimal | None = None,
    page: int = 1,
    per_page: int = 10,
) -> WorkerSearchPage:
    """Execute a filtered, paginated query over eligible available WorkerProfile records."""
    safe_page = max(1, int(page))
    safe_per_page = max(1, min(50, int(per_page)))

    filters = _eligible_worker_filters()

    if q.strip():
        pattern = f"%{q.strip()}%"
        filters.append(
            or_(
                User.full_name.ilike(pattern),
                WorkerProfile.skills.ilike(pattern),
                WorkerProfile.experience_summary.ilike(pattern),
                WorkerProfile.preferred_categories.ilike(pattern),
            )
        )

    if location.strip():
        loc_pattern = f"%{location.strip()}%"
        filters.append(
            or_(
                WorkerProfile.preferred_location.ilike(loc_pattern),
                WorkerProfile.pincode.ilike(loc_pattern),
            )
        )

    if category.strip():
        cat_pattern = f"%{category.strip()}%"
        filters.append(WorkerProfile.preferred_categories.ilike(cat_pattern))

    if availability.strip():
        filters.append(WorkerProfile.availability == availability.strip().lower())

    if min_wage is not None:
        filters.append(WorkerProfile.expected_daily_wage.is_not(None))
        filters.append(WorkerProfile.expected_daily_wage >= min_wage)

    if max_wage is not None:
        filters.append(WorkerProfile.expected_daily_wage.is_not(None))
        filters.append(WorkerProfile.expected_daily_wage <= max_wage)

    count_stmt = (
        select(func.count(func.distinct(WorkerProfile.id)))
        .join(WorkerProfile.user)
        .where(*filters)
    )
    total_count = int(db.session.execute(count_stmt).scalar_one() or 0)
    total_pages = max(1, math.ceil(total_count / safe_per_page))
    if safe_page > total_pages:
        safe_page = total_pages

    offset = (safe_page - 1) * safe_per_page
    stmt = (
        select(WorkerProfile)
        .join(WorkerProfile.user)
        .options(selectinload(WorkerProfile.user))
        .where(*filters)
        .order_by(WorkerProfile.updated_at.desc(), WorkerProfile.id.desc())
        .offset(offset)
        .limit(safe_per_page)
    )
    workers = list(db.session.execute(stmt).scalars().all())

    return WorkerSearchPage(
        workers=workers,
        total_count=total_count,
        page=safe_page,
        per_page=safe_per_page,
        total_pages=total_pages,
    )


def update_worker_profile(
    *,
    user: User,
    full_name: str,
    phone_number: str | None,
    skills: str | None,
    experience_summary: str | None,
    preferred_categories: str | None,
    preferred_location: str | None,
    pincode: str | None,
    travel_radius_km: int,
    availability: str,
    expected_daily_wage: Decimal | None,
    is_profile_public: bool,
    show_phone_to_employers: bool,
    ip_address: str | None = None,
) -> WorkerProfile:
    """Atomically update a Worker's identity, skills, preferences, and privacy settings."""
    if not user.is_worker:
        msg = "Only Worker accounts can update a worker profile."
        raise AuthorizationError(msg)

    try:
        profile = user.worker_profile
        if profile is None:
            profile = WorkerProfile(user_id=user.id)
            db.session.add(profile)

        user.full_name = full_name.strip()
        profile.phone_number = phone_number.strip() if phone_number else None
        profile.skills = skills.strip() if skills else None
        profile.experience_summary = experience_summary.strip() if experience_summary else None
        profile.preferred_categories = (
            preferred_categories.strip() if preferred_categories else None
        )
        profile.preferred_location = preferred_location.strip() if preferred_location else None
        profile.pincode = pincode.strip() if pincode else None
        profile.travel_radius_km = int(travel_radius_km)
        profile.availability = availability.strip().lower()
        profile.expected_daily_wage = expected_daily_wage
        profile.is_profile_public = bool(is_profile_public)
        profile.show_phone_to_employers = bool(show_phone_to_employers)

        audit = AuditEvent.record(
            actor_id=user.id,
            action="worker_profile.update",
            resource_type="worker_profile",
            resource_id=profile.id,
            metadata={
                "is_profile_public": profile.is_profile_public,
                "show_phone_to_employers": profile.show_phone_to_employers,
                "completion": profile.completion_percentage,
            },
            ip_address=ip_address,
        )
        db.session.add(audit)
        db.session.commit()
        return profile
    except Exception:
        db.session.rollback()
        raise


def update_employer_profile(
    *,
    user: User,
    full_name: str,
    business_name: str,
    business_type: str,
    description: str | None,
    address: str | None,
    location: str | None,
    pincode: str | None,
    contact_phone: str | None,
    request_verification: bool = False,
    ip_address: str | None = None,
) -> EmployerProfile:
    """Atomically update an Employer's business profile and optional verification request."""
    if not user.is_employer:
        msg = "Only Employer accounts can update an employer business profile."
        raise AuthorizationError(msg)

    try:
        profile = user.employer_profile
        if profile is None:
            profile = EmployerProfile(user_id=user.id, business_name=business_name.strip())
            db.session.add(profile)

        user.full_name = full_name.strip()
        profile.business_name = business_name.strip()
        profile.business_type = business_type.strip().lower()
        profile.description = description.strip() if description else None
        profile.address = address.strip() if address else None
        profile.location = location.strip() if location else None
        profile.pincode = pincode.strip() if pincode else None
        profile.contact_phone = contact_phone.strip() if contact_phone else None

        # Allow unverified employers to submit their profile for moderator review
        if request_verification and profile.verification_status == "unverified":
            profile.verification_status = "pending"

        audit = AuditEvent.record(
            actor_id=user.id,
            action="employer_profile.update",
            resource_type="employer_profile",
            resource_id=profile.id,
            metadata={
                "business_type": profile.business_type,
                "verification_status": profile.verification_status,
            },
            ip_address=ip_address,
        )
        db.session.add(audit)
        db.session.commit()
        return profile
    except Exception:
        db.session.rollback()
        raise


def can_employer_view_worker_profile(viewer: User, worker_profile: WorkerProfile) -> bool:
    """Return True if viewer is authorized to view worker_profile (public or active applicant)."""
    if viewer.is_admin:
        return True
    if viewer.id == worker_profile.user_id:
        return True
    if not viewer.is_employer or viewer.employer_profile is None:
        return False
    if worker_profile.is_profile_public:
        return True

    # Even if profile is marked private, an employer can view an applicant who applied to their job
    stmt = (
        select(JobApplication.id)
        .join(JobApplication.job)
        .where(
            JobApplication.worker_id == worker_profile.id,
            JobApplication.job.has(employer_id=viewer.employer_profile.id),
        )
        .limit(1)
    )
    return db.session.execute(stmt).scalar_one_or_none() is not None


def request_account_deletion(
    *,
    user: User,
    confirm_email: str,
    reason: str | None = None,
    ip_address: str | None = None,
) -> None:
    """Execute a documented account deletion and deactivation workflow."""
    if normalize_email(confirm_email) != user.normalized_email:
        msg = "The confirmation email address does not match your account email."
        raise DomainRuleError(msg)

    try:
        now = utc_now()
        user.account_status = "deleted"
        user.deletion_requested_at = now

        if user.worker_profile is not None:
            user.worker_profile.is_profile_public = False
            user.worker_profile.show_phone_to_employers = False
            user.worker_profile.phone_number = None

        if user.employer_profile is not None:
            for job in user.employer_profile.jobs:
                if job.status in ("draft", "published"):
                    job.status = "closed"

        audit = AuditEvent.record(
            actor_id=user.id,
            action="user.deletion_requested",
            resource_type="user",
            resource_id=user.id,
            metadata={"reason_provided": bool(reason and reason.strip())},
            ip_address=ip_address,
        )
        db.session.add(audit)
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise
