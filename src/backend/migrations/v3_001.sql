-- Additive SQLite/PostgreSQL migration, matching manufacturing.store.SCHEMA.
-- V3 observations/predictions/cohorts use existing append-only domain_records.
CREATE TABLE IF NOT EXISTS v3_operations (
    operation_id TEXT PRIMARY KEY,
    fingerprint TEXT NOT NULL,
    status_code INTEGER,
    response TEXT
);
