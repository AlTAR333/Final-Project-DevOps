"""Unit tests for api.validation (owner: Armand). No database, no network."""

import json

import pytest

from api.errors import ApiError
from api.validation import validate_order
from common.contract import ErrorCode

KEY = "contract-key-0001"


def body(**overrides) -> bytes:
    payload = {"customer_id": "CUST-042", "items": [{"sku": "KIT-100", "quantity": 1}]}
    payload.update(overrides)
    return json.dumps(payload).encode()


def fails(key, raw, status: int, code: ErrorCode) -> None:
    with pytest.raises(ApiError) as exc:
        validate_order(key, raw)
    assert (exc.value.status, exc.value.code) == (status, code)
    assert exc.value.message  # safe, non-empty message


# --- happy path ------------------------------------------------------------------------------


def test_valid_order_returns_key_and_request():
    key, order = validate_order(KEY, body())
    assert key == KEY
    assert order.customer_id == "CUST-042"
    assert order.items == [("KIT-100", 1)]
    assert order.payload["customer_id"] == "CUST-042"


def test_duplicate_sku_lines_are_kept_as_sent():
    items = [{"sku": "PACK-300", "quantity": 2}, {"sku": "PACK-300", "quantity": 2}]
    _, order = validate_order(KEY, body(items=items))
    assert order.items == [("PACK-300", 2), ("PACK-300", 2)]  # aggregation is place_order's job


def test_boundaries_are_accepted():
    items = [{"sku": "KIT-100", "quantity": q} for q in (1, 20)] * 5  # 10 lines
    validate_order("k" * 8, body(items=items, customer_id="c" * 64))
    validate_order("k" * 128, body())


def test_extra_fields_are_ignored():
    validate_order(KEY, body(note="gift", items=[{"sku": "KIT-100", "quantity": 1, "x": 1}]))


# --- Idempotency-Key -------------------------------------------------------------------------


@pytest.mark.parametrize(
    "key", [None, "", "short", "k" * 7, "k" * 129, "bad\nkey-0001", "clé-12345"]
)
def test_missing_or_unusable_key(key):
    fails(key, body(), 400, ErrorCode.IDEMPOTENCY_REQUIRED)


def test_key_is_checked_before_body():
    fails(None, b"not json", 400, ErrorCode.IDEMPOTENCY_REQUIRED)


# --- JSON ------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw",
    [
        b"",
        b"{",
        b"not json",
        b'{"a":1,}',
        b"\xff\xfe",
        b'{"a": NaN}',
    ],
    ids=["empty", "truncated", "text", "trailing-comma", "bad-utf8", "nan"],
)
def test_invalid_json(raw):
    fails(KEY, raw, 400, ErrorCode.INVALID_JSON)


def test_deeply_nested_body_never_crashes():
    # Under 16 KiB. Python < 3.13 raises RecursionError (-> INVALID_JSON); newer versions parse
    # it into a list (-> INVALID_REQUEST). Either way: a clean 400, never an unhandled 500.
    raw = b"[" * 8000 + b"]" * 8000
    with pytest.raises(ApiError) as exc:
        validate_order(KEY, raw)
    assert exc.value.status == 400
    assert exc.value.code in (ErrorCode.INVALID_JSON, ErrorCode.INVALID_REQUEST)


def test_body_over_16_kib_is_rejected():
    raw = body(customer_id="x") + b" " * (16 * 1024)
    fails(KEY, raw, 413, ErrorCode.INVALID_REQUEST)


# --- structure -------------------------------------------------------------------------------


@pytest.mark.parametrize("raw", [b"[]", b'"text"', b"42", b"null", b"true"])
def test_body_must_be_an_object(raw):
    fails(KEY, raw, 400, ErrorCode.INVALID_REQUEST)


@pytest.mark.parametrize("customer_id", [None, "", "   ", 42, True, ["a"], "c" * 65])
def test_bad_customer_id(customer_id):
    fails(KEY, body(customer_id=customer_id), 400, ErrorCode.INVALID_REQUEST)


def test_missing_customer_id():
    raw = json.dumps({"items": [{"sku": "KIT-100", "quantity": 1}]}).encode()
    fails(KEY, raw, 400, ErrorCode.INVALID_REQUEST)


@pytest.mark.parametrize(
    "items",
    [
        None,
        [],
        "KIT-100",
        {"sku": "KIT-100", "quantity": 1},
        [{"sku": "KIT-100", "quantity": 1}] * 11,
        ["KIT-100"],
        [{"sku": "KIT-100"}],
        [{"quantity": 1}],
        [{"sku": "KIT-100", "quantity": 1}, {"sku": "PART-200"}],
    ],
)
def test_bad_items_structure(items):
    fails(KEY, body(items=items), 400, ErrorCode.INVALID_REQUEST)


def test_missing_items():
    raw = json.dumps({"customer_id": "CUST-042"}).encode()
    fails(KEY, raw, 400, ErrorCode.INVALID_REQUEST)


def test_malformed_later_line_beats_semantic_error_on_earlier_line():
    items = [{"sku": "NOPE-1", "quantity": 1}, {"sku": "KIT-100"}]
    fails(KEY, body(items=items), 400, ErrorCode.INVALID_REQUEST)


# --- quantity (422) --------------------------------------------------------------------------


@pytest.mark.parametrize("quantity", [0, -1, 21, 1.0, 2.5, "1", None, True, False, [1], {}])
def test_invalid_quantity(quantity):
    raw = body(items=[{"sku": "KIT-100", "quantity": quantity}])
    fails(KEY, raw, 422, ErrorCode.INVALID_QUANTITY)


def test_huge_integer_quantity_is_invalid_quantity():
    raw = b'{"customer_id":"C","items":[{"sku":"KIT-100","quantity":' + b"9" * 400 + b"}]}"
    fails(KEY, raw, 422, ErrorCode.INVALID_QUANTITY)


# --- sku (422) -------------------------------------------------------------------------------


@pytest.mark.parametrize("sku", ["NOPE-1", "", "kit-100", " KIT-100", 7, None, ["KIT-100"]])
def test_invalid_sku(sku):
    fails(KEY, body(items=[{"sku": sku, "quantity": 1}]), 422, ErrorCode.INVALID_SKU)


def test_one_bad_line_rejects_the_whole_order():
    items = [{"sku": "KIT-100", "quantity": 1}, {"sku": "NOPE-1", "quantity": 1}]
    fails(KEY, body(items=items), 422, ErrorCode.INVALID_SKU)


# --- safety ----------------------------------------------------------------------------------


def test_messages_never_echo_client_input():
    secret = "SECRET-CUSTOMER-VALUE"
    with pytest.raises(ApiError) as exc:
        validate_order(KEY, body(items=[{"sku": secret, "quantity": 1}]))
    assert secret not in exc.value.message
