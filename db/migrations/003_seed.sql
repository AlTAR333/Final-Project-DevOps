-- Owner: Tristan. Runs once with the migrations, so restarts never restore spent stock.
-- ON CONFLICT DO NOTHING: re-running never overwrites stock that has already been used.

INSERT INTO products (sku, unit_price_cents, available) VALUES
    ('KIT-100',  1299,  7),
    ('PART-200',  599, 12),
    ('PACK-300',  249,  5)
ON CONFLICT (sku) DO NOTHING;
