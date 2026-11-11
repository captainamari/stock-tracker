CREATE TABLE digest_runs (
    profile TEXT NOT NULL,
    target_date TEXT NOT NULL,
    channel TEXT NOT NULL,
    delivery_id TEXT NOT NULL REFERENCES deliveries(delivery_id),
    config_json TEXT NOT NULL,
    batch_id TEXT REFERENCES publications(batch_id),
    readiness TEXT NOT NULL,
    PRIMARY KEY(profile, target_date, channel)
);

ALTER TABLE update_runs ADD COLUMN universe_status TEXT NOT NULL DEFAULT 'legacy_unknown';
