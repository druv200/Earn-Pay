"""Flask-WTF forms for Suspicious Job/User Reporting and Admin Moderation Workflows."""

from __future__ import annotations

from flask_wtf import FlaskForm
from wtforms import IntegerField, SelectField, StringField, TextAreaField
from wtforms.validators import DataRequired, Length, NumberRange, Optional

from app.forms.auth_forms import _strip_whitespace


class ReportSubmissionForm(FlaskForm):
    """Form for workers and employers to flag suspicious jobs, fee demands, or abuse."""

    target_type = SelectField(
        "What are you reporting?",
        choices=[
            ("job", "Job Vacancy Listing"),
            ("employer", "Employer / Business Profile"),
            ("worker", "Worker / Applicant Profile"),
        ],
        default="job",
        validators=[DataRequired()],
    )
    target_id = IntegerField(
        "Target Reference ID",
        validators=[
            DataRequired(message="Please specify the ID of the listing or profile."),
            NumberRange(min=1, message="Reference ID must be a positive number."),
        ],
    )
    reason = SelectField(
        "Reason for Report",
        choices=[
            ("fee_demand", "Illegal Fee / Deposit Demand (Asking for money to apply or join)"),
            ("misleading_wage", "Misleading Wage or Working Hours"),
            ("fake_job", "Fake or Non-Existent Vacancy / Scam"),
            ("harassment", "Harassment, Abuse, or Discriminatory Conduct"),
            ("unsafe_workplace", "Unsafe Workplace Conditions"),
            ("other", "Other Policy Violation"),
        ],
        default="fee_demand",
        validators=[DataRequired()],
    )
    details = TextAreaField(
        "Incident Details",
        filters=[_strip_whitespace],
        validators=[
            DataRequired(message="Please describe what happened so our team can investigate."),
            Length(
                min=10,
                max=2000,
                message="Please provide between 10 and 2,000 characters of detail.",
            ),
        ],
    )


class AdminReportResolutionForm(FlaskForm):
    """Form for administrators to investigate, resolve, or dismiss moderation reports."""

    status = SelectField(
        "Report Status",
        choices=[
            ("investigating", "Mark as Investigating"),
            ("resolved", "Resolve Report"),
            ("dismissed", "Dismiss Report (No Violation Found)"),
        ],
        default="resolved",
        validators=[DataRequired()],
    )
    moderation_action = SelectField(
        "Enforcement Action",
        choices=[
            ("none", "No Enforcement Action"),
            ("listing_hidden", "Archive / Hide Reported Job Listing"),
            ("account_suspended", "Suspend Target Account"),
            ("warning_issued", "Issue Formal Safety Warning to Target"),
        ],
        default="none",
        validators=[DataRequired()],
    )
    resolution_notes = TextAreaField(
        "Moderator Resolution Notes",
        filters=[_strip_whitespace],
        validators=[Optional(), Length(max=2000)],
    )


class AdminEmployerVerificationForm(FlaskForm):
    """Form for administrators to verify or revoke an employer's business badge."""

    decision = SelectField(
        "Verification Decision",
        choices=[
            ("verified", "Approve & Grant Verified Employer Badge"),
            ("pending", "Keep in Pending Review"),
            ("unverified", "Revoke / Mark Unverified"),
        ],
        validators=[DataRequired()],
    )
    verification_notes = TextAreaField(
        "Verification Audit Notes",
        filters=[_strip_whitespace],
        validators=[Optional(), Length(max=1000)],
    )


class AdminJobModerationForm(FlaskForm):
    """Form for administrators to hide, close, or restore a job listing."""

    target_status = SelectField(
        "Listing Status",
        choices=[
            ("archived", "Archive / Hide Listing"),
            ("closed", "Close Listing"),
            ("published", "Restore to Published"),
        ],
        validators=[DataRequired()],
    )
    reason = StringField(
        "Moderation Reason",
        filters=[_strip_whitespace],
        validators=[Optional(), Length(max=500)],
    )


class AdminUserStatusForm(FlaskForm):
    """Form for administrators to suspend or reactivate a user account."""

    target_status = SelectField(
        "Account Status",
        choices=[
            ("suspended", "Suspend Account"),
            ("active", "Reactivate Account"),
        ],
        validators=[DataRequired()],
    )
    reason = StringField(
        "Audit Reason",
        filters=[_strip_whitespace],
        validators=[Optional(), Length(max=500)],
    )
