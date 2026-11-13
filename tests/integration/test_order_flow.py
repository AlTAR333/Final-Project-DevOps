"""Owner: Tristan."""

import pytest

from api.errors import ApiError
from api.orders import get_order, place_order
from common.db import connect
from tests.helpers import available, count


def test_order_reserves_stock_and_creates_job(db, make_order, new_key):
    result = place_order(db, new_key(), make_order([("KIT-100", 1), ("PART-200", 2)]))
    assert result.replayed is False
    assert available(db, "KIT-100") == 6
    assert available(db, "PART-200") == 10
    assert get_order(db, result.order_id) == {
        "order_id": result.order_id,
        "status": "queued",
        "total_cents": 2497,
    }
    assert count(db, "SELECT count(*) FROM jobs WHERE order_id = %s", (result.order_id,)) == 1


def test_duplicate_sku_lines_are_aggregated(db, make_order, new_key):
    result = place_order(db, new_key(), make_order([("PACK-300", 2), ("PACK-300", 3)]))
    assert available(db, "PACK-300") == 0
    assert get_order(db, result.order_id)["total_cents"] == 5 * 249
    assert (
        count(
            db,
            "SELECT count(*) FROM order_lines WHERE order_id = %s",
            (result.order_id,),
        )
        == 1
    )


def test_duplicate_sku_lines_checked_against_stock_as_total(db, make_order, new_key):
    with pytest.raises(ApiError) as exc:
        place_order(db, new_key(), make_order([("PACK-300", 3), ("PACK-300", 3)]))
    assert exc.value.code == "OUT_OF_STOCK"
    assert available(db, "PACK-300") == 5


def test_replay_returns_same_order_without_second_reservation(db, make_order, new_key):
    key = new_key()
    first = place_order(db, key, make_order([("KIT-100", 1)]))
    again = place_order(db, key, make_order([("KIT-100", 1)]))
    assert again.order_id == first.order_id and again.replayed is True
    assert available(db, "KIT-100") == 6
    assert count(db, "SELECT count(*) FROM orders") == 1


def test_replay_after_completion_still_returns_same_order(db, make_order, new_key):
    key = new_key()
    first = place_order(db, key, make_order([("KIT-100", 1)]))
    db.execute("UPDATE orders SET status = 'completed' WHERE order_id = %s", (first.order_id,))
    assert place_order(db, key, make_order([("KIT-100", 1)])).order_id == first.order_id


def test_replay_survives_new_connection(db, database_url, make_order, new_key):
    key = new_key()
    first = place_order(db, key, make_order([("KIT-100", 1)]))
    with connect(database_url) as fresh:
        assert place_order(fresh, key, make_order([("KIT-100", 1)])).order_id == first.order_id
    assert available(db, "KIT-100") == 6


def test_same_key_different_payload_conflicts(db, make_order, new_key):
    key = new_key()
    place_order(db, key, make_order([("KIT-100", 1)]))
    with pytest.raises(ApiError) as exc:
        place_order(db, key, make_order([("KIT-100", 2)]))
    assert exc.value.code == "IDEMPOTENCY_CONFLICT"
    assert available(db, "KIT-100") == 6


def test_out_of_stock_on_second_sku_reserves_nothing(db, make_order, new_key):
    with pytest.raises(ApiError) as exc:
        place_order(db, new_key(), make_order([("KIT-100", 2), ("PACK-300", 6)]))
    assert exc.value.code == "OUT_OF_STOCK" and exc.value.status == 409
    assert available(db, "KIT-100") == 7
    assert available(db, "PACK-300") == 5
    assert count(db, "SELECT count(*) FROM orders") == 0
    assert count(db, "SELECT count(*) FROM jobs") == 0


def test_key_of_rejected_order_can_be_retried(db, make_order, new_key):
    key = new_key()
    with pytest.raises(ApiError):
        place_order(db, key, make_order([("PACK-300", 6)]))
    result = place_order(db, key, make_order([("PACK-300", 5)]))
    assert result.replayed is False
    assert available(db, "PACK-300") == 0


def test_exact_remaining_stock_is_accepted(db, make_order, new_key):
    place_order(db, new_key(), make_order([("PACK-300", 5)]))
    assert available(db, "PACK-300") == 0
    with pytest.raises(ApiError):
        place_order(db, new_key(), make_order([("PACK-300", 1)]))


@pytest.mark.parametrize("order_id", ["not-real-order", "", "00000000-0000-0000-0000-000000000000"])
def test_unknown_order_returns_none(db, order_id):
    assert get_order(db, order_id) is None
