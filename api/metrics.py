"""Prometheus exposition for /metrics. Metric names live in common.contract.

Owner: Armand. Worker retry/failure counts come from the jobs table (agree with Mink).

Two kinds of series:
  * HTTP request count and latency histogram: kept in this process (each API replica is
    scraped separately, which is how Prometheus expects per-process counters to work).
  * Orders created / failed and worker retries: derived from the database, so every replica
    reports the same authoritative values and nothing is lost when a pod restarts.

Labels never contain customer IDs, idempotency keys or raw paths: `route` is the route
template (e.g. /api/v1/orders/{order_id}), which also keeps cardinality bounded.
"""

import threading
from collections import defaultdict

from common.contract import (
    METRIC_HTTP_DURATION,
    METRIC_HTTP_REQUESTS,
    METRIC_ORDERS_CREATED,
    METRIC_ORDERS_FAILED,
    METRIC_WORKER_RETRIES,
)

# Seconds. Dense around the 300 ms SLO so an observed p95 can be computed accurately.
BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.2, 0.3, 0.5, 1.0, 2.5, 5.0, 10.0)

_lock = threading.Lock()
_requests: dict[tuple[str, str, str], int] = defaultdict(int)
# (method, route) -> [per-bucket cumulative-ready counts..., sum, count]
_latency: dict[tuple[str, str], dict] = {}

# retries = attempts beyond the first, summed over all jobs.
_DB_SQL = """
SELECT
    (SELECT count(*) FROM orders),
    (SELECT count(*) FROM orders WHERE status = 'failed'),
    (SELECT COALESCE(SUM(GREATEST(attempts - 1, 0)), 0) FROM jobs)
"""


def observe_request(method: str, route: str, status: int, seconds: float) -> None:
    with _lock:
        _requests[(method, route, str(status))] += 1
        hist = _latency.setdefault(
            (method, route), {"buckets": [0] * len(BUCKETS), "sum": 0.0, "count": 0}
        )
        for i, upper in enumerate(BUCKETS):
            if seconds <= upper:
                hist["buckets"][i] += 1
                break
        hist["sum"] += seconds
        hist["count"] += 1


def reset() -> None:
    """Clear in-process series. For tests only."""
    with _lock:
        _requests.clear()
        _latency.clear()


def _esc(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


def _fmt(value: float) -> str:
    return repr(float(value)) if isinstance(value, float) else str(value)


def _render_http() -> list[str]:
    lines = [
        f"# HELP {METRIC_HTTP_REQUESTS} Total HTTP requests handled by this API instance.",
        f"# TYPE {METRIC_HTTP_REQUESTS} counter",
    ]
    with _lock:
        requests = sorted(_requests.items())
        latency = sorted((k, {**v, "buckets": list(v["buckets"])}) for k, v in _latency.items())

    for (method, route, status), count in requests:
        labels = f'method="{_esc(method)}",route="{_esc(route)}",status="{status}"'
        lines.append(f"{METRIC_HTTP_REQUESTS}{{{labels}}} {count}")

    lines += [
        f"# HELP {METRIC_HTTP_DURATION} HTTP request latency in seconds.",
        f"# TYPE {METRIC_HTTP_DURATION} histogram",
    ]
    for (method, route), hist in latency:
        base = f'method="{_esc(method)}",route="{_esc(route)}"'
        cumulative = 0
        for upper, n in zip(BUCKETS, hist["buckets"], strict=True):
            cumulative += n
            lines.append(f'{METRIC_HTTP_DURATION}_bucket{{{base},le="{upper}"}} {cumulative}')
        lines.append(f'{METRIC_HTTP_DURATION}_bucket{{{base},le="+Inf"}} {hist["count"]}')
        lines.append(f"{METRIC_HTTP_DURATION}_sum{{{base}}} {_fmt(hist['sum'])}")
        lines.append(f"{METRIC_HTTP_DURATION}_count{{{base}}} {hist['count']}")
    return lines


def _render_db(conn) -> list[str]:
    try:
        created, failed, retries = conn.execute(_DB_SQL).fetchone()
    except Exception:  # keep /metrics up even when storage is down
        return [
            "# HELP fulfillops_db_up 1 if the database answered the metrics query.",
            "# TYPE fulfillops_db_up gauge",
            "fulfillops_db_up 0",
        ]
    return [
        f"# HELP {METRIC_ORDERS_CREATED} Orders accepted (persisted) so far.",
        f"# TYPE {METRIC_ORDERS_CREATED} counter",
        f"{METRIC_ORDERS_CREATED} {int(created)}",
        f"# HELP {METRIC_ORDERS_FAILED} Orders that exhausted retries and are failed.",
        f"# TYPE {METRIC_ORDERS_FAILED} counter",
        f"{METRIC_ORDERS_FAILED} {int(failed)}",
        f"# HELP {METRIC_WORKER_RETRIES} Worker attempts beyond the first, summed over all jobs.",
        f"# TYPE {METRIC_WORKER_RETRIES} counter",
        f"{METRIC_WORKER_RETRIES} {int(retries)}",
        "# HELP fulfillops_db_up 1 if the database answered the metrics query.",
        "# TYPE fulfillops_db_up gauge",
        "fulfillops_db_up 1",
    ]


def render(conn) -> str:
    """Prometheus text format (serve as text/plain; version=0.0.4)."""
    return "\n".join(_render_db(conn) + _render_http()) + "\n"
