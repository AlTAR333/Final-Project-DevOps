BEGIN;
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

CREATE TABLE IF NOT EXISTS jobs (
    order_id          UUID PRIMARY KEY REFERENCES orders(order_id),
    attempts          INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    max_attempts      INTEGER NOT NULL DEFAULT 5 CHECK (max_attempts > 0),
    next_attempt_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    locked_by         TEXT,
    lease_until       TIMESTAMPTZ,
    last_error        TEXT,
    completed_at      TIMESTAMPTZ,
    dead_lettered_at  TIMESTAMPTZ,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS jobs_ready_idx
    ON jobs (next_attempt_at)
    WHERE completed_at IS NULL AND dead_lettered_at IS NULL;

CREATE TABLE IF NOT EXISTS schema_migrations (
    version     TEXT PRIMARY KEY,
    applied_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
INSERT INTO schema_migrations (version) VALUES ('001_init') ON CONFLICT DO NOTHING;

COMMIT;
