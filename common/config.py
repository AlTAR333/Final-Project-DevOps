"""Environment variables read by API, worker and scripts.

Owner: all three. Names must match .env.example, compose.yaml and infra/k8s.
"""

import os
import socket
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    database_url: str
    app_env: str  # "test" | "dev" | "prod"; reset script refuses anything but "test"
    log_level: str
    api_port: int
    worker_id: str
    poll_interval_seconds: float
    lease_seconds: int
    max_attempts: int
    backoff_base_seconds: float
    backoff_cap_seconds: float
    processing_delay_seconds: float  # lab only: widens the kill-mid-job window
    fault_injection_enabled: bool  # lab only: enables the poison-job trigger


def load_settings() -> Settings:
    env = os.environ
    return Settings(
        database_url=env["DATABASE_URL"],
        app_env=env.get("APP_ENV", "dev"),
        log_level=env.get("LOG_LEVEL", "INFO"),
        api_port=int(env.get("API_PORT", "8080")),
        worker_id=env.get("WORKER_ID") or socket.gethostname(),
        poll_interval_seconds=float(env.get("POLL_INTERVAL_SECONDS", "0.5")),
        lease_seconds=int(env.get("LEASE_SECONDS", "30")),
        max_attempts=int(env.get("MAX_ATTEMPTS", "5")),
        backoff_base_seconds=float(env.get("BACKOFF_BASE_SECONDS", "1")),
        backoff_cap_seconds=float(env.get("BACKOFF_CAP_SECONDS", "60")),
        processing_delay_seconds=float(env.get("PROCESSING_DELAY_SECONDS", "0")),
        fault_injection_enabled=env.get("FAULT_INJECTION_ENABLED", "false").lower() == "true",
    )
