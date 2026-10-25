"""Transactional authentication, registration, verification, and password recovery services."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from werkzeug.security import check_password_hash, generate_password_hash

from app.extensions import db
from app.models.security_and_trust import (
    AuditEvent,
    EmailVerificationToken,
    Notification,
    PasswordResetToken,
    hash_security_token,
)
from app.models.user import EmployerProfile, User, WorkerProfile, normalize_user_role, utc_now
from app.services.job_transactions import AuthorizationError, DomainRuleError
from app.utils.security import normalize_email

# Precomputed dummy hash mitigates timing side-channels when an email is not registered
_DUMMY_PASSWORD_HASH: str = generate_password_hash("dummy-timing-defense-password-#2026")


def register_user_account(
    *,
    full_name: str,
    email: str,
    password: str,
    role: str,
    business_name: str | None = None,
    ip_address: str | None = None,
) -> tuple[User, str]:
    """Atomically create a Worker/Employer user, initial profile, verification token, and audit."""
    cleaned_role = normalize_user_role(role)
    if cleaned_role not in ("worker", "employer"):
        msg = "Self-registration is only permitted for Worker or Employer roles."
        raise AuthorizationError(msg)

    cleaned_email = normalize_email(email)
    cleaned_name = full_name.strip()

    try:
        existing_stmt = select(User.id).where(User.normalized_email == cleaned_email)
        if db.session.execute(existing_stmt).scalar_one_or_none() is not None:
            msg = (
                "Unable to complete registration with that email address. "
                "Please sign in or use password recovery."
            )
            raise DomainRuleError(msg)

        user = User(
            full_name=cleaned_name,
            normalized_email=cleaned_email,
            role=cleaned_role,
            account_status="pending_verification",
            email_verified=False,
        )
        user.set_password(password)
        db.session.add(user)
        db.session.flush()

        if cleaned_role == "worker":
            worker_profile = WorkerProfile(user_id=user.id)
            db.session.add(worker_profile)
        else:
            resolved_business = (business_name or "").strip() or f"{cleaned_name}'s Business"
            employer_profile = EmployerProfile(
                user_id=user.id,
                business_name=resolved_business,
                verification_status="unverified",
            )
            db.session.add(employer_profile)

        ver_record, raw_token = EmailVerificationToken.issue(user.id, ttl_minutes=60)
        welcome_notif = Notification(
            user_id=user.id,
            notification_type="system",
            title="Welcome to Earn & Pay",
            message="Please verify your email address and complete your profile to get started.",
            link_url="/auth/verify-email",
        )
        audit = AuditEvent.record(
            actor_id=user.id,
            action="user.register",
            resource_type="user",
            resource_id=user.id,
            metadata={"role": cleaned_role},
            ip_address=ip_address,
        )
        db.session.add_all([ver_record, welcome_notif, audit])
        db.session.commit()
        return user, raw_token

    except IntegrityError as exc:
        db.session.rollback()
        msg = (
            "Unable to complete registration with that email address. "
            "Please sign in or use password recovery."
        )
        raise DomainRuleError(msg) from exc
    except Exception:
        db.session.rollback()
        raise


def authenticate_user(
    *,
    email: str,
    password: str,
    ip_address: str | None = None,
) -> User:
    """Verify credentials in constant-ish time and enforce account status restrictions."""
    cleaned_email = normalize_email(email)
    stmt = select(User).where(User.normalized_email == cleaned_email)
    user = db.session.execute(stmt).scalar_one_or_none()

    if user is None:
        check_password_hash(_DUMMY_PASSWORD_HASH, password or "")
        msg = "Invalid email address or password."
        raise DomainRuleError(msg)

    if not user.check_password(password):
        audit = AuditEvent.record(
            actor_id=user.id,
            action="user.login_failed",
            resource_type="user",
            resource_id=user.id,
            ip_address=ip_address,
        )
        db.session.add(audit)
        db.session.commit()
        msg = "Invalid email address or password."
        raise DomainRuleError(msg)

    if not user.is_active:
        audit = AuditEvent.record(
            actor_id=user.id,
            action="user.login_blocked",
            resource_type="user",
            resource_id=user.id,
            metadata={"account_status": user.account_status},
            ip_address=ip_address,
        )
        db.session.add(audit)
        db.session.commit()
        msg = "This account has been suspended or deactivated. Please contact support."
        raise AuthorizationError(msg)

    audit = AuditEvent.record(
        actor_id=user.id,
        action="user.login_success",
        resource_type="user",
        resource_id=user.id,
        ip_address=ip_address,
    )
    db.session.add(audit)
    db.session.commit()
    return user


def verify_user_email_token(raw_token: str, *, ip_address: str | None = None) -> User:
    """Consume a single-use email verification token and activate the user's account."""
    if not raw_token or not raw_token.strip():
        msg = "Invalid verification token."
        raise DomainRuleError(msg)

    token_digest = hash_security_token(raw_token)
    try:
        stmt = (
            select(EmailVerificationToken)
            .where(EmailVerificationToken.token_hash == token_digest)
            .with_for_update()
        )
        token_record = db.session.execute(stmt).scalar_one_or_none()
        if token_record is None or not token_record.consume():
            msg = "This verification link is invalid, expired, or has already been used."
            raise DomainRuleError(msg)

        user = token_record.user
        user.email_verified = True
        if user.account_status == "pending_verification":
            user.account_status = "active"

        # Invalidate any other unused verification tokens for this user
        now = utc_now()
        other_stmt = select(EmailVerificationToken).where(
            EmailVerificationToken.user_id == user.id,
            EmailVerificationToken.used_at.is_(None),
        )
        for other in db.session.execute(other_stmt).scalars():
            other.used_at = now

        audit = AuditEvent.record(
            actor_id=user.id,
            action="user.email_verified",
            resource_type="user",
            resource_id=user.id,
            ip_address=ip_address,
        )
        db.session.add(audit)
        db.session.commit()
        return user
    except Exception:
        db.session.rollback()
        raise


