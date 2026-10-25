"""Initial Earn & Pay relational schema (11 entities, constraints, and indexes).

Revision ID: 0001_initial_schema
Revises: None
Create Date: 2026-10-24 19:55:00.000000

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None

PK_TYPE = sa.BigInteger().with_variant(sa.Integer, "sqlite")


def upgrade() -> None:
    # 1. users
    op.create_table(
        "users",
        sa.Column("id", PK_TYPE, autoincrement=True, nullable=False),
        sa.Column("full_name", sa.String(length=120), nullable=False),
        sa.Column("normalized_email", sa.String(length=255), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("account_status", sa.String(length=30), nullable=False),
        sa.Column("email_verified", sa.Boolean(), nullable=False),
        sa.Column("deletion_requested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "account_status IN ('active', 'pending_verification', 'suspended', 'deleted')",
            name=op.f("ck_users_valid_account_status"),
        ),
        sa.CheckConstraint(
            "length(trim(full_name)) >= 2",
            name=op.f("ck_users_non_empty_full_name"),
        ),
        sa.CheckConstraint(
            "length(trim(normalized_email)) >= 5",
            name=op.f("ck_users_non_empty_normalized_email"),
        ),
        sa.CheckConstraint(
            "role IN ('worker', 'employer', 'admin')",
            name=op.f("ck_users_valid_user_role"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("normalized_email", name="uq_users_normalized_email"),
    )
    op.create_index(op.f("ix_users_normalized_email"), "users", ["normalized_email"], unique=False)
    op.create_index("ix_users_role_status", "users", ["role", "account_status"], unique=False)

    # 2. worker_profiles
    op.create_table(
        "worker_profiles",
        sa.Column("id", PK_TYPE, autoincrement=True, nullable=False),
        sa.Column("user_id", PK_TYPE, nullable=False),
        sa.Column("phone_number", sa.String(length=20), nullable=True),
        sa.Column("skills", sa.Text(), nullable=True),
        sa.Column("experience_summary", sa.Text(), nullable=True),
        sa.Column("preferred_categories", sa.String(length=255), nullable=True),
        sa.Column("preferred_location", sa.String(length=120), nullable=True),
        sa.Column("pincode", sa.String(length=10), nullable=True),
        sa.Column("travel_radius_km", sa.Integer(), nullable=False),
        sa.Column("availability", sa.String(length=30), nullable=False),
        sa.Column("expected_daily_wage", sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column("show_phone_to_employers", sa.Boolean(), nullable=False),
        sa.Column("is_profile_public", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "availability IN ('daily', 'part_time', 'weekends', 'flexible', 'full_time')",
            name=op.f("ck_worker_profiles_valid_worker_availability"),
        ),
        sa.CheckConstraint(
            "expected_daily_wage IS NULL OR expected_daily_wage >= 0",
            name=op.f("ck_worker_profiles_non_negative_expected_daily_wage"),
        ),
        sa.CheckConstraint(
            "travel_radius_km >= 0 AND travel_radius_km <= 200",
            name=op.f("ck_worker_profiles_valid_travel_radius_km"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_worker_profiles_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_worker_profiles")),
        sa.UniqueConstraint("user_id", name="uq_worker_profiles_user_id"),
    )
    op.create_index(
        op.f("ix_worker_profiles_pincode"),
        "worker_profiles",
        ["pincode"],
        unique=False,
    )
    op.create_index(
        "ix_worker_profiles_pincode_availability",
        "worker_profiles",
        ["pincode", "availability"],
        unique=False,
    )
    op.create_index(
        op.f("ix_worker_profiles_user_id"),
        "worker_profiles",
        ["user_id"],
        unique=False,
    )

    # 3. employer_profiles
    op.create_table(
        "employer_profiles",
        sa.Column("id", PK_TYPE, autoincrement=True, nullable=False),
        sa.Column("user_id", PK_TYPE, nullable=False),
        sa.Column("business_name", sa.String(length=150), nullable=False),
        sa.Column("business_type", sa.String(length=30), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("address", sa.Text(), nullable=True),
        sa.Column("location", sa.String(length=120), nullable=True),
        sa.Column("pincode", sa.String(length=10), nullable=True),
        sa.Column("contact_phone", sa.String(length=20), nullable=True),
        sa.Column("verification_status", sa.String(length=20), nullable=False),
        sa.Column("verification_notes", sa.Text(), nullable=True),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "business_type IN ('shop', 'restaurant', 'logistics', 'service', 'individual', 'other')",
            name=op.f("ck_employer_profiles_valid_business_type"),
        ),
        sa.CheckConstraint(
            "length(trim(business_name)) >= 2",
            name=op.f("ck_employer_profiles_non_empty_business_name"),
        ),
        sa.CheckConstraint(
            "verification_status IN ('unverified', 'pending', 'verified')",
            name=op.f("ck_employer_profiles_valid_employer_verification_status"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_employer_profiles_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_employer_profiles")),
        sa.UniqueConstraint("user_id", name="uq_employer_profiles_user_id"),
    )
    op.create_index(
        op.f("ix_employer_profiles_pincode"),
        "employer_profiles",
        ["pincode"],
        unique=False,
    )
    op.create_index(
        "ix_employer_profiles_pincode_verification",
        "employer_profiles",
        ["pincode", "verification_status"],
        unique=False,
    )
    op.create_index(
        op.f("ix_employer_profiles_user_id"),
        "employer_profiles",
        ["user_id"],
        unique=False,
    )

    # 4. jobs
    op.create_table(
        "jobs",
        sa.Column("id", PK_TYPE, autoincrement=True, nullable=False),
        sa.Column("employer_id", PK_TYPE, nullable=False),
        sa.Column("title", sa.String(length=160), nullable=False),
        sa.Column("category", sa.String(length=80), nullable=False),
        sa.Column("job_type", sa.String(length=30), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("responsibilities", sa.Text(), nullable=False),
        sa.Column("required_skills", sa.Text(), nullable=True),
        sa.Column("experience_required", sa.String(length=120), nullable=True),
        sa.Column("location", sa.String(length=120), nullable=False),
        sa.Column("pincode", sa.String(length=10), nullable=False),
        sa.Column("wage_amount", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("wage_frequency", sa.String(length=20), nullable=False),
        sa.Column("working_hours", sa.String(length=120), nullable=False),
        sa.Column("vacancies", sa.Integer(), nullable=False),
        sa.Column("application_deadline", sa.Date(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "job_type IN ('daily_wage', 'part_time', 'temporary', 'full_time')",
            name=op.f("ck_jobs_valid_job_type"),
        ),
        sa.CheckConstraint(
            "length(trim(currency)) = 3",
            name=op.f("ck_jobs_valid_currency_code"),
        ),
        sa.CheckConstraint(
            "length(trim(title)) >= 3",
            name=op.f("ck_jobs_non_empty_job_title"),
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'published', 'closed', 'archived')",
            name=op.f("ck_jobs_valid_job_status"),
        ),
        sa.CheckConstraint(
            "vacancies >= 1 AND vacancies <= 500",
            name=op.f("ck_jobs_valid_vacancy_count"),
        ),
        sa.CheckConstraint(
            "wage_amount > 0",
            name=op.f("ck_jobs_positive_wage_amount"),
        ),
        sa.CheckConstraint(
            "wage_frequency IN ('hourly', 'daily', 'weekly', 'monthly', 'fixed_shift')",
            name=op.f("ck_jobs_valid_wage_frequency"),
        ),
        sa.ForeignKeyConstraint(
            ["employer_id"],
            ["employer_profiles.id"],
            name=op.f("fk_jobs_employer_id_employer_profiles"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_jobs")),
    )
    op.create_index(op.f("ix_jobs_application_deadline"), "jobs", ["application_deadline"])
    op.create_index(op.f("ix_jobs_category"), "jobs", ["category"])
    op.create_index(op.f("ix_jobs_employer_id"), "jobs", ["employer_id"])
    op.create_index(op.f("ix_jobs_location"), "jobs", ["location"])
    op.create_index("ix_jobs_location_status", "jobs", ["location", "status"])
    op.create_index(op.f("ix_jobs_pincode"), "jobs", ["pincode"])
    op.create_index(op.f("ix_jobs_status"), "jobs", ["status"])
    op.create_index(
        "ix_jobs_status_category_pincode",
        "jobs",
        ["status", "category", "pincode"],
    )
    op.create_index("ix_jobs_status_deadline", "jobs", ["status", "application_deadline"])

    # 5. job_applications
    op.create_table(
        "job_applications",
        sa.Column("id", PK_TYPE, autoincrement=True, nullable=False),
        sa.Column("job_id", PK_TYPE, nullable=False),
        sa.Column("worker_id", PK_TYPE, nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("cover_note", sa.Text(), nullable=True),
        sa.Column("employer_private_notes", sa.Text(), nullable=True),
        sa.Column("interview_scheduled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("interview_details", sa.String(length=255), nullable=True),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('applied', 'under_review', 'shortlisted', "
            "'interview_scheduled', 'accepted', 'rejected', 'withdrawn')",
            name=op.f("ck_job_applications_valid_application_status"),
        ),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["jobs.id"],
            name=op.f("fk_job_applications_job_id_jobs"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["worker_id"],
            ["worker_profiles.id"],
            name=op.f("fk_job_applications_worker_id_worker_profiles"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_job_applications")),
        sa.UniqueConstraint("job_id", "worker_id", name="uq_job_applications_job_id_worker_id"),
    )
    op.create_index(op.f("ix_job_applications_job_id"), "job_applications", ["job_id"])
    op.create_index(
        "ix_job_applications_job_status",
        "job_applications",
        ["job_id", "status"],
    )
    op.create_index(op.f("ix_job_applications_status"), "job_applications", ["status"])
    op.create_index(op.f("ix_job_applications_worker_id"), "job_applications", ["worker_id"])
    op.create_index(
        "ix_job_applications_worker_status",
        "job_applications",
        ["worker_id", "status"],
    )

    # 6. saved_jobs
    op.create_table(
        "saved_jobs",
        sa.Column("id", PK_TYPE, autoincrement=True, nullable=False),
        sa.Column("worker_id", PK_TYPE, nullable=False),
        sa.Column("job_id", PK_TYPE, nullable=False),
        sa.Column("saved_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["jobs.id"],
            name=op.f("fk_saved_jobs_job_id_jobs"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["worker_id"],
            ["worker_profiles.id"],
            name=op.f("fk_saved_jobs_worker_id_worker_profiles"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_saved_jobs")),
        sa.UniqueConstraint("worker_id", "job_id", name="uq_saved_jobs_worker_id_job_id"),
    )
    op.create_index(op.f("ix_saved_jobs_job_id"), "saved_jobs", ["job_id"])
    op.create_index(op.f("ix_saved_jobs_worker_id"), "saved_jobs", ["worker_id"])

    # 7. notifications
    op.create_table(
        "notifications",
        sa.Column("id", PK_TYPE, autoincrement=True, nullable=False),
        sa.Column("user_id", PK_TYPE, nullable=False),
        sa.Column("notification_type", sa.String(length=30), nullable=False),
        sa.Column("title", sa.String(length=160), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("link_url", sa.String(length=255), nullable=True),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "length(trim(title)) >= 2",
            name=op.f("ck_notifications_non_empty_notification_title"),
        ),
        sa.CheckConstraint(
            "notification_type IN ('application_status', 'job_alert', 'moderation', 'system')",
            name=op.f("ck_notifications_valid_notification_type"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_notifications_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_notifications")),
    )
    op.create_index(op.f("ix_notifications_user_id"), "notifications", ["user_id"])
    op.create_index(
        "ix_notifications_user_unread",
        "notifications",
        ["user_id", "read_at", "created_at"],
    )

    # 8. email_verification_tokens
    op.create_table(
        "email_verification_tokens",
        sa.Column("id", PK_TYPE, autoincrement=True, nullable=False),
        sa.Column("user_id", PK_TYPE, nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_email_verification_tokens_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_email_verification_tokens")),
        sa.UniqueConstraint("token_hash", name="uq_email_verification_tokens_token_hash"),
    )
    op.create_index(
        op.f("ix_email_verification_tokens_user_id"),
        "email_verification_tokens",
        ["user_id"],
    )
    op.create_index(
        "ix_email_verification_tokens_user_expiry",
        "email_verification_tokens",
        ["user_id", "expires_at"],
    )

    # 9. password_reset_tokens
    op.create_table(
        "password_reset_tokens",
        sa.Column("id", PK_TYPE, autoincrement=True, nullable=False),
        sa.Column("user_id", PK_TYPE, nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_password_reset_tokens_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_password_reset_tokens")),
        sa.UniqueConstraint("token_hash", name="uq_password_reset_tokens_token_hash"),
    )
    op.create_index(
        op.f("ix_password_reset_tokens_user_id"),
        "password_reset_tokens",
        ["user_id"],
    )
    op.create_index(
        "ix_password_reset_tokens_user_expiry",
        "password_reset_tokens",
        ["user_id", "expires_at"],
    )

    # 10. reports
    op.create_table(
        "reports",
        sa.Column("id", PK_TYPE, autoincrement=True, nullable=False),
        sa.Column("reporter_id", PK_TYPE, nullable=True),
        sa.Column("target_type", sa.String(length=20), nullable=False),
        sa.Column("target_id", PK_TYPE, nullable=False),
        sa.Column("reason", sa.String(length=40), nullable=False),
        sa.Column("details", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("reviewer_id", PK_TYPE, nullable=True),
        sa.Column("moderation_action", sa.String(length=30), nullable=False),
        sa.Column("resolution_notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "moderation_action IN ('none', 'listing_hidden', "
            "'account_suspended', 'warning_issued')",
            name=op.f("ck_reports_valid_moderation_action"),
        ),
        sa.CheckConstraint(
            "reason IN ('fee_demand', 'misleading_wage', 'fake_job', "
            "'harassment', 'unsafe_workplace', 'other')",
            name=op.f("ck_reports_valid_report_reason"),
        ),
        sa.CheckConstraint(
            "status IN ('open', 'investigating', 'resolved', 'dismissed')",
            name=op.f("ck_reports_valid_report_status"),
        ),
        sa.CheckConstraint(
            "target_id > 0",
            name=op.f("ck_reports_positive_report_target_id"),
        ),
        sa.CheckConstraint(
            "target_type IN ('job', 'employer', 'worker')",
            name=op.f("ck_reports_valid_report_target_type"),
        ),
        sa.ForeignKeyConstraint(
            ["reporter_id"],
            ["users.id"],
            name=op.f("fk_reports_reporter_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["reviewer_id"],
            ["users.id"],
            name=op.f("fk_reports_reviewer_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_reports")),
    )
    op.create_index(op.f("ix_reports_reporter_id"), "reports", ["reporter_id"])
    op.create_index(op.f("ix_reports_reviewer_id"), "reports", ["reviewer_id"])
    op.create_index(op.f("ix_reports_status"), "reports", ["status"])
    op.create_index("ix_reports_status_created", "reports", ["status", "created_at"])
    op.create_index("ix_reports_target", "reports", ["target_type", "target_id"])

    # 11. audit_events
    op.create_table(
        "audit_events",
        sa.Column("id", PK_TYPE, autoincrement=True, nullable=False),
        sa.Column("actor_id", PK_TYPE, nullable=True),
        sa.Column("action", sa.String(length=80), nullable=False),
        sa.Column("resource_type", sa.String(length=40), nullable=False),
        sa.Column("resource_id", PK_TYPE, nullable=True),
        sa.Column("safe_metadata", sa.JSON(), nullable=True),
        sa.Column("ip_address", sa.String(length=45), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "length(trim(action)) >= 3",
            name=op.f("ck_audit_events_non_empty_audit_action"),
        ),
        sa.ForeignKeyConstraint(
            ["actor_id"],
            ["users.id"],
            name=op.f("fk_audit_events_actor_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_events")),
    )
    op.create_index(op.f("ix_audit_events_action"), "audit_events", ["action"])
    op.create_index("ix_audit_events_action_created", "audit_events", ["action", "created_at"])
    op.create_index(op.f("ix_audit_events_actor_id"), "audit_events", ["actor_id"])
    op.create_index(op.f("ix_audit_events_created_at"), "audit_events", ["created_at"])
    op.create_index("ix_audit_events_resource", "audit_events", ["resource_type", "resource_id"])


def downgrade() -> None:
    op.drop_table("audit_events")
    op.drop_table("reports")
    op.drop_table("password_reset_tokens")
    op.drop_table("email_verification_tokens")
    op.drop_table("notifications")
    op.drop_table("saved_jobs")
    op.drop_table("job_applications")
    op.drop_table("jobs")
    op.drop_table("employer_profiles")
    op.drop_table("worker_profiles")
    op.drop_table("users")
