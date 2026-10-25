"""Form validation package for Earn & Pay."""

from app.forms.auth_forms import (
    ForgotPasswordForm,
    LoginForm,
    LogoutForm,
    RegistrationForm,
    ResendVerificationForm,
    ResetPasswordForm,
)
from app.forms.job_forms import (
    DEFAULT_JOB_CATEGORIES,
    ApplicationWithdrawalForm,
    EmployerApplicantUpdateForm,
    JobApplicationForm,
    JobPostForm,
    JobStatusActionForm,
    NotificationReadForm,
    SavedJobToggleForm,
)
from app.forms.moderation_forms import (
    AdminEmployerVerificationForm,
    AdminJobModerationForm,
    AdminReportResolutionForm,
    AdminUserStatusForm,
    ReportSubmissionForm,
)
from app.forms.profile_forms import (
    AccountDeletionRequestForm,
    EmployerProfileForm,
    WorkerProfileForm,
)

__all__ = [
    "DEFAULT_JOB_CATEGORIES",
    "AccountDeletionRequestForm",
    "AdminEmployerVerificationForm",
    "AdminJobModerationForm",
    "AdminReportResolutionForm",
    "AdminUserStatusForm",
    "ApplicationWithdrawalForm",
    "EmployerApplicantUpdateForm",
    "EmployerProfileForm",
    "ForgotPasswordForm",
    "JobApplicationForm",
    "JobPostForm",
    "JobStatusActionForm",
    "LoginForm",
    "LogoutForm",
    "NotificationReadForm",
    "RegistrationForm",
    "ReportSubmissionForm",
    "ResendVerificationForm",
    "ResetPasswordForm",
    "SavedJobToggleForm",
    "WorkerProfileForm",
]
