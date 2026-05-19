"""
Database Migration: Add Momentum V3 tables
============================================
Adds momentum_scores, sector_mappings, sector_definitions, and score_history
tables to support the Momentum V3 strategy and relative strength analysis.

Run: python -m lib.migrations.add_momentum_tables
"""

import sys
from pathlib import Path

# Ensure project root is importable
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from lib.db import get_connection, DB_PATH


MIGRATION_SQL = """
-- Momentum Scores: Daily momentum computation results for all layers
CREATE TABLE IF NOT EXISTS momentum_scores (
    symbol          TEXT NOT NULL,
    date            TEXT NOT NULL,
    layer           TEXT NOT NULL DEFAULT 'stock',
    raw_score       REAL,
    final_score     REAL,
    regime          TEXT,
    delta_1d        REAL,
    delta_5d        REAL,
    consecutive_above_65  INTEGER DEFAULT 0,
    consecutive_above_70  INTEGER DEFAULT 0,
    consecutive_below_60  INTEGER DEFAULT 0,
    signals         TEXT DEFAULT '[]',
    position_advice INTEGER,
    urgency         TEXT DEFAULT 'NONE',
    relative_strength TEXT DEFAULT '{}',
    price           REAL,
    daily_change_pct REAL,
    created_at      TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (symbol, date)
);
CREATE INDEX IF NOT EXISTS idx_momentum_layer ON momentum_scores(layer, date);
CREATE INDEX IF NOT EXISTS idx_momentum_regime ON momentum_scores(regime, date);
CREATE INDEX IF NOT EXISTS idx_momentum_urgency ON momentum_scores(urgency, date);

-- Sector Mappings: Stock-to-sector relationships
CREATE TABLE IF NOT EXISTS sector_mappings (
    stock_symbol    TEXT NOT NULL,
    sector_key      TEXT NOT NULL,
    sector_name     TEXT NOT NULL,
    sector_etf      TEXT,
    decision_priority TEXT DEFAULT 'stock_first',
    updated_at      TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (stock_symbol)
);

-- Sector Definitions: Configuration for sector ETFs
CREATE TABLE IF NOT EXISTS sector_definitions (
    sector_key      TEXT PRIMARY KEY,
    sector_name     TEXT NOT NULL,
    etf_symbol      TEXT,
    basket_tickers  TEXT DEFAULT '[]',
    description     TEXT DEFAULT '',
    decision_priority TEXT DEFAULT 'stock_first',
    enabled         INTEGER DEFAULT 1,
    updated_at      TEXT DEFAULT (datetime('now'))
);

-- Score History: Compact daily score storage for charting
CREATE TABLE IF NOT EXISTS score_history (
    symbol          TEXT NOT NULL,
    date            TEXT NOT NULL,
    strategy        TEXT NOT NULL,
    score           REAL,
    regime          TEXT,
    PRIMARY KEY (symbol, date, strategy)
);
CREATE INDEX IF NOT EXISTS idx_score_history_strategy ON score_history(strategy, date);
"""


DEFAULT_SECTOR_DEFINITIONS = [
    ("semiconductors", "Semiconductors/Storage", "SMH", "[]", "VanEck Semiconductor ETF", "sector_first"),
    ("defense", "Defense/Drones", "ITA", "[]", "iShares US Aerospace & Defense", "stock_first"),
    ("software", "Software/SaaS", "IGV", "[]", "iShares Expanded Tech-Software", "stock_first"),
    ("biotech", "AI Healthcare/Biotech", "XBI", "[]", "SPDR S&P Biotech ETF", "stock_first"),
    ("optical", "Optical Modules", "BASKET", '["COHR","LITE","ANET"]', "Coherent + Lumentum + Arista (equal-weight)", "sector_first"),
]

DEFAULT_STOCK_SECTORS = [
    ("NVDA", "semiconductors", "Semiconductors/Storage", "SMH", "sector_first"),
    ("ZETA", "software", "Software/SaaS", "IGV", "stock_first"),
    ("TEM", "biotech", "AI Healthcare/Biotech", "XBI", "stock_first"),
    ("RCAT", "defense", "Defense/Drones", "ITA", "stock_first"),
]


def run_migration(db_path=None):
    """Execute the migration."""
    path = db_path or DB_PATH
    conn = get_connection(path)

    try:
        conn.executescript(MIGRATION_SQL)

        for row in DEFAULT_SECTOR_DEFINITIONS:
            conn.execute(
                """INSERT OR IGNORE INTO sector_definitions
                   (sector_key, sector_name, etf_symbol, basket_tickers, description, decision_priority)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                row,
            )

        for row in DEFAULT_STOCK_SECTORS:
            conn.execute(
                """INSERT OR IGNORE INTO sector_mappings
                   (stock_symbol, sector_key, sector_name, sector_etf, decision_priority)
                   VALUES (?, ?, ?, ?, ?)""",
                row,
            )

        conn.execute(
            """INSERT OR REPLACE INTO db_meta (key, value, updated_at)
               VALUES ('schema_version', '1.2.0', datetime('now'))"""
        )

        conn.commit()
        print("✅ Migration successful: Added momentum_scores, sector_mappings, sector_definitions, score_history")
        print(f"   Database: {path}")

    except Exception as e:
        conn.rollback()
        print(f"❌ Migration failed: {e}")
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    run_migration()
