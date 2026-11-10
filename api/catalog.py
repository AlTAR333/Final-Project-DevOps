"""Catalog and inventory reads.

Owner: Armand.
"""


def get_catalog(conn) -> list[dict]:
    raise NotImplementedError


def get_inventory(conn, sku: str) -> dict | None:
    """Return {"sku", "available"} or None for an unknown SKU."""
    raise NotImplementedError
