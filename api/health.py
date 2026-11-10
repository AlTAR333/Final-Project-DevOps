"""Liveness and readiness.

Owner: Armand.
"""


def live() -> dict:
    return {"status": "ok"}


def ready(conn) -> tuple[int, dict]:
    """200 {"status":"ready"} if the DB is reachable and migrations are applied, else 503."""
    raise NotImplementedError
