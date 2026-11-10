"""Order placement: aggregation, idempotency and atomic stock reservation.

Owner: Tristan.
"""

from common.models import OrderRequest, PlaceOrderResult


def aggregate_lines(items: list[tuple[str, int]]) -> dict[str, int]:
    """Sum duplicate SKU lines."""
    raise NotImplementedError


def normalize_and_hash(payload: dict) -> str:
    """Stable hash of the request body, independent of JSON key order."""
    raise NotImplementedError


def compute_total(lines: dict[str, int], prices: dict[str, int]) -> int:
    raise NotImplementedError


def place_order(conn, idempotency_key: str, order: OrderRequest) -> PlaceOrderResult:
    """One transaction: order + lines + stock decrement + idempotency mapping + jobs row.

    Raises ApiError OUT_OF_STOCK or IDEMPOTENCY_CONFLICT. Concurrent same-key callers
    must all get the winner's order_id.
    """
    raise NotImplementedError


def get_order(conn, order_id: str) -> dict | None:
    """Return {"order_id", "status", "total_cents"}; None for unknown or malformed IDs."""
    raise NotImplementedError
