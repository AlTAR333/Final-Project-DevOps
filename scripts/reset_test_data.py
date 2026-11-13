"""Recreate the isolated test dataset. Must refuse unless APP_ENV=test.

Owner: Tristan.
"""

import sys

from common.config import load_settings
from common.db import connect
from db.migrate import migrate

SEED = [("KIT-100", 1299, 7), ("PART-200", 599, 12), ("PACK-300", 249, 5)]


class UnsafeResetError(RuntimeError):
    pass


def check_safe(app_env: str, dbname: str) -> None:
    if app_env != "test":
        raise UnsafeResetError(
            f"refusing to reset: APP_ENV is {app_env!r}, expected 'test'"
        )
    if "test" not in dbname.lower():
        raise UnsafeResetError(
            f"refusing to reset: database {dbname!r} is not a test database"
        )


def reset(conn) -> None:
    migrate(conn)
    with conn.transaction():
        conn.execute("TRUNCATE jobs, order_lines, orders")
        conn.cursor().executemany(
            "INSERT INTO products (sku, unit_price_cents, available) VALUES (%s, %s, %s) "
            "ON CONFLICT (sku) DO UPDATE SET unit_price_cents = EXCLUDED.unit_price_cents, "
            "available = EXCLUDED.available",
            SEED,
        )


def main() -> None:
    settings = load_settings()
    with connect(settings.database_url) as conn:
        try:
            check_safe(settings.app_env, conn.info.dbname)
        except UnsafeResetError as exc:
            print(exc, file=sys.stderr)
            sys.exit(2)
        reset(conn)
    print("test dataset reset: KIT-100=7, PART-200=12, PACK-300=5")


if __name__ == "__main__":
    main()
