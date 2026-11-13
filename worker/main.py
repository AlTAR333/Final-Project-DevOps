"""Worker loop. Run with: python -m worker.main

Owner: Mink. Claims jobs, processes them, retries with backoff, exits cleanly on SIGTERM.

SIGTERM/SIGINT stop the loop after the current job; a hard kill leaves the job's lease to
expire so another worker reclaims it. Database outages are retried with backoff instead of
crashing, so Kubernetes restarts only a worker whose loop is genuinely stuck.
"""

import json
import logging
import signal
import threading
from collections.abc import Callable
from datetime import UTC, datetime

import psycopg

from common import db
from common.config import Settings, load_settings
from worker import jobs
from worker.health import HEALTH_PORT, Health, serve

log = logging.getLogger("worker")

_LOG_FIELDS = ("event", "worker_id", "order_id", "attempts", "outcome", "error")
_RECONNECT_CAP_SECONDS = 30.0


class JsonFormatter(logging.Formatter):
    """One JSON object per line. Only whitelisted fields: no customer IDs, keys or DSNs."""

    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "msg": record.getMessage(),
        }
        entry.update({k: getattr(record, k) for k in _LOG_FIELDS if hasattr(record, k)})
        return json.dumps(entry)


def configure_logging(level: str) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    logging.basicConfig(level=level.upper(), handlers=[handler], force=True)


def connect(database_url: str):
    try:
        conn = db.connect(database_url)
    except NotImplementedError:  # TODO(Mink): drop once common.db.connect lands (Tristan)
        conn = psycopg.connect(database_url, connect_timeout=5)
    conn.autocommit = False  # worker.jobs commits each step explicitly
    return conn


def check_db(database_url: str) -> None:
    """Readiness: a short-lived connection, so a probe never waits behind a running job."""
    with psycopg.connect(database_url, connect_timeout=2) as conn:
        if not conn.execute("SELECT to_regclass('public.jobs') IS NOT NULL").fetchone()[0]:
            raise RuntimeError("migrations not applied")


def handle(conn, job: jobs.Job, settings: Settings) -> None:
    fields = {"worker_id": settings.worker_id, "order_id": job.order_id, "attempts": job.attempts}
    if job.attempts > job.max_attempts:  # every earlier holder died mid-job
        error = RuntimeError("lease expired on every attempt")
        outcome = jobs.on_failure(conn, job, settings.worker_id, error)
        log.error("job abandoned", extra={**fields, "event": "job_failed", "outcome": outcome})
        return
    try:
        jobs.process_job(
            conn,
            job,
            delay_seconds=settings.processing_delay_seconds,
            fault_injection=settings.fault_injection_enabled,
        )
    except Exception as exc:
        conn.rollback()
        outcome = jobs.on_failure(
            conn,
            job,
            settings.worker_id,
            exc,
            backoff_base=settings.backoff_base_seconds,
            backoff_cap=settings.backoff_cap_seconds,
        )
        level = logging.ERROR if outcome == "dead" else logging.WARNING
        log.log(
            level,
            "job failed",
            extra={
                **fields,
                "event": "job_failed",
                "outcome": outcome,
                "error": jobs.safe_error(exc),
            },
        )
        return
    if jobs.complete_job(conn, job, settings.worker_id):
        log.info("job completed", extra={**fields, "event": "job_completed"})
    else:
        log.warning("lease lost before completion", extra={**fields, "event": "job_lease_lost"})


def run(
    settings: Settings,
    stop: threading.Event,
    health: Health,
    connect: Callable = connect,
) -> None:
    conn = None
    reconnect_delay = settings.poll_interval_seconds
    while not stop.is_set():
        health.beat()
        try:
            if conn is None or conn.closed:
                conn = connect(settings.database_url)
                log.info("database connected", extra={"event": "db_connected"})
                reconnect_delay = settings.poll_interval_seconds
            job = jobs.claim_job(conn, settings.worker_id, settings.lease_seconds)
            if job is None:
                stop.wait(settings.poll_interval_seconds)
                continue
            log.info(
                "job claimed",
                extra={
                    "event": "job_claimed",
                    "worker_id": settings.worker_id,
                    "order_id": job.order_id,
                    "attempts": job.attempts,
                },
            )
            handle(conn, job, settings)
        except Exception as exc:  # DB outage or bug: back off, reconnect, keep the process alive
            log.error(
                "worker loop error",
                extra={"event": "loop_error", "error": jobs.safe_error(exc)},
            )
            if conn is not None:
                conn.close()
            conn = None
            stop.wait(reconnect_delay)
            reconnect_delay = min(reconnect_delay * 2, _RECONNECT_CAP_SECONDS)
    if conn is not None:
        conn.close()


def main() -> None:
    settings = load_settings()
    configure_logging(settings.log_level)

    stop = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda signum, frame: stop.set())

    # A job may legitimately run for up to a lease; only a loop silent for longer is stuck.
    stale_after = max(30.0, 2.0 * settings.lease_seconds)
    health = Health(lambda: check_db(settings.database_url), stale_after)
    server = serve(HEALTH_PORT, health)

    log.info("worker started", extra={"event": "worker_started", "worker_id": settings.worker_id})
    run(settings, stop, health)
    server.shutdown()
    log.info("worker stopped", extra={"event": "worker_stopped", "worker_id": settings.worker_id})


if __name__ == "__main__":
    main()
