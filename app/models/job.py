"""Job, JobApplication, and SavedJob relational models."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, Index, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship, validates

from app.extensions import db
from app.models.user import PK_TYPE, utc_now

if TYPE_CHECKING:
    from app.models.user import EmployerProfile, User, WorkerProfile

VALID_JOB_TYPES: tuple[str, ...] = (
    "daily_wage",
    "part_time",
    "temporary",
    "full_time",
)
VALID_WAGE_FREQUENCIES: tuple[str, ...] = (
    "hourly",
    "daily",
    "weekly",
    "monthly",
    "fixed_shift",
)
VALID_JOB_STATUSES: tuple[str, ...] = (
    "draft",
    "published",
    "closed",
    "archived",
)
VALID_APPLICATION_STATUSES: tuple[str, ...] = (
    "applied",
    "under_review",
    "shortlisted",
    "interview_scheduled",
    "accepted",
    "rejected",
    "withdrawn",
)

# Controlled state machine for application status transitions
ALLOWED_APPLICATION_TRANSITIONS: dict[str, frozenset[str]] = {
    "applied": frozenset(
        {
            "under_review",
            "shortlisted",
            "interview_scheduled",
            "accepted",
            "rejected",
            "withdrawn",
        }
    ),
    "under_review": frozenset(
        {
            "shortlisted",
            "interview_scheduled",
            "accepted",
            "rejected",
            "withdrawn",
        }
    ),
    "shortlisted": frozenset(
        {
            "interview_scheduled",
            "accepted",
            "rejected",
            "withdrawn",
        }
    ),
    "interview_scheduled": frozenset(
        {
            "accepted",
            "rejected",
            "withdrawn",
        }
    ),
    "accepted": frozenset(),
    "rejected": frozenset(),
    "withdrawn": frozenset(),
}


class Job(db.Model):
    """Structured local job vacancy published by an EmployerProfile."""

    __tablename__ = "jobs"
    __table_args__ = (
        CheckConstraint(
            "job_type IN ('daily_wage', 'part_time', 'temporary', 'full_time')",
            name="valid_job_type",
        ),
        CheckConstraint(
            "wage_frequency IN ('hourly', 'daily', 'weekly', 'monthly', 'fixed_shift')",
            name="valid_wage_frequency",
        ),
        CheckConstraint(
            "status IN ('draft', 'published', 'closed', 'archived')",
            name="valid_job_status",
        ),
        CheckConstraint(
            "wage_amount > 0",
            name="positive_wage_amount",
        ),
        CheckConstraint(
            "vacancies >= 1 AND vacancies <= 500",
            name="valid_vacancy_count",
        ),
        CheckConstraint(
            "length(trim(currency)) = 3",
            name="valid_currency_code",
        ),
        CheckConstraint(
            "length(trim(title)) >= 3",
            name="non_empty_job_title",
        ),
        Index("ix_jobs_status_category_pincode", "status", "category", "pincode"),
        Index("ix_jobs_status_deadline", "status", "application_deadline"),
        Index("ix_jobs_location_status", "location", "status"),
    )

    id: Mapped[int] = mapped_column(PK_TYPE, primary_key=True, autoincrement=True)
    employer_id: Mapped[int] = mapped_column(
        PK_TYPE,
        db.ForeignKey("employer_profiles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    title: Mapped[str] = mapped_column(db.String(160), nullable=False)
    category: Mapped[str] = mapped_column(db.String(80), nullable=False, index=True)
    job_type: Mapped[str] = mapped_column(
        db.String(30),
        nullable=False,
        default="daily_wage",
    )
    description: Mapped[str] = mapped_column(db.Text, nullable=False)
    responsibilities: Mapped[str] = mapped_column(db.Text, nullable=False)
    required_skills: Mapped[str | None] = mapped_column(db.Text, nullable=True)
    experience_required: Mapped[str | None] = mapped_column(db.String(120), nullable=True)
    location: Mapped[str] = mapped_column(db.String(120), nullable=False, index=True)
    pincode: Mapped[str] = mapped_column(db.String(10), nullable=False, index=True)
    wage_amount: Mapped[Decimal] = mapped_column(db.Numeric(10, 2), nullable=False)
    currency: Mapped[str] = mapped_column(db.String(3), nullable=False, default="INR")
    wage_frequency: Mapped[str] = mapped_column(
        db.String(20),
        nullable=False,
        default="daily",
    )
    working_hours: Mapped[str] = mapped_column(db.String(120), nullable=False)
    vacancies: Mapped[int] = mapped_column(db.Integer, nullable=False, default=1)
    application_deadline: Mapped[date] = mapped_column(db.Date, nullable=False, index=True)
    status: Mapped[str] = mapped_column(
        db.String(20),
        nullable=False,
        default="draft",
        index=True,
    )
    published_at: Mapped[datetime | None] = mapped_column(
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
    employer: Mapped[EmployerProfile] = relationship("EmployerProfile", back_populates="jobs")
    applications: Mapped[list[JobApplication]] = relationship(
        "JobApplication",
        back_populates="job",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    saved_by_workers: Mapped[list[SavedJob]] = relationship(
        "SavedJob",
        back_populates="job",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    @validates("wage_amount")
    def _validate_wage_amount(self, _key: str, value: Decimal | float | int | str) -> Decimal:
        dec = Decimal(str(value))
        if dec <= 0:
            msg = "Wage amount must be greater than zero."
            raise ValueError(msg)
        return dec

    @validates("vacancies")
    def _validate_vacancies(self, _key: str, value: int) -> int:
        if int(value) < 1:
            msg = "Vacancies must be at least 1."
            raise ValueError(msg)
        return int(value)

    @validates("job_type")
    def _validate_job_type(self, _key: str, value: str) -> str:
        cleaned = value.strip().lower()
        if cleaned not in VALID_JOB_TYPES:
            msg = f"Invalid job_type '{value}'. Expected one of {VALID_JOB_TYPES}."
            raise ValueError(msg)
        return cleaned

    @validates("wage_frequency")
    def _validate_wage_frequency(self, _key: str, value: str) -> str:
        cleaned = value.strip().lower()
        if cleaned not in VALID_WAGE_FREQUENCIES:
            msg = f"Invalid wage_frequency '{value}'. Expected one of {VALID_WAGE_FREQUENCIES}."
            raise ValueError(msg)
        return cleaned

    @validates("status")
    def _validate_status(self, _key: str, value: str) -> str:
        cleaned = value.strip().lower()
        if cleaned not in VALID_JOB_STATUSES:
            msg = f"Invalid job status '{value}'. Expected one of {VALID_JOB_STATUSES}."
            raise ValueError(msg)
        return cleaned

    def is_expired(self, reference_date: date | None = None) -> bool:
        """Return True if the job's application deadline has passed."""
        today = reference_date or datetime.now(UTC).date()
        return self.application_deadline < today

    def is_accepting_applications(self, reference_date: date | None = None) -> bool:
        """Return True only when published and not past application deadline."""
        return self.status == "published" and not self.is_expired(reference_date)

    def is_owned_by_user(self, user: User | None) -> bool:
        """Verify whether the given User owns this job listing."""
        if user is None or not user.is_employer or self.employer is None:
            return False
        return self.employer.user_id == user.id

    def publish(self) -> None:
        """Transition job status to published and record UTC timestamp."""
        self.status = "published"
        if self.published_at is None:
            self.published_at = utc_now()

    def __repr__(self) -> str:
        return (
            f"<Job id={self.id} title={self.title!r} status={self.status!r} "
            f"wage={self.wage_amount}/{self.wage_frequency}>"
        )


