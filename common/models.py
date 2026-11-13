"""Types passed between modules owned by different people.

Owner: all three. Any change needs a PR reviewed by every team member.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class OrderRequest:
    """Output of api.validation.validate_order (Armand).

    Input of api.orders.place_order (Tristan).
    """

    customer_id: str
    items: list[tuple[str, int]]  # (sku, quantity) as sent, before aggregation
    payload: dict  # parsed JSON body, used for idempotency comparison


@dataclass(frozen=True)
class PlaceOrderResult:
    order_id: str
    replayed: bool  # True when an existing order was returned for the same key
