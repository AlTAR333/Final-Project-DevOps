"""Owner: Tristan."""


def available(conn, sku):
    return conn.execute("SELECT available FROM products WHERE sku = %s", (sku,)).fetchone()[0]


def count(conn, sql, params=()):
    return conn.execute(sql, params).fetchone()[0]
