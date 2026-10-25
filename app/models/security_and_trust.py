"""Notification, Verification/Reset Tokens, Report, and AuditEvent relational models."""

from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from sqlalchemy import CheckConstraint, Index, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship, validates

from app.extensions import db
from app.models.user import PK_TYPE, utc_now

if TYPE_CHECKING:
    from app.models.user import User

VALID_NOTIFICATION_TYPES: tuple[str, ...] = (
    "application_status",
    "job_alert",
    "moderation",
    "system",
)
VALID_REPORT_TARGETS: tuple[str, ...] = ("job", "employer", "worker")
VALID_REPORT_REASONS: tuple[str, ...] = (
    "fee_demand",
    "misleading_wage",
    "fake_job",
    "harassment",
    "unsafe_workplace",
    "other",
)
VALID_REPORT_STATUSES: tuple[str, ...] = (
    "open",
    "investigating",
    "resolved",
    "dismissed",
)
VALID_MODERATION_ACTIONS: tuple[str, ...] = (
    "none",
    "listing_hidden",
    "account_suspended",
    "warning_issued",
)

FORBIDDEN_METADATA_KEYS: frozenset[str] = frozenset(
    {
        "password",
        "password_hash",
        "raw_password",
        "token",
        "raw_token",
        "token_hash",
        "secret",
        "secret_key",
        "cookie",
        "session",
        "csrf_token",
        "authorization",
    }
)


def hash_security_token(raw_token: str) -> str:
    """Compute a deterministic SHA-256 hex digest of a raw single-use token."""
    return hashlib.sha256(raw_token.strip().encode("utf-8")).hexdigest()


