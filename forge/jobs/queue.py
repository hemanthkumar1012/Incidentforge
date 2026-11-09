"""Postgres-backed job queue.

Why a table and not Celery/Redis: the workload is a handful of slow jobs
(investigations, validations, recoveries), the data they act on already lives
in Postgres, and enqueueing in the same transaction as the state change means
a job can never exist without its subject row or vice versa.

* Claiming uses ``FOR UPDATE SKIP LOCKED``: concurrent workers never take the
  same job and never block each other.
* A job holds a lease. If a worker dies, ``requeue_stale`` returns the job to
  the queue after ``LEASE`` so it is retried (up to ``max_attempts``).
* Failures are retried with linear backoff; the last error is kept for display.
"""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from forge.db.models import Job
from forge.services.common import utcnow

LEASE = timedelta(minutes=10)
RETRY_BACKOFF = timedelta(seconds=15)


def enqueue(session: Session, kind: str, subject_id: str, *, max_attempts: int = 2) -> Job:
    job = Job(kind=kind, subject_id=subject_id, status="queued", max_attempts=max_attempts, run_after=utcnow())
    session.add(job)
    session.flush()
    return job


def claim_next(session: Session, worker_id: str) -> Job | None:
    job = session.scalars(
        select(Job)
        .where(Job.status == "queued", Job.run_after <= utcnow())
        .order_by(Job.run_after, Job.id)
        .limit(1)
        .with_for_update(skip_locked=True)
    ).first()
    if job is None:
        return None
    job.status, job.locked_by, job.locked_at = "running", worker_id, utcnow()
    job.attempts += 1
    return job


def complete(session: Session, job_id: int) -> None:
    session.execute(update(Job).where(Job.id == job_id).values(status="done", last_error=None))


def fail(session: Session, job_id: int, error: str) -> bool:
    """Record a failure; returns True if the job will be retried."""
    job = session.get(Job, job_id, with_for_update=True)
    if job is None:
        return False
    job.last_error = error[:2000]
    if job.attempts < job.max_attempts:
        job.status, job.run_after, job.locked_by = "queued", utcnow() + RETRY_BACKOFF * job.attempts, None
        return True
    job.status = "failed"
    return False


def requeue_stale(session: Session) -> int:
    result = session.execute(
        update(Job)
        .where(Job.status == "running", Job.locked_at < utcnow() - LEASE)
        .values(status="queued", locked_by=None, last_error="lease expired (worker stopped?)")
    )
    return result.rowcount or 0
