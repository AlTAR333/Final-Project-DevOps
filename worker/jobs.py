"""Job claiming, completion and failure handling on the jobs table.

Owner: Mink.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Job:
    id: int
    order_id: str
    attempts: int
    max_attempts: int


def claim_job(conn, worker_id: str, lease_seconds: int) -> Job | None:
    """Atomically claim one pending job or one whose lease expired (FOR UPDATE SKIP LOCKED)."""
    raise NotImplementedError


def process_job(conn, job: Job) -> None:
    raise NotImplementedError


def complete_job(conn, job: Job, worker_id: str) -> bool:
    """Mark order completed and job done. False if this worker no longer holds the lease.

    Running it twice must have no additional effect.
    """
    raise NotImplementedError


def on_failure(conn, job: Job, worker_id: str, error: Exception) -> None:
    """Reschedule with backoff, or mark job dead and order failed. Never restock."""
    raise NotImplementedError


def backoff_seconds(attempts: int, base: float, cap: float) -> float:
    raise NotImplementedError
