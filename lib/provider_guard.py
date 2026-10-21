"""Persistent pacing of history calls, not a promise about Yahoo HTTP quotas."""
import time
from datetime import datetime, timezone
from lib import db
from lib.settings import settings


class YahooCooldownActive(RuntimeError):
    pass


def status():
    with db.get_db() as conn:
        row = conn.execute("SELECT * FROM provider_guard WHERE provider='yfinance'").fetchone()
    until = row['cooldown_until']
    return {'cooldown_active': until > time.time(),
            'cooldown_until': datetime.fromtimestamp(until, timezone.utc).isoformat() if until else None}


def before_call():
    # Reserve only when due. Waiting never holds a database transaction, and
    # every wake checks for a cooldown imposed by another worker/process.
    while True:
        with db.get_db() as conn:
            conn.execute('BEGIN IMMEDIATE')
            row = conn.execute("SELECT * FROM provider_guard WHERE provider='yfinance'").fetchone()
            now = time.time()
            if row['cooldown_until'] > now:
                raise YahooCooldownActive('Yahoo requests paused after rate limiting')
            wait = row['next_call_at'] - now
            if wait <= 0:
                conn.execute("UPDATE provider_guard SET next_call_at=? WHERE provider='yfinance'",
                             (now + settings().yahoo_min_interval_seconds,))
                return
        time.sleep(min(wait, 5))


def rate_limited():
    with db.get_db() as conn:
        conn.execute('BEGIN IMMEDIATE')
        until = time.time() + settings().yahoo_cooldown_seconds
        conn.execute("UPDATE provider_guard SET cooldown_until=MAX(cooldown_until,?) WHERE provider='yfinance'", (until,))
