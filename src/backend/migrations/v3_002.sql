CREATE TABLE IF NOT EXISTS v3_job_leases (
    job_id TEXT PRIMARY KEY,
    owner TEXT NOT NULL,
    expires_at DOUBLE PRECISION NOT NULL
);
INSERT INTO counters (name,value) VALUES ('v3_transaction_guard',0) ON CONFLICT (name) DO NOTHING;
