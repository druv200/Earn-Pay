"""Flask-WTF forms for Job Creation/Editing, Applications, Saved Jobs, and Applicant Management."""

from __future__ import annotations

from datetime import UTC, date, datetime

from flask_wtf import FlaskForm
from wtforms import (
    DateField,
    DecimalField,
    IntegerField,
    SelectField,
    StringField,
    TextAreaField,
)
from wtforms.validators import (
    DataRequired,
    Length,
    NumberRange,
    Optional,
    ValidationError,
)

from app.forms.auth_forms import _strip_whitespace
from app.forms.profile_forms import validate_indian_pincode

DEFAULT_JOB_CATEGORIES: tuple[str, ...] = (
    "Retail",
    "Restaurant & Food",
    "Delivery & Logistics",
    "Warehouse & Stock",
    "Cleaning & Housekeeping",
    "Event & Helper",
    "Office & Billing",
)


class JobPostForm(FlaskForm):
    """Structured form for creating and editing local job listings."""

    title = StringField(
        "Job Title",
        filters=[_strip_whitespace],
        validators=[
            DataRequired(message="Please enter a clear job title."),
            Length(min=3, max=160, message="Job title must be between 3 and 160 characters."),
        ],
    )
    category = SelectField(
        "Job Category",
        choices=[(cat, cat) for cat in DEFAULT_JOB_CATEGORIES],
        validators=[DataRequired(message="Please select a job category.")],
    )
    job_type = SelectField(
        "Job Type",
        choices=[
            ("daily_wage", "Daily Wage (Paid per day/shift)"),
            ("part_time", "Part-Time (Morning / Evening / Few hours)"),
            ("temporary", "Temporary / Short-Term (Events, peak season)"),
            ("full_time", "Full-Time Local Role"),
        ],
        default="daily_wage",
        validators=[DataRequired()],
    )
    description = TextAreaField(
        "Job Description & Overview",
        filters=[_strip_whitespace],
        validators=[
            DataRequired(message="Please describe the job role and workplace."),
            Length(min=10, max=4000),
        ],
    )
    responsibilities = TextAreaField(
        "Specific Daily Responsibilities",
        filters=[_strip_whitespace],
        validators=[
            DataRequired(message="Please list the specific duties expected of the worker."),
            Length(min=5, max=3000),
        ],
    )
    required_skills = StringField(
        "Required Skills (Comma-separated, Optional)",
        filters=[_strip_whitespace],
        validators=[Optional(), Length(max=500)],
    )
    experience_required = StringField(
        "Experience Requirements (Optional)",
        filters=[_strip_whitespace],
        validators=[Optional(), Length(max=120)],
    )
    location = StringField(
        "Workplace Neighborhood & City",
        filters=[_strip_whitespace],
        validators=[
            DataRequired(message="Please specify the neighborhood and city."),
            Length(min=2, max=120),
        ],
    )
    pincode = StringField(
        "6-Digit Workplace Pincode",
        filters=[_strip_whitespace],
        validators=[
            DataRequired(message="Please enter the 6-digit workplace pincode."),
            validate_indian_pincode,
        ],
    )
    wage_amount = DecimalField(
        "Wage Amount (₹ INR)",
        places=2,
        validators=[
            DataRequired(message="Please enter a positive numeric wage amount."),
            NumberRange(min=1, max=500000, message="Wage amount must be at least ₹1."),
        ],
    )
    wage_frequency = SelectField(
        "Payment Frequency",
        choices=[
            ("hourly", "Per Hour (Hourly)"),
            ("daily", "Per Day (Daily Wage)"),
            ("weekly", "Per Week (Weekly)"),
            ("monthly", "Per Month (Monthly Salary)"),
            ("fixed_shift", "Fixed Shift / Task Rate"),
        ],
        default="daily",
        validators=[DataRequired()],
    )
    working_hours = StringField(
        "Working Hours & Shift Schedule",
        filters=[_strip_whitespace],
        validators=[
            DataRequired(message="Please specify the working hours (e.g., 9:00 AM - 6:00 PM)."),
            Length(min=3, max=120),
        ],
    )
    vacancies = IntegerField(
        "Number of Openings (Vacancies)",
        default=1,
        validators=[
            DataRequired(message="Please enter the number of openings."),
            NumberRange(min=1, max=500, message="Vacancies must be between 1 and 500."),
        ],
    )
    application_deadline = DateField(
        "Application Deadline (YYYY-MM-DD)",
        format="%Y-%m-%d",
        validators=[DataRequired(message="Please enter an application deadline in YYYY-MM-DD.")],
    )
    submit_action = SelectField(
        "Publication Action",
        choices=[
            ("publish", "Publish Immediately to Marketplace"),
            ("preview", "Save as Draft & Preview Before Publishing"),
            ("draft", "Save as Draft"),
        ],
        default="publish",
        validators=[DataRequired()],
    )

    def validate_application_deadline(self, field: DateField) -> None:
        """Ensure application deadline is today or in the future."""
        today: date = datetime.now(UTC).date()
        if field.data and field.data < today:
            msg = "Application deadline cannot be in the past."
            raise ValidationError(msg)


class JobApplicationForm(FlaskForm):
    """Form for a Worker to submit an application to a published Job."""

    cover_note = TextAreaField(
        "Short Note to Employer (Optional)",
        filters=[_strip_whitespace],
        validators=[
            Optional(),
            Length(max=1000, message="Note must be under 1000 characters."),
        ],
    )


class ApplicationWithdrawalForm(FlaskForm):
    """CSRF-protected form for a Worker to withdraw an active application."""


class SavedJobToggleForm(FlaskForm):
    """CSRF-protected form for bookmarking or unbookmarking a Job."""


class JobStatusActionForm(FlaskForm):
    """CSRF-protected form for an Employer to publish, close, or archive a Job."""

    target_status = SelectField(
        "Job Status",
        choices=[
            ("published", "Publish Listing"),
            ("closed", "Close Applications"),
            ("archived", "Archive Listing"),
        ],
        validators=[DataRequired()],
    )


class EmployerApplicantUpdateForm(FlaskForm):
    """Form for an authorized Employer to update candidate status, interview, and private notes."""

    target_status = SelectField(
        "Update Application Status",
        choices=[
            ("under_review", "Under Review"),
            ("shortlisted", "Shortlisted"),
            ("interview_scheduled", "Interview Scheduled"),
            ("accepted", "Accepted (Hire Candidate)"),
            ("rejected", "Not Selected (Rejected)"),
        ],
        validators=[DataRequired()],
    )
    interview_date = StringField(
        "Interview Date & Time (Optional, YYYY-MM-DD HH:MM)",
        filters=[_strip_whitespace],
        validators=[Optional(), Length(max=40)],
    )
    interview_details = StringField(
        "Interview Location / Instructions (Visible to Candidate)",
        filters=[_strip_whitespace],
        validators=[Optional(), Length(max=255)],
    )
    employer_private_notes = TextAreaField(
        "Internal Hiring Notes (Private — Visible ONLY to You)",
        filters=[_strip_whitespace],
        validators=[Optional(), Length(max=2000)],
    )


class NotificationReadForm(FlaskForm):
    """CSRF-protected form to mark notifications as read."""
