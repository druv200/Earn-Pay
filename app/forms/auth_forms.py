"""Flask-WTF authentication, registration, verification, and password recovery forms."""

from __future__ import annotations

from flask_wtf import FlaskForm
from wtforms import BooleanField, PasswordField, RadioField, StringField
from wtforms.validators import DataRequired, Email, EqualTo, Length, ValidationError


def _strip_whitespace(value: str | None) -> str:
    """Strip leading and trailing whitespace from text inputs."""
    return value.strip() if isinstance(value, str) else ""


def validate_password_strength(_form: FlaskForm, field: PasswordField) -> None:
    """Ensure passwords contain at least 8 characters with letters and digits/symbols."""
    value = field.data or ""
    if len(value) < 8:
        msg = "Password must be at least 8 characters long."
        raise ValidationError(msg)
    has_alpha = any(ch.isalpha() for ch in value)
    has_digit_or_symbol = any(not ch.isalpha() for ch in value)
    if not (has_alpha and has_digit_or_symbol):
        msg = "Password must include both letters and at least one number or symbol."
        raise ValidationError(msg)


class RegistrationForm(FlaskForm):
    """Role-selection registration form for Workers and Employers."""

    role = RadioField(
        "Account Type",
        choices=[
            ("worker", "Worker — For people looking for work."),
            ("employer", "Employer — For people or businesses looking to hire workers."),
        ],
        default="worker",
        validators=[DataRequired(message="Please choose whether you are a Worker or Employer.")],
    )
    full_name = StringField(
        "Full Name",
        filters=[_strip_whitespace],
        validators=[
            DataRequired(message="Please enter your full name."),
            Length(min=2, max=120, message="Name must be between 2 and 120 characters."),
        ],
    )
    business_name = StringField(
        "Shop or Business Name (Required for Employers)",
        filters=[_strip_whitespace],
        validators=[
            Length(max=150, message="Business name must be under 150 characters."),
        ],
    )
    email = StringField(
        "Email Address",
        filters=[_strip_whitespace],
        validators=[
            DataRequired(message="Please enter your email address."),
            Email(message="Please enter a valid email address."),
            Length(max=255),
        ],
    )
    password = PasswordField(
        "Password",
        validators=[
            DataRequired(message="Please create a password."),
            Length(min=8, max=128),
            validate_password_strength,
        ],
    )
    confirm_password = PasswordField(
        "Confirm Password",
        validators=[
            DataRequired(message="Please confirm your password."),
            EqualTo("password", message="Passwords do not match."),
        ],
    )
    accept_terms = BooleanField(
        "I agree to the Terms of Service, Privacy Policy, and Safety Guidelines",
        validators=[
            DataRequired(
                message="You must accept the Terms of Service and Privacy Policy to register."
            )
        ],
    )

    def validate_business_name(self, field: StringField) -> None:
        """Require business_name when registering as an employer."""
        if self.role.data == "employer":
            cleaned = (field.data or "").strip()
            if len(cleaned) < 2:
                msg = "Please enter your shop or business name (at least 2 characters)."
                raise ValidationError(msg)


class LoginForm(FlaskForm):
    """Session login form."""

    email = StringField(
        "Email Address",
        filters=[_strip_whitespace],
        validators=[
            DataRequired(message="Please enter your email address."),
            Email(message="Please enter a valid email address."),
            Length(max=255),
        ],
    )
    password = PasswordField(
        "Password",
        validators=[DataRequired(message="Please enter your password.")],
    )
    remember_me = BooleanField("Keep me signed in on this device")


class ForgotPasswordForm(FlaskForm):
    """Enumeration-safe password reset request form."""

    email = StringField(
        "Registered Email Address",
        filters=[_strip_whitespace],
        validators=[
            DataRequired(message="Please enter your email address."),
            Email(message="Please enter a valid email address."),
            Length(max=255),
        ],
    )


class ResetPasswordForm(FlaskForm):
    """New password submission form using a single-use reset token."""

    password = PasswordField(
        "New Password",
        validators=[
            DataRequired(message="Please enter a new password."),
            Length(min=8, max=128),
            validate_password_strength,
        ],
    )
    confirm_password = PasswordField(
        "Confirm New Password",
        validators=[
            DataRequired(message="Please confirm your new password."),
            EqualTo("password", message="Passwords do not match."),
        ],
    )


class ResendVerificationForm(FlaskForm):
    """CSRF-protected form to request a fresh email verification token."""


class LogoutForm(FlaskForm):
    """CSRF-protected POST form for logging out safely."""
