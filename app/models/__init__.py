"""Database models package and connectivity verification helpers."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.extensions import db
from app.models.job import (
    ALLOWED_APPLICATION_TRANSITIONS,
    VALID_APPLICATION_STATUSES,
    VALID_JOB_STATUSES,
    VALID_JOB_TYPES,
    VALID_WAGE_FREQUENCIES,
    Job,
    JobApplication,
    SavedJob,
)
from app.models.security_and_trust import (
    VALID_MODERATION_ACTIONS,
    VALID_NOTIFICATION_TYPES,
    VALID_REPORT_REASONS,
    VALID_REPORT_STATUSES,
    VALID_REPORT_TARGETS,
    AuditEvent,
    EmailVerificationToken,
    Notification,
    PasswordResetToken,
    Report,
    hash_security_token,
)
from app.models.user import (
    VALID_ACCOUNT_STATUSES,
    VALID_BUSINESS_TYPES,
    VALID_USER_ROLES,
    VALID_VERIFICATION_STATUSES,
    VALID_WORKER_AVAILABILITY,
    EmployerProfile,
    User,
    WorkerProfile,
    normalize_user_role,
)

__all__ = [
    "ALLOWED_APPLICATION_TRANSITIONS",
    "AuditEvent",
    "EmailVerificationToken",
    "EmployerProfile",
    "Job",
    "JobApplication",
    "Notification",
    "PasswordResetToken",
    "Report",
    "SavedJob",
    "User",
    "VALID_ACCOUNT_STATUSES",
    "VALID_APPLICATION_STATUSES",
    "VALID_BUSINESS_TYPES",
    "VALID_JOB_STATUSES",
    "VALID_JOB_TYPES",
    "VALID_MODERATION_ACTIONS",
    "VALID_NOTIFICATION_TYPES",
    "VALID_REPORT_REASONS",
    "VALID_REPORT_STATUSES",
    "VALID_REPORT_TARGETS",
    "VALID_USER_ROLES",
    "VALID_VERIFICATION_STATUSES",
    "VALID_WAGE_FREQUENCIES",
    "VALID_WORKER_AVAILABILITY",
    "WorkerProfile",
    "hash_security_token",
    "normalize_user_role",
    "verify_database_connection",
]


def verify_database_connection() -> tuple[bool, str]:
    """Execute a lightweight parameterized query (`SELECT 1`) to verify DB readiness."""
    try:
        result = db.session.execute(text("SELECT 1")).scalar()
        if result == 1:
            dialect = db.engine.dialect.name
            return True, f"Connected ({dialect})"
        return False, "Unexpected database probe response"
    except SQLAlchemyError as exc:
        db.session.rollback()
        return False, f"Database connection error: {exc.__class__.__name__}"
