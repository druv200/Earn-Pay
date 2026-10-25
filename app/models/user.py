"""User, WorkerProfile, and EmployerProfile relational models."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from flask_login import UserMixin
from sqlalchemy import CheckConstraint, Index, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship, validates
from werkzeug.security import check_password_hash, generate_password_hash

from app.extensions import db
from app.utils.security import normalize_email

if TYPE_CHECKING:
    from app.models.job import Job, JobApplication, SavedJob
    from app.models.security_and_trust import (
        AuditEvent,
        EmailVerificationToken,
        Notification,
        PasswordResetToken,
        Report,
    )

PK_TYPE = db.BigInteger().with_variant(db.Integer, "sqlite")

VALID_USER_ROLES: tuple[str, ...] = ("worker", "employer", "admin")
LEGACY_ROLE_COMPATIBILITY_MAP: dict[str, str] = {
    "employee": "worker",
    "job_seeker": "worker",
    "jobseeker": "worker",
    "hiring": "employer",
    "business": "employer",
}


def normalize_user_role(value: str | None) -> str:
    """Normalize role string and map legacy role names ('employee') to canonical values."""
    cleaned = (value or "").strip().lower()
    return LEGACY_ROLE_COMPATIBILITY_MAP.get(cleaned, cleaned)

VALID_ACCOUNT_STATUSES: tuple[str, ...] = (
    "active",
    "pending_verification",
    "suspended",
    "deleted",
)
VALID_WORKER_AVAILABILITY: tuple[str, ...] = (
    "daily",
    "part_time",
    "weekends",
    "flexible",
    "full_time",
)
VALID_BUSINESS_TYPES: tuple[str, ...] = (
    "shop",
    "restaurant",
    "logistics",
    "service",
    "individual",
    "other",
)
VALID_VERIFICATION_STATUSES: tuple[str, ...] = (
    "unverified",
    "pending",
    "verified",
)


def utc_now() -> datetime:
    """Return current timezone-aware UTC timestamp."""
    return datetime.now(UTC)


class User(UserMixin, db.Model):
    """Core user identity supporting Worker, Employer, and Administrator roles."""

    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("normalized_email", name="uq_users_normalized_email"),
        CheckConstraint(
            "role IN ('worker', 'employer', 'admin')",
            name="valid_user_role",
        ),
        CheckConstraint(
            "account_status IN ('active', 'pending_verification', 'suspended', 'deleted')",
            name="valid_account_status",
        ),
        CheckConstraint(
            "length(trim(full_name)) >= 2",
            name="non_empty_full_name",
        ),
        CheckConstraint(
            "length(trim(normalized_email)) >= 5",
            name="non_empty_normalized_email",
        ),
        Index("ix_users_role_status", "role", "account_status"),
    )

    id: Mapped[int] = mapped_column(PK_TYPE, primary_key=True, autoincrement=True)
    full_name: Mapped[str] = mapped_column(db.String(120), nullable=False)
    normalized_email: Mapped[str] = mapped_column(db.String(255), nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(db.String(255), nullable=False)
    role: Mapped[str] = mapped_column(db.String(20), nullable=False, default="worker")
    account_status: Mapped[str] = mapped_column(
        db.String(30),
        nullable=False,
        default="pending_verification",
    )
    email_verified: Mapped[bool] = mapped_column(db.Boolean, nullable=False, default=False)
    deletion_requested_at: Mapped[datetime | None] = mapped_column(
        db.DateTime(timezone=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        db.DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )
    updated_at: Mapped[datetime] = mapped_column(
        db.DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
    )

    # One-to-one role profiles
    worker_profile: Mapped[WorkerProfile | None] = relationship(
        "WorkerProfile",
        back_populates="user",
        uselist=False,
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    employer_profile: Mapped[EmployerProfile | None] = relationship(
        "EmployerProfile",
        back_populates="user",
        uselist=False,
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    # Security, notifications & audit relationships
    notifications: Mapped[list[Notification]] = relationship(
        "Notification",
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    verification_tokens: Mapped[list[EmailVerificationToken]] = relationship(
        "EmailVerificationToken",
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    password_reset_tokens: Mapped[list[PasswordResetToken]] = relationship(
        "PasswordResetToken",
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    reports_submitted: Mapped[list[Report]] = relationship(
        "Report",
        foreign_keys="Report.reporter_id",
        back_populates="reporter",
    )
    reports_reviewed: Mapped[list[Report]] = relationship(
        "Report",
        foreign_keys="Report.reviewer_id",
        back_populates="reviewer",
    )
    audit_events: Mapped[list[AuditEvent]] = relationship(
        "AuditEvent",
        back_populates="actor",
    )

    @validates("normalized_email")
    def _validate_email(self, _key: str, value: str) -> str:
        cleaned = normalize_email(value)
        if "@" not in cleaned or len(cleaned) < 5:
            msg = "A valid email address is required."
            raise ValueError(msg)
        return cleaned

    @validates("role")
    def _validate_role(self, _key: str, value: str) -> str:
        cleaned = normalize_user_role(value)
        if cleaned not in VALID_USER_ROLES:
            msg = f"Invalid user role '{value}'. Must be one of {VALID_USER_ROLES}."
            raise ValueError(msg)
        return cleaned

    @validates("account_status")
    def _validate_account_status(self, _key: str, value: str) -> str:
        cleaned = value.strip().lower()
        if cleaned not in VALID_ACCOUNT_STATUSES:
            msg = f"Invalid account_status '{value}'. Must be one of {VALID_ACCOUNT_STATUSES}."
            raise ValueError(msg)
        return cleaned

    def set_password(self, raw_password: str) -> None:
        """Hash and store a user password using Werkzeug PBKDF2/scrypt."""
        if not raw_password or len(raw_password) < 8:
            msg = "Password must be at least 8 characters long."
            raise ValueError(msg)
        self.password_hash = generate_password_hash(raw_password)

    def check_password(self, raw_password: str) -> bool:
        """Verify a plaintext password against the stored salted hash."""
        if not self.password_hash or not raw_password:
            return False
        return check_password_hash(self.password_hash, raw_password)

    @property
    def is_active(self) -> bool:
        """Flask-Login integration: suspended or deleted accounts cannot authenticate."""
        return self.account_status in ("active", "pending_verification")

    @property
    def is_worker(self) -> bool:
        return self.role == "worker"

    @property
    def is_employer(self) -> bool:
        return self.role == "employer"

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"

    def __repr__(self) -> str:
        return f"<User id={self.id} email={self.normalized_email!r} role={self.role!r}>"


class WorkerProfile(db.Model):
    """Profile for job seekers looking for local daily-wage, part-time, or temporary work."""

    __tablename__ = "worker_profiles"
    __table_args__ = (
        UniqueConstraint("user_id", name="uq_worker_profiles_user_id"),
        CheckConstraint(
            "travel_radius_km >= 0 AND travel_radius_km <= 200",
            name="valid_travel_radius_km",
        ),
        CheckConstraint(
            "expected_daily_wage IS NULL OR expected_daily_wage >= 0",
            name="non_negative_expected_daily_wage",
        ),
        CheckConstraint(
            "availability IN ('daily', 'part_time', 'weekends', 'flexible', 'full_time')",
            name="valid_worker_availability",
        ),
        Index("ix_worker_profiles_pincode_availability", "pincode", "availability"),
    )

    id: Mapped[int] = mapped_column(PK_TYPE, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        PK_TYPE,
        db.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    phone_number: Mapped[str | None] = mapped_column(db.String(20), nullable=True)
    skills: Mapped[str | None] = mapped_column(db.Text, nullable=True)
    experience_summary: Mapped[str | None] = mapped_column(db.Text, nullable=True)
    preferred_categories: Mapped[str | None] = mapped_column(db.String(255), nullable=True)
    preferred_location: Mapped[str | None] = mapped_column(db.String(120), nullable=True)
    pincode: Mapped[str | None] = mapped_column(db.String(10), nullable=True, index=True)
    travel_radius_km: Mapped[int] = mapped_column(db.Integer, nullable=False, default=10)
    availability: Mapped[str] = mapped_column(
        db.String(30),
        nullable=False,
        default="flexible",
    )
    expected_daily_wage: Mapped[Decimal | None] = mapped_column(
        db.Numeric(10, 2),
        nullable=True,
    )
    show_phone_to_employers: Mapped[bool] = mapped_column(
        db.Boolean,
        nullable=False,
        default=False,
    )
    is_profile_public: Mapped[bool] = mapped_column(
        db.Boolean,
        nullable=False,
        default=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        db.DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )
    updated_at: Mapped[datetime] = mapped_column(
        db.DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
    )

    # Relationships
    user: Mapped[User] = relationship("User", back_populates="worker_profile")
    applications: Mapped[list[JobApplication]] = relationship(
        "JobApplication",
        back_populates="worker",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    saved_jobs: Mapped[list[SavedJob]] = relationship(
        "SavedJob",
        back_populates="worker",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    @property
    def skill_list(self) -> list[str]:
        """Parse comma-separated skills into a normalized lowercase list for matching."""
        if not self.skills:
            return []
        return [item.strip().lower() for item in self.skills.split(",") if item.strip()]

    @property
    def completion_percentage(self) -> int:
        """Compute explainable profile completion score (0-100) for the Worker Dashboard."""
        fields = [
            bool(self.skills and self.skills.strip()),
            bool(self.experience_summary and self.experience_summary.strip()),
            bool(self.preferred_categories and self.preferred_categories.strip()),
            bool(self.preferred_location and self.preferred_location.strip()),
            bool(self.pincode and self.pincode.strip()),
            self.expected_daily_wage is not None,
        ]
        completed = sum(1 for item in fields if item)
        return int(round((completed / len(fields)) * 100))

    @property
    def is_eligible_for_directory(self) -> bool:
        """Return True if this worker profile meets all eligibility rules for employer discovery."""
        if self.user is None or self.user.role != "worker" or not self.user.is_active:
            return False
        if not self.is_profile_public:
            return False
        if self.availability not in VALID_WORKER_AVAILABILITY:
            return False
        has_skills = bool(self.skills and self.skills.strip())
        has_area = bool(
            (self.pincode and self.pincode.strip())
            or (self.preferred_location and self.preferred_location.strip())
        )
        return has_skills and has_area

    def __repr__(self) -> str:
        return f"<WorkerProfile id={self.id} user_id={self.user_id} pincode={self.pincode!r}>"


class EmployerProfile(db.Model):
    """Profile for local shops, restaurants, small businesses, and employers."""

    __tablename__ = "employer_profiles"
    __table_args__ = (
        UniqueConstraint("user_id", name="uq_employer_profiles_user_id"),
        CheckConstraint(
            "business_type IN "
            "('shop', 'restaurant', 'logistics', 'service', 'individual', 'other')",
            name="valid_business_type",
        ),
        CheckConstraint(
            "verification_status IN ('unverified', 'pending', 'verified')",
            name="valid_employer_verification_status",
        ),
        CheckConstraint(
            "length(trim(business_name)) >= 2",
            name="non_empty_business_name",
        ),
        Index("ix_employer_profiles_pincode_verification", "pincode", "verification_status"),
    )

    id: Mapped[int] = mapped_column(PK_TYPE, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        PK_TYPE,
        db.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    business_name: Mapped[str] = mapped_column(db.String(150), nullable=False)
    business_type: Mapped[str] = mapped_column(
        db.String(30),
        nullable=False,
        default="shop",
    )
    description: Mapped[str | None] = mapped_column(db.Text, nullable=True)
    address: Mapped[str | None] = mapped_column(db.Text, nullable=True)
    location: Mapped[str | None] = mapped_column(db.String(120), nullable=True)
    pincode: Mapped[str | None] = mapped_column(db.String(10), nullable=True, index=True)
    contact_phone: Mapped[str | None] = mapped_column(db.String(20), nullable=True)
    verification_status: Mapped[str] = mapped_column(
        db.String(20),
        nullable=False,
        default="unverified",
    )
    verification_notes: Mapped[str | None] = mapped_column(db.Text, nullable=True)
    verified_at: Mapped[datetime | None] = mapped_column(
        db.DateTime(timezone=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        db.DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )
    updated_at: Mapped[datetime] = mapped_column(
        db.DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
    )

    # Relationships
    user: Mapped[User] = relationship("User", back_populates="employer_profile")
    jobs: Mapped[list[Job]] = relationship(
        "Job",
        back_populates="employer",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    @property
    def is_genuinely_verified(self) -> bool:
        """Integrity Rule: Only verified when status=='verified' and verified_at is set."""
        return self.verification_status == "verified" and self.verified_at is not None

    def __repr__(self) -> str:
        return (
            f"<EmployerProfile id={self.id} business={self.business_name!r} "
            f"verification={self.verification_status!r}>"
        )
