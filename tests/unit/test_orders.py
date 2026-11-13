"""Owner: Tristan."""

import pytest

from api.orders import aggregate_lines, compute_total, normalize_and_hash
from scripts.reset_test_data import UnsafeResetError, check_safe


def test_aggregate_merges_duplicate_skus():
    assert aggregate_lines([("KIT-100", 1), ("PART-200", 2), ("KIT-100", 3)]) == {
        "KIT-100": 4,
        "PART-200": 2,
    }


def test_aggregate_single_line():
    assert aggregate_lines([("PACK-300", 5)]) == {"PACK-300": 5}


def test_aggregate_can_exceed_per_line_limit():
    assert aggregate_lines([("KIT-100", 20)] * 10) == {"KIT-100": 200}


def test_hash_ignores_key_order():
    a = {"customer_id": "C1", "items": [{"sku": "KIT-100", "quantity": 1}]}
    b = {"items": [{"quantity": 1, "sku": "KIT-100"}], "customer_id": "C1"}
    assert normalize_and_hash(a) == normalize_and_hash(b)


def test_hash_differs_for_different_quantity():
    a = {"customer_id": "C1", "items": [{"sku": "KIT-100", "quantity": 1}]}
    b = {"customer_id": "C1", "items": [{"sku": "KIT-100", "quantity": 2}]}
    assert normalize_and_hash(a) != normalize_and_hash(b)


def test_hash_differs_for_different_customer():
    a = {"customer_id": "C1", "items": [{"sku": "KIT-100", "quantity": 1}]}
    b = {"customer_id": "C2", "items": [{"sku": "KIT-100", "quantity": 1}]}
    assert normalize_and_hash(a) != normalize_and_hash(b)


def test_hash_is_hex_sha256():
    h = normalize_and_hash({"x": 1})
    assert len(h) == 64 and int(h, 16) >= 0


def test_total_matches_contract_example():
    assert (
        compute_total({"KIT-100": 1, "PART-200": 2}, {"KIT-100": 1299, "PART-200": 599})
        == 2497
    )


def test_total_empty():
    assert compute_total({}, {}) == 0


@pytest.mark.parametrize(
    "env,db",
    [("prod", "fulfillops_test"), ("dev", "fulfillops_test"), ("test", "fulfillops")],
)
def test_reset_refuses_unsafe_targets(env, db):
    with pytest.raises(UnsafeResetError):
        check_safe(env, db)


def test_reset_allows_test_database():
    check_safe("test", "fulfillops_test")
