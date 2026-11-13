"""Unit tests for api.metrics (owner: Armand). Fake connection, no database."""

import pytest

from api import metrics
from common.contract import (
    METRIC_HTTP_DURATION,
    METRIC_HTTP_REQUESTS,
    METRIC_ORDERS_CREATED,
    METRIC_ORDERS_FAILED,
    METRIC_WORKER_RETRIES,
)


class FakeResult:
    def __init__(self, row):
        self._row = row

    def fetchone(self):
        return self._row


class FakeConn:
    def __init__(self, row=(0, 0, 0), error=None):
        self.row = row
        self.error = error

    def execute(self, sql, params=None):
        if self.error:
            raise self.error
        return FakeResult(self.row)


@pytest.fixture(autouse=True)
def clean_metrics():
    metrics.reset()
    yield
    metrics.reset()


def sample(text: str, prefix: str) -> float:
    """Value of the single sample line starting with `prefix`."""
    lines = [ln for ln in text.splitlines() if ln.startswith(prefix)]
    assert len(lines) == 1, f"expected exactly one line for {prefix!r}, got {lines}"
    return float(lines[0].rsplit(" ", 1)[1])


def test_required_names_present_before_any_traffic():
    text = metrics.render(FakeConn())
    for name in (
        METRIC_ORDERS_CREATED,
        METRIC_ORDERS_FAILED,
        METRIC_WORKER_RETRIES,
        METRIC_HTTP_REQUESTS,
        METRIC_HTTP_DURATION,
    ):
        assert name in text


def test_database_derived_counters():
    text = metrics.render(FakeConn(row=(12, 2, 7)))
    assert sample(text, METRIC_ORDERS_CREATED + " ") == 12
    assert sample(text, METRIC_ORDERS_FAILED + " ") == 2
    assert sample(text, METRIC_WORKER_RETRIES + " ") == 7
    assert sample(text, "fulfillops_db_up ") == 1


def test_http_counter_is_labelled_and_accumulates():
    metrics.observe_request("GET", "/api/v1/catalog", 200, 0.01)
    metrics.observe_request("GET", "/api/v1/catalog", 200, 0.02)
    metrics.observe_request("POST", "/api/v1/orders", 409, 0.03)
    text = metrics.render(FakeConn())
    ok = f'{METRIC_HTTP_REQUESTS}{{method="GET",route="/api/v1/catalog",status="200"}} '
    conflict = f'{METRIC_HTTP_REQUESTS}{{method="POST",route="/api/v1/orders",status="409"}} '
    assert sample(text, ok) == 2
    assert sample(text, conflict) == 1


def test_histogram_buckets_are_cumulative_and_consistent():
    route = '{method="GET",route="/api/v1/catalog"'
    for seconds in (0.004, 0.04, 0.04, 0.25, 20.0):  # the last exceeds every finite bucket
        metrics.observe_request("GET", "/api/v1/catalog", 200, seconds)
    text = metrics.render(FakeConn())

    def bucket(le: str) -> float:
        return sample(text, f'{METRIC_HTTP_DURATION}_bucket{route},le="{le}"}}')

    assert bucket("0.005") == 1
    assert bucket("0.05") == 3
    assert bucket("0.3") == 4
    assert bucket("10.0") == 4
    assert bucket("+Inf") == 5  # +Inf always equals _count
    assert sample(text, f"{METRIC_HTTP_DURATION}_count{route}}}") == 5
    assert sample(text, f"{METRIC_HTTP_DURATION}_sum{route}}}") == pytest.approx(20.334)

    counts = [bucket(str(b)) for b in metrics.BUCKETS]
    assert counts == sorted(counts)  # monotonic non-decreasing


def test_labels_hold_route_templates_not_identifiers():
    metrics.observe_request("GET", "/api/v1/orders/{order_id}", 200, 0.01)
    text = metrics.render(FakeConn())
    assert 'route="/api/v1/orders/{order_id}"' in text


def test_label_values_are_escaped():
    metrics.observe_request("GET", 'a"b\\c\nd', 200, 0.01)
    text = metrics.render(FakeConn())
    assert 'route="a\\"b\\\\c\\nd"' in text
    assert all(ln.startswith(("#", "fulfillops_")) for ln in text.splitlines() if ln)


def test_metrics_survive_a_database_outage():
    metrics.observe_request("GET", "/health/live", 200, 0.001)
    text = metrics.render(FakeConn(error=ConnectionError("db down")))
    assert sample(text, "fulfillops_db_up ") == 0
    assert METRIC_ORDERS_CREATED not in text  # no fake zeros when the truth is unknown
    assert f'{METRIC_HTTP_REQUESTS}{{method="GET",route="/health/live",status="200"}} 1' in text


def test_output_ends_with_newline():
    assert metrics.render(FakeConn()).endswith("\n")
