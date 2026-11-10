-- Owner: Tristan. Runs once with the migrations, so restarts never restore spent stock.

INSERT INTO products (sku, unit_price_cents) VALUES
    ('KIT-100', 1299),
    ('PART-200', 599),
    ('PACK-300', 249)
ON CONFLICT DO NOTHING;

INSERT INTO inventory (sku, available) VALUES
    ('KIT-100', 7),
    ('PART-200', 12),
    ('PACK-300', 5)
ON CONFLICT DO NOTHING;
