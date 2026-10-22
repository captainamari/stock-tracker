"""Real constituent metadata; all prices and HTTP fault responses are isolated fixtures."""
import copy
import json
import time
from datetime import datetime, timedelta, timezone
import pytest
from lib import db, jobs, universe
from lib.pipeline import request_update


def snapshot(days_old=0):
    value = json.loads(universe.BUNDLE.read_text(encoding='utf-8'))
    value['fetched_at'] = (datetime.now(timezone.utc)-timedelta(days=days_old)).isoformat()
    return value


def apply(value):
    with db.get_db() as conn:
        conn.execute('BEGIN IMMEDIATE')
        return universe.apply_snapshot(conn, value)


def symbols(index, value):
    return {r['symbol'] for r in value['indices'][index]['members']}


def replace_symbol(value, old, new):
    for entry in value['indices'].values():
        for row in entry['members']:
            if row['symbol'] == old:
                row.update(symbol=new, name=f'SYNTHETIC member {new}')


def test_union_preserves_personal_preferences_aliases_and_benchmarks(database, monkeypatch):
    monkeypatch.setenv('INDEX_UNIVERSE_ENABLED', 'true')
    db.upsert_watchlist([
        {'symbol':'MYOWN','name':'My private name','yf_ticker':'MYOWN'},
        {'symbol':'AAPL','name':'Personal Apple','enabled':False},
        {'symbol':'BRK.B','name':'Personal Berkshire','yf_ticker':'BRK-B'},
        {'symbol':'SPY','name':'My benchmark','enabled':False,'yf_ticker':'WRONG'},
        {'symbol':'^VIX','name':'Alias benchmark','yf_ticker':'^VIX'},
    ])
    before = {r['symbol']:dict(r) for r in db.get_watchlist(enabled_only=False)}
    value = snapshot()
    apply(value)
    apply(value)  # Idempotent membership, no preference reset.
    with db.get_db() as conn:
        for symbol, original in before.items():
            assert dict(conn.execute('SELECT * FROM watchlist WHERE symbol=?',(symbol,)).fetchone()) == original
        assets = jobs.dependencies(conn)
        by_yf = {a['yf_ticker']:a for a in assets}
        assert len(assets) == len(by_yf)
        assert 'AAPL' not in by_yf
        assert by_yf['BRK-B']['symbol'] == 'BRK.B'
        assert not by_yf['BRK-B']['is_public']
        assert by_yf['MYOWN']['name'] == 'My private name'
        assert not by_yf['MYOWN']['is_public']
        for symbol,yf in jobs.DEPENDENCIES.items():
            assert by_yf[yf]['symbol'] == symbol
        assert 'WRONG' not in by_yf
        union = symbols('sp500',value) | symbols('nasdaq100',value)
        assert set(by_yf) == (union-{'AAPL'}) | {'MYOWN','SPY','QQQ','IWM','^VIX'}
        assert conn.execute("SELECT COUNT(*) FROM watchlist WHERE symbol='BRK-B'").fetchone()[0] == 0


def test_member_removal_keeps_personal_rows_prices_and_disable_choices(database, monkeypatch):
    monkeypatch.setenv('INDEX_UNIVERSE_ENABLED','true')
    value = snapshot()
    db.upsert_watchlist([{'symbol':'AAPL','name':'Personal Apple'}])
    apply(value)
    retired = sorted(symbols('sp500',value)-symbols('nasdaq100',value)-{'AAPL'})[0]
    with db.get_db() as conn:
        conn.execute('INSERT INTO stock_prices(symbol,date,close) VALUES (?,?,?)',(retired,'2026-10-20',123))
        conn.execute("UPDATE watchlist SET enabled=0 WHERE symbol='MSFT'")
    changed = copy.deepcopy(value)
    replace_symbol(changed, retired, 'SYNNEW')
    replace_symbol(changed, 'AAPL', 'SYNAPPLE')
    apply(changed)
    with db.get_db() as conn:
        collected = {a['symbol'] for a in jobs.dependencies(conn)}
        assert retired not in collected
        assert 'AAPL' in collected and 'SYNNEW' in collected
        assert 'MSFT' not in collected
        assert conn.execute('SELECT close FROM stock_prices WHERE symbol=?',(retired,)).fetchone()[0] == 123
        assert conn.execute('SELECT 1 FROM watchlist WHERE symbol=?',(retired,)).fetchone()
    apply(value)  # Rejoining revives managed membership, not an explicit disable.
    with db.get_db() as conn:
        collected = {a['symbol'] for a in jobs.dependencies(conn)}
        assert retired in collected and 'MSFT' not in collected
        assert conn.execute('SELECT COUNT(*) FROM universe_snapshots').fetchone()[0] == 2


