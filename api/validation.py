"""Request validation for POST /api/v1/orders.

Owner: Armand.

Order of checks (first failure wins):
  1. Idempotency-Key header        -> 400 IDEMPOTENCY_REQUIRED
  2. body size                     -> 413 INVALID_REQUEST
  3. JSON syntax                   -> 400 INVALID_JSON
  4. overall structure             -> 400 INVALID_REQUEST
  5. each item, in array order:
       sku                         -> 422 INVALID_SKU
       quantity                    -> 422 INVALID_QUANTITY

Error messages are fixed strings: they never echo client input (no reflection, no PII).
"""

import json

from api.errors import ApiError
from common.contract import (
    CUSTOMER_ID_MAX_LEN,
    IDEMPOTENCY_KEY_MAX_LEN,
    IDEMPOTENCY_KEY_MIN_LEN,
    ITEMS_MAX,
    ITEMS_MIN,
    MAX_BODY_BYTES,
    QUANTITY_MAX,
    QUANTITY_MIN,
    ErrorCode,
)
from common.models import OrderRequest

# The catalog is fixed by the API contract. Kept here (not in the DB) so validation stays
# a pure function. place_order must still tolerate a missing product row defensively.
KNOWN_SKUS = frozenset({"KIT-100", "PART-200", "PACK-300"})


def _reject_constant(name: str):
    """json.loads accepts NaN/Infinity by default; they are not valid JSON."""
    raise ValueError(f"invalid JSON constant: {name}")


def _check_key(key: str | None) -> str:
    # Printable ASCII only (0x20-0x7E). The contract defines no separate code for a
    # malformed key, so a missing and an unusable key are both IDEMPOTENCY_REQUIRED.
    if (
        key is None
        or not (IDEMPOTENCY_KEY_MIN_LEN <= len(key) <= IDEMPOTENCY_KEY_MAX_LEN)
        or not (key.isascii() and key.isprintable())
    ):
        raise ApiError(
            400,
            ErrorCode.IDEMPOTENCY_REQUIRED,
            "A valid Idempotency-Key header (8-128 printable ASCII characters) is required",
        )
    return key


def _parse_json(body: bytes) -> object:
    if len(body) > MAX_BODY_BYTES:
        raise ApiError(413, ErrorCode.INVALID_REQUEST, "Request body is too large")
    try:
        return json.loads(body.decode("utf-8"), parse_constant=_reject_constant)
    except (UnicodeDecodeError, ValueError, RecursionError):
        # JSONDecodeError is a ValueError; RecursionError covers absurdly deep nesting.
        raise ApiError(400, ErrorCode.INVALID_JSON, "Request body is not valid JSON") from None


def _invalid_request(message: str) -> ApiError:
    return ApiError(400, ErrorCode.INVALID_REQUEST, message)


def validate_order(idempotency_key: str | None, body: bytes) -> tuple[str, OrderRequest]:
    """Return (idempotency_key, order) or raise ApiError with the contract status and code.

    Booleans are not valid quantities: isinstance(True, int) is True in Python.
    """
    key = _check_key(idempotency_key)
    payload = _parse_json(body)

    if not isinstance(payload, dict):
        raise _invalid_request("Request body must be a JSON object")

    customer_id = payload.get("customer_id")
    if (
        not isinstance(customer_id, str)
        or not customer_id.strip()
        or len(customer_id) > CUSTOMER_ID_MAX_LEN
    ):
        raise _invalid_request("customer_id must be a non-empty string of at most 64 characters")

    items = payload.get("items")
    if not isinstance(items, list) or not (ITEMS_MIN <= len(items) <= ITEMS_MAX):
        raise _invalid_request("items must be an array of 1 to 10 objects")

    # Structure of every line first, so a malformed line is INVALID_REQUEST
    # even when an earlier line has a semantic (422) problem.
    for item in items:
        if not isinstance(item, dict) or "sku" not in item or "quantity" not in item:
            raise _invalid_request("Each item must be an object with sku and quantity")

    lines: list[tuple[str, int]] = []
    for item in items:
        sku, quantity = item["sku"], item["quantity"]
        if not isinstance(sku, str) or sku not in KNOWN_SKUS:
            raise ApiError(422, ErrorCode.INVALID_SKU, "Unknown or invalid SKU")
        if (
            isinstance(quantity, bool)
            or not isinstance(quantity, int)
            or not (QUANTITY_MIN <= quantity <= QUANTITY_MAX)
        ):
            raise ApiError(
                422, ErrorCode.INVALID_QUANTITY, "quantity must be an integer from 1 to 20"
            )
        lines.append((sku, quantity))

    return key, OrderRequest(customer_id=customer_id, items=lines, payload=payload)
