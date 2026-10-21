CREATE TABLE deliveries (
 delivery_id TEXT PRIMARY KEY, report_id TEXT NOT NULL REFERENCES report_snapshots(report_id),
 target_date TEXT NOT NULL, channel TEXT NOT NULL, backend TEXT NOT NULL CHECK(backend='hub'),
 status TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, lease_until REAL,
 owner TEXT, next_attempt REAL NOT NULL DEFAULT 0, resolution TEXT,
 schedule_key TEXT UNIQUE
);
CREATE TABLE delivery_parts (
 delivery_id TEXT NOT NULL REFERENCES deliveries(delivery_id), part INTEGER NOT NULL,
 body TEXT NOT NULL, status TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
 receipt TEXT, error TEXT, PRIMARY KEY(delivery_id,part)
);
