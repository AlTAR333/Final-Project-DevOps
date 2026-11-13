"""Owner: Tristan."""

import threading

import psycopg

from api.errors import ApiError
from api.orders import place_order
from common.db import connect
from tests.helpers import available, count

THREADS = 8


def _fire(database_url, key, order, n):
    barrier = threading.Barrier(n)
    results, errors = [], []
    lock = threading.Lock()

    def worker():
        with connect(database_url) as conn:
            barrier.wait()
            try:
                r = place_order(conn, key, order)
                with lock:
                    results.append(r)
            except (ApiError, psycopg.Error) as exc:
                with lock:
                    errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return results, errors


def test_eight_simultaneous_same_key_requests_create_one_order(
    db, database_url, make_order, new_key
):
    key = new_key()
    results, errors = _fire(database_url, key, make_order([("KIT-100", 1)]), THREADS)

    assert errors == []
    assert len(results) == THREADS
    assert len({r.order_id for r in results}) == 1
    assert sum(not r.replayed for r in results) == 1
    assert available(db, "KIT-100") == 6
    assert (
        count(db, "SELECT count(*) FROM orders WHERE idempotency_key = %s", (key,)) == 1
    )
    assert count(db, "SELECT count(*) FROM jobs") == 1


def test_same_key_race_with_multi_line_payload(db, database_url, make_order, new_key):
    key = new_key()
    order = make_order([("PART-200", 2), ("PACK-300", 1), ("PART-200", 1)])
    results, errors = _fire(database_url, key, order, THREADS)

    assert errors == []
    assert len({r.order_id for r in results}) == 1
    assert available(db, "PART-200") == 9
    assert available(db, "PACK-300") == 4
