from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import time
import pytest
from lib import db, jobs
from lib.market_calendar import is_trading_day, completed_session
from lib.pipeline import request_update

NOW = datetime(2026,10,21,8,tzinfo=timezone.utc)


def test_calendar_boundaries():
    from scripts.daily_pipeline import is_trading_day as legacy_calendar
    assert not legacy_calendar(datetime(2026,12,25))
    assert not is_trading_day('2026-12-25')
    assert completed_session(datetime(2026,11,27,17,59,tzinfo=timezone.utc)) == '2026-11-25'
    assert completed_session(datetime(2026,11,27,18,1,tzinfo=timezone.utc)) == '2026-11-27'
    assert completed_session(datetime(2026,3,9,19,59,tzinfo=timezone.utc)) == '2026-03-06'
    assert completed_session(datetime(2026,3,9,20,1,tzinfo=timezone.utc)) == '2026-03-09'
    assert completed_session(datetime(2027,1,1,10,tzinfo=timezone.utc)) == '2026-12-31'


def test_atomic_enqueue_claim_and_recovery(database):
    with ThreadPoolExecutor(max_workers=8) as pool:
        ids = list(pool.map(lambda i: request_update('manual' if i%2 else 'scheduled', NOW), range(16)))
    assert len(set(ids)) == 1
    with ThreadPoolExecutor(max_workers=8) as pool:
        claimed = [j for j in pool.map(lambda _: jobs.claim(), range(8)) if j]
    assert len(claimed) == 1
    original = claimed[0]
    with db.get_db() as conn:
        conn.execute('UPDATE update_runs SET lease_until=?', (time.time()-1,))
    replacement = jobs.claim()
    assert replacement['run_id'] == original['run_id']
    assert replacement['attempt'] == 2
    with db.get_db() as conn, pytest.raises(jobs.LostLease):
        jobs.fence(conn, original)
    jobs.heartbeat(replacement)


def test_database_authority_and_pending_add(database):
    from lib.config import sync_watchlist
    from lib.cli import main
    main(['asset-add','NEW','--yahoo','NEW-A','--public'])
    assert db.get_price_count('NEW')==0
    main(['asset-disable','NEW'])
    assert datetime.fromisoformat(db.get_watchlist_item('NEW')['updated_at']).utcoffset().total_seconds()==0
    sync_watchlist({'monitored':[{'symbol':'NEW','name':'Overwrite','enabled':True}]})
    assert not db.get_watchlist_item('NEW')['enabled']
    main(['asset-enable','NEW'])
    run=request_update('manual',NOW)
    with db.get_db() as conn:
        assets={r['symbol']:r['yf_ticker'] for r in conn.execute('SELECT * FROM run_assets WHERE run_id=?',(run,))}
    assert assets['NEW']=='NEW-A' and assets['VIX']=='^VIX'
    assert set(jobs.DEPENDENCIES)<=set(assets)



def test_public_http_cannot_write_market_values(client):
    for path in ('/api/tickers','/api/prices','/api/indicators','/api/strategy-results','/api/prices/import'):
        assert client.post(path,json={'symbol':'BAD','close':999}).status_code==404
