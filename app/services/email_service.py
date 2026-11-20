"""Transactional email delivery through Resend's HTTPS API."""

from __future__ import annotations

import json
from html import escape
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import Request, urlopen

from flask import current_app

from app.models.user import User


class EmailDeliveryError(RuntimeError):
    """Raised when a transactional email provider cannot accept a message."""


def _absolute_url(path: str) -> str:
    """Build a public URL from the configured canonical application URL."""
    base_url = str(current_app.config["PUBLIC_BASE_URL"]).rstrip("/") + "/"
    return urljoin(base_url, path.lstrip("/"))


def _deliver(*, recipient: str, subject: str, text: str, html: str, kind: str) -> None:
    """Deliver a message without logging its single-use token or URL."""
    backend = str(current_app.config.get("EMAIL_BACKEND", "console")).lower()
    if backend == "console":
        current_app.logger.info("Transactional email suppressed by console backend: kind=%s", kind)
        return
    if backend != "resend":
        raise EmailDeliveryError("Email delivery is not configured.")

    payload = json.dumps(
        {
            "from": current_app.config["EMAIL_FROM"],
            "to": [recipient],
            "subject": subject,
            "text": text,
            "html": html,
        }
    ).encode("utf-8")
    request = Request(
        "https://api.resend.com/emails",
        data=payload,
        headers={
            "Authorization": f"Bearer {current_app.config['RESEND_API_KEY']}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=10):  # noqa: S310 - fixed Resend API endpoint
            pass
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        raise EmailDeliveryError("The email provider could not accept the message.") from exc


def send_verification_email(user: User, raw_token: str) -> None:
    """Send a one-time email-address confirmation link to a newly registered user."""
    verification_url = _absolute_url(f"/auth/verify-email/{raw_token}")
    subject = "Verify your Earn & Pay email address"
    text = (
        f"Hello {user.full_name},\n\n"
        "Confirm your email address to activate your Earn & Pay account:\n"
        f"{verification_url}\n\n"
        "This link expires in 60 minutes. If you did not create this account, ignore this email."
    )
    escaped_name = escape(user.full_name)
    html = (
        f"<p>Hello {escaped_name},</p>"
        "<p>Confirm your email address to activate your Earn &amp; Pay account.</p>"
        f'<p><a href="{verification_url}">Verify my email address</a></p>'
        "<p>This link expires in 60 minutes. If you did not create this account, "
        "ignore this email.</p>"
    )
    _deliver(
        recipient=user.normalized_email,
        subject=subject,
        text=text,
        html=html,
        kind="verification",
    )


def send_password_reset_email(user: User, raw_token: str) -> None:
    """Send a one-time password-reset link without exposing it in logs."""
    reset_url = _absolute_url(f"/auth/reset-password/{raw_token}")
    subject = "Reset your Earn & Pay password"
    text = (
        f"Hello {user.full_name},\n\n"
        "Use this link to choose a new Earn & Pay password:\n"
        f"{reset_url}\n\n"
        "This link expires in 30 minutes. If you did not request a reset, ignore this email."
    )
    escaped_name = escape(user.full_name)
    html = (
        f"<p>Hello {escaped_name},</p>"
        "<p>Use this link to choose a new Earn &amp; Pay password.</p>"
        f'<p><a href="{reset_url}">Reset my password</a></p>'
        "<p>This link expires in 30 minutes. If you did not request a reset, ignore this email.</p>"
    )
    _deliver(
        recipient=user.normalized_email,
        subject=subject,
        text=text,
        html=html,
        kind="password_reset",
    )
