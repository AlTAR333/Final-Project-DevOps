-- Owner: Mink, reviewed by Tristan. DRAFT: agree with the team before the first merge.
-- A jobs row is inserted by place_order in the same transaction as the order (outbox).

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


CREATE INDEX IF NOT EXISTS jobs_claimable_idx
    ON jobs (next_attempt_at)
    WHERE completed_at IS NULL AND dead_lettered_at IS NULL;
