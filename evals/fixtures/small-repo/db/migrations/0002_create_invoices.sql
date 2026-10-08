CREATE TABLE invoices (
    id INTEGER PRIMARY KEY,
    order_id INTEGER NOT NULL REFERENCES orders (id),
    amount_cents INTEGER NOT NULL,
    issued_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    paid_at TEXT
);

CREATE INDEX invoices_order_id ON invoices (order_id);
