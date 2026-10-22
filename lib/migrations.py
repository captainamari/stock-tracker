"""Additive, transactional migrations; existing rows remain explicitly unverified."""
from pathlib import Path
from lib import db


def migrate(path=None):
    db.init_db(path)
    with db.get_db(path) as conn:
        conn.execute('CREATE TABLE IF NOT EXISTS schema_migrations (version TEXT PRIMARY KEY, applied_at TEXT NOT NULL)')
    for file in sorted((Path(__file__).resolve().parents[1] / 'migrations').glob('*.sql')):
        with db.get_db(path) as conn:
            conn.execute('BEGIN IMMEDIATE')
            if conn.execute('SELECT 1 FROM schema_migrations WHERE version=?', (file.name,)).fetchone():
                continue
            # SQL files contain ordinary DDL only, no triggers or embedded semicolons.
            for statement in file.read_text(encoding='utf-8').split(';'):
                if statement.strip():
                    conn.execute(statement)
            conn.execute("INSERT INTO schema_migrations VALUES (?,strftime('%Y-%m-%dT%H:%M:%fZ','now'))", (file.name,))
