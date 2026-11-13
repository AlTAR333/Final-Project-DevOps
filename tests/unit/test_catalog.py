"""Unit tests for api.catalog (owner: Armand). Fake connection, no database."""

from api.catalog import get_catalog, get_inventory


class FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._rows[0] if self._rows else None


class FakeConn:
    """Records executed SQL and returns canned rows."""

    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    def execute(self, sql, params=None):
        self.calls.append((sql, params))
        return FakeResult(self.rows)


def test_catalog_maps_rows_to_contract_shape():
    conn = FakeConn([("KIT-100", 1299), ("PACK-300", 249), ("PART-200", 599)])
    assert get_catalog(conn) == [
        {"sku": "KIT-100", "unit_price_cents": 1299},
        {"sku": "PACK-300", "unit_price_cents": 249},
        {"sku": "PART-200", "unit_price_cents": 599},
    ]


def test_inventory_found():
    conn = FakeConn([("KIT-100", 7)])
    assert get_inventory(conn, "KIT-100") == {"sku": "KIT-100", "available": 7}


def test_inventory_unknown_sku_returns_none():
    assert get_inventory(FakeConn([]), "NOPE-1") is None


def test_inventory_sku_is_a_bound_parameter_not_interpolated():
    conn = FakeConn([])
    get_inventory(conn, "x'; DROP TABLE products;--")
    sql, params = conn.calls[0]
    assert "DROP" not in sql
    assert params == ("x'; DROP TABLE products;--",)
