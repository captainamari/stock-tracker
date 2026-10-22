ALTER TABLE watchlist ADD COLUMN is_personal INTEGER NOT NULL DEFAULT 1 CHECK(is_personal IN (0,1));
CREATE TABLE universe_snapshots (
    snapshot_id TEXT PRIMARY KEY, fetched_at TEXT NOT NULL, payload TEXT NOT NULL
);
CREATE TABLE universe_state (
    id INTEGER PRIMARY KEY CHECK(id=1), snapshot_id TEXT NOT NULL REFERENCES universe_snapshots(snapshot_id),
    last_attempt REAL NOT NULL DEFAULT 0, last_error TEXT
);
CREATE TABLE index_memberships (
    index_id TEXT NOT NULL CHECK(index_id IN ('sp500','nasdaq100')),
    symbol TEXT NOT NULL REFERENCES watchlist(symbol),
    PRIMARY KEY(index_id,symbol)
);
CREATE INDEX memberships_symbol ON index_memberships(symbol);
ALTER TABLE update_runs ADD COLUMN universe_snapshot TEXT REFERENCES universe_snapshots(snapshot_id);
ALTER TABLE update_runs ADD COLUMN universe_prepared INTEGER NOT NULL DEFAULT 0;
UPDATE update_runs SET universe_prepared=1 WHERE status='running';
