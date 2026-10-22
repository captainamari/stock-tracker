CREATE TABLE update_runs (
 run_id TEXT PRIMARY KEY, trigger TEXT NOT NULL CHECK(trigger IN ('manual','scheduled')),
 target_date TEXT NOT NULL, status TEXT NOT NULL CHECK(status IN ('queued','running','published','failed')),
 created_at TEXT NOT NULL, started_at TEXT, finished_at TEXT, heartbeat REAL, lease_until REAL,
 owner TEXT, attempt INTEGER NOT NULL DEFAULT 0, stage TEXT NOT NULL DEFAULT 'queued',
 completed INTEGER NOT NULL DEFAULT 0, total INTEGER NOT NULL DEFAULT 0, error TEXT
);
CREATE UNIQUE INDEX single_update ON update_runs((1)) WHERE status IN ('queued','running');
CREATE TABLE schedule_fires (kind TEXT NOT NULL, local_date TEXT NOT NULL, run_id TEXT, PRIMARY KEY(kind,local_date));
CREATE TABLE price_revisions (
 id INTEGER PRIMARY KEY, symbol TEXT NOT NULL, date TEXT NOT NULL,
 open REAL, high REAL, low REAL, close REAL, volume REAL,
 source TEXT NOT NULL, basis TEXT NOT NULL, fetched_at TEXT NOT NULL,
 quality TEXT NOT NULL, fingerprint TEXT NOT NULL, run_id TEXT NOT NULL REFERENCES update_runs(run_id)
);
CREATE INDEX revision_history ON price_revisions(symbol,date,id DESC);
CREATE INDEX revision_watermark ON price_revisions(symbol,id);
CREATE TABLE run_assets (
 run_id TEXT NOT NULL REFERENCES update_runs(run_id), symbol TEXT NOT NULL, name TEXT NOT NULL,
 sector TEXT NOT NULL DEFAULT '', yf_ticker TEXT NOT NULL, is_public INTEGER NOT NULL,
 role TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending', reason TEXT,
 actual_date TEXT, input_revision INTEGER, fetched_at TEXT, missing_count INTEGER NOT NULL DEFAULT 0,
 PRIMARY KEY(run_id,symbol)
);
