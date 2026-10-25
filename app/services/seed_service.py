"""Administrative Account Provisioning Service for Earn & Pay."""

from __future__ import annotations

from sqlalchemy import select

from app.extensions import db
from app.models.security_and_trust import AuditEvent
from app.models.user import User
from app.utils.security import normalize_email


def create_or_promote_admin_user(
    *,
    email: str,
    full_name: str,
    password: str,
) -> User:
    """Create or promote a user account to the `admin` role with verified email."""
    normalized = normalize_email(email)
    user = db.session.execute(
        select(User).where(User.normalized_email == normalized)
    ).scalar_one_or_none()
    if user is None:
        user = User(
            full_name=full_name.strip(),
            normalized_email=normalized,
            role="admin",
            account_status="active",
            email_verified=True,
        )
        user.set_password(password)
        db.session.add(user)
        db.session.flush()
    else:
        user.full_name = full_name.strip()
        user.role = "admin"
        user.account_status = "active"
        user.email_verified = True
        user.set_password(password)

    db.session.add(
        AuditEvent.record(
            actor_id=user.id,
            action="admin.account_provisioned",
            resource_type="user",
            resource_id=user.id,
            metadata={"email": normalized, "role": "admin"},
        )
    )
    db.session.commit()
    return user


def seed_demo_marketplace() -> dict[str, int]:
    """No-op stub: dummy marketplace listings are disabled in development and production."""
    return {
        "admin_id": 0,
        "employers": 0,
        "workers": 0,
        "jobs": 0,
    }
