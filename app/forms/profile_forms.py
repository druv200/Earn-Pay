"""Flask-WTF forms for Worker Profile, Employer Profile, and Account Settings."""

from __future__ import annotations

import re

from flask_wtf import FlaskForm
from wtforms import (
    BooleanField,
    DecimalField,
    IntegerField,
    SelectField,
    StringField,
    TextAreaField,
)
from wtforms.validators import (
    DataRequired,
    Email,
    Length,
    NumberRange,
    Optional,
    ValidationError,
)

from app.forms.auth_forms import _strip_whitespace

_PINCODE_RE = re.compile(r"^\d{6}$")
_PHONE_RE = re.compile(r"^[0-9+\-\s()]{7,20}$")


def validate_indian_pincode(_form: FlaskForm, field: StringField) -> None:
    """Validate optional or required 6-digit Indian postal pincode."""
    value = (field.data or "").strip()
    if value and not _PINCODE_RE.match(value):
        msg = "Please enter a valid 6-digit Indian pincode (e.g., 560041)."
        raise ValidationError(msg)


def validate_phone_number(_form: FlaskForm, field: StringField) -> None:
    """Validate optional phone number format."""
    value = (field.data or "").strip()
    if value and not _PHONE_RE.match(value):
        msg = "Please enter a valid phone number (7 to 20 digits)."
        raise ValidationError(msg)


class WorkerProfileForm(FlaskForm):
    """Form for workers to update their skills, availability, preferences, and privacy controls."""

    full_name = StringField(
        "Full Name",
        filters=[_strip_whitespace],
        validators=[
            DataRequired(message="Please enter your full name."),
            Length(min=2, max=120),
        ],
    )
    phone_number = StringField(
        "Contact Phone Number (Optional)",
        filters=[_strip_whitespace],
        validators=[Optional(), Length(max=20), validate_phone_number],
    )
    skills = TextAreaField(
        "Skills (Comma-separated)",
        filters=[_strip_whitespace],
        validators=[
            Optional(),
            Length(max=1000, message="Skills list must be under 1000 characters."),
        ],
    )
    experience_summary = TextAreaField(
        "Work Experience Summary",
        filters=[_strip_whitespace],
        validators=[
            Optional(),
            Length(max=2000, message="Experience summary must be under 2000 characters."),
        ],
    )
    preferred_categories = StringField(
        "Preferred Job Categories (Comma-separated)",
        filters=[_strip_whitespace],
        validators=[Optional(), Length(max=255)],
    )
    preferred_location = StringField(
        "Preferred Neighborhood / Area",
        filters=[_strip_whitespace],
        validators=[Optional(), Length(max=120)],
    )
    pincode = StringField(
        "6-Digit Pincode",
        filters=[_strip_whitespace],
        validators=[Optional(), validate_indian_pincode],
    )
    travel_radius_km = IntegerField(
        "Maximum Travel Distance (km)",
        default=10,
        validators=[
            DataRequired(message="Please specify a travel radius between 0 and 200 km."),
            NumberRange(min=0, max=200, message="Travel distance must be between 0 and 200 km."),
        ],
    )
    availability = SelectField(
        "Work Availability",
        choices=[
            ("daily", "Daily Wage / Immediate Shifts"),
            ("part_time", "Part-Time (Morning / Evening)"),
            ("weekends", "Weekends Only"),
            ("flexible", "Flexible Schedule"),
            ("full_time", "Full-Time Local Role"),
        ],
        default="flexible",
        validators=[DataRequired()],
    )
    expected_daily_wage = DecimalField(
        "Expected Daily Wage (₹ INR)",
        places=2,
        validators=[
            Optional(),
            NumberRange(min=0, max=100000, message="Expected wage cannot be negative."),
        ],
    )
    is_profile_public = BooleanField(
        "Allow verified and active employers on Earn & Pay to view my worker profile summary"
    )
    show_phone_to_employers = BooleanField(
        "Show my phone number on my profile to employers (Off by default for privacy)"
    )


class EmployerProfileForm(FlaskForm):
    """Form for local employers and shopkeepers to manage their business profile."""

    full_name = StringField(
        "Contact Person Full Name",
        filters=[_strip_whitespace],
        validators=[
            DataRequired(message="Please enter the contact person's full name."),
            Length(min=2, max=120),
        ],
    )
    business_name = StringField(
        "Shop or Business Name",
        filters=[_strip_whitespace],
        validators=[
            DataRequired(message="Please enter your business name."),
            Length(min=2, max=150),
        ],
    )
    business_type = SelectField(
        "Business Category",
        choices=[
            ("shop", "Retail Shop / Store"),
            ("restaurant", "Restaurant / Bakery / Food Counter"),
            ("logistics", "Delivery / Warehouse / Logistics"),
            ("service", "Local Workshop / Service Provider"),
            ("individual", "Individual Household / Event Host"),
            ("other", "Other Small Business"),
        ],
        default="shop",
        validators=[DataRequired()],
    )
    description = TextAreaField(
        "Business Overview",
        filters=[_strip_whitespace],
        validators=[Optional(), Length(max=2000)],
    )
    address = TextAreaField(
        "Street Address / Landmark",
        filters=[_strip_whitespace],
        validators=[Optional(), Length(max=500)],
    )
    location = StringField(
        "Locality & City",
        filters=[_strip_whitespace],
        validators=[Optional(), Length(max=120)],
    )
    pincode = StringField(
        "6-Digit Workplace Pincode",
        filters=[_strip_whitespace],
        validators=[Optional(), validate_indian_pincode],
    )
    contact_phone = StringField(
        "Business Contact Phone",
        filters=[_strip_whitespace],
        validators=[Optional(), Length(max=20), validate_phone_number],
    )
    request_verification = BooleanField(
        "Submit my business profile for administrator verification review"
    )


class AccountDeletionRequestForm(FlaskForm):
    """Documented account deletion confirmation form."""

    confirm_email = StringField(
        "Type Your Account Email Address to Confirm Deletion",
        filters=[_strip_whitespace],
        validators=[
            DataRequired(message="Please type your email address to confirm."),
            Email(message="Please enter a valid email address."),
        ],
    )
    reason = TextAreaField(
        "Reason for Leaving (Optional)",
        filters=[_strip_whitespace],
        validators=[Optional(), Length(max=500)],
    )
