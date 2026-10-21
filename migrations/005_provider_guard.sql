CREATE TABLE provider_guard (
    provider TEXT PRIMARY KEY,
    next_call_at REAL NOT NULL DEFAULT 0,
    cooldown_until REAL NOT NULL DEFAULT 0
);
INSERT INTO provider_guard(provider) VALUES ('yfinance');
