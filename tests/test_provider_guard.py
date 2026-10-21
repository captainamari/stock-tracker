import importlib
import time
from types import SimpleNamespace
import pytest
from lib import db, jobs, provider_guard
from lib.pipeline import request_update
from lib.worker import run_once


def test_rate_limit_stops_batch_and_survives_restart(database, monkeypatch):
    import yfinance
    from yfinance.exceptions import YFRateLimitError
    calls = []
    class Limited:
        def history(self, **kwargs):
            calls.append(kwargs)
            raise YFRateLimitError()
    monkeypatch.setattr(yfinance, 'Ticker', lambda _: Limited())
    run = request_update('manual')
    with pytest.raises(provider_guard.YahooCooldownActive):
        run_once()
    assert len(calls) == 1  # No immediate retry and no request for the next asset.
    assert jobs.get_run(run)['status'] == 'failed'
    with db.get_db() as conn:
        assert conn.execute('SELECT COUNT(*) FROM publications').fetchone()[0] == 0
        until = conn.execute('SELECT cooldown_until FROM provider_guard').fetchone()[0]
    assert until > time.time() + 21500
    importlib.reload(provider_guard)
    retry = request_update('manual')
    with pytest.raises(provider_guard.YahooCooldownActive):
        run_once()
    assert len(calls) == 1
    assert jobs.get_run(retry)['error'] == 'YahooCooldownActive'


def test_pacing_persists_and_waits_without_write_lock(database, monkeypatch):
    clock = [time.time()]
    waited = []
    def sleep(seconds):
        # A second connection can write while pacing waits.
        with db.get_db() as conn:
            conn.execute("INSERT OR REPLACE INTO settings VALUES ('pacing-test','true')")
        waited.append(seconds)
        clock[0] += seconds
    monkeypatch.setattr(provider_guard, 'time', SimpleNamespace(time=lambda:clock[0], sleep=sleep))
    provider_guard.before_call()
    provider_guard.before_call()
    assert sum(waited) == 5
    provider_guard.rate_limited()
    with pytest.raises(provider_guard.YahooCooldownActive):
        provider_guard.before_call()
    assert sum(waited) == 5  # Cooldown rejects immediately without a six-hour wait.
    clock[0] += 21601
    provider_guard.before_call()
