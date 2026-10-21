ALTER TABLE run_assets ADD COLUMN price REAL;
ALTER TABLE run_assets ADD COLUMN change_1d REAL;
CREATE TABLE daily_results (
 run_id TEXT NOT NULL REFERENCES update_runs(run_id), symbol TEXT NOT NULL, strategy_id TEXT NOT NULL,
 rule_version TEXT NOT NULL, actual_date TEXT, input_revision INTEGER,
 status TEXT NOT NULL CHECK(status IN ('ok','insufficient_data','stale','failed')),
 is_signal INTEGER CHECK(is_signal IN (0,1) OR is_signal IS NULL),
 payload TEXT NOT NULL, computed_at TEXT NOT NULL,
 PRIMARY KEY(run_id,symbol,strategy_id),
 CHECK((status='ok' AND is_signal IS NOT NULL) OR (status!='ok' AND is_signal IS NULL))
);
CREATE INDEX daily_signals ON daily_results(run_id,strategy_id,status,is_signal);
CREATE TABLE publications (
 batch_id TEXT PRIMARY KEY REFERENCES update_runs(run_id), target_date TEXT NOT NULL,
 published_at TEXT NOT NULL, pulse TEXT NOT NULL
);
CREATE TABLE current_publication (id INTEGER PRIMARY KEY CHECK(id=1), batch_id TEXT NOT NULL REFERENCES publications(batch_id));
CREATE TABLE candidate_states (
 symbol TEXT NOT NULL, strategy_id TEXT NOT NULL, active INTEGER NOT NULL,
 entry_date TEXT, entry_price REAL, last_date TEXT NOT NULL,
 PRIMARY KEY(symbol,strategy_id)
);
CREATE TABLE candidate_changes (
 batch_id TEXT NOT NULL REFERENCES publications(batch_id), symbol TEXT NOT NULL, strategy_id TEXT NOT NULL,
 date TEXT NOT NULL, change_type TEXT NOT NULL, price REAL,
 PRIMARY KEY(batch_id,symbol,strategy_id)
);
CREATE TABLE report_snapshots (
 report_id TEXT PRIMARY KEY, batch_id TEXT REFERENCES publications(batch_id), target_date TEXT NOT NULL,
 kind TEXT NOT NULL, body TEXT NOT NULL, created_at TEXT NOT NULL, public INTEGER NOT NULL DEFAULT 1
);
