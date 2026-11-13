"""Order placement: aggregation, idempotency and atomic stock reservation.

Owner: Tristan.
"""

import hashlib
import json
import uuid

from api.errors import ApiError
from common.contract import ErrorCode
from common.models import OrderRequest, PlaceOrderResult


def aggregate_lines(items: list[tuple[str, int]]) -> dict[str, int]:
    """Sum duplicate SKU lines."""
    lines: dict[str, int] = {}
    for sku, quantity in items:
        lines[sku] = lines.get(sku, 0) + quantity
    return lines


def normalize_and_hash(payload: dict) -> str:
    """Stable hash of the request body, independent of JSON key order."""
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def compute_total(lines: dict[str, int], prices: dict[str, int]) -> int:
    return sum(quantity * prices[sku] for sku, quantity in lines.items())


def _out_of_stock() -> ApiError:
    return ApiError(409, ErrorCode.OUT_OF_STOCK, "Not enough items available")


def _idempotency_conflict() -> ApiError:
    return ApiError(
        409,
        ErrorCode.IDEMPOTENCY_CONFLICT,
        "Idempotency key already used with a different request",
    )


def _replay(conn, idempotency_key: str, request_hash: str) -> PlaceOrderResult:
    row = conn.execute(
        "SELECT order_id, request_hash FROM orders WHERE idempotency_key = %s",
        (idempotency_key,),
    ).fetchone()
    if row[1] != request_hash:
        raise _idempotency_conflict()
    return PlaceOrderResult(order_id=str(row[0]), replayed=True)


def place_order(conn, idempotency_key: str, order: OrderRequest) -> PlaceOrderResult:
    """One transaction: order + lines + stock decrement + idempotency mapping + jobs row.

    Raises ApiError OUT_OF_STOCK or IDEMPOTENCY_CONFLICT. Concurrent same-key callers
    must all get the winner's order_id.
    """
    lines = aggregate_lines(order.items)
    request_hash = normalize_and_hash(order.payload)
    order_id = uuid.uuid4()

    with conn.transaction():
        inserted = conn.execute(
            "INSERT INTO orders "
            "(order_id, idempotency_key, request_hash, customer_id, total_cents) "
            "VALUES (%s, %s, %s, %s, 0) "
            "ON CONFLICT (idempotency_key) DO NOTHING RETURNING order_id",
            (order_id, idempotency_key, request_hash, order.customer_id),
        ).fetchone()
        if inserted is None:
            return _replay(conn, idempotency_key, request_hash)

        prices: dict[str, int] = {}
        for sku in sorted(lines):
            row = conn.execute(
                "UPDATE products SET available = available - %s "
                "WHERE sku = %s AND available >= %s RETURNING unit_price_cents",
                (lines[sku], sku, lines[sku]),
            ).fetchone()
            if row is None:
                raise _out_of_stock()
            prices[sku] = row[0]

        conn.execute(
            "UPDATE orders SET total_cents = %s WHERE order_id = %s",
            (compute_total(lines, prices), order_id),
        )
        with conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO order_lines (order_id, sku, quantity, unit_price_cents) "
                "VALUES (%s, %s, %s, %s)",
                [(order_id, sku, qty, prices[sku]) for sku, qty in sorted(lines.items())],
            )
        conn.execute("INSERT INTO jobs (order_id) VALUES (%s)", (order_id,))

    return PlaceOrderResult(order_id=str(order_id), replayed=False)


def get_order(conn, order_id: str) -> dict | None:
    """Return {"order_id", "status", "total_cents"}; None for unknown or malformed IDs."""
    try:
        parsed = uuid.UUID(order_id)
    except (ValueError, TypeError, AttributeError):
        return None
    row = conn.execute(
        "SELECT order_id, status, total_cents FROM orders WHERE order_id = %s",
        (parsed,),
    ).fetchone()
    if row is None:
        return None
    return {"order_id": str(row[0]), "status": row[1], "total_cents": row[2]}
