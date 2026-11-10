-- 001_init.sql — products, orders and order lines.
-- Owner: Tristan. db/migrate.py runs each file in its own transaction and records it
-- in schema_migrations, so no BEGIN/COMMIT here.

CREATE TABLE IF NOT EXISTS products (
    sku               TEXT    PRIMARY KEY,
    unit_price_cents  INTEGER NOT NULL CHECK (unit_price_cents > 0),
    available         INTEGER NOT NULL CHECK (available >= 0)
);

CREATE TABLE IF NOT EXISTS orders (
    order_id         UUID PRIMARY KEY,
    idempotency_key  TEXT NOT NULL UNIQUE,
    request_hash     TEXT NOT NULL,
    customer_id      VARCHAR(64) NOT NULL,
    status           TEXT NOT NULL DEFAULT 'queued'
                     CHECK (status IN ('queued', 'processing', 'completed', 'failed')),
    total_cents      INTEGER NOT NULL CHECK (total_cents >= 0),
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS order_lines (
    order_id          UUID    NOT NULL REFERENCES orders(order_id),
    sku               TEXT    NOT NULL REFERENCES products(sku),
    quantity          INTEGER NOT NULL CHECK (quantity BETWEEN 1 AND 200),
    unit_price_cents  INTEGER NOT NULL CHECK (unit_price_cents > 0),
    PRIMARY KEY (order_id, sku)
);
