"""Job claiming, completion and failure handling on the jobs table.

Owner: Mink.

Delivery is at-least-once: a job whose lease expires (worker died) is claimed again.
The business effect is applied once because every state change is a conditional UPDATE
guarded by `locked_by = <this worker>` and "not already completed / dead-lettered".
A worker that lost its lease therefore changes nothing. Stock is reserved by the API at
acceptance and is never touched here, so neither a retry nor a dead letter restocks.
"""

import time
from contextlib import contextmanager
from dataclasses import dataclass

POISON_PREFIX = "poison-"  # lab only, honoured only when FAULT_INJECTION_ENABLED=true
MAX_ERROR_CHARS = 500


@dataclass(frozen=True)
class Job:
    order_id: str
    attempts: int  # including the current one: claim_job increments it
    max_attempts: int


class PoisonJobError(Exception):
    """Deterministic failure injected in the lab to exercise retries and the dead letter."""


@contextmanager
def _transaction(conn):
    try:
        yield
        conn.commit()
    except BaseException:
        conn.rollback()
        raise


_CLAIM_SQL = """
WITH next AS (
    SELECT order_id
    FROM jobs
    WHERE completed_at IS NULL
      AND dead_lettered_at IS NULL
      AND next_attempt_at <= now()
      AND (lease_until IS NULL OR lease_until < now())
    ORDER BY next_attempt_at
    LIMIT 1
    FOR UPDATE SKIP LOCKED
)
UPDATE jobs AS j
SET locked_by = %(worker_id)s,
    lease_until = now() + %(lease)s * interval '1 second',
    attempts = j.attempts + 1
FROM next
WHERE j.order_id = next.order_id
RETURNING j.order_id, j.attempts, j.max_attempts
"""


def claim_job(conn, worker_id: str, lease_seconds: int) -> Job | None:
    """Atomically claim one pending job or one whose lease expired (FOR UPDATE SKIP LOCKED)."""
    with _transaction(conn):
        row = conn.execute(_CLAIM_SQL, {"worker_id": worker_id, "lease": lease_seconds}).fetchone()
        if row is None:
            return None
        order_id, attempts, max_attempts = row
        conn.execute(
            "UPDATE orders SET status = 'processing', updated_at = now()"
            " WHERE order_id = %s AND status IN ('queued', 'processing')",
            (order_id,),
        )
    return Job(order_id=str(order_id), attempts=attempts, max_attempts=max_attempts)


def is_poison(customer_id: str) -> bool:
    return customer_id.startswith(POISON_PREFIX)


def process_job(
    conn, job: Job, *, delay_seconds: float = 0.0, fault_injection: bool = False
) -> None:
    """Fulfil the order. Stock is already reserved, so this only simulates the work.

    `delay_seconds` widens the window for the kill-a-worker drill; `fault_injection` makes
    orders from a `poison-` customer fail every time. Both are lab-only settings.
    """
    if fault_injection:
        with _transaction(conn):
            row = conn.execute(
                "SELECT customer_id FROM orders WHERE order_id = %s", (job.order_id,)
            ).fetchone()
        if row is not None and is_poison(row[0]):
            raise PoisonJobError("poison order injected by the fault drill")
    if delay_seconds > 0:
        time.sleep(delay_seconds)


def complete_job(conn, job: Job, worker_id: str) -> bool:
    """Mark order completed and job done. False if this worker no longer holds the lease.

    Running it twice must have no additional effect.
    """
    with _transaction(conn):
        cur = conn.execute(
            "UPDATE jobs SET completed_at = now(), locked_by = NULL, lease_until = NULL"
            " WHERE order_id = %s AND locked_by = %s"
            " AND completed_at IS NULL AND dead_lettered_at IS NULL",
            (job.order_id, worker_id),
        )
        if cur.rowcount != 1:
            return False
        conn.execute(
            "UPDATE orders SET status = 'completed', updated_at = now()"
            " WHERE order_id = %s AND status <> 'completed'",
            (job.order_id,),
        )
    return True


def on_failure(
    conn,
    job: Job,
    worker_id: str,
    error: BaseException,
    *,
    backoff_base: float = 1.0,
    backoff_cap: float = 60.0,
) -> str:
    """Reschedule with backoff, or mark job dead and order failed. Never restock.

    Returns "retry", "dead", or "lost" (another worker holds the lease, nothing changed).
    """
    message = safe_error(error)
    owned = (
        " WHERE order_id = %s AND locked_by = %s"
        " AND completed_at IS NULL AND dead_lettered_at IS NULL"
    )
    with _transaction(conn):
        if job.attempts >= job.max_attempts:
            cur = conn.execute(
                "UPDATE jobs SET dead_lettered_at = now(), locked_by = NULL,"
                " lease_until = NULL, last_error = %s" + owned,
                (message, job.order_id, worker_id),
            )
            if cur.rowcount != 1:
                return "lost"
            conn.execute(
                "UPDATE orders SET status = 'failed', updated_at = now()"
                " WHERE order_id = %s AND status <> 'completed'",
                (job.order_id,),
            )
            return "dead"

        delay = backoff_seconds(job.attempts, backoff_base, backoff_cap)
        cur = conn.execute(
            "UPDATE jobs SET next_attempt_at = now() + %s * interval '1 second',"
            " locked_by = NULL, lease_until = NULL, last_error = %s" + owned,
            (delay, message, job.order_id, worker_id),
        )
        if cur.rowcount != 1:
            return "lost"
        conn.execute(
            "UPDATE orders SET status = 'queued', updated_at = now()"
            " WHERE order_id = %s AND status = 'processing'",
            (job.order_id,),
        )
        return "retry"


def backoff_seconds(attempts: int, base: float, cap: float) -> float:
    """Exponential: base, 2*base, 4*base, ... after attempt 1, 2, 3, ..., capped at `cap`."""
    exponent = min(max(attempts, 1) - 1, 32)
    return min(cap, base * 2**exponent)


def safe_error(error: BaseException) -> str:
    """One line for jobs.last_error: exception type and first message line, no traceback."""
    first_line = str(error).splitlines()[0] if str(error) else ""
    text = f"{type(error).__name__}: {first_line}" if first_line else type(error).__name__
    return text[:MAX_ERROR_CHARS]
