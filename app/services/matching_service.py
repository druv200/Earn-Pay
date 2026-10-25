"""Explainable, rule-based job matching engine for Earn & Pay (No black-box AI claims)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.extensions import db
from app.models.job import Job
from app.models.user import WorkerProfile

_AVAILABILITY_COMPATIBILITY: dict[str, frozenset[str]] = {
    "daily": frozenset({"daily_wage", "temporary"}),
    "part_time": frozenset({"part_time", "temporary", "daily_wage"}),
    "weekends": frozenset({"part_time", "temporary", "daily_wage"}),
    "full_time": frozenset({"full_time"}),
    "flexible": frozenset({"daily_wage", "part_time", "temporary", "full_time"}),
}


@dataclass(frozen=True)
class JobMatchResult:
    """Explainable match result pairing a Job with its score and human-readable reasons."""

    job: Job
    score: int
    reasons: tuple[str, ...]


def evaluate_job_match(worker: WorkerProfile, job: Job) -> JobMatchResult:
    """Evaluate a single Job against a WorkerProfile using 5 transparent rules."""
    score = 0
    reasons: list[str] = []

    # 1. Location / Pincode Match (up to 30 pts)
    worker_pin = (worker.pincode or "").strip()
    job_pin = (job.pincode or "").strip()
    worker_loc = (worker.preferred_location or "").strip().lower()
    job_loc = (job.location or "").strip().lower()

    if worker_pin and worker_pin == job_pin:
        score += 30
        reasons.append(f"Same pincode ({job_pin})")
    elif worker_loc and worker_loc in job_loc:
        score += 20
        reasons.append(f"Preferred area ({worker.preferred_location})")

    # 2. Category Match (25 pts)
    pref_cats = {
        cat.strip().lower()
        for cat in (worker.preferred_categories or "").split(",")
        if cat.strip()
    }
    if job.category.strip().lower() in pref_cats:
        score += 25
        reasons.append(f"Category match ({job.category})")

    # 3. Skills Overlap (up to 25 pts)
    worker_skills = worker.skill_list
    if worker_skills:
        searchable_job_text = (
            f"{job.title} {job.required_skills or ''} {job.description}".lower()
        )
        matched_skills = [skill for skill in worker_skills if skill in searchable_job_text]
        if matched_skills:
            score += 25
            preview = ", ".join(matched_skills[:2])
            reasons.append(f"Skills match ({preview})")

    # 4. Availability & Job-Type Compatibility (10 pts)
    compatible_types = _AVAILABILITY_COMPATIBILITY.get(
        worker.availability,
        frozenset({"daily_wage", "part_time", "temporary", "full_time"}),
    )
    if job.job_type in compatible_types:
        score += 10
        reasons.append(f"Fits {worker.availability.replace('_', ' ')} schedule")

    # 5. Wage Expectation Fit (10 pts)
    if (
        worker.expected_daily_wage is not None
        and job.wage_frequency == "daily"
        and job.wage_amount >= worker.expected_daily_wage
    ):
        score += 10
        reasons.append(f"Meets expected daily wage (₹{int(job.wage_amount)})")

    return JobMatchResult(job=job, score=score, reasons=tuple(reasons))


def get_recommended_jobs_for_worker(
    worker: WorkerProfile,
    *,
    limit: int = 6,
) -> list[JobMatchResult]:
    """Query active published jobs and return top explainable rule-based recommendations."""
    today = datetime.now(UTC).date()
    stmt = (
        select(Job)
        .options(selectinload(Job.employer))
        .where(
            Job.status == "published",
            Job.application_deadline >= today,
        )
        .order_by(Job.published_at.desc(), Job.id.desc())
        .limit(50)
    )
    candidate_jobs = list(db.session.execute(stmt).scalars().all())
    scored = [evaluate_job_match(worker, job) for job in candidate_jobs]
    scored.sort(key=lambda item: (item.score, item.job.id), reverse=True)
    return scored[:limit]
