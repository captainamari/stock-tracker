ALTER TABLE watchlist ADD COLUMN is_followed INTEGER NOT NULL DEFAULT 0 CHECK(is_followed IN (0,1));
ALTER TABLE watchlist ADD COLUMN is_held INTEGER NOT NULL DEFAULT 0 CHECK(is_held IN (0,1));
UPDATE watchlist SET is_followed=1 WHERE is_personal=1;
CREATE TABLE report_documents (
    report_id TEXT PRIMARY KEY REFERENCES report_snapshots(report_id),
    version INTEGER NOT NULL,
    scope TEXT NOT NULL,
    payload TEXT NOT NULL
);
