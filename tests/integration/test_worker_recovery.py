"""Integration tests for worker.jobs against a real Postgres (owner: Mink).

Needs APP_ENV=test and TEST_DATABASE_URL pointing at an isolated test server, e.g.
  docker run -d --name mink-testdb -e POSTGRES_PASSWORD=test -p 55432:5432 postgres:16.4
  APP_ENV=test TEST_DATABASE_URL=postgresql://postgres:test@localhost:55432/postgres \
    pytest -m integration tests/integration/test_worker_recovery.py
Each test gets a freshly created and migrated database that is dropped afterwards.
"""

import os
import uuid
from pathlib import Path

import pytest

psycopg = pytest.importorskip("psycopg")

from worker.jobs import (  # noqa: E402
    PoisonJobError,
    claim_job,
    complete_job,
    on_failure,
    process_job,
)

pytestmark = pytest.mark.integration

MIGRATIONS = sorted((Path(__file__).parents[2] / "db" / "migrations").glob("*.sql"))
LEASE = 30


@pytest.fixture
def db_url():
    admin_url = os.environ.get("TEST_DATABASE_URL")
    if not admin_url:
        pytest.skip("TEST_DATABASE_URL not set")
    if os.environ.get("APP_ENV") != "test":
        pytest.fail("refusing to run worker integration tests unless APP_ENV=test")

    name = f"worker_test_{uuid.uuid4().hex[:12]}"
    with psycopg.connect(admin_url, autocommit=True) as admin:
        admin.execute(f'CREATE DATABASE "{name}"')
    url = psycopg.conninfo.make_conninfo(admin_url, dbname=name)
    with psycopg.connect(url) as conn:
        for migration in MIGRATIONS:
            conn.execute(migration.read_text())
        conn.commit()
    yield url
    with psycopg.connect(admin_url, autocommit=True) as admin:
        admin.execute(f'DROP DATABASE "{name}" WITH (FORCE)')


@pytest.fixture
def connect(db_url):
    conns = []

    def _connect():
        conn = psycopg.connect(db_url)
        conns.append(conn)
        return conn

    yield _connect
    for conn in conns:
        conn.close()


def add_order(conn, customer_id="cust-1", max_attempts=5) -> str:
    """Insert what place_order would commit: an order and its jobs row."""
    order_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO orders (order_id, idempotency_key, request_hash, customer_id, total_cents)"
        " VALUES (%s, %s, 'hash', %s, 1299)",
        (order_id, f"key-{order_id}", customer_id),
    )
    conn.execute(
        "INSERT INTO jobs (order_id, max_attempts) VALUES (%s, %s)", (order_id, max_attempts)
    )
    conn.commit()
    return order_id


def order_status(conn, order_id) -> str:
    status = conn.execute("SELECT status FROM orders WHERE order_id = %s", (order_id,)).fetchone()
    conn.commit()
    return status[0]


def job_row(conn, order_id) -> dict:
    cur = conn.execute(
        "SELECT attempts, locked_by, completed_at, dead_lettered_at, last_error,"
        " next_attempt_at > now() AS scheduled_later FROM jobs WHERE order_id = %s",
        (order_id,),
    )
    names = [col.name for col in cur.description]
    row = dict(zip(names, cur.fetchone(), strict=True))
    conn.commit()
    return row


def total_stock(conn) -> int:
    total = conn.execute("SELECT sum(available) FROM products").fetchone()[0]
    conn.commit()
    return total


def expire_lease(conn, order_id):
    conn.execute(
        "UPDATE jobs SET lease_until = now() - interval '1 second' WHERE order_id = %s",
        (order_id,),
    )
    conn.commit()


def test_claim_marks_order_processing_and_takes_a_lease(connect):
    conn = connect()
    order_id = add_order(conn)

    job = claim_job(conn, "worker-a", LEASE)

    assert job.order_id == order_id and job.attempts == 1
    assert order_status(conn, order_id) == "processing"
    assert job_row(conn, order_id)["locked_by"] == "worker-a"
    assert claim_job(connect(), "worker-b", LEASE) is None  # lease still held


