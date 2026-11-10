-- Owner: Mink, reviewed by Tristan. DRAFT: agree with the team before the first merge.
-- A jobs row is inserted by place_order in the same transaction as the order (outbox).

CREATE TABLE jobs (
    id               bigserial PRIMARY KEY,
    order_id         uuid NOT NULL UNIQUE REFERENCES orders (id),
    status           text NOT NULL DEFAULT 'pending'
                     CHECK (status IN ('pending', 'processing', 'done', 'dead')),
    attempts         integer NOT NULL DEFAULT 0,
    max_attempts     integer NOT NULL DEFAULT 5,
    next_attempt_at  timestamptz NOT NULL DEFAULT now(),
    locked_by        text,
    lease_expires_at timestamptz,
    last_error       text,
    created_at       timestamptz NOT NULL DEFAULT now(),
    updated_at       timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX jobs_claimable_idx ON jobs (status, next_attempt_at);
