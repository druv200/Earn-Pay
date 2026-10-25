"""Authentication, role registration, email verification, and password recovery routes."""

from __future__ import annotations

from flask import Blueprint, flash, g, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required, login_user, logout_user

from app.extensions import db, limiter
from app.forms.auth_forms import (
    ForgotPasswordForm,
    LoginForm,
    LogoutForm,
    RegistrationForm,
    ResendVerificationForm,
    ResetPasswordForm,
)
from app.models.security_and_trust import AuditEvent
from app.models.user import normalize_user_role
from app.services.auth_service import (
    authenticate_user,
    issue_new_verification_token,
    register_user_account,
    request_password_reset,
    reset_password_with_token,
    validate_password_reset_token,
    verify_user_email_token,
)
from app.services.job_transactions import AuthorizationError, DomainRuleError
from app.utils.security import is_safe_redirect_url

auth_bp = Blueprint("auth", __name__, url_prefix="/auth")


@auth_bp.route("/register", methods=["GET", "POST"])
@limiter.limit("10 per minute")
def register():
    """Render role-selection registration page and provision Worker or Employer account."""
    if current_user.is_authenticated:
        return redirect(url_for("public.index"))

    form = RegistrationForm()
    if request.method == "GET":
        requested_role = normalize_user_role(request.args.get("role", ""))
        if requested_role in ("worker", "employer"):
            form.role.data = requested_role

    if form.validate_on_submit():
        try:
            user, _raw_token = register_user_account(
                full_name=form.full_name.data or "",
                email=form.email.data or "",
                password=form.password.data or "",
                role=form.role.data or "worker",
                business_name=form.business_name.data,
                ip_address=request.remote_addr,
            )
            session.permanent = True
            login_user(user)
            flash(
                "Account created! Please verify your email address to complete activation.",
                "success",
            )
            return redirect(url_for("auth.verify_email_status"))
        except (DomainRuleError, AuthorizationError) as exc:
            flash(str(exc), "danger")

    return render_template("auth/register.html", form=form)


@auth_bp.route("/login", methods=["GET", "POST"])
@limiter.limit("15 per minute")
def login():
    """Authenticate an existing Worker, Employer, or Administrator."""
    if current_user.is_authenticated:
        return redirect(url_for("public.index"))

    form = LoginForm()
    if form.validate_on_submit():
        try:
            user = authenticate_user(
                email=form.email.data or "",
                password=form.password.data or "",
                ip_address=request.remote_addr,
            )
            session.permanent = True
            login_user(user, remember=bool(form.remember_me.data))
            flash(f"Welcome back, {user.full_name}.", "success")

            next_url = request.args.get("next")
            if next_url and is_safe_redirect_url(next_url):
                return redirect(next_url)
            return redirect(url_for("public.index"))
        except (DomainRuleError, AuthorizationError) as exc:
            flash(str(exc), "danger")

    return render_template("auth/login.html", form=form)


@auth_bp.post("/logout")
@login_required
def logout():
    """Terminate the active user session safely via CSRF-protected POST."""
    form = LogoutForm()
    if not form.validate_on_submit():
        flash("Unable to verify logout request. Please try again.", "warning")
        return redirect(url_for("public.index"))

    actor_id = current_user.id
    audit = AuditEvent.record(
        actor_id=actor_id,
        action="user.logout",
        resource_type="user",
        resource_id=actor_id,
        ip_address=request.remote_addr,
    )
    db.session.add(audit)
    db.session.commit()

    logout_user()
    session.clear()
    g.pop("csrf_token", None)
    flash("You have been signed out safely.", "success")
    return redirect(url_for("public.index"))


@auth_bp.get("/verify-email")
@login_required
def verify_email_status():
    """Display the current user's email verification status and resend option."""
    resend_form = ResendVerificationForm()
    return render_template("auth/verify_email_status.html", resend_form=resend_form)


@auth_bp.post("/resend-verification")
@login_required
@limiter.limit("5 per minute")
def resend_verification():
    """Issue a fresh single-use email verification token for the current user."""
    form = ResendVerificationForm()
    if form.validate_on_submit():
        try:
            issue_new_verification_token(current_user, ip_address=request.remote_addr)
            flash("A new verification link has been issued for your email address.", "success")
        except DomainRuleError as exc:
            flash(str(exc), "warning")
    return redirect(url_for("auth.verify_email_status"))


@auth_bp.get("/verify-email/<string:token>")
@limiter.limit("10 per minute")
def verify_email_token(token: str):
    """Consume an email verification token and mark the user's email as verified."""
    try:
        user = verify_user_email_token(token, ip_address=request.remote_addr)
        flash(
            f"Thank you, {user.full_name}. Your email address is now verified!",
            "success",
        )
        if current_user.is_authenticated:
            return redirect(url_for("auth.verify_email_status"))
        return redirect(url_for("auth.login"))
    except DomainRuleError as exc:
        flash(str(exc), "danger")
        if current_user.is_authenticated:
            return redirect(url_for("auth.verify_email_status"))
        return redirect(url_for("auth.login"))


@auth_bp.route("/forgot-password", methods=["GET", "POST"])
@limiter.limit("5 per minute")
def forgot_password():
    """Accept password recovery requests with enumeration-safe responses."""
    if current_user.is_authenticated:
        return redirect(url_for("public.index"))

    form = ForgotPasswordForm()
    if form.validate_on_submit():
        request_password_reset(
            form.email.data or "",
            ip_address=request.remote_addr,
        )
        # Always display the exact same message regardless of whether the email exists
        flash(
            "If an active account exists for that email address, "
            "password reset instructions have been issued.",
            "success",
        )
        return redirect(url_for("auth.login"))

    return render_template("auth/forgot_password.html", form=form)


@auth_bp.route("/reset-password/<string:token>", methods=["GET", "POST"])
@limiter.limit("10 per minute")
def reset_password(token: str):
    """Verify a single-use reset token and allow the user to set a new password."""
    if current_user.is_authenticated:
        return redirect(url_for("public.index"))

    token_record = validate_password_reset_token(token)
    if token_record is None:
        flash(
            "This password reset link is invalid, expired, or has already been used.",
            "danger",
        )
        return redirect(url_for("auth.forgot_password"))

    form = ResetPasswordForm()
    if form.validate_on_submit():
        try:
            reset_password_with_token(
                raw_token=token,
                new_password=form.password.data or "",
                ip_address=request.remote_addr,
            )
            flash(
                "Your password has been updated. Please sign in with your new password.",
                "success",
            )
            return redirect(url_for("auth.login"))
        except DomainRuleError as exc:
            flash(str(exc), "danger")
            return redirect(url_for("auth.forgot_password"))

    return render_template("auth/reset_password.html", form=form, token=token)
