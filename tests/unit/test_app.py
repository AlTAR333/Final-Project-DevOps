"""Unit tests for api.app (owner: Armand). Flask test client, fake connection, no database."""

import json

import pytest

from api import catalog, health, metrics, orders
from api.app import create_app
from api.errors import ApiError
from common.contract import MAX_BODY_BYTES, ErrorCode
from common.models import PlaceOrderResult

KEY = "contract-key-0001"
ORDER = {"customer_id": "CUST-042", "items": [{"sku": "KIT-100", "quantity": 1}]}
ORDER_ID = "0d9674de-7fac-4c13-bb2f-c4bcbaf743da"


class FakeConn:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


class Env:
    """A test app plus a record of the connections it opened."""

    def __init__(self, fail_connect: bool = False):
        self.conns: list[FakeConn] = []
        self.fail_connect = fail_connect
        self.app = create_app(connect=self._connect)
        self.client = self.app.test_client()

    def _connect(self):
        if self.fail_connect:
            raise ConnectionError("postgresql://user:SECRET@db:5432/app refused")
        conn = FakeConn()
        self.conns.append(conn)
        return conn

    def post(self, payload=ORDER, key=KEY, raw: bytes | None = None):
        headers = {"Idempotency-Key": key} if key is not None else {}
        data = raw if raw is not None else json.dumps(payload).encode()
        return self.client.post("/api/v1/orders", data=data, headers=headers)


@pytest.fixture(autouse=True)
def clean_metrics():
    metrics.reset()
    yield
    metrics.reset()


@pytest.fixture
def env():
    return Env()


def assert_error(response, status: int, code):
    assert response.status_code == status
    assert response.is_json
    error = response.get_json()["error"]
    assert error["code"] == str(code)
    assert isinstance(error["message"], str) and error["message"]


# --- health ----------------------------------------------------------------------------------


def test_live_does_not_need_the_database():
    env = Env(fail_connect=True)
    response = env.client.get("/health/live")
    assert response.status_code == 200
    assert response.get_json() == {"status": "ok"}
    assert env.conns == []


def test_ready_ok(env, monkeypatch):
    monkeypatch.setattr(health, "ready", lambda conn: (200, {"status": "ready"}))
    response = env.client.get("/health/ready")
    assert (response.status_code, response.get_json()) == (200, {"status": "ready"})


def test_ready_503_when_migrations_missing(env, monkeypatch):
    monkeypatch.setattr(health, "ready", lambda conn: (503, {"status": "not_ready"}))
    response = env.client.get("/health/ready")
    assert (response.status_code, response.get_json()) == (503, {"status": "not_ready"})


def test_ready_503_when_database_unreachable():
    response = Env(fail_connect=True).client.get("/health/ready")
    assert (response.status_code, response.get_json()) == (503, {"status": "not_ready"})


# --- catalog and inventory -------------------------------------------------------------------


def test_catalog(env, monkeypatch):
    products = [{"sku": "KIT-100", "unit_price_cents": 1299}]
    monkeypatch.setattr(catalog, "get_catalog", lambda conn: products)
    response = env.client.get("/api/v1/catalog")
    assert response.status_code == 200
    assert response.get_json() == {"products": products}


def test_inventory_found(env, monkeypatch):
    monkeypatch.setattr(catalog, "get_inventory", lambda conn, sku: {"sku": sku, "available": 7})
    response = env.client.get("/api/v1/inventory/KIT-100")
    assert (response.status_code, response.get_json()) == (200, {"sku": "KIT-100", "available": 7})


def test_inventory_unknown_sku(env, monkeypatch):
    monkeypatch.setattr(catalog, "get_inventory", lambda conn, sku: None)
    assert_error(env.client.get("/api/v1/inventory/NOPE-1"), 404, ErrorCode.SKU_NOT_FOUND)


def test_database_outage_on_a_data_route_is_503():
    response = Env(fail_connect=True).client.get("/api/v1/catalog")
    assert_error(response, 503, "SERVICE_UNAVAILABLE")
    assert "SECRET" not in response.get_data(as_text=True)


# --- POST /api/v1/orders ---------------------------------------------------------------------


def test_create_order_returns_202_queued(env, monkeypatch):
    seen = {}

    def fake_place(conn, key, order):
        seen.update(key=key, order=order)
        return PlaceOrderResult(order_id=ORDER_ID, replayed=False)

    monkeypatch.setattr(orders, "place_order", fake_place)
    response = env.post()
    assert response.status_code == 202
    assert response.get_json() == {"order_id": ORDER_ID, "status": "queued"}
    assert seen["key"] == KEY
    assert seen["order"].items == [("KIT-100", 1)]


def test_replay_is_also_202_queued(env, monkeypatch):
    monkeypatch.setattr(
        orders, "place_order", lambda *a: PlaceOrderResult(order_id=ORDER_ID, replayed=True)
    )
    response = env.post()
    assert response.status_code == 202
    assert response.get_json() == {"order_id": ORDER_ID, "status": "queued"}


@pytest.mark.parametrize(
    ("kwargs", "status", "code"),
    [
        ({"key": None}, 400, ErrorCode.IDEMPOTENCY_REQUIRED),
        ({"raw": b"{not json"}, 400, ErrorCode.INVALID_JSON),
        ({"payload": {"customer_id": "C", "items": []}}, 400, ErrorCode.INVALID_REQUEST),
        (
            {"payload": {"customer_id": "C", "items": [{"sku": "KIT-100", "quantity": 0}]}},
            422,
            ErrorCode.INVALID_QUANTITY,
        ),
        (
            {"payload": {"customer_id": "C", "items": [{"sku": "NOPE", "quantity": 1}]}},
            422,
            ErrorCode.INVALID_SKU,
        ),
    ],
)
def test_validation_errors_never_touch_the_database(env, kwargs, status, code):
    assert_error(env.post(**kwargs), status, code)
    assert env.conns == []