def test_skip_locked_gives_concurrent_workers_different_jobs(connect):
    setup, a, b = connect(), connect(), connect()
    first, second = add_order(setup), add_order(setup)

    # Worker A is mid-claim: its transaction holds the row lock on the first job.
    a.execute("SELECT 1 FROM jobs WHERE order_id = %s FOR UPDATE", (first,))
    job_b = claim_job(b, "worker-b", LEASE)
    a.rollback()

    assert job_b.order_id == second  # B skipped the locked row instead of waiting on it


def test_expired_lease_is_reclaimed_and_stale_worker_cannot_complete(connect):
    a, b = connect(), connect()
    order_id = add_order(a)
    job_a = claim_job(a, "worker-a", LEASE)

    expire_lease(a, order_id)  # worker A died mid-job
    job_b = claim_job(b, "worker-b", LEASE)

    assert job_b.order_id == order_id and job_b.attempts == 2
    assert complete_job(a, job_a, "worker-a") is False  # zombie A changes nothing
    assert complete_job(b, job_b, "worker-b") is True
    assert order_status(b, order_id) == "completed"


def test_completing_twice_has_no_additional_effect(connect):
    conn = connect()
    order_id = add_order(conn)
    job = claim_job(conn, "worker-a", LEASE)

    assert complete_job(conn, job, "worker-a") is True
    completed_at = job_row(conn, order_id)["completed_at"]
    assert complete_job(conn, job, "worker-a") is False

    assert job_row(conn, order_id)["completed_at"] == completed_at
    assert order_status(conn, order_id) == "completed"
    assert claim_job(conn, "worker-a", LEASE) is None  # done jobs are never handed out again


def test_failure_reschedules_with_backoff(connect):
    conn = connect()
    order_id = add_order(conn)
    job = claim_job(conn, "worker-a", LEASE)

    outcome = on_failure(conn, job, "worker-a", RuntimeError("downstream timeout"), backoff_base=30)

    row = job_row(conn, order_id)
    assert outcome == "retry"
    assert row["locked_by"] is None and row["scheduled_later"]
    assert row["last_error"] == "RuntimeError: downstream timeout"
    assert order_status(conn, order_id) == "queued"
    assert claim_job(conn, "worker-a", LEASE) is None  # not due yet


def test_poison_job_is_dead_lettered_after_bounded_retries_without_restock(connect):
    conn = connect()
    order_id = add_order(conn, customer_id="poison-drill", max_attempts=3)
    stock_before = total_stock(conn)

    outcomes = []
    while (job := claim_job(conn, "worker-a", LEASE)) is not None:
        with pytest.raises(PoisonJobError) as raised:
            process_job(conn, job, fault_injection=True)
        outcomes.append(on_failure(conn, job, "worker-a", raised.value, backoff_base=0))
        assert len(outcomes) <= 3, "retry loop is not bounded"

    row = job_row(conn, order_id)
    assert outcomes == ["retry", "retry", "dead"]
    assert row["attempts"] == 3 and row["dead_lettered_at"] is not None
    assert row["last_error"].startswith("PoisonJobError")
    assert order_status(conn, order_id) == "failed"
    assert total_stock(conn) == stock_before  # reserved stock is kept for manual review


def test_crash_looping_job_goes_to_dead_letter(connect):
    conn = connect()
    order_id = add_order(conn, max_attempts=2)
    for _ in range(2):  # two workers die holding the lease
        claim_job(conn, "worker-a", LEASE)
        expire_lease(conn, order_id)

    job = claim_job(conn, "worker-b", LEASE)
    assert job.attempts > job.max_attempts
    assert on_failure(conn, job, "worker-b", RuntimeError("lease expired too often")) == "dead"
    assert order_status(conn, order_id) == "failed"


def test_failure_after_losing_the_lease_changes_nothing(connect):
    a, b = connect(), connect()
    order_id = add_order(a)
    job_a = claim_job(a, "worker-a", LEASE)
    expire_lease(a, order_id)
    claim_job(b, "worker-b", LEASE)

    assert on_failure(a, job_a, "worker-a", RuntimeError("late failure")) == "lost"
    assert job_row(b, order_id)["locked_by"] == "worker-b"
    assert order_status(b, order_id) == "processing"