def test_weekly_worker_refresh_is_atomic_offline_enqueue_and_restart_pinned(database, monkeypatch):
    monkeypatch.setenv('INDEX_UNIVERSE_ENABLED','true')
    original = snapshot(8)
    apply(original)
    fresh = snapshot()
    replace_symbol(fresh, 'AAPL', 'SYNREPLACEMENT')
    calls = []
    def fetch():
        calls.append(1)
        with db.get_db() as conn:  # No write transaction held during network.
            conn.execute("INSERT OR REPLACE INTO settings VALUES ('universe-test','true')")
        return fresh
    monkeypatch.setattr(universe,'fetch_snapshot',fetch)
    run = request_update('scheduled')
    assert calls == []
    job = jobs.claim()
    universe.prepare_run(job)
    assert calls == [1]
    with db.get_db() as conn:
        assets = {r[0] for r in conn.execute('SELECT symbol FROM run_assets WHERE run_id=?',(run,))}
        pinned = conn.execute('SELECT universe_snapshot FROM update_runs WHERE run_id=?',(run,)).fetchone()[0]
        assert 'SYNREPLACEMENT' in assets and 'AAPL' not in assets
        conn.execute('UPDATE update_runs SET lease_until=? WHERE run_id=?',(time.time()-1,run))
    apply(original)  # Simulates configuration changing between process restarts.
    replacement = jobs.claim()
    universe.prepare_run(replacement)
    with db.get_db() as conn:
        assert assets == {r[0] for r in conn.execute('SELECT symbol FROM run_assets WHERE run_id=?',(run,))}
        assert pinned == conn.execute('SELECT universe_snapshot FROM update_runs WHERE run_id=?',(run,)).fetchone()[0]
    assert calls == [1]


def test_failed_or_truncated_refresh_keeps_both_lists_and_retries_after_day(database, monkeypatch):
    monkeypatch.setenv('INDEX_UNIVERSE_ENABLED','true')
    original = snapshot(8)
    identifier = apply(original)
    malformed = snapshot()
    malformed['indices']['nasdaq100']['members'] = []
    calls = []
    def fetch():
        calls.append(1)
        return malformed
    run = request_update('manual')
    universe.prepare_run(jobs.claim(), fetch)
    with db.get_db() as conn:
        state = conn.execute('SELECT * FROM universe_state').fetchone()
        assert state['snapshot_id'] == identifier and state['last_error'] == 'ValueError'
        assert conn.execute('SELECT COUNT(*) FROM universe_snapshots').fetchone()[0] == 1
        assert conn.execute('SELECT COUNT(*) FROM index_memberships').fetchone()[0] == sum(len(x['members']) for x in original['indices'].values())
        conn.execute("UPDATE update_runs SET status='failed' WHERE run_id=?",(run,))
    request_update('manual')
    universe.prepare_run(jobs.claim(), fetch)
    assert calls == [1]  # Repeated clicks cannot hammer the membership source.


