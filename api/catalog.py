"""Catalog and inventory reads.

Owner: Armand.

ASSUMPTION (agree with Tristan): stock lives in products.available, as in
db/migrations/001_init.sql. If it moves to a separate inventory table, only the two SQL
strings below change.

`conn` is a psycopg 3 connection with the default tuple row factory.
"""

_CATALOG_SQL = "SELECT sku, unit_price_cents FROM products ORDER BY sku"
_INVENTORY_SQL = "SELECT sku, available FROM products WHERE sku = %s"


def get_catalog(conn) -> list[dict]:
    rows = conn.execute(_CATALOG_SQL).fetchall()
    return [{"sku": sku, "unit_price_cents": price} for sku, price in rows]


def get_inventory(conn, sku: str) -> dict | None:
    """Return {"sku", "available"} or None for an unknown SKU."""
    row = conn.execute(_INVENTORY_SQL, (sku,)).fetchone()
    if row is None:
        return None
    return {"sku": row[0], "available": row[1]}
