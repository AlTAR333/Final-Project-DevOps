"""Unit tests for worker.jobs, worker.health and worker.main (owner: Mink). No database."""

import json
import logging
import threading
import urllib.error
import urllib.request

import pytest

from common.config import Settings
from worker import main as worker_main
from worker.health import Health, serve
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


# --- worker.health -------------------------------------------------------------------------


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def test_live_while_loop_beats_and_stalled_when_it_stops():
    clock = FakeClock()
    health = Health(lambda: None, stale_after=60, clock=clock)
    clock.now += 59
    assert health.live() == (200, {"status": "ok"})
    clock.now += 2
    assert health.live() == (503, {"status": "stalled"})
    health.beat()
    assert health.live() == (200, {"status": "ok"})


def test_ready_depends_on_database_and_never_leaks_the_error():
    def broken():
        raise ConnectionError("connection refused: postgresql://user:secret@db")

    assert Health(lambda: None, 60).ready() == (200, {"status": "ready"})
    status, body = Health(broken, 60).ready()
    assert (status, body) == (503, {"status": "not_ready"})
    assert "secret" not in json.dumps(body)


def test_health_server_routes():
    def broken():
        raise RuntimeError("db down")

    server = serve(0, Health(broken, 60))  # port 0: any free port
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:

        def get(path):
            try:
                with urllib.request.urlopen(base + path, timeout=2) as resp:
                    return resp.status, json.loads(resp.read())
            except urllib.error.HTTPError as err:
                return err.code, json.loads(err.read())

        assert get("/health/live") == (200, {"status": "ok"})
        assert get("/health/ready") == (503, {"status": "not_ready"})
        assert get("/nope") == (404, {"status": "not_found"})
    finally:
        server.shutdown()


# --- worker.main ---------------------------------------------------------------------------


def make_settings(**overrides) -> Settings:
    values = {
        "database_url": "postgresql://unused",
        "app_env": "test",
        "log_level": "INFO",
        "api_port": 8080,
        "worker_id": "worker-t",
        "poll_interval_seconds": 0.001,
        "lease_seconds": 30,
        "max_attempts": 5,
        "backoff_base_seconds": 1.0,
        "backoff_cap_seconds": 60.0,
        "processing_delay_seconds": 0.0,
        "fault_injection_enabled": False,
    }
    return Settings(**{**values, **overrides})


class LoopConn:
    def __init__(self):
        self.closed = False
        self.rollbacks = 0
        self.autocommit = True

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        self.closed = True


class FakeQueue:
    """Stands in for worker.jobs: hands out the given jobs once, then stops the loop."""

    def __init__(self, monkeypatch, stop, *jobs, process_error=None):
        self.jobs, self.stop, self.process_error = list(jobs), stop, process_error
        self.processed, self.completed, self.failures = [], [], []
        monkeypatch.setattr(worker_main.jobs, "claim_job", self.claim)
        monkeypatch.setattr(worker_main.jobs, "process_job", self.process)
        monkeypatch.setattr(worker_main.jobs, "complete_job", self.complete)
        monkeypatch.setattr(worker_main.jobs, "on_failure", self.on_failure)

    def claim(self, conn, worker_id, lease_seconds):
        if not self.jobs:
            self.stop.set()
            return None
        return self.jobs.pop(0)

    def process(self, conn, job, **kwargs):
        self.processed.append(job)
        if self.process_error:
            raise self.process_error

    def complete(self, conn, job, worker_id):
        self.completed.append(job)
        return True

    def on_failure(self, conn, job, worker_id, error, **kwargs):
        self.failures.append((job, error))
        return "retry"


def run_loop(monkeypatch, *jobs, connect=None, process_error=None):
    stop = threading.Event()
    queue = FakeQueue(monkeypatch, stop, *jobs, process_error=process_error)
    conn = LoopConn()
    worker_main.run(make_settings(), stop, Health(lambda: None, 60), connect or (lambda url: conn))
    return queue, conn


def test_loop_processes_and_completes_a_job(monkeypatch):
    queue, conn = run_loop(monkeypatch, JOB)
    assert queue.processed == [JOB] and queue.completed == [JOB]
    assert queue.failures == []
    assert conn.closed  # connection released on shutdown


def test_loop_sends_processing_errors_to_on_failure(monkeypatch):
    error = PoisonJobError("boom")
    queue, conn = run_loop(monkeypatch, JOB, process_error=error)
    assert queue.failures == [(JOB, error)]
    assert queue.completed == []
    assert conn.rollbacks == 1


def test_loop_dead_letters_a_crash_looping_job_without_processing_it(monkeypatch):
    exhausted = Job(order_id=JOB.order_id, attempts=6, max_attempts=5)
    queue, _ = run_loop(monkeypatch, exhausted)
    assert queue.processed == []
    assert [job for job, _ in queue.failures] == [exhausted]


def test_loop_survives_a_database_outage(monkeypatch):
    import psycopg

    conn = LoopConn()
    attempts = []

    def flaky_connect(url):
        attempts.append(url)
        if len(attempts) == 1:
            raise psycopg.OperationalError("server closed the connection")
        return conn

    queue, _ = run_loop(monkeypatch, JOB, connect=flaky_connect)
    assert len(attempts) == 2
    assert queue.completed == [JOB]


def test_loop_does_nothing_once_stopped(monkeypatch):
    stop = threading.Event()
    stop.set()
    queue = FakeQueue(monkeypatch, stop, JOB)

    def must_not_connect(url):
        raise AssertionError("connected after stop")

    worker_main.run(make_settings(), stop, Health(lambda: None, 60), must_not_connect)
    assert queue.processed == []


def test_json_logs_keep_only_whitelisted_fields():
    record = logging.LogRecord("worker", logging.INFO, __file__, 1, "job completed", None, None)
    record.event, record.order_id, record.customer_id = "job_completed", JOB.order_id, "CUST-042"
    entry = json.loads(worker_main.JsonFormatter().format(record))
    assert entry["event"] == "job_completed" and entry["order_id"] == JOB.order_id
    assert entry["level"] == "INFO" and entry["ts"].endswith("+00:00")
    assert "customer_id" not in entry
