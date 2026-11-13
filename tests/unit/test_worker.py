"""Unit tests for worker.jobs (owner: Mink). Fake connection, no database."""

import pytest

from worker.jobs import (
    MAX_ERROR_CHARS,
    Job,
    PoisonJobError,
    backoff_seconds,
    is_poison,
    process_job,
    safe_error,
)

JOB = Job(order_id="0d9674de-7fac-4c13-bb2f-c4bcbaf743da", attempts=1, max_attempts=5)


class FakeResult:
    def __init__(self, row):
        self._row = row

    def fetchone(self):
        return self._row


class FakeConn:
    """Returns the given customer_id for the order lookup and records every query."""

    def __init__(self, customer_id="cust-1"):
        self.customer_id = customer_id
        self.queries = []
        self.commits = 0

    def execute(self, sql, params=None):
        self.queries.append(sql)
        return FakeResult((self.customer_id,))

    def commit(self):
        self.commits += 1

    def rollback(self):
        pass


def test_backoff_doubles_from_base():
    assert [backoff_seconds(n, 1.0, 60.0) for n in (1, 2, 3, 4)] == [1.0, 2.0, 4.0, 8.0]


def test_backoff_is_capped():
    assert backoff_seconds(10, 1.0, 60.0) == 60.0
    assert backoff_seconds(10_000, 1.0, 60.0) == 60.0  # no overflow on huge counts


def test_backoff_treats_zero_attempts_as_first():
    assert backoff_seconds(0, 2.0, 60.0) == 2.0


def test_poison_prefix():
    assert is_poison("poison-drill-1")
    assert not is_poison("cust-poison-")


def test_process_without_fault_injection_never_queries():
    conn = FakeConn(customer_id="poison-x")
    process_job(conn, JOB)  # poison customer is harmless when the lab switch is off
    assert conn.queries == []


def test_process_with_fault_injection_fails_poison_orders():
    conn = FakeConn(customer_id="poison-x")
    with pytest.raises(PoisonJobError):
        process_job(conn, JOB, fault_injection=True)
    assert conn.commits == 1  # read transaction closed before raising


def test_process_with_fault_injection_passes_normal_orders():
    process_job(FakeConn(customer_id="cust-1"), JOB, fault_injection=True)


def test_safe_error_keeps_one_line_and_type():
    error = ValueError("first line\nTraceback (most recent call last): ...")
    assert safe_error(error) == "ValueError: first line"


def test_safe_error_is_bounded():
    assert len(safe_error(RuntimeError("x" * 10_000))) == MAX_ERROR_CHARS


def test_safe_error_without_message():
    assert safe_error(TimeoutError()) == "TimeoutError"
