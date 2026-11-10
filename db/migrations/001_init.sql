-- Owner: Tristan. DRAFT: agree with the team before the first merge.
-- Never edit a merged migration; add the next number instead.

CREATE TABLE products (
    sku              text PRIMARY KEY,
    unit_price_cents integer NOT NULL CHECK (unit_price_cents > 0)
);

CREATE TABLE inventory (
    sku       text PRIMARY KEY REFERENCES products (sku),
    available integer NOT NULL CHECK (available >= 0)
);

CREATE TABLE orders (
    id              uuid PRIMARY KEY,
    idempotency_key text NOT NULL UNIQUE,
    request_hash    text NOT NULL,
    customer_id     text NOT NULL,
    status          text NOT NULL CHECK (status IN ('queued', 'processing', 'completed', 'failed')),
    total_cents     integer NOT NULL CHECK (total_cents >= 0),
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE order_lines (
    order_id uuid NOT NULL REFERENCES orders (id),
    sku      text NOT NULL REFERENCES products (sku),
    quantity integer NOT NULL CHECK (quantity > 0),
    PRIMARY KEY (order_id, sku)
);