class JobApplication(db.Model):
    """Worker application to a specific Job with status history and race-safe constraints."""

    __tablename__ = "job_applications"
    __table_args__ = (
        UniqueConstraint("job_id", "worker_id", name="uq_job_applications_job_id_worker_id"),
        CheckConstraint(
            "status IN ('applied', 'under_review', 'shortlisted', "
            "'interview_scheduled', 'accepted', 'rejected', 'withdrawn')",
            name="valid_application_status",
        ),
        Index("ix_job_applications_job_status", "job_id", "status"),
        Index("ix_job_applications_worker_status", "worker_id", "status"),
    )

    id: Mapped[int] = mapped_column(PK_TYPE, primary_key=True, autoincrement=True)
    job_id: Mapped[int] = mapped_column(
        PK_TYPE,
        db.ForeignKey("jobs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    worker_id: Mapped[int] = mapped_column(
        PK_TYPE,
        db.ForeignKey("worker_profiles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    status: Mapped[str] = mapped_column(
        db.String(30),
        nullable=False,
        default="applied",
        index=True,
    )
    cover_note: Mapped[str | None] = mapped_column(db.Text, nullable=True)
    employer_private_notes: Mapped[str | None] = mapped_column(db.Text, nullable=True)
    interview_scheduled_at: Mapped[datetime | None] = mapped_column(
        db.DateTime(timezone=True),
        nullable=True,
    )
    interview_details: Mapped[str | None] = mapped_column(db.String(255), nullable=True)
    applied_at: Mapped[datetime] = mapped_column(
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
    job: Mapped[Job] = relationship("Job", back_populates="applications")
    worker: Mapped[WorkerProfile] = relationship("WorkerProfile", back_populates="applications")

    @validates("status")
    def _validate_status(self, _key: str, value: str) -> str:
        cleaned = value.strip().lower()
        if cleaned not in VALID_APPLICATION_STATUSES:
            msg = (
                f"Invalid application status '{value}'. "
                f"Expected one of {VALID_APPLICATION_STATUSES}."
            )
            raise ValueError(msg)
        return cleaned

    def can_transition_to(self, target_status: str) -> bool:
        """Return True if transitioning from current status to target_status is valid."""
        allowed = ALLOWED_APPLICATION_TRANSITIONS.get(self.status, frozenset())
        return target_status in allowed

    def __repr__(self) -> str:
        return (
            f"<JobApplication id={self.id} job_id={self.job_id} "
            f"worker_id={self.worker_id} status={self.status!r}>"
        )


class SavedJob(db.Model):
    """Bookmarked job saved by a WorkerProfile for later review."""

    __tablename__ = "saved_jobs"
    __table_args__ = (
        UniqueConstraint("worker_id", "job_id", name="uq_saved_jobs_worker_id_job_id"),
    )

    id: Mapped[int] = mapped_column(PK_TYPE, primary_key=True, autoincrement=True)
    worker_id: Mapped[int] = mapped_column(
        PK_TYPE,
        db.ForeignKey("worker_profiles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    job_id: Mapped[int] = mapped_column(
        PK_TYPE,
        db.ForeignKey("jobs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    saved_at: Mapped[datetime] = mapped_column(
        db.DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )

    # Relationships
    worker: Mapped[WorkerProfile] = relationship("WorkerProfile", back_populates="saved_jobs")
    job: Mapped[Job] = relationship("Job", back_populates="saved_by_workers")

    def __repr__(self) -> str:
        return f"<SavedJob id={self.id} worker_id={self.worker_id} job_id={self.job_id}>"
