"""HTTP application and routes. Run with: python -m api.app

Owner: Armand. Contract: docs/assignment/API_CONTRACT_EN.md

  GET  /health/live              -> health.live
  GET  /health/ready             -> health.ready
  GET  /api/v1/catalog           -> catalog.get_catalog
  GET  /api/v1/inventory/{sku}   -> catalog.get_inventory
  POST /api/v1/orders            -> validation.validate_order, then orders.place_order (Tristan)
  GET  /api/v1/orders/{order_id} -> orders.get_order (Tristan)
  GET  /metrics                  -> metrics.render

Design notes
  * Flask for routing, Waitress as the production WSGI server (pure Python, same on every OS).
  * The API keeps no authoritative state in memory: stock and idempotency live in Postgres,
    so any replica can serve any request. Only request metrics are per-process.
  * One database connection per request, opened lazily and always closed. Liveness and
    request validation never open one, so they work while the database is down.
  * Every error, including 404/405/500, uses the contract body {"error": {"code", "message"}}.
    Unexpected exceptions are logged server-side and never echoed to the client.
"""

import logging
import re
import time

from flask import Flask, Response, g, jsonify, request
from werkzeug.exceptions import HTTPException

from api import catalog, health, metrics, orders
from api.errors import ApiError, error_body
from api.validation import validate_order
from common import db
from common.config import Settings, load_settings
from common.contract import MAX_BODY_BYTES, ErrorCode

log = logging.getLogger("fulfillops.api")

# Codes outside the contract's ErrorCode enum (the contract defines none for these cases).
SERVICE_UNAVAILABLE = "SERVICE_UNAVAILABLE"
INTERNAL_ERROR = "INTERNAL_ERROR"
_HTTP_ERROR_CODES = {404: "NOT_FOUND", 405: "METHOD_NOT_ALLOWED", 413: ErrorCode.INVALID_REQUEST}

# Waitress buffers a request body before Flask sees it. The contract limit (16 KiB) is enforced
# in validation, which answers with the JSON error body; this larger cap only protects memory,
# and anything above it is refused by Waitress itself.
_SERVER_BODY_CAP = 1024 * 1024
_KNOWN_METHODS = {"GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"}
_RULE_PARAM = re.compile(r"<(?:[^:>]+:)?([^>]+)>")


class _NoDatabase:
    """Stand-in connection used by /metrics when storage is unreachable."""

    def execute(self, *_args, **_kwargs):
        raise ConnectionError("database unavailable")


def _route_label() -> str:
    """Route template for logs and metrics: bounded cardinality, no identifiers."""
    rule = request.url_rule
    if rule is None:
        return "unmatched"
    return _RULE_PARAM.sub(r"{\1}", rule.rule)


def _error(status: int, code, message: str):
    response = jsonify(error_body(code, message))
    response.status_code = status
    return response


def create_app(settings: Settings | None = None, connect=None) -> Flask:
    """Build the app. `connect` (a zero-argument callable returning a connection) is for tests."""
    if connect is None:
        settings = settings or load_settings()

        def connect():
            return db.connect(settings.database_url)

    app = Flask(__name__)
    app.json.sort_keys = False

    def get_conn():
        if "conn" not in g:
            try:
                g.conn = connect()
            except Exception:
                log.warning("database connection failed")
                raise ApiError(
                    503, SERVICE_UNAVAILABLE, "Service temporarily unavailable"
                ) from None
        return g.conn

    @app.teardown_request
    def close_conn(_exc):
        conn = g.pop("conn", None)
        if conn is not None:
            try:
                conn.close()
            except Exception:
                log.warning("closing the database connection failed")

    @app.before_request
    def start_timer():
        g.started = time.perf_counter()

    @app.after_request
    def observe(response: Response) -> Response:
        seconds = time.perf_counter() - g.get("started", time.perf_counter())
        method = request.method if request.method in _KNOWN_METHODS else "OTHER"
        route = _route_label()
        metrics.observe_request(method, route, response.status_code, seconds)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Cache-Control"] = "no-store"
        # Never log headers, bodies, customer ids or idempotency keys.
        log.info(
            "request method=%s route=%s status=%s duration_ms=%.1f",
            method,
            route,
            response.status_code,
            seconds * 1000,
        )
        return response

    # --- health ----------------------------------------------------------------------------

    @app.get("/health/live")
    def live():
        return jsonify(health.live())

    @app.get("/health/ready")
    def ready():
        try:
            status, body = health.ready(get_conn())
        except ApiError:
            status, body = 503, {"status": "not_ready"}
        return jsonify(body), status

    # --- catalog and inventory -------------------------------------------------------------

    @app.get("/api/v1/catalog")
    def get_catalog():
        return jsonify({"products": catalog.get_catalog(get_conn())})

    @app.get("/api/v1/inventory/<sku>")
    def get_inventory(sku: str):
        item = catalog.get_inventory(get_conn(), sku)
        if item is None:
            raise ApiError(404, ErrorCode.SKU_NOT_FOUND, "SKU not found")
        return jsonify(item)

    # --- orders ----------------------------------------------------------------------------

    @app.post("/api/v1/orders")
    def create_order():
        # Read at most one byte past the limit; validation turns that into the 413 response.
        raw = request.stream.read(MAX_BODY_BYTES + 1)
        key, order = validate_order(request.headers.get("Idempotency-Key"), raw)
        result = orders.place_order(get_conn(), key, order)
        # 202 for both a first acceptance and an idempotent replay: the contract wants the
        # same acceptance receipt, even if the order has completed since.
        return jsonify({"order_id": result.order_id, "status": "queued"}), 202

    @app.get("/api/v1/orders/<order_id>")
    def get_order(order_id: str):
        order = orders.get_order(get_conn(), order_id)
        if order is None:
            raise ApiError(404, ErrorCode.ORDER_NOT_FOUND, "Order not found")
        return jsonify(order)

    # --- metrics ---------------------------------------------------------------------------

    @app.get("/metrics")
    def prometheus():
        try:
            conn = get_conn()
        except ApiError:
            conn = _NoDatabase()
        return Response(metrics.render(conn), mimetype="text/plain; version=0.0.4")

    # --- errors ----------------------------------------------------------------------------

    @app.errorhandler(ApiError)
    def api_error(exc: ApiError):
        return _error(exc.status, exc.code, exc.message)

    @app.errorhandler(HTTPException)
    def http_error(exc: HTTPException):
        code = _HTTP_ERROR_CODES.get(exc.code, "HTTP_ERROR")
        response = _error(exc.code or 500, code, exc.name)
        for name, value in exc.get_headers():
            if name.lower() == "allow":  # keep the Allow header on 405 responses
                response.headers[name] = value
        return response

    @app.errorhandler(Exception)
    def unexpected(_exc: Exception):
        log.exception("unhandled error on %s %s", request.method, _route_label())
        return _error(500, INTERNAL_ERROR, "Internal server error")

    return app


def main() -> None:
    from waitress import serve

    settings = load_settings()
    logging.basicConfig(
        level=settings.log_level.upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    log.info("starting API on port %s (env=%s)", settings.api_port, settings.app_env)
    serve(
        create_app(settings),
        host="0.0.0.0",  # noqa: S104 - inside a container; exposure is decided by compose/k8s
        port=settings.api_port,
        threads=8,
        max_request_body_size=_SERVER_BODY_CAP,
        ident="fulfillops",
    )


if __name__ == "__main__":
    main()
