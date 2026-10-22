"""SQLite online backup; restore only to a NEW destination, never overwrite live data."""
import sqlite3
from pathlib import Path
from lib import db


def backup(destination, source=None):
    destination = Path(destination).resolve()
    if destination.exists():
        raise ValueError('Destination already exists; choose a new backup filename')
    destination.parent.mkdir(parents=True, exist_ok=True)
    src = db.get_connection(source)
    dst = sqlite3.connect(destination)
    try:
        src.backup(dst, pages=1000)
        if dst.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise RuntimeError('Backup integrity check failed')
    finally:
        dst.close()
        src.close()
    return destination


def restore(source, destination):
    source = Path(source).resolve()
    if not source.is_file():
        raise ValueError('Backup does not exist')
    return backup(destination, source)
