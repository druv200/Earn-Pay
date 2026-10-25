"""Public marketplace routes: Landing page, About, Safety Guidelines, Privacy, Terms, and Help."""

from __future__ import annotations

from datetime import UTC, datetime

from flask import (
    Blueprint,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import current_user
from sqlalchemy import func, select

from app.extensions import db
from app.models.job import Job
from app.models.user import EmployerProfile, User
from app.services.job_service import search_published_jobs
from app.services.profile_service import count_available_workers

public_bp = Blueprint("public", __name__)

DEFAULT_JOB_CATEGORIES: tuple[str, ...] = (
    "Retail",
    "Restaurant & Food",
    "Delivery & Logistics",
    "Warehouse & Stock",
    "Cleaning & Housekeeping",
    "Event & Helper",
    "Office & Billing",
)


def _wants_json() -> bool:
    best = request.accept_mimetypes.best_match(["application/json", "text/html"])
    return (
        best == "application/json"
        and request.accept_mimetypes[best] > request.accept_mimetypes["text/html"]
    )


@public_bp.get("/")
def index():
    """Render the editorial landing page adapted to visitor, worker, or employer context."""
    today = datetime.now(UTC).date()
    search_query = request.args.get("q", "").strip()
    selected_location = request.args.get("location", "").strip()
    selected_category = request.args.get("category", "").strip()
    has_search_params = any(
        key in request.args for key in ("q", "location", "category", "find_work")
    )

    # Require registration/sign-in before interactive job search for unauthenticated visitors
    if not current_user.is_authenticated and has_search_params:
        flash(
            "Please register or sign in with a Worker account to search and apply for local jobs.",
            "warning",
        )
        target_jobs_url = url_for(
            "jobs.job_discovery",
            q=search_query or None,
            location=selected_location or None,
            category=selected_category or None,
        )
        return redirect(url_for("auth.login", next=target_jobs_url))

    # Signed-in employers submitting search on homepage are routed to Find Workers
    if current_user.is_authenticated and current_user.is_employer and has_search_params:
        return redirect(
            url_for(
                "profiles.find_workers",
                q=search_query or None,
                location=selected_location or None,
                category=selected_category or None,
            )
        )

    count_stmt = (
        select(func.count(Job.id))
        .join(Job.employer)
        .join(EmployerProfile.user)
        .where(
            Job.status == "published",
            Job.application_deadline >= today,
            Job.vacancies >= 1,
            User.role == "employer",
            User.account_status.in_(("active", "pending_verification")),
        )
    )
    live_job_count = int(db.session.execute(count_stmt).scalar_one() or 0)
    available_worker_count = count_available_workers()

    selected_jobs: list[Job] = []
    if current_user.is_authenticated and (current_user.is_worker or current_user.is_admin):
        search_page = search_published_jobs(
            q=search_query,
            location=selected_location,
            category=selected_category,
            page=1,
            per_page=8,
        )
        selected_jobs = search_page.jobs

    if _wants_json():
        return (
            jsonify(
                {
                    "product": current_app.config.get("APP_NAME", "Earn & Pay"),
                    "tagline": "Find Work. Earn Money. Build Your Future.",
                    "status": "foundation_ready",
                    "launch_city": current_app.config.get("LAUNCH_CITY", "Bengaluru"),
                    "live_job_count": live_job_count,
                }
            ),
            200,
        )

    return render_template(
        "public/landing.html",
        selected_jobs=selected_jobs,
        live_job_count=live_job_count,
        available_worker_count=available_worker_count,
        categories=DEFAULT_JOB_CATEGORIES,
        search_query=search_query,
        selected_location=selected_location,
        selected_category=selected_category,
    )


@public_bp.get("/about")
def about():
    """Render About Earn & Pay page."""
    return render_template("public/about.html")


@public_bp.get("/safety")
def safety_guidelines():
    """Render Community and Job Safety Guidelines page."""
    return render_template("public/safety.html")


@public_bp.get("/privacy")
def privacy_policy():
    """Render Privacy Policy page."""
    return render_template("public/privacy.html")


@public_bp.get("/terms")
def terms_of_service():
    """Render Terms of Service page."""
    return render_template("public/terms.html")


@public_bp.get("/help")
def help_contact():
    """Render Help, Contact, and Escalation Support page."""
    return render_template("public/help.html")
