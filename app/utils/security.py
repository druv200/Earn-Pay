"""Security headers, RBAC decorators, email normalization, and safe redirect helpers."""

from __future__ import annotations

from collections.abc import Callable
from functools import wraps
from typing import Any
from urllib.parse import urljoin, urlparse

from flask import Response, abort, redirect, request, url_for
from flask_login import current_user


def normalize_email(email: str) -> str:
    """Normalize an email address to lowercase and strip surrounding whitespace."""
    return email.strip().lower()


def is_safe_redirect_url(target: str | None) -> bool:
    """Verify that a redirect target points to the same host and uses HTTP/HTTPS."""
    if not target:
        return False
    ref_url = urlparse(request.host_url)
    test_url = urlparse(urljoin(request.host_url, target))
    return test_url.scheme in ("http", "https") and ref_url.netloc == test_url.netloc


def role_required(*allowed_roles: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Enforce server-side authentication and role-based access control on a route."""
    normalized_allowed = frozenset(role.strip().lower() for role in allowed_roles)

    def decorator(view_func: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(view_func)
        def wrapped(*args: Any, **kwargs: Any) -> Any:
            if not current_user.is_authenticated:
                return redirect(url_for("auth.login", next=request.full_path.rstrip("?")))
            if not current_user.is_active:
                abort(403)
            if current_user.role not in normalized_allowed:
                abort(403)
            return view_func(*args, **kwargs)

        return wrapped

    return decorator


def apply_security_headers(response: Response, *, is_production: bool = False) -> Response:
    """Attach defense-in-depth HTTP security headers to every outgoing response."""
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault(
        "Permissions-Policy",
        "geolocation=(), camera=(), microphone=(), payment=()",
    )
    response.headers.setdefault(
        "Content-Security-Policy",
        (
            "default-src 'self'; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "font-src 'self' https://fonts.gstatic.com; "
            "img-src 'self' data:; "
            "script-src 'self'; "
            "frame-ancestors 'none'; "
            "base-uri 'self'; "
            "form-action 'self'"
        ),
    )
    if is_production:
        response.headers.setdefault(
            "Strict-Transport-Security",
            "max-age=31536000; includeSubDomains",
        )
    return response
