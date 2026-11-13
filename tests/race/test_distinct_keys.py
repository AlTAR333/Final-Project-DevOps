"""Owner: Tristan."""

import threading

import psycopg
import pytest

from api.errors import ApiError
from api.orders import place_order
from common.db import connect
from tests.helpers import available, count


def _race(database_url, orders):
    barrier = threading.Barrier(len(orders))
    accepted, rejected, unexpected = [], [], []
    lock = threading.Lock()

    def worker(key, order):
        with connect(database_url) as conn:
            barrier.wait()
            try:
                r = place_order(conn, key, order)
                with lock:
                    accepted.append(r)
            except ApiError as exc:
                with lock:
                    rejected.append(exc.code)
            except psycopg.Error as exc:
                with lock:
                    unexpected.append(exc)

    threads = [threading.Thread(target=worker, args=ko) for ko in orders]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return accepted, rejected, unexpected


@pytest.mark.parametrize("n", [12, 30])
def test_competing_orders_never_oversell(db, database_url, make_order, new_key, n):
    orders = [(new_key(), make_order([("PACK-300", 1)])) for _ in range(n)]
    accepted, rejected, unexpected = _race(database_url, orders)

    assert unexpected == []
    assert len(accepted) == 5
    assert rejected == ["OUT_OF_STOCK"] * (n - 5)
    assert len({r.order_id for r in accepted}) == 5
    assert available(db, "PACK-300") == 0
    assert (
        count(
            db,
            "SELECT coalesce(sum(quantity), 0) FROM order_lines WHERE sku = 'PACK-300'",
        )
        == 5
    )


def test_multi_sku_orders_in_opposite_order_do_not_deadlock(db, database_url, make_order, new_key):
    a = [(new_key(), make_order([("KIT-100", 1), ("PART-200", 1)])) for _ in range(10)]
    b = [(new_key(), make_order([("PART-200", 1), ("KIT-100", 1)])) for _ in range(10)]
    accepted, rejected, unexpected = _race(database_url, a + b)

    assert unexpected == []
    assert len(accepted) == 7
    assert set(rejected) == {"OUT_OF_STOCK"}
    assert available(db, "KIT-100") == 0
    assert available(db, "PART-200") == 5