def test_parser_and_large_change_validation(database):
    members = universe.parse_table('<table id="constituents"><tr><th>Symbol</th><th>Security</th></tr><tr><td>BRK.B<sup>[1]</sup></td><td>Berkshire</td></tr></table>','sp500')
    assert members == [{'symbol':'BRK-B','name':'Berkshire'}]
    with pytest.raises(ValueError):
        universe.parse_table('<table id="constituents"><tr><th>Price</th></tr></table>','sp500')
    original = snapshot()
    identifier = apply(original)
    duplicate = copy.deepcopy(original)
    duplicate['indices']['sp500']['members'][1] = duplicate['indices']['sp500']['members'][0]
    with pytest.raises(ValueError):
        apply(duplicate)
    massive = copy.deepcopy(original)
    for i,row in enumerate(massive['indices']['sp500']['members'][:70]):
        row['symbol'] = f'SYN{i}'
    with pytest.raises(ValueError):
        apply(massive)
    with db.get_db() as conn:
        assert conn.execute('SELECT snapshot_id FROM universe_state').fetchone()[0] == identifier


def test_gets_do_not_refresh_and_adding_index_stock_keeps_it_personal(admin, monkeypatch):
    monkeypatch.setenv('INDEX_UNIVERSE_ENABLED','true')
    apply(snapshot(8))
    def prohibited():
        raise AssertionError('GET refreshed index membership')
    monkeypatch.setattr(universe,'fetch_snapshot',prohibited)
    for path in ('/watchlist?lang=en','/watchlist?lang=zh','/admin','/api/dashboard'):
        assert admin.get(path).status_code == 200
    assert 'unique index stocks' in admin.get('/watchlist?lang=en').text
    assert '成分名单待刷新' in admin.get('/watchlist?lang=zh').text
    result = admin.post('/api/tickers',json={'symbol':'AAPL','name':'My Apple','is_public':False})
    assert result.status_code == 200
    changed = snapshot()
    replace_symbol(changed, 'AAPL', 'SYNAPPLE')
    apply(changed)
    with db.get_db() as conn:
        a = conn.execute("SELECT * FROM watchlist WHERE symbol='AAPL'").fetchone()
        assert a['is_personal'] == 1 and a['is_public'] == 0 and a['name'] == 'My Apple'
        assert 'AAPL' in {r['symbol'] for r in jobs.dependencies(conn)}


def test_complete_union_flows_through_worker_once_per_stock(database, monkeypatch):
    from lib.worker import run_once
    from tests.fixtures import bars, NOW
    from lib.queries import dashboard_data
    monkeypatch.setenv('INDEX_UNIVERSE_ENABLED','true')
    db.upsert_watchlist([{'symbol':'MYOWN','name':'Private personal stock'}])
    frame = bars('SYNTHETIC', short=True)
    calls = []
    def source(symbol, start, target):
        calls.append(symbol)
        return frame.copy()
    def prohibited():
        raise AssertionError('Fresh membership should not use network')
    monkeypatch.setattr(universe,'fetch_snapshot',prohibited)
    # Pin the fixture date independently of how long the committed bundle ages.
    apply(snapshot())
    run = request_update('manual',NOW)
    assert run_once(source) == run
    expected = set().union(*(symbols(i,snapshot()) for i in universe.SOURCES)) | {'MYOWN','SPY','QQQ','IWM','^VIX'}
    assert len(calls) == len(set(calls)) == len(expected)
    assert set(calls) == expected
    with db.get_db() as conn:
        assert conn.execute('SELECT status FROM update_runs WHERE run_id=?',(run,)).fetchone()[0] == 'published'
        assert conn.execute('SELECT COUNT(*) FROM daily_results WHERE run_id=?',(run,)).fetchone()[0] == 5 * len(expected)
        assert conn.execute('SELECT COUNT(*) FROM price_revisions WHERE source!=?',('synthetic_test',)).fetchone()[0] == 0
        body = conn.execute('SELECT body FROM report_snapshots WHERE batch_id=?',(run,)).fetchone()[0]
        assert 'MYOWN' not in body
    data = dashboard_data()
    assert 'MYOWN' not in {a['symbol'] for a in data['assets']}
    assert data['batch_id'] == run