def ensure_utc(dt: datetime) -> datetime:
    """Ensure a datetime instance is timezone-aware UTC (normalizes SQLite naive reads)."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


class Notification(db.Model):
    """In-app notification delivered to a User without exposing sensitive PII."""

    __tablename__ = "notifications"
    __table_args__ = (
        CheckConstraint(
            "notification_type IN ('application_status', 'job_alert', 'moderation', 'system')",
            name="valid_notification_type",
        ),
        CheckConstraint(
            "length(trim(title)) >= 2",
            name="non_empty_notification_title",
        ),
        Index("ix_notifications_user_unread", "user_id", "read_at", "created_at"),
    )

    id: Mapped[int] = mapped_column(PK_TYPE, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        PK_TYPE,
        db.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    notification_type: Mapped[str] = mapped_column(
        db.String(30),
        nullable=False,
        default="system",
    )
    title: Mapped[str] = mapped_column(db.String(160), nullable=False)
    message: Mapped[str] = mapped_column(db.Text, nullable=False)
    link_url: Mapped[str | None] = mapped_column(db.String(255), nullable=True)
    read_at: Mapped[datetime | None] = mapped_column(
        db.DateTime(timezone=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        db.DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )

    user: Mapped[User] = relationship("User", back_populates="notifications")

    @property
    def is_read(self) -> bool:
        return self.read_at is not None

    def mark_read(self) -> None:
        if self.read_at is None:
            self.read_at = utc_now()

    def __repr__(self) -> str:
        return (
            f"<Notification id={self.id} user_id={self.user_id} "
            f"type={self.notification_type!r} read={self.is_read}>"
        )


class EmailVerificationToken(db.Model):
    """Expiring, single-use SHA-256 hashed token for verifying a user's email address."""

    __tablename__ = "email_verification_tokens"
    __table_args__ = (
        UniqueConstraint("token_hash", name="uq_email_verification_tokens_token_hash"),
        Index("ix_email_verification_tokens_user_expiry", "user_id", "expires_at"),
    )

    id: Mapped[int] = mapped_column(PK_TYPE, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        PK_TYPE,
        db.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    token_hash: Mapped[str] = mapped_column(db.String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(
        db.DateTime(timezone=True),
        nullable=False,
    )
    used_at: Mapped[datetime | None] = mapped_column(
        db.DateTime(timezone=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        db.DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )

    user: Mapped[User] = relationship("User", back_populates="verification_tokens")

    @classmethod
    def issue(cls, user_id: int, ttl_minutes: int = 60) -> tuple[EmailVerificationToken, str]:
        """Create a new hashed verification token record and return `(instance, raw_token)`."""
        raw_token = secrets.token_urlsafe(32)
        now = utc_now()
        record = cls(
            user_id=user_id,
            token_hash=hash_security_token(raw_token),
            expires_at=now + timedelta(minutes=ttl_minutes),
            created_at=now,
        )
        return record, raw_token

    def is_valid(self, reference_time: datetime | None = None) -> bool:
        """Return True if token has not been used and has not expired."""
        now = ensure_utc(reference_time or utc_now())
        return self.used_at is None and ensure_utc(self.expires_at) > now

    def consume(self, reference_time: datetime | None = None) -> bool:
        """Mark token as used if valid; return False if already used or expired."""
        if not self.is_valid(reference_time):
            return False
        self.used_at = ensure_utc(reference_time or utc_now())
        return True


class PasswordResetToken(db.Model):
    """Expiring, single-use SHA-256 hashed token for account password recovery."""

    __tablename__ = "password_reset_tokens"
    __table_args__ = (
        UniqueConstraint("token_hash", name="uq_password_reset_tokens_token_hash"),
        Index("ix_password_reset_tokens_user_expiry", "user_id", "expires_at"),
    )

    id: Mapped[int] = mapped_column(PK_TYPE, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        PK_TYPE,
        db.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    token_hash: Mapped[str] = mapped_column(db.String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(
        db.DateTime(timezone=True),
        nullable=False,
    )
    used_at: Mapped[datetime | None] = mapped_column(
        db.DateTime(timezone=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        db.DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )

    user: Mapped[User] = relationship("User", back_populates="password_reset_tokens")

    @classmethod
    def issue(cls, user_id: int, ttl_minutes: int = 30) -> tuple[PasswordResetToken, str]:
        """Create a new hashed password reset token record and return `(instance, raw_token)`."""
        raw_token = secrets.token_urlsafe(32)
        now = utc_now()
        record = cls(
            user_id=user_id,
            token_hash=hash_security_token(raw_token),
            expires_at=now + timedelta(minutes=ttl_minutes),
            created_at=now,
        )
        return record, raw_token

    def is_valid(self, reference_time: datetime | None = None) -> bool:
        """Return True if token has not been used and has not expired."""
        now = ensure_utc(reference_time or utc_now())
        return self.used_at is None and ensure_utc(self.expires_at) > now

    def consume(self, reference_time: datetime | None = None) -> bool:
        """Mark token as used if valid; return False if already used or expired."""
        if not self.is_valid(reference_time):
            return False
        self.used_at = ensure_utc(reference_time or utc_now())
        return True


class Report(db.Model):
    """User report flagging a suspicious job, employer, or worker for admin moderation."""

    __tablename__ = "reports"
    __table_args__ = (
        CheckConstraint(
            "target_type IN ('job', 'employer', 'worker')",
            name="valid_report_target_type",
        ),
        CheckConstraint(
            "reason IN ('fee_demand', 'misleading_wage', 'fake_job', "
            "'harassment', 'unsafe_workplace', 'other')",
            name="valid_report_reason",
        ),
        CheckConstraint(
            "status IN ('open', 'investigating', 'resolved', 'dismissed')",
            name="valid_report_status",
        ),
        CheckConstraint(
            "moderation_action IN ('none', 'listing_hidden', "
            "'account_suspended', 'warning_issued')",
            name="valid_moderation_action",
        ),
        CheckConstraint(
            "target_id > 0",
            name="positive_report_target_id",
        ),
        Index("ix_reports_status_created", "status", "created_at"),
        Index("ix_reports_target", "target_type", "target_id"),
    )

    id: Mapped[int] = mapped_column(PK_TYPE, primary_key=True, autoincrement=True)
    reporter_id: Mapped[int | None] = mapped_column(
        PK_TYPE,
        db.ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    target_type: Mapped[str] = mapped_column(db.String(20), nullable=False)
    target_id: Mapped[int] = mapped_column(PK_TYPE, nullable=False)
    reason: Mapped[str] = mapped_column(db.String(40), nullable=False)
    details: Mapped[str | None] = mapped_column(db.Text, nullable=True)
    status: Mapped[str] = mapped_column(
        db.String(20),
        nullable=False,
        default="open",
        index=True,
    )
    reviewer_id: Mapped[int | None] = mapped_column(
        PK_TYPE,
        db.ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    moderation_action: Mapped[str] = mapped_column(
        db.String(30),
        nullable=False,
        default="none",
    )
    resolution_notes: Mapped[str | None] = mapped_column(db.Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        db.DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        db.DateTime(timezone=True),
        nullable=True,
    )

    reporter: Mapped[User | None] = relationship(
        "User",
        foreign_keys=[reporter_id],
        back_populates="reports_submitted",
    )
    reviewer: Mapped[User | None] = relationship(
        "User",
        foreign_keys=[reviewer_id],
        back_populates="reports_reviewed",
    )

    @validates("target_type")
    def _validate_target_type(self, _key: str, value: str) -> str:
        cleaned = value.strip().lower()
        if cleaned not in VALID_REPORT_TARGETS:
            msg = f"Invalid report target_type '{value}'. Expected {VALID_REPORT_TARGETS}."
            raise ValueError(msg)
        return cleaned

    @validates("reason")
    def _validate_reason(self, _key: str, value: str) -> str:
        cleaned = value.strip().lower()
        if cleaned not in VALID_REPORT_REASONS:
            msg = f"Invalid report reason '{value}'. Expected {VALID_REPORT_REASONS}."
            raise ValueError(msg)
        return cleaned

    def resolve(
        self,
        *,
        reviewer_id: int,
        action: str,
        status: str = "resolved",
        notes: str | None = None,
    ) -> None:
        """Record an authorized moderator's decision and timestamp."""
        if action not in VALID_MODERATION_ACTIONS:
            msg = f"Invalid moderation action '{action}'."
            raise ValueError(msg)
        if status not in ("resolved", "dismissed"):
            msg = "Resolution status must be 'resolved' or 'dismissed'."
            raise ValueError(msg)
        self.reviewer_id = reviewer_id
        self.moderation_action = action
        self.status = status
        self.resolution_notes = notes
        self.resolved_at = utc_now()

    def __repr__(self) -> str:
        return (
            f"<Report id={self.id} target={self.target_type}:{self.target_id} "
            f"status={self.status!r}>"
        )


class AuditEvent(db.Model):
    """Immutable security and moderation audit log entry with automatic secret scrubbing."""

    __tablename__ = "audit_events"
    __table_args__ = (
        CheckConstraint(
            "length(trim(action)) >= 3",
            name="non_empty_audit_action",
        ),
        Index("ix_audit_events_action_created", "action", "created_at"),
        Index("ix_audit_events_resource", "resource_type", "resource_id"),
    )

    id: Mapped[int] = mapped_column(PK_TYPE, primary_key=True, autoincrement=True)
    actor_id: Mapped[int | None] = mapped_column(
        PK_TYPE,
        db.ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    action: Mapped[str] = mapped_column(db.String(80), nullable=False, index=True)
    resource_type: Mapped[str] = mapped_column(db.String(40), nullable=False)
    resource_id: Mapped[int | None] = mapped_column(PK_TYPE, nullable=True)
    safe_metadata: Mapped[dict[str, Any] | None] = mapped_column(db.JSON, nullable=True)
    ip_address: Mapped[str | None] = mapped_column(db.String(45), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        db.DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        index=True,
    )

    actor: Mapped[User | None] = relationship("User", back_populates="audit_events")

    @staticmethod
    def sanitize_metadata(raw_metadata: dict[str, Any] | None) -> dict[str, Any] | None:
        """Strip any sensitive keys (passwords, tokens, cookies) before persisting metadata."""
        if not raw_metadata:
            return None
        cleaned: dict[str, Any] = {}
        for key, value in raw_metadata.items():
            normalized_key = str(key).strip().lower()
            if normalized_key in FORBIDDEN_METADATA_KEYS or "password" in normalized_key:
                continue
            if "token" in normalized_key or "secret" in normalized_key:
                continue
            cleaned[str(key)] = value
        return cleaned

    @classmethod
    def record(
        cls,
        *,
        action: str,
        resource_type: str,
        actor_id: int | None = None,
        resource_id: int | None = None,
        metadata: dict[str, Any] | None = None,
        ip_address: str | None = None,
    ) -> AuditEvent:
        """Construct a sanitized AuditEvent ready to be added to the current DB session."""
        return cls(
            actor_id=actor_id,
            action=action.strip(),
            resource_type=resource_type.strip(),
            resource_id=resource_id,
            safe_metadata=cls.sanitize_metadata(metadata),
            ip_address=ip_address,
        )

    def __repr__(self) -> str:
        return (
            f"<AuditEvent id={self.id} action={self.action!r} "
            f"resource={self.resource_type}:{self.resource_id}>"
        )
