"""Liveness and readiness.

Owner: Armand.

live() never touches the database: the process is alive even if storage is down.
ready() is the only place that decides whether the API may receive traffic.
"""

# Tables that migrations must have created, and the seed that must have run.
_READY_SQL = """
SELECT
    to_regclass('public.products') IS NOT NULL
    AND to_regclass('public.orders') IS NOT NULL
    AND to_regclass('public.jobs') IS NOT NULL
"""
_SEEDED_SQL = "SELECT EXISTS (SELECT 1 FROM products)"

_READY = (200, {"status": "ready"})
_NOT_READY = (503, {"status": "not_ready"})


def live() -> dict:
    return {"status": "ok"}


def ready(conn) -> tuple[int, dict]:
    """200 {"status":"ready"} if the DB is reachable and migrations are applied, else 503."""
    try:
        if not conn.execute(_READY_SQL).fetchone()[0]:
            return _NOT_READY
        if not conn.execute(_SEEDED_SQL).fetchone()[0]:
            return _NOT_READY
    except Exception:  # any DB failure means "cannot accept orders safely"
        return _NOT_READY
    return _READY
