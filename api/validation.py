"""Request validation for POST /api/v1/orders.

Owner: Armand.
"""

from common.models import OrderRequest


def validate_order(idempotency_key: str | None, body: bytes) -> tuple[str, OrderRequest]:
    """Return (idempotency_key, order) or raise ApiError with the contract status and code.

    Booleans are not valid quantities: isinstance(True, int) is True in Python.
    """
    raise NotImplementedError