def issue_new_verification_token(user: User, *, ip_address: str | None = None) -> str:
    """Invalidate previous unused verification tokens and issue a fresh single-use token."""
    if user.email_verified:
        msg = "Your email address is already verified."
        raise DomainRuleError(msg)

    try:
        now = utc_now()
        old_stmt = select(EmailVerificationToken).where(
            EmailVerificationToken.user_id == user.id,
            EmailVerificationToken.used_at.is_(None),
        )
        for old_token in db.session.execute(old_stmt).scalars():
            old_token.used_at = now

        record, raw_token = EmailVerificationToken.issue(user.id, ttl_minutes=60)
        audit = AuditEvent.record(
            actor_id=user.id,
            action="user.verification_resent",
            resource_type="user",
            resource_id=user.id,
            ip_address=ip_address,
        )
        db.session.add_all([record, audit])
        db.session.commit()
        return raw_token
    except Exception:
        db.session.rollback()
        raise


def request_password_reset(email: str, *, ip_address: str | None = None) -> str | None:
    """Issue a single-use password reset token if the email belongs to an active user.

    Returns None when the email does not exist so callers can return an identical
    enumeration-safe response to the client.
    """
    cleaned_email = normalize_email(email)
    stmt = select(User).where(User.normalized_email == cleaned_email)
    user = db.session.execute(stmt).scalar_one_or_none()

    if user is None or not user.is_active:
        return None

    try:
        now = utc_now()
        old_stmt = select(PasswordResetToken).where(
            PasswordResetToken.user_id == user.id,
            PasswordResetToken.used_at.is_(None),
        )
        for old_token in db.session.execute(old_stmt).scalars():
            old_token.used_at = now

        reset_record, raw_token = PasswordResetToken.issue(user.id, ttl_minutes=30)
        audit = AuditEvent.record(
            actor_id=user.id,
            action="user.password_reset_requested",
            resource_type="user",
            resource_id=user.id,
            ip_address=ip_address,
        )
        db.session.add_all([reset_record, audit])
        db.session.commit()
        return raw_token
    except Exception:
        db.session.rollback()
        raise


def validate_password_reset_token(raw_token: str) -> PasswordResetToken | None:
    """Return PasswordResetToken if it exists, is unexpired/unused, and belongs to active user."""
    if not raw_token or not raw_token.strip():
        return None
    token_digest = hash_security_token(raw_token)
    stmt = select(PasswordResetToken).where(PasswordResetToken.token_hash == token_digest)
    record = db.session.execute(stmt).scalar_one_or_none()
    if record is None or not record.is_valid() or not record.user.is_active:
        return None
    return record


def reset_password_with_token(
    *,
    raw_token: str,
    new_password: str,
    ip_address: str | None = None,
) -> User:
    """Atomically consume a password reset token, update the user's password hash, and log audit."""
    if not raw_token or not raw_token.strip():
        msg = "Invalid password reset link."
        raise DomainRuleError(msg)

    token_digest = hash_security_token(raw_token)
    try:
        stmt = (
            select(PasswordResetToken)
            .where(PasswordResetToken.token_hash == token_digest)
            .with_for_update()
        )
        token_record = db.session.execute(stmt).scalar_one_or_none()
        if (
            token_record is None
            or not token_record.user.is_active
            or not token_record.consume()
        ):
            msg = "This password reset link is invalid, expired, or has already been used."
            raise DomainRuleError(msg)

        user = token_record.user
        user.set_password(new_password)

        # Invalidate any other unused reset tokens for this user
        now = utc_now()
        other_stmt = select(PasswordResetToken).where(
            PasswordResetToken.user_id == user.id,
            PasswordResetToken.used_at.is_(None),
        )
        for other in db.session.execute(other_stmt).scalars():
            other.used_at = now

        notif = Notification(
            user_id=user.id,
            notification_type="system",
            title="Your password was updated",
            message="Your Earn & Pay account password was recently reset.",
            link_url="/auth/login",
        )
        audit = AuditEvent.record(
            actor_id=user.id,
            action="user.password_reset_completed",
            resource_type="user",
            resource_id=user.id,
            ip_address=ip_address,
        )
        db.session.add_all([notif, audit])
        db.session.commit()
        return user
    except Exception:
        db.session.rollback()
        raise