def test_body_over_16_kib_is_rejected_with_json_413(env):
    raw = json.dumps(ORDER).encode().ljust(MAX_BODY_BYTES + 1)
    assert_error(env.post(raw=raw), 413, ErrorCode.INVALID_REQUEST)
    assert env.conns == []


def test_body_of_exactly_16_kib_is_accepted(env, monkeypatch):
    monkeypatch.setattr(
        orders, "place_order", lambda *a: PlaceOrderResult(order_id=ORDER_ID, replayed=False)
    )
    raw = json.dumps(ORDER).encode().ljust(MAX_BODY_BYTES)  # valid JSON plus trailing spaces
    assert len(raw) == MAX_BODY_BYTES
    assert env.post(raw=raw).status_code == 202


def test_missing_key_wins_over_oversized_body(env):
    raw = b"x" * (MAX_BODY_BYTES * 3)
    assert_error(env.post(raw=raw, key=None), 400, ErrorCode.IDEMPOTENCY_REQUIRED)


@pytest.mark.parametrize(
    ("status", "code", "message"),
    [
        (409, ErrorCode.OUT_OF_STOCK, "Not enough items available"),
        (409, ErrorCode.IDEMPOTENCY_CONFLICT, "Idempotency key reused with a different payload"),
    ],
)
def test_business_errors_from_place_order_use_the_contract_body(
    env, monkeypatch, status, code, message
):
    def refuse(*_args):
        raise ApiError(status, code, message)

    monkeypatch.setattr(orders, "place_order", refuse)
    assert_error(env.post(), status, code)


# --- GET /api/v1/orders/{id} -----------------------------------------------------------------


def test_get_order(env, monkeypatch):
    found = {"order_id": ORDER_ID, "status": "completed", "total_cents": 2497}
    monkeypatch.setattr(orders, "get_order", lambda conn, oid: found)
    response = env.client.get(f"/api/v1/orders/{ORDER_ID}")
    assert (response.status_code, response.get_json()) == (200, found)


def test_get_unknown_order(env, monkeypatch):
    monkeypatch.setattr(orders, "get_order", lambda conn, oid: None)
    assert_error(env.client.get("/api/v1/orders/not-real-order"), 404, ErrorCode.ORDER_NOT_FOUND)


# --- error handling --------------------------------------------------------------------------


def test_unknown_route_is_json_404(env):
    assert_error(env.client.get("/admin/reset"), 404, "NOT_FOUND")


def test_wrong_method_is_json_405_with_allow_header(env):
    response = env.client.post("/health/live")
    assert_error(response, 405, "METHOD_NOT_ALLOWED")
    assert "GET" in response.headers["Allow"]


def test_unexpected_exception_is_a_safe_500(env, monkeypatch, caplog):
    def explode(*_args):
        raise RuntimeError("SELECT * FROM orders; password=hunter2")

    monkeypatch.setattr(orders, "place_order", explode)
    response = env.post()
    assert_error(response, 500, "INTERNAL_ERROR")
    body = response.get_data(as_text=True)
    assert "hunter2" not in body and "SELECT" not in body and "Traceback" not in body
    assert "hunter2" in caplog.text  # the detail is kept in the server log, not in the response


def test_connection_is_closed_after_the_request(env, monkeypatch):
    monkeypatch.setattr(catalog, "get_catalog", lambda conn: [])
    env.client.get("/api/v1/catalog")
    assert len(env.conns) == 1 and env.conns[0].closed


def test_connection_is_closed_even_when_the_handler_fails(env, monkeypatch):
    def explode(*_args):
        raise RuntimeError("boom")

    monkeypatch.setattr(orders, "place_order", explode)
    env.post()
    assert len(env.conns) == 1 and env.conns[0].closed


def test_security_headers_on_every_response(env):
    for path in ("/health/live", "/nope"):
        response = env.client.get(path)
        assert response.headers["X-Content-Type-Options"] == "nosniff"
        assert response.headers["Cache-Control"] == "no-store"


# --- /metrics --------------------------------------------------------------------------------


def test_metrics_is_prometheus_text_with_required_series(env, monkeypatch):
    monkeypatch.setattr(metrics, "render", lambda conn: "fulfillops_orders_created_total 3\n")
    response = env.client.get("/metrics")
    assert response.status_code == 200
    assert response.mimetype == "text/plain"
    assert "fulfillops_orders_created_total 3" in response.get_data(as_text=True)


def test_metrics_counts_requests_by_route_template_not_by_identifier(env, monkeypatch):
    monkeypatch.setattr(orders, "get_order", lambda conn, oid: None)
    env.client.get("/api/v1/orders/customer-secret-id-123")
    env.client.get("/does/not/exist")
    env.client.open("/health/live", method="FOO")
    text = metrics.render(FakeConn.__new__(FakeConn))  # DB part fails -> http part still renders
    assert 'route="/api/v1/orders/{order_id}",status="404"} 1' in text
    assert 'route="unmatched",status="404"} 1' in text
    assert 'method="OTHER",route="unmatched",status="405"} 1' in text
    assert "customer-secret-id-123" not in text


def test_metrics_endpoint_survives_a_database_outage():
    env = Env(fail_connect=True)
    response = env.client.get("/metrics")
    text = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "fulfillops_db_up 0" in text
    assert "fulfillops_http_requests_total" in text


def test_latency_histogram_is_recorded_for_requests(env):
    env.client.get("/health/live")
    text = Env(fail_connect=True).client.get("/metrics").get_data(as_text=True)
    assert (
        'fulfillops_http_request_duration_seconds_count{method="GET",route="/health/live"} 1'
        in text
    )
